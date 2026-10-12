"""Retainer pause funding controls."""
from alembic import op
import sqlalchemy as sa
revision = "b7309c12e541"
down_revision = "f1360ce42a96"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("contracts", sa.Column("retainer_paused", sa.Boolean(), nullable=False, server_default=sa.false()), schema="contract")

def downgrade():
    op.drop_column("contracts", "retainer_paused", schema="contract")
