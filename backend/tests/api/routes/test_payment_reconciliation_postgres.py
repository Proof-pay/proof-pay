"""Exercise real row locks and allocation uniqueness with deterministic evidence.

Run with the rest of the backend suite against an isolated PostgreSQL database.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    AddressReservation,
    Invoice,
    Merchant,
    PaymentOutput,
    Receipt,
    User,
)
from app.payments.service import reconcile_claim

ADDRESS = "bitcoincash:qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a"


@pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Requires PostgreSQL row locks"
)
def test_concurrent_verified_claims_allocate_output_to_exactly_one_invoice(db):
    user = User(
        email=f"concurrent-{uuid.uuid4().hex}@example.com", hashed_password="test"
    )
    db.add(user)
    db.flush()
    merchant = Merchant(user_id=user.id, business_name="Concurrent allocation test")
    db.add(merchant)
    db.flush()
    invoices = [
        Invoice(
            merchant_id=merchant.id,
            network="mainnet",
            receiving_address=ADDRESS,
            order_reference=f"RACE-{uuid.uuid4().hex}",
            expected_amount_sats=100000,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        for _ in range(2)
    ]
    db.add_all(invoices)
    db.flush()
    db.add(
        AddressReservation(
            network="mainnet",
            address=ADDRESS,
            merchant_id=merchant.id,
            invoice_id=invoices[0].id,
        )
    )
    db.commit()
    ids = [invoice.id for invoice in invoices]
    txid = uuid.uuid4().hex * 2
    verified = Barrier(2)

    class Provider:
        def transaction(self, requested_txid, network):
            assert requested_txid == txid and network == "mainnet"
            verified.wait(timeout=10)
            return {
                "txid": txid,
                "confirmations": 2,
                "vout": [
                    {
                        "n": 0,
                        "value": Decimal("0.001"),
                        "scriptPubKey": {"addresses": [ADDRESS]},
                    }
                ],
            }

    def claim(invoice_id):
        with Session(engine) as session:
            invoice = session.exec(
                select(Invoice).where(Invoice.id == invoice_id).with_for_update()
            ).one()
            try:
                reconcile_claim(session, invoice, txid, Provider(), [0])
                session.commit()
                return "allocated"
            except HTTPException as exc:
                session.rollback()
                assert exc.status_code == 409
                return "conflict"
            except IntegrityError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(claim, ids))
    assert sorted(results) == ["allocated", "conflict"]
    with Session(engine) as session:
        allocations = session.exec(
            select(PaymentOutput).where(PaymentOutput.txid == txid)
        ).all()
        assert len(allocations) == 1
        receipts = session.exec(
            select(Receipt).where(Receipt.invoice_id.in_(ids))
        ).all()
        assert (
            len(receipts) == 1 and receipts[0].invoice_id == allocations[0].invoice_id
        )
        assert sum(session.get(Invoice, id_).status == "confirmed" for id_ in ids) == 1
