"""saved searches: daily new-match alerts

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-14 20:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('saved_searches', sa.Column('alerts_on', sa.Boolean(), server_default=sa.true(), nullable=False),
                  schema='marketplace')
    op.alter_column('saved_searches', 'alerts_on', server_default=None, schema='marketplace')
    op.add_column('saved_searches', sa.Column('last_alerted_at', sa.DateTime(timezone=True), nullable=True), schema='marketplace')


def downgrade() -> None:
    op.drop_column('saved_searches', 'last_alerted_at', schema='marketplace')
    op.drop_column('saved_searches', 'alerts_on', schema='marketplace')
