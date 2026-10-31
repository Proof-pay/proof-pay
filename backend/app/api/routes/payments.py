"""Merchant payment API and token-scoped public views."""

import csv
import hashlib
import io
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models import DetectedOutput, Invoice, Merchant, PaymentOutput, Receipt
from app.payments.chain import (
    BCHNodeProvider,
    ProviderError,
    bch_to_sats,
    normalize_address,
)
from app.payments.schemas import (
    ClaimInput,
    DashboardSummary,
    InvoiceCreateInput,
    InvoicePage,
    InvoicePatch,
    InvoiceView,
    MerchantPatch,
    MerchantSettings,
    PaymentHistoryPage,
    PaymentPage,
    PaymentView,
    PublicCheckout,
    PublicReceipt,
    ReceiptPage,
    ReceiptView,
)
from app.payments.service import (
    associate_destination,
    aware,
    invoice_status_expression,
    invoice_view,
    invoice_views,
    merchant_for_user,
    now,
    outputs,
    owned_invoice,
    payment_state,
    public_view,
    receipt_view,
    recheck_output,
    reconcile_claim,
    refresh_state,
    review_transaction,
    scan_stale,
    sums,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["payments"])


def _merchant(session: SessionDep, user: CurrentUser) -> Merchant:
    return merchant_for_user(session, user)


def _commit(session: SessionDep) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            409, "Duplicate reference or concurrent payment allocation"
        ) from exc


@router.get("/merchant/settings", response_model=MerchantSettings)
def get_settings(session: SessionDep, user: CurrentUser) -> Merchant:
    return _merchant(session, user)


@router.patch("/merchant/settings", response_model=MerchantSettings)
def update_settings(
    session: SessionDep, user: CurrentUser, patch: MerchantPatch
) -> Merchant:
    merchant = _merchant(session, user)
    data = patch.model_dump(exclude_unset=True)
    if "receiving_address" in data and data["receiving_address"]:
        try:
            data["receiving_address"] = normalize_address(
                data["receiving_address"], merchant.network
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    for key, value in data.items():
        setattr(merchant, key, value)
    session.add(merchant)
    _commit(session)
    session.refresh(merchant)
    return merchant


@router.post("/payment-requests", response_model=InvoiceView, status_code=201)
def create_request(
    session: SessionDep,
    user: CurrentUser,
    payload: InvoiceCreateInput,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> InvoiceView:
    merchant = _merchant(session, user)
    canonical = json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    if idempotency_key:
        prior = session.exec(
            select(Invoice).where(
                Invoice.merchant_id == merchant.id,
                Invoice.idempotency_key == idempotency_key,
            )
        ).first()
        if prior:
            if prior.idempotency_hash != digest:
                raise HTTPException(
                    409, "Idempotency key already used for another request"
                )
            return invoice_view(session, prior)
    address = payload.receiving_address or merchant.receiving_address
    if not address:
        raise HTTPException(422, "Configure a BCH receiving address first")
    try:
        address = normalize_address(address, merchant.network)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    expiry = payload.expires_at or now() + timedelta(
        hours=merchant.default_expiry_hours
    )
    if aware(expiry) <= now():
        raise HTTPException(422, "Expiry must be in the future")
    invoice = Invoice(
        merchant_id=merchant.id,
        order_reference=payload.order_reference,
        title=payload.title,
        description=payload.description,
        network=merchant.network,
        receiving_address=address,
        expected_amount_sats=bch_to_sats(payload.amount_bch),
        required_confirmations=merchant.required_confirmations,
        status="draft",
        expires_at=expiry,
        fiat_reference_amount=payload.fiat_reference_amount,
        fiat_currency=payload.fiat_currency,
        idempotency_key=idempotency_key,
        idempotency_hash=digest if idempotency_key else None,
    )
    associate_destination(session, invoice, address, allow_automatic=True)
    session.add(invoice)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key:
            prior = session.exec(
                select(Invoice).where(
                    Invoice.merchant_id == merchant.id,
                    Invoice.idempotency_key == idempotency_key,
                )
            ).first()
            if prior:
                if prior.idempotency_hash == digest:
                    return invoice_view(session, prior)
                raise HTTPException(
                    409, "Idempotency key already used for another request"
                ) from exc
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        # Avoid logging SQL parameters, which can contain private payment details.
        logger.error("Payment request integrity failure (constraint=%s)", constraint)
        raise HTTPException(
            500, "Could not save the payment request. Please retry or contact support."
        ) from exc
    session.refresh(invoice)
    return invoice_view(session, invoice)


@router.get("/payment-requests", response_model=InvoicePage)
def list_requests(
    session: SessionDep,
    user: CurrentUser,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[str, Query()] = "-created_at",
) -> dict[str, Any]:
    merchant = _merchant(session, user)
    if status and status not in {
        "draft",
        "pending",
        "confirmed",
        "expired",
        "cancelled",
    }:
        raise HTTPException(422, "Unsupported status")
    if sort not in {"-created_at", "created_at", "expires_at", "-expires_at"}:
        raise HTTPException(422, "Unsupported sort")
    stmt = select(Invoice).where(Invoice.merchant_id == merchant.id)
    if status:
        stmt = stmt.where(invoice_status_expression() == status)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                col(Invoice.title).ilike(term), col(Invoice.order_reference).ilike(term)
            )
        )
    count = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    field = col(Invoice.created_at) if "created_at" in sort else col(Invoice.expires_at)
    stmt = (
        stmt.order_by(field.desc() if sort.startswith("-") else field.asc())
        .offset(offset)
        .limit(limit)
    )
    data = invoice_views(session, list(session.exec(stmt).all()))
    return {"data": data, "count": count}


