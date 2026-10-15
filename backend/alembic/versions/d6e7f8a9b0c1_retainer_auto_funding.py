"""escrow: retainer auto-funding from a saved payment method

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-10-16 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd6e7f8a9b0c1'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('auto_fund_token', sa.String(length=120), nullable=True), schema='escrow')
    op.add_column('accounts', sa.Column('auto_fund_identity_id', postgresql.UUID(as_uuid=True), nullable=True), schema='escrow')
    op.add_column('accounts', sa.Column('auto_fund_enabled_at', sa.DateTime(timezone=True), nullable=True), schema='escrow')


def downgrade() -> None:
    for column in ('auto_fund_enabled_at', 'auto_fund_identity_id', 'auto_fund_token'):
        op.drop_column('accounts', column, schema='escrow')
