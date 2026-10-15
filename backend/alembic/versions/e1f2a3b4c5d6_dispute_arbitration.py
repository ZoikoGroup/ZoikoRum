"""disputes: referral to external arbitration

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-15 15:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e1f2a3b4c5d6'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('arbitration', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='dispute')


def downgrade() -> None:
    op.drop_column('cases', 'arbitration', schema='dispute')
