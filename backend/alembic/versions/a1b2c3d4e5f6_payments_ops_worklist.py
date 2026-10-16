"""payments: refund failure reason and Financial Operations resolutions

Revision ID: a1b2c3d4e5f6
Revises: 9d2e3f4a5b6c
Create Date: 2026-10-14 15:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a1b2c3d4e5f6'
down_revision = '9d2e3f4a5b6c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('refunds', sa.Column('failure_message', sa.String(length=300), nullable=True), schema='payments')
    op.create_table(
        'ops_resolutions',
        sa.Column('item_kind', sa.String(length=30), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('outcome', sa.String(length=30), nullable=False),
        sa.Column('note', sa.String(length=1000), nullable=False),
        sa.Column('resolved_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ops_resolutions')),
        sa.UniqueConstraint('item_kind', 'item_id', name=op.f('uq_ops_resolutions_item_kind_item_id')),
        schema='payments',
    )


def downgrade() -> None:
    op.drop_table('ops_resolutions', schema='payments')
    op.drop_column('refunds', 'failure_message', schema='payments')
