"""firm-level offerings

Firm: firm.offerings, services a firm publishes and its member professionals deliver (DRAFT -> PUBLISHED <->
UNPUBLISHED). Regulated specializations publish only with a verified, licensed delivering member (enforced in the
firm service). Policy payment rules, exception roles and regional contract variants live in the existing
policy.versions.settings JSON and need no schema change.

Revision ID: a6b7c8d9e0f1
Revises: a1c2e3f4a5b6
Create Date: 2026-10-23 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a6b7c8d9e0f1'
down_revision = 'a1c2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('offerings',
    sa.Column('firm_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.String(length=2000), nullable=False),
    sa.Column('specialization', sa.String(length=100), nullable=False),
    sa.Column('engagement_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('pricing_model', sa.String(length=20), nullable=False),
    sa.Column('starting_price_minor', sa.BigInteger(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('delivered_by', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('regulated', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_by', sa.UUID(), nullable=True),
    sa.Column('unpublished_reason', sa.String(length=300), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['firm_id'], ['firm.firms.id'], name=op.f('fk_offerings_firm_id_firms')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_offerings')),
    schema='firm'
    )
    op.create_index('ix_firm_offerings_firm_status', 'offerings', ['firm_id', 'status'], unique=False, schema='firm')


def downgrade() -> None:
    op.drop_index('ix_firm_offerings_firm_status', table_name='offerings', schema='firm')
    op.drop_table('offerings', schema='firm')
