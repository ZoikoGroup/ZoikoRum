"""incident register

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-15 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'incidents',
        sa.Column('reference', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('severity', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('summary', sa.String(length=4000), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('contained_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('timeline', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('notifications', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('root_cause', sa.String(length=4000), nullable=True),
        sa.Column('remediation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('review', sa.String(length=8000), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_incidents')),
        sa.UniqueConstraint('reference', name=op.f('uq_incidents_reference')),
        schema='admin',
    )


def downgrade() -> None:
    op.drop_table('incidents', schema='admin')
