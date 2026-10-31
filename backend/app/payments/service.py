"""Payment accounting. All write paths lock the invoice row on PostgreSQL."""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    AddressReservation,
    DetectedOutput,
    Invoice,
    Merchant,
    PaymentOutput,
    Receipt,
    User,
)
from app.payments.chain import (
    BCHNodeProvider,
    ProviderError,
    TransactionNotFound,
    address_script_hex,
    bch_to_sats,
    normalize_address,
    sats_to_bch,
)
from app.payments.schemas import (
    InvoiceView,
    PaymentView,
    PublicCheckout,
    PublicPayment,
    ReceiptView,
)

TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def now() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def merchant_for_user(session: Session, user: User) -> Merchant:
    merchant = session.exec(select(Merchant).where(Merchant.user_id == user.id)).first()
    if merchant:
        if merchant.network != settings.BCH_NETWORK:
            raise HTTPException(409, "Merchant network differs from deployment network")
        return merchant
    merchant = Merchant(
        user_id=user.id,
        business_name=user.full_name or "ProofPay merchant",
        network=settings.BCH_NETWORK,
        required_confirmations=settings.BCH_REQUIRED_CONFIRMATIONS,
    )
    session.add(merchant)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        merchant = session.exec(
            select(Merchant).where(Merchant.user_id == user.id)
        ).one()
    session.refresh(merchant)
    return merchant


