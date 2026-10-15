"""contract termination requests

Revision ID: 9d2e3f4a5b6c
Revises: 8c1d2e3f4a5b
Create Date: 2026-10-14 13:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '9d2e3f4a5b6c'
down_revision = '8c1d2e3f4a5b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'termination_requests',
        sa.Column('contract_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('requested_by_identity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('requester_party', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.String(length=1000), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decided_by_identity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('decision_note', sa.String(length=1000), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contract_id'], ['contract.contracts.id'], name=op.f('fk_termination_requests_contract_id_contracts')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_termination_requests')),
        schema='contract',
    )
    op.create_index('ix_termination_requests_contract', 'termination_requests', ['contract_id', 'created_at'],
                    unique=False, schema='contract')


def downgrade() -> None:
    op.drop_index('ix_termination_requests_contract', table_name='termination_requests', schema='contract')
    op.drop_table('termination_requests', schema='contract')
