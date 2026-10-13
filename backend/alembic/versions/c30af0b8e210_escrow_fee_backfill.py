"""escrow fee backfill

Engagements that started before the fee was recorded per escrow account keep the fee in force when this runs, so a later
change of ZK_PLATFORM_FEE_BPS never alters an engagement that was already signed.

Revision ID: c30af0b8e210
Revises: 632f70603204
Create Date: 2026-10-12 15:37:36.211286
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from zoikorum.config import get_settings

revision = 'c30af0b8e210'
down_revision = '632f70603204'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE escrow.accounts SET fee_bps = :bps WHERE fee_bps IS NULL")
               .bindparams(bps=get_settings().platform_fee_bps))


def downgrade() -> None:
    pass  # the recorded fees stay: forgetting them would let a fee change reach signed engagements
