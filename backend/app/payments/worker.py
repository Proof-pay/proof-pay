"""Single durable poller, independently deployable from API workers."""

import logging
import time

from sqlalchemy import text
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.models import Invoice
from app.payments.chain import BCHNodeProvider
from app.payments.reconcile import run_once
from app.payments.service import now, reconcile_claim, verify_transaction

logger = logging.getLogger(__name__)


def discover(limit: int = 100) -> tuple[int, int]:
    provider = BCHNodeProvider()
    checked = failed = 0
    with Session(engine) as session:
        ids = session.exec(
            select(Invoice.id)
            .where(col(Invoice.watched_at).is_not(None), Invoice.status != "draft")
            .order_by(
                col(Invoice.scan_attempted_at).asc().nulls_first(), col(Invoice.id)
            )
            .limit(limit)
        ).all()
    for invoice_id in ids:
        with Session(engine) as session:
            invoice = session.exec(
                select(Invoice).where(Invoice.id == invoice_id).with_for_update()
            ).one()
            try:
                for txid in provider.incoming(
                    invoice.receiving_address, invoice.network
                ):
                    # All matching outputs belong to this permanently reserved destination.
                    matches = verify_transaction(
                        provider, txid, invoice.network, invoice.receiving_address
                    )
                    if matches:
                        reconcile_claim(
                            session,
                            invoice,
                            txid,
                            provider,
                            [vout for vout, _, _ in matches],
                        )
                invoice.scan_attempted_at = now()
                invoice.last_scanned_at = now()
                session.add(invoice)
                session.commit()
                checked += 1
            except Exception:
                session.rollback()
                failed += 1
                invoice.scan_attempted_at = now()
                session.add(invoice)
                session.commit()
                # Avoid addresses, RPC credentials and session data in logs.
                logger.warning(
                    "Incoming payment discovery failed for request %s", invoice_id
                )
    return checked, failed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    backoff = settings.BCH_RECONCILIATION_INTERVAL_SECONDS
    # Session advisory lock held on a dedicated connection: multiple deployed
    # replicas cannot run competing watchers. Released by PostgreSQL on crash.
    with engine.connect() as connection:
        if not connection.execute(
            text("SELECT pg_try_advisory_lock(7129674001)")
        ).scalar():
            logger.info("Another reconciliation worker holds the lock")
            return
        connection.commit()
        while True:
            # Fail the process if the lock connection is lost; Compose restarts it.
            connection.execute(text("SELECT 1"))
            connection.commit()
            try:
                discovered, failures = discover()
                checked, errors = run_once()
                logger.info(
                    "Scanned %d requests; rechecked %d outputs; failures=%d",
                    discovered,
                    checked,
                    failures + errors,
                )
                backoff = (
                    min(300, backoff * 2)
                    if failures + errors
                    else settings.BCH_RECONCILIATION_INTERVAL_SECONDS
                )
            except Exception:
                logger.error("Reconciliation cycle failed; retrying")
                backoff = min(300, backoff * 2)
            time.sleep(backoff)


if __name__ == "__main__":
    main()