@router.get("/payment-requests/{invoice_id}", response_model=InvoiceView)
def get_request(
    session: SessionDep, user: CurrentUser, invoice_id: uuid.UUID
) -> InvoiceView:
    return invoice_view(
        session, owned_invoice(session, _merchant(session, user), invoice_id)
    )


@router.patch("/payment-requests/{invoice_id}", response_model=InvoiceView)
def update_request(
    session: SessionDep, user: CurrentUser, invoice_id: uuid.UUID, patch: InvoicePatch
) -> InvoiceView:
    invoice = owned_invoice(session, _merchant(session, user), invoice_id, lock=True)
    if invoice.status != "draft":
        raise HTTPException(409, "Only draft requests can be edited")
    data = patch.model_dump(exclude_unset=True)
    if "amount_bch" in data:
        invoice.expected_amount_sats = bch_to_sats(data.pop("amount_bch"))
    if "receiving_address" in data:
        try:
            data["receiving_address"] = normalize_address(
                data["receiving_address"], invoice.network
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if "expires_at" in data and (
        data["expires_at"] is None or aware(data["expires_at"]) <= now()
    ):
        raise HTTPException(422, "Expiry must be in the future")
    if (
        "receiving_address" in data
        and data["receiving_address"] != invoice.receiving_address
    ):
        associate_destination(
            session, invoice, data["receiving_address"], allow_automatic=True
        )
    for key, value in data.items():
        setattr(invoice, key, value)
    if bool(invoice.fiat_reference_amount) != bool(invoice.fiat_currency):
        raise HTTPException(
            422, "Fiat reference amount and currency must be supplied together"
        )
    invoice.updated_at = now()
    session.add(invoice)
    _commit(session)
    return invoice_view(session, invoice)


@router.post("/payment-requests/{invoice_id}/issue", response_model=InvoiceView)
def issue_request(
    session: SessionDep, user: CurrentUser, invoice_id: uuid.UUID
) -> InvoiceView:
    invoice = owned_invoice(session, _merchant(session, user), invoice_id, lock=True)
    if invoice.status != "draft" or aware(invoice.expires_at) <= now():
        raise HTTPException(409, "Request cannot be issued")
    associate_destination(session, invoice, invoice.receiving_address)
    watched = session.exec(
        select(Invoice.id).where(
            Invoice.network == invoice.network,
            Invoice.receiving_address == invoice.receiving_address,
            col(Invoice.watched_at).is_not(None),
        )
    ).first()
    try:
        if not watched:
            BCHNodeProvider().watch_address(invoice.receiving_address, invoice.network)
    except ProviderError as exc:
        raise HTTPException(
            503,
            "Cannot monitor this destination. Check the BCH node watch-only wallet configuration.",
        ) from exc
    invoice.watched_at = now()
    invoice.status = "pending"
    invoice.issued_at = now()
    invoice.updated_at = now()
    session.add(invoice)
    _commit(session)
    return invoice_view(session, invoice)


@router.post("/payment-requests/{invoice_id}/cancel", response_model=InvoiceView)
def cancel_request(
    session: SessionDep, user: CurrentUser, invoice_id: uuid.UUID
) -> InvoiceView:
    invoice = owned_invoice(session, _merchant(session, user), invoice_id, lock=True)
    if invoice.status not in {"draft", "pending"} or outputs(session, invoice):
        raise HTTPException(
            409, "Only unpaid draft or pending requests can be cancelled"
        )
    invoice.status = "cancelled"
    invoice.updated_at = now()
    session.add(invoice)
    _commit(session)
    return invoice_view(session, invoice)


@router.delete("/payment-requests/{invoice_id}", status_code=204)
def delete_request(
    session: SessionDep, user: CurrentUser, invoice_id: uuid.UUID
) -> None:
    """Only an unpublished draft with no payment history can be removed."""
    invoice = owned_invoice(session, _merchant(session, user), invoice_id, lock=True)
    receipt = session.exec(
        select(Receipt).where(Receipt.invoice_id == invoice.id)
    ).first()
    if invoice.status != "draft" or outputs(session, invoice) or receipt:
        raise HTTPException(409, "Only unpaid draft requests can be deleted")
    session.delete(invoice)
    _commit(session)


@router.get("/payment-requests/{invoice_id}/detected")
def detected_payments(
    session: SessionDep, user: CurrentUser, invoice_id: uuid.UUID
) -> list[dict[str, Any]]:
    invoice = owned_invoice(session, _merchant(session, user), invoice_id)
    associate_destination(session, invoice, invoice.receiving_address)
    rows = session.exec(
        select(DetectedOutput)
        .outerjoin(
            PaymentOutput,
            and_(
                col(PaymentOutput.network) == col(DetectedOutput.network),
                col(PaymentOutput.txid) == col(DetectedOutput.txid),
                col(PaymentOutput.vout) == col(DetectedOutput.vout),
            ),
        )
        .where(
            DetectedOutput.network == invoice.network,
            DetectedOutput.address == invoice.receiving_address,
            col(PaymentOutput.id).is_(None),
        )
        .order_by(col(DetectedOutput.last_checked_at).desc())
        .limit(100)
    ).all()
    return [
        {
            "txid": row.txid,
            "vout": row.vout,
            "amount_sats": row.amount_sats,
            "confirmations": row.confirmations,
            "last_checked_at": row.last_checked_at,
        }
        for row in rows
    ]


@router.get("/payment-requests/{invoice_id}/monitoring")
def payment_monitoring(
    session: SessionDep, user: CurrentUser, invoice_id: uuid.UUID
) -> dict[str, Any]:
    invoice = owned_invoice(session, _merchant(session, user), invoice_id)
    successful = invoice.last_scanned_at
    attempted = invoice.scan_attempted_at
    failed = attempted is not None and (
        successful is None or aware(attempted) > aware(successful)
    )
    status = (
        "failed"
        if failed
        else "never"
        if successful is None
        else "stale"
        if scan_stale(invoice)
        else "current"
    )
    return {
        "scan_status": status,
        "last_successful_scan_at": successful,
        "last_scan_attempt_at": attempted,
        "outputs": detected_payments(session, user, invoice_id),
    }


@router.get("/payment-requests/{invoice_id}/transactions/{txid}")
def review_payment(
    session: SessionDep, user: CurrentUser, invoice_id: uuid.UUID, txid: str
) -> list[dict[str, Any]]:
    invoice = owned_invoice(session, _merchant(session, user), invoice_id, lock=True)
    provider = BCHNodeProvider()
    result = review_transaction(session, invoice, txid, provider)
    assigned_here = [row["vout"] for row in result if row["assigned_to_this_invoice"]]
    if assigned_here:
        payments = session.exec(
            select(PaymentOutput).where(
                PaymentOutput.invoice_id == invoice.id,
                PaymentOutput.txid == txid.lower(),
                col(PaymentOutput.vout).in_(assigned_here),
            )
        ).all()
        for payment in payments:
            if not recheck_output(session, payment, provider, update_state=False):
                raise HTTPException(
                    503,
                    "Could not refresh allocated payment evidence; retry or wait for the payment worker",
                )
        refresh_state(session, invoice)
    _commit(session)
    return result


@router.post("/payment-requests/{invoice_id}/claims/{txid}", response_model=InvoiceView)
def claim_transaction(
    session: SessionDep,
    user: CurrentUser,
    invoice_id: uuid.UUID,
    txid: str,
    claim: ClaimInput | None = None,
) -> InvoiceView:
    invoice = owned_invoice(session, _merchant(session, user), invoice_id, lock=True)
    if invoice.status == "draft":
        raise HTTPException(409, "Issue the request before claiming a transaction")
    try:
        reconcile_claim(
            session, invoice, txid, BCHNodeProvider(), claim.vouts if claim else None
        )
        _commit(session)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            409,
            "Transaction output already allocated by a concurrent claim; refresh and retry",
        ) from exc
    except Exception:
        session.rollback()
        raise
    return invoice_view(session, invoice)


