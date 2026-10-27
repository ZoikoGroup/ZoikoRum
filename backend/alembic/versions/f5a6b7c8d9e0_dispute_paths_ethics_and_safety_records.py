"""dispute decision paths and reports; ethics, referrals, fraud alerts and post-reviews

Dispute: cases.agreements (each party's consent to a binding recommendation or an enterprise admin decision),
cases.provisional_decision (waiting out its challenge period), appeals.against (DECISION | PROVISIONAL), and
report_subscriptions (organisation admins' weekly / monthly CSV reports).

Admin: enforcement_cases.user_impact (recorded at assessment), post_review and concluded_at (Level 3+ post-review),
incidents.ux_impact and policy_updates (post-incident review), and three new tables: enforcement_referrals (Level 4
law enforcement / regulator referrals, Legal only), conflict_declarations (staff conflicts of interest and recusals)
and fraud_alerts (third-party fraud alerts, advisory).

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-10-23 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)]


def upgrade() -> None:
    op.add_column('cases', sa.Column('agreements', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False), schema='dispute')
    op.add_column('cases', sa.Column('provisional_decision', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='dispute')
    op.add_column('appeals', sa.Column('against', sa.String(length=20), server_default='DECISION', nullable=False), schema='dispute')
    op.create_table('report_subscriptions',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('identity_id', sa.UUID(), nullable=False),
    sa.Column('frequency', sa.String(length=10), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
    *_timestamps(),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_subscriptions')),
    sa.UniqueConstraint('organization_id', 'identity_id', name='uq_dispute_report_subscriber'),
    schema='dispute'
    )
    op.create_index(op.f('ix_dispute_report_subscriptions_organization_id'), 'report_subscriptions', ['organization_id'], unique=False, schema='dispute')

    op.add_column('enforcement_cases', sa.Column('user_impact', sa.String(length=2000), nullable=True), schema='admin')
    op.add_column('enforcement_cases', sa.Column('post_review', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='admin')
    op.add_column('enforcement_cases', sa.Column('concluded_at', sa.DateTime(timezone=True), nullable=True), schema='admin')
    op.add_column('incidents', sa.Column('ux_impact', sa.String(length=4000), nullable=True), schema='admin')
    op.add_column('incidents', sa.Column('policy_updates', sa.String(length=4000), nullable=True), schema='admin')

    op.create_table('enforcement_referrals',
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('agency', sa.String(length=200), nullable=False),
    sa.Column('agency_reference', sa.String(length=200), nullable=False),
    sa.Column('referred_on', sa.Date(), nullable=False),
    sa.Column('legal_signoff_by', sa.UUID(), nullable=False),
    sa.Column('legal_signoff_note', sa.String(length=2000), nullable=False),
    *_timestamps(),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_enforcement_referrals')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_enforcement_referrals_case_id'), 'enforcement_referrals', ['case_id'], unique=False, schema='admin')

    op.create_table('conflict_declarations',
    sa.Column('identity_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('subject_type', sa.String(length=30), nullable=True),
    sa.Column('subject_id', sa.UUID(), nullable=True),
    sa.Column('case_kind', sa.String(length=30), nullable=True),
    sa.Column('case_id', sa.String(length=80), nullable=True),
    sa.Column('reason', sa.String(length=2000), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
    *_timestamps(),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conflict_declarations')),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_conflict_declarations_identity_id'), 'conflict_declarations', ['identity_id'], unique=False, schema='admin')
    op.create_index(op.f('ix_admin_conflict_declarations_subject_id'), 'conflict_declarations', ['subject_id'], unique=False, schema='admin')

    op.create_table('fraud_alerts',
    sa.Column('provider', sa.String(length=60), nullable=False),
    sa.Column('external_id', sa.String(length=120), nullable=False),
    sa.Column('subject_type', sa.String(length=30), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column('reason_code', sa.String(length=100), nullable=False),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('case_id', sa.UUID(), nullable=True),
    *_timestamps(),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fraud_alerts')),
    sa.UniqueConstraint('provider', 'external_id', name='uq_fraud_alert_provider_external'),
    schema='admin'
    )
    op.create_index(op.f('ix_admin_fraud_alerts_subject_id'), 'fraud_alerts', ['subject_id'], unique=False, schema='admin')


def downgrade() -> None:
    op.drop_index(op.f('ix_admin_fraud_alerts_subject_id'), table_name='fraud_alerts', schema='admin')
    op.drop_table('fraud_alerts', schema='admin')
    op.drop_index(op.f('ix_admin_conflict_declarations_subject_id'), table_name='conflict_declarations', schema='admin')
    op.drop_index(op.f('ix_admin_conflict_declarations_identity_id'), table_name='conflict_declarations', schema='admin')
    op.drop_table('conflict_declarations', schema='admin')
    op.drop_index(op.f('ix_admin_enforcement_referrals_case_id'), table_name='enforcement_referrals', schema='admin')
    op.drop_table('enforcement_referrals', schema='admin')
    op.drop_column('incidents', 'policy_updates', schema='admin')
    op.drop_column('incidents', 'ux_impact', schema='admin')
    op.drop_column('enforcement_cases', 'concluded_at', schema='admin')
    op.drop_column('enforcement_cases', 'post_review', schema='admin')
    op.drop_column('enforcement_cases', 'user_impact', schema='admin')
    op.drop_index(op.f('ix_dispute_report_subscriptions_organization_id'), table_name='report_subscriptions', schema='dispute')
    op.drop_table('report_subscriptions', schema='dispute')
    op.drop_column('appeals', 'against', schema='dispute')
    op.drop_column('cases', 'provisional_decision', schema='dispute')
    op.drop_column('cases', 'agreements', schema='dispute')
