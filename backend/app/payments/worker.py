"""Single durable poller, independently deployable from API workers."""

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import func, text
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.models import AddressReservation, Invoice
from app.payments.chain import BCHNodeProvider
from app.payments.reconcile import run_once
from app.payments.service import (
    associate_destination,
    now,
    reconcile_claim,
    review_transaction,
)

logger = logging.getLogger(__name__)


def discover(limit: int = 100) -> tuple[int, int]:
    provider = BCHNodeProvider()
    checked = failed = 0
    with Session(engine) as session:
        destinations = session.exec(
            select(Invoice.network, Invoice.receiving_address)
            .where(col(Invoice.watched_at).is_not(None), Invoice.status != "draft")
            .group_by(Invoice.network, Invoice.receiving_address)
            .order_by(
                func.min(Invoice.scan_attempted_at).asc().nulls_first(),
                Invoice.network,
                Invoice.receiving_address,
            )
            .limit(limit)
        ).all()
    for network, address in destinations:
        with Session(engine) as session:
            invoices = session.exec(
                select(Invoice)
                .where(
                    Invoice.network == network,
                    Invoice.receiving_address == address,
                    col(Invoice.watched_at).is_not(None),
                    Invoice.status != "draft",
                )
                .order_by(col(Invoice.id))
            ).all()
            if not invoices:
                continue
            invoice_id = invoices[0].id
            try:
                # Representative only for destination observation. It grants no
                # attribution; automatic credit requires the permanent association
                # to identify this exact invoice as the only request ever tracked.
                invoice = invoices[0]
                for txid in provider.incoming(
                    invoice.receiving_address, invoice.network
                ):
                    matches = review_transaction(session, invoice, txid, provider)
                    # Observations do not need an invoice lock. Release their
                    # association lock before acquiring invoice -> association,
                    # the same lock order used by authenticated claims/edits.
                    session.commit()
                    eligible = [row["vout"] for row in matches if not row["allocated"]]
                    if eligible:
                        invoice = session.exec(
                            select(Invoice)
                            .where(Invoice.id == invoice_id)
                            .with_for_update()
                            .execution_options(populate_existing=True)
                        ).one()
                        associate_destination(
                            session, invoice, invoice.receiving_address
                        )
                        association = session.exec(
                            select(AddressReservation)
                            .where(
                                AddressReservation.network == invoice.network,
                                AddressReservation.address == invoice.receiving_address,
                            )
                            .with_for_update()
                        ).one()
                        if (
                            association.auto_allocate
                            and association.invoice_id == invoice.id
                        ):
                            reconcile_claim(session, invoice, txid, provider, eligible)
                        session.commit()
                for request in invoices:
                    request.scan_attempted_at = now()
                    request.last_scanned_at = now()
                    session.add(request)
                session.commit()
                checked += 1
            except Exception:
                session.rollback()
                failed += 1
                for request in invoices:
                    request.scan_attempted_at = now()
                    session.add(request)
                session.commit()
                # Avoid addresses, RPC credentials and session data in logs.
                logger.warning(
                    "Incoming payment discovery failed for request %s", invoice_id
                )
    return checked, failed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    interval = settings.BCH_RECONCILIATION_INTERVAL_SECONDS
    # Discovery has separate scheduling: historical address scans or discovery
    # failures must not postpone reorg/confirmation checks for allocated outputs.
    # Only the advisory-lock owner creates this executor; API processes never do.
    with engine.connect() as connection, ThreadPoolExecutor(max_workers=1) as discovery:
        if not connection.execute(
            text("SELECT pg_try_advisory_lock(7129674001)")
        ).scalar():
            logger.info("Another reconciliation worker holds the lock")
            return
        connection.commit()
        pending: Future[tuple[int, int]] | None = None
        while True:
            cycle_start = time.monotonic()
            # Fail the process if the lock connection is lost; Compose restarts it.
            connection.execute(text("SELECT 1"))
            connection.commit()
            try:
                checked, errors = run_once()
                logger.info(
                    "Rechecked %d allocated outputs; failures=%d", checked, errors
                )
            except Exception:
                logger.error(
                    "Allocated payment reconciliation failed; retrying next interval"
                )
            if pending is not None and pending.done():
                try:
                    scanned, failures = pending.result()
                    logger.info(
                        "Scanned %d destinations; failures=%d", scanned, failures
                    )
                except Exception:
                    logger.error("Payment discovery failed; retrying next interval")
                pending = None
            if pending is None:
                pending = discovery.submit(discover)
            # Never apply discovery's global backoff to successful evidence checks.
            time.sleep(max(1, interval - (time.monotonic() - cycle_start)))


if __name__ == "__main__":
    main()
