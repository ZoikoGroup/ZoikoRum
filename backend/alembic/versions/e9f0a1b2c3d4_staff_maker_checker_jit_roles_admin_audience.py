"""staff maker-checker approvals, just-in-time staff roles, admin session audience

admin.approval_requests: privileged staff actions wait for a second person's approval (admin/approvals.py).
identity.identities.platform_role_expiry: {role: end time} for time-limited staff roles.
identity.sessions.audience: ADMIN for sessions from the staff sign-in page, APP for every other session. Existing
sessions become APP, so staff sign in again on the staff sign-in page once after this release.

Revision ID: e9f0a1b2c3d4
Revises: 8f9e49f8e7c1
Create Date: 2026-10-21 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e9f0a1b2c3d4'
down_revision = '8f9e49f8e7c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('identities', sa.Column('platform_role_expiry', postgresql.JSONB(astext_type=sa.Text()),
                                          server_default='{}', nullable=False), schema='identity')
    op.add_column('sessions', sa.Column('audience', sa.String(length=10), server_default='APP', nullable=False),
                  schema='identity')
    op.create_table(
        'approval_requests',
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('summary', sa.String(length=300), nullable=False),
        sa.Column('target_key', sa.String(length=200), nullable=False),
        sa.Column('justification', sa.String(length=2000), nullable=False),
        sa.Column('requested_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approver_roles', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('decided_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_note', sa.String(length=1000), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('apply_error', sa.String(length=1000), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_approval_requests'),
        schema='admin',
    )
    for column in ('kind', 'target_key', 'requested_by', 'status'):
        op.create_index(f'ix_admin_approval_requests_{column}', 'approval_requests', [column], unique=False, schema='admin')


def downgrade() -> None:
    for column in ('kind', 'target_key', 'requested_by', 'status'):
        op.drop_index(f'ix_admin_approval_requests_{column}', table_name='approval_requests', schema='admin')
    op.drop_table('approval_requests', schema='admin')
    op.drop_column('sessions', 'audience', schema='identity')
    op.drop_column('identities', 'platform_role_expiry', schema='identity')
