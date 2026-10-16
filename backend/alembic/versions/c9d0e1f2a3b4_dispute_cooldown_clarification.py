"""disputes: early-resolution preference, cooldown, clarifications, timeline links

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-15 11:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('prefers_early_resolution', sa.Boolean(), server_default='false', nullable=False), schema='dispute')
    op.add_column('cases', sa.Column('cooldown_used_by', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False), schema='dispute')
    op.add_column('cases', sa.Column('clarifications', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False), schema='dispute')
    op.add_column('timeline', sa.Column('ref', sa.String(length=100), nullable=True), schema='dispute')


def downgrade() -> None:
    op.drop_column('timeline', 'ref', schema='dispute')
    op.drop_column('cases', 'clarifications', schema='dispute')
    op.drop_column('cases', 'cooldown_used_by', schema='dispute')
    op.drop_column('cases', 'prefers_early_resolution', schema='dispute')
