"""professionals: enterprise readiness designation; search: enterprise-ready filter

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-10-15 22:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('professionals', sa.Column('enterprise_status', sa.String(length=20), server_default='NONE', nullable=False), schema='professional')
    op.add_column('professionals', sa.Column('enterprise_attestation', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='professional')
    op.add_column('professionals', sa.Column('enterprise_applied_at', sa.DateTime(timezone=True), nullable=True), schema='professional')
    op.add_column('professionals', sa.Column('enterprise_decided_at', sa.DateTime(timezone=True), nullable=True), schema='professional')
    op.add_column('professionals', sa.Column('enterprise_decision_reason', sa.String(length=500), nullable=True), schema='professional')
    op.add_column('professional_documents', sa.Column('enterprise_ready', sa.Boolean(), server_default='false', nullable=False), schema='search')


def downgrade() -> None:
    op.drop_column('professional_documents', 'enterprise_ready', schema='search')
    for column in ('enterprise_decision_reason', 'enterprise_decided_at', 'enterprise_applied_at', 'enterprise_attestation', 'enterprise_status'):
        op.drop_column('professionals', column, schema='professional')
