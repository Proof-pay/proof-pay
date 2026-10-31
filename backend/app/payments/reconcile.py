"""Run once per schedule: python -m app.payments.reconcile."""

import logging

from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import Invoice, PaymentOutput
from app.payments.chain import BCHNodeProvider
from app.payments.service import aware, now, outputs, recheck_output, refresh_state

logger = logging.getLogger(__name__)


def reconcile_invoice(
    session: Session, invoice: Invoice, provider: BCHNodeProvider
) -> tuple[int, int]:
    """Reverify existing allocations and calculate state once, in one transaction.

    No discovery or attribution occurs here. The invoice lock serializes claims,
    scheduled reconciliation and repair; outputs are refreshed after that lock.
    """
    checked = failed = 0
    for output in outputs(session, invoice):
        success = recheck_output(session, output, provider, update_state=False)
        output.last_attempted_at = now()
        session.add(output)
        checked += 1
        failed += not success
    refresh_state(session, invoice)
    return checked, failed


def run_once(limit: int = 500) -> tuple[int, int]:
    provider = BCHNodeProvider()
    checked = failed = 0
    with Session(engine) as session:
        # Pick the oldest outputs, then process all allocations for each selected
        # invoice atomically. A receipt must not snapshot half-rechecked evidence.
        invoice_ids = session.exec(
            select(PaymentOutput.invoice_id)
            .order_by(
                col(PaymentOutput.last_attempted_at).asc().nulls_first(),
                col(PaymentOutput.id),
            )
            .limit(limit)
        ).all()
    for invoice_id in dict.fromkeys(invoice_ids):
        with Session(engine) as session:
            invoice = session.exec(
                select(Invoice).where(Invoice.id == invoice_id).with_for_update()
            ).first()
            if not invoice:
                continue
            try:
                count, errors = reconcile_invoice(session, invoice, provider)
                session.commit()
                checked += count
                failed += errors
            except Exception:
                session.rollback()
                failed += 1
                # Persist an attempt, never a successful verification timestamp.
                for output in outputs(session, invoice):
                    output.last_attempted_at = now()
                    session.add(output)
                session.commit()
                logger.error(
                    "Invoice payment reconciliation failed for request %s", invoice_id
                )
    with Session(engine) as session:
        pending = session.exec(
            select(Invoice)
            .where(Invoice.status == "pending", Invoice.expires_at <= now())
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
        for invoice in pending:
            if aware(invoice.expires_at) <= now():
                refresh_state(session, invoice)
        session.commit()
    return checked, failed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count, errors = run_once()
    logger.info(
        "Reconciled %d outputs; %d provider or processing failures", count, errors
    )
    if errors:
        raise SystemExit(1)
