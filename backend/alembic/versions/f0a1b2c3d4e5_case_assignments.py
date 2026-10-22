"""admin: case owners and escalations across the staff console

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-10-21 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'f0a1b2c3d4e5'
down_revision = 'e9f0a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'case_assignments',
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('case_id', sa.String(length=80), nullable=False),
        sa.Column('owner_identity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('escalated', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('escalation_reason', sa.String(length=1000), nullable=True),
        sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'case_id', name='uq_case_assignments_kind_case'),
        schema='admin',
    )
    op.create_index(op.f('ix_admin_case_assignments_owner_identity_id'), 'case_assignments', ['owner_identity_id'],
                    unique=False, schema='admin')


def downgrade() -> None:
    op.drop_index(op.f('ix_admin_case_assignments_owner_identity_id'), table_name='case_assignments', schema='admin')
    op.drop_table('case_assignments', schema='admin')
