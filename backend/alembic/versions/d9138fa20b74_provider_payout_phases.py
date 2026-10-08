"""Separate durable Connect transfers from bank payout attempts."""
from alembic import op
import sqlalchemy as sa

revision = "d9138fa20b74"
down_revision = "c8427d916a30"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payouts", sa.Column("transfer_ref", sa.String(100)), schema="payments")
    op.add_column("payouts", sa.Column("provider_attempt", sa.Integer(), nullable=False, server_default="0"), schema="payments")
    op.alter_column("payouts", "provider_attempt", server_default=None, schema="payments")


def downgrade():
    op.drop_column("payouts", "provider_attempt", schema="payments")
    op.drop_column("payouts", "transfer_ref", schema="payments")
