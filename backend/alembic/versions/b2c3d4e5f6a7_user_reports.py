"""user reports

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-14 16:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_reports',
        sa.Column('reporter_identity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject_type', sa.String(length=30), nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=False),
        sa.Column('description', sa.String(length=2000), nullable=False),
        sa.Column('confidential', sa.Boolean(), nullable=False),
        sa.Column('possible_retaliation', sa.Boolean(), nullable=False),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('outcome', sa.String(length=20), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_user_reports')),
        schema='admin',
    )
    op.create_index(op.f('ix_admin_user_reports_reporter_identity_id'), 'user_reports', ['reporter_identity_id'], unique=False, schema='admin')
    op.create_index(op.f('ix_admin_user_reports_case_id'), 'user_reports', ['case_id'], unique=False, schema='admin')


def downgrade() -> None:
    op.drop_index(op.f('ix_admin_user_reports_case_id'), table_name='user_reports', schema='admin')
    op.drop_index(op.f('ix_admin_user_reports_reporter_identity_id'), table_name='user_reports', schema='admin')
    op.drop_table('user_reports', schema='admin')
