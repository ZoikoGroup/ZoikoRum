"""authenticator codes are single-use

Revision ID: 8c1d2e3f4a5b
Revises: 710d1280b58a
Create Date: 2026-10-14 12:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '8c1d2e3f4a5b'
down_revision = '710d1280b58a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('identities', sa.Column('mfa_totp_last_step', sa.BigInteger(), nullable=True), schema='identity')


def downgrade() -> None:
    op.drop_column('identities', 'mfa_totp_last_step', schema='identity')
