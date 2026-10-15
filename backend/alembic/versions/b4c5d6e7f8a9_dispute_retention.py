"""disputes: retention date, legal hold

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-10-15 20:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('retain_until', sa.Date(), nullable=True), schema='dispute')
    op.add_column('cases', sa.Column('retention_basis', sa.String(length=200), nullable=True), schema='dispute')
    op.add_column('cases', sa.Column('legal_hold', sa.Boolean(), server_default='false', nullable=False), schema='dispute')
    op.add_column('cases', sa.Column('retention_review_due', sa.Boolean(), server_default='false', nullable=False), schema='dispute')


def downgrade() -> None:
    for column in ('retention_review_due', 'legal_hold', 'retention_basis', 'retain_until'):
        op.drop_column('cases', column, schema='dispute')
