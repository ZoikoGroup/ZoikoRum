"""identity: single sign-on connections, sign-in states, external logins

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-10-17 09:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'c1d2e3f4a5b6'
down_revision = 'b0c1d2e3f4a5'
branch_labels = None
depends_on = None


def _base():
    return [sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)]


def upgrade() -> None:
    op.create_table(
        'sso_connections',
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('issuer', sa.String(length=500), nullable=False),
        sa.Column('client_id', sa.String(length=300), nullable=False),
        sa.Column('client_secret_enc', sa.String(length=2000), nullable=False),
        sa.Column('email_domains', postgresql.ARRAY(sa.String(length=253)), nullable=False),
        sa.Column('enforce', sa.Boolean(), nullable=False),
        sa.Column('jit', sa.Boolean(), nullable=False),
        sa.Column('default_roles', postgresql.ARRAY(sa.String(length=40)), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('scim_token_hash', sa.String(length=64), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        *_base(),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('organization_id'), sa.UniqueConstraint('scim_token_hash'),
        schema='identity',
    )
    op.create_table(
        'sso_logins',
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('nonce', sa.String(length=100), nullable=False),
        sa.Column('code_verifier', sa.String(length=200), nullable=False),
        sa.Column('link_identity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        *_base(),
        sa.PrimaryKeyConstraint('id'),
        schema='identity',
    )
    op.create_table(
        'external_logins',
        sa.Column('identity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('subject', sa.String(length=600), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(['identity_id'], ['identity.identities.id']),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('subject'),
        schema='identity',
    )
    op.create_index('ix_identity_external_logins_identity_id', 'external_logins', ['identity_id'], unique=False, schema='identity')


def downgrade() -> None:
    op.drop_index('ix_identity_external_logins_identity_id', table_name='external_logins', schema='identity')
    op.drop_table('external_logins', schema='identity')
    op.drop_table('sso_logins', schema='identity')
    op.drop_table('sso_connections', schema='identity')
