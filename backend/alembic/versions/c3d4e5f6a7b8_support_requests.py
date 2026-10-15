"""support requests

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-14 17:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS support')
    op.create_table(
        'requests',
        sa.Column('reference', sa.String(length=20), nullable=False),
        sa.Column('requester_identity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('topic', sa.String(length=30), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('assigned_to', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('first_response_due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('first_responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_requests')),
        sa.UniqueConstraint('reference', name=op.f('uq_requests_reference')),
        schema='support',
    )
    op.create_index('ix_support_requests_status', 'requests', ['status', 'created_at'], unique=False, schema='support')
    op.create_index(op.f('ix_support_requests_requester_identity_id'), 'requests', ['requester_identity_id'], unique=False, schema='support')
    op.create_table(
        'messages',
        sa.Column('request_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('author_identity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('from_staff', sa.Boolean(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['support.requests.id'], name=op.f('fk_messages_request_id_requests')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
        schema='support',
    )
    op.create_index('ix_support_messages_request', 'messages', ['request_id', 'created_at'], unique=False, schema='support')


def downgrade() -> None:
    op.drop_index('ix_support_messages_request', table_name='messages', schema='support')
    op.drop_table('messages', schema='support')
    op.drop_index(op.f('ix_support_requests_requester_identity_id'), table_name='requests', schema='support')
    op.drop_index('ix_support_requests_status', table_name='requests', schema='support')
    op.drop_table('requests', schema='support')
