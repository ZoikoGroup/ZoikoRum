"""verification: human second look at automatic approvals

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-14 18:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('second_look', sa.String(length=20), nullable=True), schema='verification')
    op.add_column('cases', sa.Column('second_look_by', postgresql.UUID(as_uuid=True), nullable=True), schema='verification')
    op.add_column('cases', sa.Column('second_look_at', sa.DateTime(timezone=True), nullable=True), schema='verification')
    op.create_index(op.f('ix_verification_cases_second_look'), 'cases', ['second_look'], unique=False, schema='verification')


def downgrade() -> None:
    op.drop_index(op.f('ix_verification_cases_second_look'), table_name='cases', schema='verification')
    op.drop_column('cases', 'second_look_at', schema='verification')
    op.drop_column('cases', 'second_look_by', schema='verification')
    op.drop_column('cases', 'second_look', schema='verification')
