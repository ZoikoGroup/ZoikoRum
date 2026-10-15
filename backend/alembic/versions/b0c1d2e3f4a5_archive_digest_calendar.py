"""audit archive batches; notification digests and private calendar feed

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-10-16 18:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'b0c1d2e3f4a5'
down_revision = 'a9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'archives',
        sa.Column('from_seq', sa.BigInteger(), nullable=False),
        sa.Column('to_seq', sa.BigInteger(), nullable=False),
        sa.Column('record_count', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('object_key', sa.String(length=300), nullable=False),
        sa.Column('version_id', sa.String(length=200), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('to_seq'),
        schema='audit',
    )
    op.add_column('preferences', sa.Column('digest', sa.String(length=10), server_default='OFF', nullable=False), schema='notification')
    op.add_column('preferences', sa.Column('digest_sent_at', sa.DateTime(timezone=True), nullable=True), schema='notification')
    op.add_column('preferences', sa.Column('calendar_token_hash', sa.String(length=64), nullable=True), schema='notification')
    op.create_unique_constraint('uq_preferences_calendar_token_hash', 'preferences', ['calendar_token_hash'], schema='notification')


def downgrade() -> None:
    op.drop_constraint('uq_preferences_calendar_token_hash', 'preferences', schema='notification')
    for column in ('calendar_token_hash', 'digest_sent_at', 'digest'):
        op.drop_column('preferences', column, schema='notification')
    op.drop_table('archives', schema='audit')