@router.get("/public/payment-requests/{token}", response_model=PublicCheckout)
def public_checkout(session: SessionDep, token: str) -> PublicCheckout:
    invoice = session.exec(
        select(Invoice).where(Invoice.public_token == token, Invoice.status != "draft")
    ).first()
    if not invoice:
        raise HTTPException(404, "Payment request not found")
    return public_view(session, invoice)


@router.get("/public/payment-requests/{token}/status", response_model=PublicCheckout)
def public_status(session: SessionDep, token: str) -> PublicCheckout:
    return public_checkout(session, token)


@router.get("/payments", response_model=PaymentPage)
def list_payments(
    session: SessionDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    sort: Annotated[str, Query()] = "-first_seen_at",
) -> dict[str, Any]:
    merchant = _merchant(session, user)
    if status and status not in {"detected", "confirmed", "orphaned"}:
        raise HTTPException(422, "Unsupported status")
    if sort not in {"first_seen_at", "-first_seen_at"}:
        raise HTTPException(422, "Unsupported sort")
    stmt = select(PaymentOutput).join(Invoice).where(Invoice.merchant_id == merchant.id)
    if status:
        stmt = stmt.where(PaymentOutput.status == status)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                col(PaymentOutput.txid).ilike(term),
                col(Invoice.title).ilike(term),
                col(Invoice.order_reference).ilike(term),
            )
        )
    count = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    order = col(PaymentOutput.first_seen_at)
    payments = session.exec(
        stmt.order_by(order.desc() if sort.startswith("-") else order.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "data": [PaymentView.model_validate(p, from_attributes=True) for p in payments],
        "count": count,
    }


@router.get("/payments/export.csv")
def export_payments(session: SessionDep, user: CurrentUser) -> StreamingResponse:

    merchant = _merchant(session, user)
    cutoff = now()

    def rows() -> Iterator[str]:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "network",
                "txid",
                "vout",
                "amount_sats",
                "confirmations",
                "status",
                "late",
                "first_seen_at",
            ]
        )
        yield buffer.getvalue()
        offset = 0
        while True:
            payments = session.exec(
                select(PaymentOutput)
                .join(Invoice)
                .where(
                    Invoice.merchant_id == merchant.id,
                    PaymentOutput.first_seen_at <= cutoff,
                )
                .order_by(col(PaymentOutput.id))
                .offset(offset)
                .limit(1000)
            ).all()
            if not payments:
                break
            buffer.seek(0)
            buffer.truncate(0)
            for p in payments:
                writer.writerow(
                    [
                        p.network,
                        p.txid,
                        p.vout,
                        p.amount_sats,
                        p.confirmations,
                        p.status,
                        p.is_late,
                        p.first_seen_at.isoformat(),
                    ]
                )
            yield buffer.getvalue()
            offset += len(payments)

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="proofpay-payments.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/payments/{payment_id}", response_model=PaymentView)
def get_payment(
    session: SessionDep, user: CurrentUser, payment_id: uuid.UUID
) -> PaymentOutput:
    merchant = _merchant(session, user)
    payment = session.exec(
        select(PaymentOutput)
        .join(Invoice)
        .where(PaymentOutput.id == payment_id, Invoice.merchant_id == merchant.id)
    ).first()
    if not payment:
        raise HTTPException(404, "Payment not found")
    return payment


