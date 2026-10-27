"""Permanent destination reservations and durable scan scheduling.

Existing invoices are reserved once. Shared legacy destinations remain manual
claim-only; they are deliberately never assigned automatically.
"""

from alembic import op
import sqlalchemy as sa

revision = "3c68e4b2a910"
down_revision = "b6e8c1d4a2f0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "payment_output",
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invoice",
        sa.Column("scan_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invoice",
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invoice", sa.Column("watched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "address_reservation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("network", sa.String(20), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("network", "address", name="uq_reserved_destination"),
    )
    op.create_index(
        "ix_address_reservation_invoice_id", "address_reservation", ["invoice_id"]
    )
    # PostgreSQL DISTINCT ON preserves one reservation per legacy destination.
    # This also renders correctly in Alembic offline SQL generation.
    op.execute(
        sa.text("""
        INSERT INTO address_reservation (id, network, address, invoice_id, created_at)
        SELECT gen_random_uuid(), network, receiving_address, id, created_at
        FROM (SELECT DISTINCT ON (network, receiving_address)
            network, receiving_address, id, created_at
            FROM invoice ORDER BY network, receiving_address, created_at, id) AS destinations
    """)
    )


def downgrade():
    op.drop_column("payment_output", "last_attempted_at")
    op.drop_table("address_reservation")
    op.drop_column("invoice", "watched_at")
    op.drop_column("invoice", "last_scanned_at")
    op.drop_column("invoice", "scan_attempted_at")
