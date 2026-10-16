"""firm on search results: the firm a professional practises under, and whether it is verified

Revision ID: b7f3e91c4d20
Revises: a0b1c2d3e4f5
Create Date: 2026-10-16 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7f3e91c4d20'
down_revision = 'a0b1c2d3e4f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('professional_documents', sa.Column('firm_id', sa.UUID(), nullable=True), schema='search')
    op.add_column('professional_documents', sa.Column('firm_name', sa.String(length=200), nullable=True), schema='search')
    op.add_column('professional_documents', sa.Column('firm_verified', sa.Boolean(), server_default='false', nullable=False),
                  schema='search')


def downgrade() -> None:
    op.drop_column('professional_documents', 'firm_verified', schema='search')
    op.drop_column('professional_documents', 'firm_name', schema='search')
    op.drop_column('professional_documents', 'firm_id', schema='search')
