"""contracts: retainer pause

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-15 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('contracts', sa.Column('paused_at', sa.DateTime(timezone=True), nullable=True), schema='contract')
    op.add_column('contracts', sa.Column('pause_reason', sa.String(length=500), nullable=True), schema='contract')


def downgrade() -> None:
    op.drop_column('contracts', 'pause_reason', schema='contract')
    op.drop_column('contracts', 'paused_at', schema='contract')
