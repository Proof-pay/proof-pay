"""Merchant scoped destinations and separate, unallocated chain observations.

Keep the destination uniqueness constraint: it now protects merchant isolation,
not invoice exclusivity. Unknown or conflicting historical ownership stays blocked.
"""
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

revision = "7e91bc24a610"
down_revision = "3c68e4b2a910"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("address_reservation", sa.Column("merchant_id", sa.Uuid(), nullable=True))
    op.create_index("ix_address_reservation_merchant_id", "address_reservation", ["merchant_id"])
    op.create_table(
        "detected_output",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("network", sa.String(20), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("txid", sa.String(64), nullable=False),
        sa.Column("vout", sa.Integer(), nullable=False),
        sa.Column("amount_sats", sa.BigInteger(), nullable=False),
        sa.Column("confirmations", sa.Integer(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("network", "txid", "vout", name="uq_detected_output"),
    )
    op.create_index("ix_detected_output_address", "detected_output", ["address"])
    # Data migration is intentionally online, using portable SQLAlchemy types.
    # Never infer ownership from a submitted address alone.
    from app.payments.chain import normalize_address

    bind = op.get_bind()
    metadata = sa.MetaData()
    invoices = sa.Table("invoice", metadata, autoload_with=bind)
    reservations = sa.Table("address_reservation", metadata, autoload_with=bind)
    history = list(bind.execute(sa.select(invoices)).mappings())
    original = list(bind.execute(sa.select(reservations)).mappings())
    by_id = {row["id"]: row for row in history}
    owners = defaultdict(set)
    representatives = {}

    def canonical(network, address):
        try:
            return normalize_address(address, network)
        except (ValueError, KeyError):
            return address

    for row in history:
        address = canonical(row["network"], row["receiving_address"])
        key = row["network"], address
        owners[key].add(row["merchant_id"])
        representatives[key] = row["id"]
        if address != row["receiving_address"]:
            bind.execute(invoices.update().where(invoices.c.id == row["id"]).values(receiving_address=address))
    for row in original:
        key = row["network"], canonical(row["network"], row["address"])
        invoice = by_id.get(row["invoice_id"])
        owners[key].add(invoice["merchant_id"] if invoice else None)
        representatives[key] = row["invoice_id"]
    existing = {(row["network"], row["address"]) for row in original}
    for row in original:
        key = row["network"], canonical(row["network"], row["address"])
        owner = next(iter(owners[key])) if len(owners[key]) == 1 else None
        bind.execute(reservations.update().where(reservations.c.id == row["id"]).values(merchant_id=owner))
    for key, merchants in owners.items():
        if key not in existing:
            bind.execute(reservations.insert().values(id=uuid.uuid4(), network=key[0], address=key[1],
                invoice_id=representatives[key], merchant_id=next(iter(merchants)) if len(merchants) == 1 else None,
                created_at=datetime.now(UTC)))


def downgrade():
    raise RuntimeError("Unsafe downgrade: historical destination reuse cannot restore exclusive invoice allocation. Restore a pre-migration backup instead.")
