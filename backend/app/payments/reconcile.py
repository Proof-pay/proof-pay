"""Run once per schedule: python -m app.payments.reconcile."""

import logging

from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import Invoice, PaymentOutput
from app.payments.chain import BCHNodeProvider
from app.payments.service import aware, now, recheck_output, refresh_state

logger = logging.getLogger(__name__)


def run_once(limit: int = 500) -> tuple[int, int]:
    provider = BCHNodeProvider()
    checked = failed = 0
    with Session(engine) as session:
        output_ids = session.exec(
            select(PaymentOutput.id)
            .order_by(
                col(PaymentOutput.last_attempted_at).asc().nulls_first(),
                col(PaymentOutput.id),
            )
            .limit(limit)
        ).all()
    for output_id in output_ids:
        with Session(engine) as session:
            output = session.get(PaymentOutput, output_id)
            if not output:
                continue
            before = output.last_checked_at
            try:
                recheck_output(session, output, provider)
                output.last_attempted_at = now()
                session.add(output)
                session.commit()
                checked += 1
                if output.last_checked_at == before:
                    failed += 1
            except Exception:
                session.rollback()
                failed += 1
                output.last_attempted_at = now()
                session.add(output)
                session.commit()
                logger.error("Payment output reconciliation failed")
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
