"""buyer: organisation API keys

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-10-16 14:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'f8a9b0c1d2e3'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'api_keys',
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('prefix', sa.String(length=16), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('scope', sa.String(length=10), nullable=False),
        sa.Column('tier', sa.String(length=12), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['buyer.organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash'),
        sa.UniqueConstraint('prefix'),
        schema='buyer',
    )
    op.create_index('ix_buyer_api_keys_organization_id', 'api_keys', ['organization_id'], unique=False, schema='buyer')


def downgrade() -> None:
    op.drop_index('ix_buyer_api_keys_organization_id', table_name='api_keys', schema='buyer')
    op.drop_table('api_keys', schema='buyer')