@router.get("/receipts", response_model=ReceiptPage)
def list_receipts(
    session: SessionDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=100)] = None,
    sort: Annotated[str, Query()] = "-issued_at",
) -> dict[str, Any]:
    merchant = _merchant(session, user)
    if sort not in {"issued_at", "-issued_at"}:
        raise HTTPException(422, "Unsupported sort")
    stmt = select(Receipt).join(Invoice).where(Invoice.merchant_id == merchant.id)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                col(Receipt.reference).ilike(term),
                col(Invoice.title).ilike(term),
                col(Invoice.order_reference).ilike(term),
            )
        )
    count = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    order = col(Receipt.issued_at)
    data = session.exec(
        stmt.order_by(order.desc() if sort.startswith("-") else order.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    ids = [r.invoice_id for r in data]
    invoices = (
        session.exec(select(Invoice).where(col(Invoice.id).in_(ids))).all()
        if ids
        else []
    )
    payments = (
        session.exec(
            select(PaymentOutput).where(col(PaymentOutput.invoice_id).in_(ids))
        ).all()
        if ids
        else []
    )
    by_id = {invoice.id: invoice for invoice in invoices}
    by_invoice: dict[uuid.UUID, list[PaymentOutput]] = {}
    for payment in payments:
        by_invoice.setdefault(payment.invoice_id, []).append(payment)
    return {
        "data": [
            receipt_view(
                session, r, by_id.get(r.invoice_id), by_invoice.get(r.invoice_id, [])
            )
            for r in data
        ],
        "count": count,
    }


@router.get("/receipts/{receipt_id}", response_model=ReceiptView)
def get_receipt(
    session: SessionDep, user: CurrentUser, receipt_id: uuid.UUID
) -> ReceiptView:
    merchant = _merchant(session, user)
    receipt = session.exec(
        select(Receipt)
        .join(Invoice)
        .where(Receipt.id == receipt_id, Invoice.merchant_id == merchant.id)
    ).first()
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    return receipt_view(session, receipt)


@router.get("/public/receipts/{token}", response_model=PublicReceipt)
def public_receipt(session: SessionDep, token: str) -> PublicReceipt:
    receipt = session.exec(select(Receipt).where(Receipt.public_token == token)).first()
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    return PublicReceipt.model_validate(receipt_view(session, receipt).model_dump())


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    merchant = _merchant(session, user)
    invoices = session.exec(
        select(Invoice)
        .where(Invoice.merchant_id == merchant.id)
        .order_by(col(Invoice.created_at).desc())
    ).all()
    invoice_ids = [i.id for i in invoices]
    all_payments = (
        session.exec(
            select(PaymentOutput).where(col(PaymentOutput.invoice_id).in_(invoice_ids))
        ).all()
        if invoice_ids
        else []
    )
    grouped: dict[uuid.UUID, list[PaymentOutput]] = {}
    for payment in all_payments:
        grouped.setdefault(payment.invoice_id, []).append(payment)
    received = outstanding = 0
    counts = dict.fromkeys(("draft", "pending", "expired", "cancelled", "confirmed"), 0)
    for invoice in invoices:
        total, confirmed = sums(invoice, grouped.get(invoice.id, []))
        received += sum(
            p.amount_sats
            for p in grouped.get(invoice.id, [])
            if p.status != "orphaned"
            and p.network == invoice.network
            and p.confirmations >= invoice.required_confirmations
        )
        effective = payment_state(invoice, grouped.get(invoice.id, [])).status
        counts[effective] += 1
        if effective == "pending":
            outstanding += max(
                0,
                invoice.expected_amount_sats - min(total, invoice.expected_amount_sats),
            )
    return {
        "network": merchant.network,
        "currency": "BCH",
        "confirmed_received_sats": received,
        "outstanding_requested_sats": outstanding,
        "request_counts": counts,
        "recent_activity": invoice_views(session, list(invoices[:10])),
    }


@router.get("/dashboard/payment-history", response_model=PaymentHistoryPage)
def payment_history(
    session: SessionDep,
    user: CurrentUser,
    from_at: AwareDatetime,
    to_at: AwareDatetime,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if from_at >= to_at or to_at - from_at > timedelta(days=366):
        raise HTTPException(422, "Date range must be ordered and at most 366 days")
    merchant = _merchant(session, user)
    stmt = (
        select(PaymentOutput)
        .join(Invoice)
        .where(
            Invoice.merchant_id == merchant.id,
            PaymentOutput.first_seen_at >= from_at,
            PaymentOutput.first_seen_at < to_at,
        )
    )
    count = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    data = session.exec(
        stmt.order_by(col(PaymentOutput.first_seen_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "network": merchant.network,
        "currency": "BCH",
        "data": [PaymentView.model_validate(p, from_attributes=True) for p in data],
        "count": count,
    }