def owned_invoice(
    session: Session, merchant: Merchant, invoice_id: uuid.UUID, lock: bool = False
) -> Invoice:
    stmt = select(Invoice).where(
        Invoice.id == invoice_id, Invoice.merchant_id == merchant.id
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    invoice = session.exec(stmt).first()
    if not invoice:
        raise HTTPException(404, "Payment request not found")
    return invoice


def associate_destination(
    session: Session, invoice: Invoice, address: str, *, allow_automatic: bool = False
) -> None:
    """Atomically establish merchant scope; address entry is not ownership proof."""
    reservation = session.exec(
        select(AddressReservation)
        .where(
            AddressReservation.network == invoice.network,
            AddressReservation.address == address,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if reservation is None:
        try:
            with session.begin_nested():
                session.add(
                    AddressReservation(
                        network=invoice.network,
                        address=address,
                        invoice_id=invoice.id,
                        merchant_id=invoice.merchant_id,
                        auto_allocate=allow_automatic,
                    )
                )
                session.flush()
        except IntegrityError:
            reservation = session.exec(
                select(AddressReservation)
                .where(
                    AddressReservation.network == invoice.network,
                    AddressReservation.address == address,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).one()
        else:
            return
    if reservation.merchant_id != invoice.merchant_id:
        raise HTTPException(
            409,
            "Destination belongs to another merchant or has ambiguous historical ownership",
        )

    if reservation.invoice_id != invoice.id:
        # Irreversible history: a second request (even a draft subsequently
        # deleted or edited away) permanently removes automatic attribution.
        reservation.auto_allocate = False
        session.add(reservation)


def review_transaction(
    session: Session, invoice: Invoice, txid: str, provider: BCHNodeProvider
) -> list[dict[str, Any]]:
    associate_destination(session, invoice, invoice.receiving_address)
    try:
        matches = verify_transaction(
            provider, txid, invoice.network, invoice.receiving_address
        )
    except TransactionNotFound as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not matches:
        raise HTTPException(422, "Transaction has no output to this request address")
    result = []
    for vout, amount, confirmations in matches:
        observation = session.exec(
            select(DetectedOutput).where(
                DetectedOutput.network == invoice.network,
                DetectedOutput.txid == txid.lower(),
                DetectedOutput.vout == vout,
            )
        ).first()
        if observation is None:
            observation = DetectedOutput(
                network=invoice.network,
                address=invoice.receiving_address,
                txid=txid.lower(),
                vout=vout,
                amount_sats=amount,
                confirmations=confirmations,
            )
        observation.confirmations = confirmations
        observation.amount_sats = amount
        observation.last_checked_at = now()
        session.add(observation)
        allocation = session.exec(
            select(PaymentOutput).where(
                PaymentOutput.network == invoice.network,
                PaymentOutput.txid == txid.lower(),
                PaymentOutput.vout == vout,
            )
        ).first()
        allocated_invoice = (
            session.get(Invoice, allocation.invoice_id) if allocation else None
        )
        visible_owner = (
            allocated_invoice
            if allocated_invoice
            and allocated_invoice.merchant_id == invoice.merchant_id
            else None
        )
        result.append(
            {
                "allocated_invoice_id": str(visible_owner.id)
                if visible_owner
                else None,
                "allocated_order_reference": visible_owner.order_reference
                if visible_owner
                else None,
                "txid": txid.lower(),
                "vout": vout,
                "amount_sats": amount,
                "confirmations": confirmations,
                "allocated": allocation is not None,
                "assigned_to_this_invoice": bool(
                    allocation and allocation.invoice_id == invoice.id
                ),
            }
        )
    return result


def outputs(session: Session, invoice: Invoice) -> list[PaymentOutput]:
    return list(
        session.exec(
            select(PaymentOutput)
            .where(PaymentOutput.invoice_id == invoice.id)
            .order_by(col(PaymentOutput.first_seen_at))
        ).all()
    )


@dataclass(frozen=True)
class PaymentState:
    total: int
    confirmed: int
    payment_status: str
    status: str


def payment_state(
    invoice: Invoice,
    payments: list[PaymentOutput],
    *,
    amount_sats: int | None = None,
    required_confirmations: int | None = None,
) -> PaymentState:
    """Authoritative accounting from attributed evidence, never address matching."""
    threshold = (
        invoice.required_confirmations
        if required_confirmations is None
        else required_confirmations
    )
    target = invoice.expected_amount_sats if amount_sats is None else amount_sats
    valid = [
        p
        for p in payments
        if p.invoice_id == invoice.id
        and p.network == invoice.network
        and not p.is_late
        and p.status != "orphaned"
    ]
    total = sum(p.amount_sats for p in valid)
    confirmed = sum(p.amount_sats for p in valid if p.confirmations >= threshold)
    funding = (
        "pending"
        if total == 0
        else "confirmed"
        if confirmed >= target
        else "detected"
        if total >= target
        else "partial"
    )
    status = invoice.status
    if status not in ("draft", "cancelled"):
        status = (
            "confirmed"
            if funding == "confirmed"
            else "expired"
            if status == "expired" or aware(invoice.expires_at) <= now()
            else "pending"
        )
    return PaymentState(total, confirmed, funding, status)


def sums(invoice: Invoice, payments: list[PaymentOutput]) -> tuple[int, int]:
    state = payment_state(invoice, payments)
    return state.total, state.confirmed


def invoice_status_expression() -> Any:
    """SQL predicate counterpart of payment_state for bounded filtered lists.

    Persisted status can predate reconciliation. Filtering must use the same
    attributed satoshis and confirmation threshold as the serialized result.
    """
    confirmed = (
        select(func.coalesce(func.sum(PaymentOutput.amount_sats), 0))
        .where(
            col(PaymentOutput.invoice_id) == col(Invoice.id),
            col(PaymentOutput.network) == col(Invoice.network),
            col(PaymentOutput.is_late).is_(False),
            PaymentOutput.status != "orphaned",
            col(PaymentOutput.confirmations) >= col(Invoice.required_confirmations),
        )
        .correlate(Invoice)
        .scalar_subquery()
    )
    return case(
        (col(Invoice.status).in_(("draft", "cancelled")), Invoice.status),
        (confirmed >= col(Invoice.expected_amount_sats), "confirmed"),
        (
            or_(col(Invoice.status) == "expired", col(Invoice.expires_at) <= now()),
            "expired",
        ),
        else_="pending",
    )


def refresh_state(session: Session, invoice: Invoice) -> None:
    if invoice.status == "draft":
        return
    payments = outputs(session, invoice)
    state = payment_state(invoice, payments)
    invoice.payment_status = state.payment_status
    invoice.status = state.status
    confirmed = state.confirmed
    invoice.updated_at = now()
    if (
        invoice.payment_status == "confirmed"
        and not session.exec(
            select(Receipt).where(Receipt.invoice_id == invoice.id)
        ).first()
    ):
        merchant = session.get(Merchant, invoice.merchant_id)
        qualifying = [
            p
            for p in payments
            if p.network == invoice.network
            and not p.is_late
            and p.status != "orphaned"
            and p.confirmations >= invoice.required_confirmations
        ]
        session.add(
            Receipt(
                invoice_id=invoice.id,
                invoice_reference=invoice.order_reference,
                merchant_name=merchant.business_name if merchant else "",
                amount_sats=confirmed,
                network=invoice.network,
                required_confirmations=invoice.required_confirmations,
                output_refs=json.dumps([f"{p.txid}:{p.vout}" for p in qualifying]),
            )
        )
    session.add(invoice)


def payment_uri(
    invoice: Invoice, received_sats: int = 0, *, status: str | None = None
) -> str | None:
    if (status or invoice.status) in (
        "draft",
        "expired",
        "cancelled",
        "confirmed",
    ) or aware(invoice.expires_at) <= now():
        return None
    remaining = max(0, invoice.expected_amount_sats - received_sats)
    return (
        f"{invoice.receiving_address}?amount={sats_to_bch(remaining)}"
        if remaining
        else None
    )


def checkout_url(token: str) -> str:
    return f"{(settings.PUBLIC_CHECKOUT_BASE_URL or settings.FRONTEND_HOST).rstrip('/')}/p/{token}"


def receipt_url(token: str) -> str:
    return f"{(settings.PUBLIC_CHECKOUT_BASE_URL or settings.FRONTEND_HOST).rstrip('/')}/r/{token}"


def scan_stale(invoice: Invoice) -> bool:
    return invoice.last_scanned_at is None or aware(
        invoice.last_scanned_at
    ) < now() - timedelta(
        seconds=max(120, settings.BCH_RECONCILIATION_INTERVAL_SECONDS * 3)
    )


def verification_stale(invoice: Invoice, payments: list[PaymentOutput]) -> bool:
    state = payment_state(invoice, payments)
    # Discovery is needed for outstanding requests, not proof of a completed
    # payment. Settled evidence is still rechecked indefinitely for reorgs.
    needs_discovery = (
        state.status == "pending" and state.total < invoice.expected_amount_sats
    )
    return stale(payments) or (needs_discovery and scan_stale(invoice))


def stale(payments: list[PaymentOutput]) -> bool:
    return bool(payments) and any(
        aware(p.last_checked_at)
        < now()
        - timedelta(seconds=max(120, settings.BCH_RECONCILIATION_INTERVAL_SECONDS * 3))
        for p in payments
    )


def invoice_view(session: Session, invoice: Invoice) -> InvoiceView:
    payments = outputs(session, invoice)
    receipt = session.exec(
        select(Receipt).where(Receipt.invoice_id == invoice.id)
    ).first()
    return invoice_view_loaded(invoice, payments, receipt)


def invoice_views(session: Session, invoices: list[Invoice]) -> list[InvoiceView]:
    if not invoices:
        return []
    ids = [invoice.id for invoice in invoices]
    all_payments = session.exec(
        select(PaymentOutput).where(col(PaymentOutput.invoice_id).in_(ids))
    ).all()
    all_receipts = session.exec(
        select(Receipt).where(col(Receipt.invoice_id).in_(ids))
    ).all()
    by_invoice: dict[uuid.UUID, list[PaymentOutput]] = {}
    for payment in all_payments:
        by_invoice.setdefault(payment.invoice_id, []).append(payment)
    receipts = {receipt.invoice_id: receipt for receipt in all_receipts}
    return [
        invoice_view_loaded(
            invoice, by_invoice.get(invoice.id, []), receipts.get(invoice.id)
        )
        for invoice in invoices
    ]


def invoice_view_loaded(
    invoice: Invoice, payments: list[PaymentOutput], receipt: Receipt | None
) -> InvoiceView:
    state = payment_state(invoice, payments)
    total, confirmed, status = state.total, state.confirmed, state.status
    return InvoiceView(
        id=invoice.id,
        order_reference=invoice.order_reference,
        title=invoice.title,
        description=invoice.description,
        network=invoice.network,
        receiving_address=invoice.receiving_address,
        expected_amount_sats=invoice.expected_amount_sats,
        amount_bch=sats_to_bch(invoice.expected_amount_sats),
        required_confirmations=invoice.required_confirmations,
        status=status,
        payment_status=state.payment_status,
        received_amount_sats=total,
        confirmed_amount_sats=confirmed,
        expires_at=invoice.expires_at,
        issued_at=invoice.issued_at,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
        fiat_reference_amount=invoice.fiat_reference_amount,
        fiat_currency=invoice.fiat_currency,
        public_token=invoice.public_token,
        checkout_url=checkout_url(invoice.public_token),
        payment_uri=payment_uri(invoice, total, status=status),
        receipt_token=receipt.public_token if receipt else None,
        verification_stale=verification_stale(invoice, payments),
        payments=[
            PaymentView.model_validate(p, from_attributes=True) for p in payments
        ],
    )


def public_view(session: Session, invoice: Invoice) -> PublicCheckout:
    merchant = session.get(Merchant, invoice.merchant_id)
    payments = outputs(session, invoice)
    state = payment_state(invoice, payments)
    total, confirmed, status = state.total, state.confirmed, state.status
    receipt = session.exec(
        select(Receipt).where(Receipt.invoice_id == invoice.id)
    ).first()
    uri = payment_uri(invoice, total, status=status)
    return PublicCheckout(
        merchant_name=merchant.business_name if merchant else "",
        title=invoice.title,
        description=invoice.description,
        order_reference=invoice.order_reference,
        network=invoice.network,
        amount_bch=sats_to_bch(invoice.expected_amount_sats),
        expected_amount_sats=invoice.expected_amount_sats,
        receiving_address=invoice.receiving_address,
        expires_at=invoice.expires_at,
        status=status,
        payment_status=state.payment_status,
        payment_uri=uri,
        qr_payload=uri,
        amount_due_bch=sats_to_bch(max(0, invoice.expected_amount_sats - total)),
        required_confirmations=invoice.required_confirmations,
        late_amount_sats=sum(
            p.amount_sats for p in payments if p.is_late and p.status != "orphaned"
        ),
        overpaid_amount_sats=max(0, total - invoice.expected_amount_sats),
        received_amount_sats=total,
        confirmed_amount_sats=confirmed,
        receipt_url=receipt_url(receipt.public_token) if receipt else None,
        verification_stale=verification_stale(invoice, payments),
    )


def receipt_view(
    session: Session,
    receipt: Receipt,
    invoice: Invoice | None = None,
    payments: list[PaymentOutput] | None = None,
) -> ReceiptView:
    if invoice is None:
        invoice = session.get(Invoice, receipt.invoice_id)
    if payments is None and invoice is not None:
        payments = outputs(session, invoice)
    # A receipt is an immutable snapshot, not a live list of every transfer
    # subsequently assigned to the same invoice (or sent to its address).
    refs = json.loads(receipt.output_refs)
    credited = [
        p
        for p in payments or []
        if p.invoice_id == receipt.invoice_id
        and p.network == receipt.network
        and f"{p.txid}:{p.vout}" in refs
    ]
    found = {f"{p.txid}:{p.vout}" for p in credited}
    missing = [ref for ref in refs if ref not in found]
    complete = bool(refs) and not missing
    receipt_state = (
        payment_state(
            invoice,
            credited,
            amount_sats=receipt.amount_sats,
            required_confirmations=receipt.required_confirmations,
        )
        if invoice
        else None
    )
    return ReceiptView(
        id=receipt.id,
        reference=receipt.reference,
        invoice_reference=receipt.invoice_reference,
        merchant_name=receipt.merchant_name,
        amount_sats=receipt.amount_sats,
        network=receipt.network,
        required_confirmations=receipt.required_confirmations,
        output_refs=refs,
        missing_output_refs=missing,
        invoice_payment_status=payment_state(invoice, payments or []).payment_status
        if invoice
        else "unavailable",
        issued_at=receipt.issued_at,
        verified_at=min((aware(p.last_checked_at) for p in credited), default=None)
        if complete
        else None,
        requested_amount_sats=invoice.expected_amount_sats if invoice else 0,
        receiving_address=invoice.receiving_address if invoice else "",
        payments=[
            PublicPayment.model_validate(p, from_attributes=True) for p in credited
        ],
        public_token=receipt.public_token,
        verification_url=receipt_url(receipt.public_token),
        current_status=receipt_state.payment_status
        if receipt_state and complete
        else "unavailable",
        verification_stale=not complete or stale(credited),
    )


def verify_transaction(
    provider: BCHNodeProvider, txid: str, network: str, address: str
) -> list[tuple[int, int, int]]:
    if not TXID_RE.fullmatch(txid):
        raise HTTPException(422, "Invalid transaction ID")
    tx = provider.transaction(txid.lower(), network)
    try:
        expected_script = address_script_hex(address, network)
        confirmations = int(tx.get("confirmations", 0))
        if confirmations < 0:
            return []  # A conflicted transaction is no longer spendable evidence.
        matches = []
        indexes: set[int] = set()
        for output in tx["vout"]:
            vout = int(output["n"])
            if vout < 0 or vout in indexes:
                raise ValueError("Invalid or repeated output index")
            indexes.add(vout)
            script = output.get("scriptPubKey", {})
            addresses = script.get("addresses") or (
                [script["address"]] if script.get("address") else []
            )
            destination_matches = (
                script["hex"].lower() == expected_script if "hex" in script else False
            )
            if "hex" not in script:
                for candidate in addresses:
                    try:
                        if normalize_address(candidate, network) == address:
                            destination_matches = True
                    except ValueError:
                        continue
            if destination_matches:
                sats = bch_to_sats(output["value"])
                matches.append((vout, sats, confirmations))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError("BCH provider returned malformed output data") from exc
    return matches


def reconcile_claim(
    session: Session,
    invoice: Invoice,
    txid: str,
    provider: BCHNodeProvider,
    vouts: list[int] | None = None,
) -> int:
    """Verify and allocate each output; unique DB key prevents double allocation."""
    if invoice.status == "draft":
        raise HTTPException(409, "Issue the request before allocating payments")
    try:
        matches = verify_transaction(
            provider, txid, invoice.network, invoice.receiving_address
        )
    except TransactionNotFound as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not matches:
        raise HTTPException(422, "Transaction has no output to this request address")
    if vouts is None and len(matches) > 1:
        raise HTTPException(409, "Multiple matching outputs; specify output indexes")
    if vouts is not None:
        matched_indexes = {vout for vout, _, _ in matches}
        if not set(vouts) <= matched_indexes:
            raise HTTPException(
                422, "Selected output does not pay this request address"
            )
        matches = [match for match in matches if match[0] in vouts]
    checked_at = now()
    # One transaction can pay multiple addresses, but an output may have only one invoice.
    for vout, amount, confirmations in matches:
        existing = session.exec(
            select(PaymentOutput).where(
                PaymentOutput.network == invoice.network,
                PaymentOutput.txid == txid.lower(),
                PaymentOutput.vout == vout,
            )
        ).first()
        if existing and existing.invoice_id != invoice.id:
            raise HTTPException(409, "Transaction output already allocated")
        if existing:
            existing.confirmations = confirmations
            existing.last_checked_at = checked_at
            existing.status = (
                "confirmed"
                if confirmations >= invoice.required_confirmations
                else "detected"
            )
            session.add(existing)
        else:
            associate_destination(session, invoice, invoice.receiving_address)
            late = (
                invoice.status in ("expired", "cancelled")
                or aware(invoice.expires_at) <= now()
            )
            session.add(
                PaymentOutput(
                    invoice_id=invoice.id,
                    network=invoice.network,
                    txid=txid.lower(),
                    vout=vout,
                    amount_sats=amount,
                    confirmations=confirmations,
                    status="confirmed"
                    if confirmations >= invoice.required_confirmations
                    else "detected",
                    is_late=late,
                    first_seen_at=checked_at,
                    last_checked_at=checked_at,
                )
            )
    session.flush()
    refresh_state(session, invoice)
    return len(matches)


def recheck_output(
    session: Session,
    output: PaymentOutput,
    provider: BCHNodeProvider,
    *,
    update_state: bool = True,
) -> bool:
    invoice = session.exec(
        select(Invoice)
        .where(Invoice.id == output.invoice_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    # The caller may have loaded this row before waiting for the invoice lock.
    session.refresh(output)
    try:
        matches = verify_transaction(
            provider, output.txid, output.network, invoice.receiving_address
        )
    except TransactionNotFound:
        output.status = "orphaned"
        output.confirmations = 0
        output.last_checked_at = now()
        session.add(output)
        session.flush()
        if update_state:
            refresh_state(session, invoice)
        return True
    except ProviderError:
        return False  # Preserve evidence and its successful-check timestamp.
    match = next(
        (
            (amount, confirmations)
            for vout, amount, confirmations in matches
            if vout == output.vout
        ),
        None,
    )
    if match is None or match[0] != output.amount_sats:
        output.status = "orphaned"
        output.confirmations = 0
    else:
        output.confirmations = match[1]
        output.status = (
            "confirmed" if match[1] >= invoice.required_confirmations else "detected"
        )
    output.last_checked_at = now()
    session.add(output)
    session.flush()
    if update_state:
        refresh_state(session, invoice)
    return True
