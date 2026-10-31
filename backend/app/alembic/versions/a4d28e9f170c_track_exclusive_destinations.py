"""Track provable single-request destination history going forward.

All historical destinations remain manual: their exclusivity cannot be proven.
New destinations become automatic only in the association-creation transaction;
any reuse permanently clears that permission, including deleted/edited drafts.
"""
from alembic import op
import sqlalchemy as sa

revision = "a4d28e9f170c"
down_revision = "7e91bc24a610"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("address_reservation", sa.Column("auto_allocate", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    raise RuntimeError("Unsafe downgrade: removing tracked exclusivity can re-enable unsafe historical attribution in older workers")
