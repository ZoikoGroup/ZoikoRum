"""SAML SSO, SCIM groups, enterprise session policy, sign-in risk signals, escrow ledger snapshots

Identity: sso_connections gets protocol (OIDC | SAML, existing rows OIDC), the SAML identity provider's entity id,
sign-on address and signing certificates, and the SCIM group-to-role map; sso_logins keeps a verified SAML assertion
until the web app redeems it; sessions record their sign-in method (idp; existing sessions NULL, treated as PASSWORD).
New tables: org_session_policies, scim_groups, sign_in_signals.

Escrow: ledger_snapshots (periodic per-account balances and integrity checks; the ledger itself is unchanged).

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-10-23 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'b7c8d9e0f1a2'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sso_connections', sa.Column('protocol', sa.String(length=10), server_default='OIDC', nullable=False), schema='identity')
    op.add_column('sso_connections', sa.Column('saml_idp_entity_id', sa.String(length=500), nullable=True), schema='identity')
    op.add_column('sso_connections', sa.Column('saml_sso_url', sa.String(length=1000), nullable=True), schema='identity')
    op.add_column('sso_connections', sa.Column('saml_certificates', postgresql.JSONB(astext_type=sa.Text()), server_default='[]',
                                               nullable=False), schema='identity')
    op.add_column('sso_connections', sa.Column('group_role_map', postgresql.JSONB(astext_type=sa.Text()), server_default='{}',
                                               nullable=False), schema='identity')
    op.add_column('sso_logins', sa.Column('assertion', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='identity')
    op.add_column('sessions', sa.Column('idp', sa.String(length=20), nullable=True), schema='identity')

    op.create_table('org_session_policies',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('max_session_seconds', sa.Integer(), nullable=True),
    sa.Column('idle_timeout_seconds', sa.Integer(), nullable=True),
    sa.Column('require_mfa', sa.Boolean(), nullable=False),
    sa.Column('allowed_idps', sa.ARRAY(sa.String(length=20)), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_org_session_policies')),
    sa.UniqueConstraint('organization_id', name=op.f('uq_org_session_policies_organization_id')),
    schema='identity'
    )
    op.create_table('scim_groups',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=True),
    sa.Column('member_ids', sa.ARRAY(sa.UUID()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scim_groups')),
    sa.UniqueConstraint('organization_id', 'display_name', name='uq_scim_group_name'),
    schema='identity'
    )
    op.create_index(op.f('ix_identity_scim_groups_organization_id'), 'scim_groups', ['organization_id'], unique=False, schema='identity')
    op.create_table('sign_in_signals',
    sa.Column('identity_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('device', sa.String(length=100), nullable=False),
    sa.Column('signals', sa.ARRAY(sa.String(length=30)), nullable=False),
    sa.Column('risk', sa.String(length=10), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sign_in_signals')),
    schema='identity'
    )
    op.create_index(op.f('ix_identity_sign_in_signals_identity_id'), 'sign_in_signals', ['identity_id'], unique=False, schema='identity')

    op.create_table('ledger_snapshots',
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('through_created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('entry_count', sa.Integer(), nullable=False),
    sa.Column('balances', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('problems', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['escrow.accounts.id'], name=op.f('fk_ledger_snapshots_account_id_accounts')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_snapshots')),
    schema='escrow'
    )
    op.create_index('ix_ledger_snapshots_account', 'ledger_snapshots', ['account_id', 'created_at'], unique=False, schema='escrow')


def downgrade() -> None:
    op.drop_index('ix_ledger_snapshots_account', table_name='ledger_snapshots', schema='escrow')
    op.drop_table('ledger_snapshots', schema='escrow')
    op.drop_index(op.f('ix_identity_sign_in_signals_identity_id'), table_name='sign_in_signals', schema='identity')
    op.drop_table('sign_in_signals', schema='identity')
    op.drop_index(op.f('ix_identity_scim_groups_organization_id'), table_name='scim_groups', schema='identity')
    op.drop_table('scim_groups', schema='identity')
    op.drop_table('org_session_policies', schema='identity')
    op.drop_column('sessions', 'idp', schema='identity')
    op.drop_column('sso_logins', 'assertion', schema='identity')
    for column in ('group_role_map', 'saml_certificates', 'saml_sso_url', 'saml_idp_entity_id', 'protocol'):
        op.drop_column('sso_connections', column, schema='identity')
