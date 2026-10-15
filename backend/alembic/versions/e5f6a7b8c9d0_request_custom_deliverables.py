"""requests: custom deliverables are flagged

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-14 19:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('requests', sa.Column('custom_deliverables', postgresql.JSONB(astext_type=sa.Text()),
                                        server_default=sa.text("'[]'::jsonb"), nullable=False), schema='proposal')
    op.alter_column('requests', 'custom_deliverables', server_default=None, schema='proposal')


def downgrade() -> None:
    op.drop_column('requests', 'custom_deliverables', schema='proposal')
