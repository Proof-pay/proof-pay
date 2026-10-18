"""Payment accounting. All write paths lock the invoice row on PostgreSQL."""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import Invoice, Merchant, PaymentOutput, Receipt, User
from app.payments.chain import (
    BCHNodeProvider,
    ProviderError,
    TransactionNotFound,
    address_script_hex,
    bch_to_sats,
    normalize_address,
    sats_to_bch,
)
from app.payments.schemas import InvoiceView, PaymentView, PublicCheckout, ReceiptView

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
        stmt = stmt.with_for_update()
    invoice = session.exec(stmt).first()
    if not invoice:
        raise HTTPException(404, "Payment request not found")
    return invoice


def outputs(session: Session, invoice: Invoice) -> list[PaymentOutput]:
    return list(
        session.exec(
            select(PaymentOutput)
            .where(PaymentOutput.invoice_id == invoice.id)
            .order_by(col(PaymentOutput.first_seen_at))
        ).all()
    )


def sums(invoice: Invoice, payments: list[PaymentOutput]) -> tuple[int, int]:
    valid = [p for p in payments if not p.is_late and p.status != "orphaned"]
    total = sum(p.amount_sats for p in valid)
    confirmed = sum(
        p.amount_sats
        for p in valid
        if p.confirmations >= invoice.required_confirmations
    )
    return total, confirmed


def refresh_state(session: Session, invoice: Invoice) -> None:
    if invoice.status == "draft":
        return
    payments = outputs(session, invoice)
    total, confirmed = sums(invoice, payments)
    if total == 0:
        invoice.payment_status = "pending"
    elif confirmed >= invoice.expected_amount_sats:
        invoice.payment_status = "confirmed"
    elif total >= invoice.expected_amount_sats:
        invoice.payment_status = "detected"
    else:
        invoice.payment_status = "partial"
    if (
        invoice.status == "pending"
        and aware(invoice.expires_at) <= now()
        and invoice.payment_status != "confirmed"
    ):
        invoice.status = "expired"
    if invoice.payment_status == "confirmed" and invoice.status in (
        "pending",
        "expired",
    ):
        invoice.status = "confirmed"
    elif invoice.status == "confirmed" and invoice.payment_status != "confirmed":
        invoice.status = "expired" if aware(invoice.expires_at) <= now() else "pending"
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
            if not p.is_late
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


def payment_uri(invoice: Invoice) -> str | None:
    if (
        invoice.status in ("draft", "expired", "cancelled")
        or aware(invoice.expires_at) <= now()
    ):
        return None
    return f"{invoice.receiving_address}?amount={sats_to_bch(invoice.expected_amount_sats)}"


def checkout_url(token: str) -> str:
    return f"{(settings.PUBLIC_CHECKOUT_BASE_URL or settings.FRONTEND_HOST).rstrip('/')}/p/{token}"


def receipt_url(token: str) -> str:
    return f"{(settings.PUBLIC_CHECKOUT_BASE_URL or settings.FRONTEND_HOST).rstrip('/')}/r/{token}"


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
    total, confirmed = sums(invoice, payments)
    status = (
        "expired"
        if invoice.status == "pending" and aware(invoice.expires_at) <= now()
        else invoice.status
    )
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
        payment_status=invoice.payment_status,
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
        payment_uri=payment_uri(invoice),
        receipt_token=receipt.public_token if receipt else None,
        verification_stale=stale(payments),
        payments=[
            PaymentView.model_validate(p, from_attributes=True) for p in payments
        ],
    )


def public_view(session: Session, invoice: Invoice) -> PublicCheckout:
    merchant = session.get(Merchant, invoice.merchant_id)
    payments = outputs(session, invoice)
    total, confirmed = sums(invoice, payments)
    receipt = session.exec(
        select(Receipt).where(Receipt.invoice_id == invoice.id)
    ).first()
    uri = payment_uri(invoice)
    status = (
        "expired"
        if invoice.status == "pending" and aware(invoice.expires_at) <= now()
        else invoice.status
    )
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
        payment_status=invoice.payment_status,
        payment_uri=uri,
        qr_payload=uri,
        received_amount_sats=total,
        confirmed_amount_sats=confirmed,
        receipt_url=receipt_url(receipt.public_token) if receipt else None,
        verification_stale=stale(payments),
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
    return ReceiptView(
        id=receipt.id,
        reference=receipt.reference,
        invoice_reference=receipt.invoice_reference,
        merchant_name=receipt.merchant_name,
        amount_sats=receipt.amount_sats,
        network=receipt.network,
        required_confirmations=receipt.required_confirmations,
        output_refs=json.loads(receipt.output_refs),
        issued_at=receipt.issued_at,
        verified_at=receipt.issued_at,
        public_token=receipt.public_token,
        verification_url=receipt_url(receipt.public_token),
        current_status=invoice.payment_status if invoice else "unavailable",
        verification_stale=stale(payments or []) if invoice else True,
    )


def verify_transaction(
    provider: BCHNodeProvider, txid: str, network: str, address: str
) -> list[tuple[int, int, int]]:
    if not TXID_RE.fullmatch(txid):
        raise HTTPException(422, "Invalid transaction ID")
    tx = provider.transaction(txid.lower(), network)
    try:
        expected_script = address_script_hex(address, network)
        confirmations = max(0, int(tx.get("confirmations", 0)))
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
            existing.last_checked_at = now()
            existing.status = (
                "confirmed"
                if confirmations >= invoice.required_confirmations
                else "detected"
            )
            session.add(existing)
        else:
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
                )
            )
    session.flush()
    refresh_state(session, invoice)
    return len(matches)


def recheck_output(
    session: Session, output: PaymentOutput, provider: BCHNodeProvider
) -> None:
    invoice = session.exec(
        select(Invoice).where(Invoice.id == output.invoice_id).with_for_update()
    ).one()
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
        refresh_state(session, invoice)
        return
    except ProviderError:
        return  # Keep old evidence, now stale; never turn a failed lookup into success.
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
    refresh_state(session, invoice)
