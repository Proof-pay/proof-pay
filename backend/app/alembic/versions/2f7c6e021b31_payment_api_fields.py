"""Payment API fields and output identity.

Revision ID: 2f7c6e021b31
Revises: 8d58bfb48f57
"""

from alembic import op
import sqlalchemy as sa

revision = "2f7c6e021b31"
down_revision = "8d58bfb48f57"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("merchant", sa.Column("contact_email", sa.String(255)))
    op.add_column("merchant", sa.Column("contact_phone", sa.String(50)))
    op.add_column("merchant", sa.Column("receiving_address", sa.String(255)))
    op.add_column("merchant", sa.Column("network", sa.String(20), nullable=False, server_default="mainnet"))
    op.add_column("merchant", sa.Column("default_expiry_hours", sa.Integer(), nullable=False, server_default="24"))
    op.add_column("merchant", sa.Column("required_confirmations", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("invoice", sa.Column("title", sa.String(255), nullable=False, server_default=""))
    op.add_column("invoice", sa.Column("payment_status", sa.String(30), nullable=False, server_default="pending"))
    op.add_column("invoice", sa.Column("issued_at", sa.DateTime(timezone=True)))
    op.add_column("invoice", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.add_column("invoice", sa.Column("fiat_reference_amount", sa.String(40)))
    op.add_column("invoice", sa.Column("fiat_currency", sa.String(3)))
    op.add_column("invoice", sa.Column("idempotency_key", sa.String(128)))
    op.add_column("invoice", sa.Column("idempotency_hash", sa.String(64)))
    op.create_unique_constraint("uq_invoice_merchant_idempotency", "invoice", ["merchant_id", "idempotency_key"])
    op.create_index("ix_invoice_merchant_status", "invoice", ["merchant_id", "status"])
    op.add_column("payment_output", sa.Column("is_late", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_constraint("uq_payment_output_txid_vout", "payment_output", type_="unique")
    op.create_unique_constraint("uq_payment_output_network_txid_vout", "payment_output", ["network", "txid", "vout"])
    op.add_column("receipt", sa.Column("reference", sa.String(32)))
    op.add_column("receipt", sa.Column("invoice_reference", sa.String(255), nullable=False, server_default=""))
    op.add_column("receipt", sa.Column("merchant_name", sa.String(255), nullable=False, server_default=""))
    op.add_column("receipt", sa.Column("amount_sats", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("receipt", sa.Column("network", sa.String(20), nullable=False, server_default="mainnet"))
    op.add_column("receipt", sa.Column("required_confirmations", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("receipt", sa.Column("output_refs", sa.Text(), nullable=False, server_default="[]"))
    op.execute(sa.text("UPDATE receipt SET reference = 'PP-' || upper(substr(replace(id::text, '-', ''), 1, 16))"))
    op.alter_column("receipt", "reference", nullable=False)
    op.create_index("ix_receipt_reference", "receipt", ["reference"], unique=True)


def downgrade():
    op.drop_index("ix_receipt_reference", table_name="receipt")
    for name in ("output_refs", "required_confirmations", "network", "amount_sats", "merchant_name", "invoice_reference", "reference"):
        op.drop_column("receipt", name)
    op.drop_constraint("uq_payment_output_network_txid_vout", "payment_output", type_="unique")
    op.create_unique_constraint("uq_payment_output_txid_vout", "payment_output", ["txid", "vout"])
    op.drop_column("payment_output", "is_late")
    op.drop_index("ix_invoice_merchant_status", table_name="invoice")
    op.drop_constraint("uq_invoice_merchant_idempotency", "invoice", type_="unique")
    for name in ("idempotency_hash", "idempotency_key", "fiat_currency", "fiat_reference_amount", "updated_at", "issued_at", "payment_status", "title"):
        op.drop_column("invoice", name)
    for name in ("required_confirmations", "default_expiry_hours", "network", "receiving_address", "contact_phone", "contact_email"):
        op.drop_column("merchant", name)
