"""proposal: open briefs and professionals' interest

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-10-16 09:47:07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a5b6c7d8e9f0'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('open_briefs',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('buyer_identity_id', sa.UUID(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('service', sa.String(length=200), nullable=False),
    sa.Column('specialization', sa.String(length=120), nullable=False),
    sa.Column('objective', sa.String(length=300), nullable=False),
    sa.Column('details', sa.String(length=1200), nullable=False),
    sa.Column('desired_start_date', sa.Date(), nullable=True),
    sa.Column('estimated_duration', sa.String(length=30), nullable=True),
    sa.Column('budget_max_minor', sa.BigInteger(), nullable=True),
    sa.Column('budget_currency', sa.String(length=3), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('closes_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_open_briefs')),
    schema='proposal'
    )
    op.create_index('ix_open_briefs_match', 'open_briefs', ['specialization', 'status', 'closes_at'], unique=False, schema='proposal')
    op.create_index('ix_open_briefs_org', 'open_briefs', ['organization_id', 'created_at'], unique=False, schema='proposal')
    op.create_table('brief_interests',
    sa.Column('brief_id', sa.UUID(), nullable=False),
    sa.Column('professional_id', sa.UUID(), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['brief_id'], ['proposal.open_briefs.id'], name=op.f('fk_brief_interests_brief_id_open_briefs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_brief_interests')),
    sa.UniqueConstraint('brief_id', 'professional_id', name=op.f('uq_brief_interests_brief_id_professional_id')),
    schema='proposal'
    )
    op.create_index(op.f('ix_proposal_brief_interests_brief_id'), 'brief_interests', ['brief_id'], unique=False, schema='proposal')
    op.create_index(op.f('ix_proposal_brief_interests_professional_id'), 'brief_interests', ['professional_id'], unique=False, schema='proposal')


def downgrade() -> None:
    op.drop_index(op.f('ix_proposal_brief_interests_professional_id'), table_name='brief_interests', schema='proposal')
    op.drop_index(op.f('ix_proposal_brief_interests_brief_id'), table_name='brief_interests', schema='proposal')
    op.drop_table('brief_interests', schema='proposal')
    op.drop_index('ix_open_briefs_org', table_name='open_briefs', schema='proposal')
    op.drop_index('ix_open_briefs_match', table_name='open_briefs', schema='proposal')
    op.drop_table('open_briefs', schema='proposal')
