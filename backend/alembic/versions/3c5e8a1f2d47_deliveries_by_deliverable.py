"""deliveries by deliverable: submission items, drafts and buyer reviews

Revision ID: 3c5e8a1f2d47
Revises: 710d1280b58a
Create Date: 2026-10-14 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from zoikorum.shared import ddl


revision = '3c5e8a1f2d47'
down_revision = '710d1280b58a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('submissions', sa.Column('revision_number', sa.Integer(), server_default='0', nullable=False), schema='contract')
    op.add_column('submissions', sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False), schema='contract')
    op.add_column('submissions', sa.Column('declaration', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='contract')
    op.add_column('submissions', sa.Column('late_reason', sa.String(length=500), nullable=True), schema='contract')
    # Earlier deliveries are numbered in the order they were made (0 = first delivery of the milestone).
    op.execute("""
        UPDATE contract.submissions s SET revision_number = n.rn
        FROM (SELECT id, row_number() OVER (PARTITION BY milestone_id ORDER BY created_at) - 1 AS rn FROM contract.submissions) n
        WHERE s.id = n.id AND n.rn > 0
    """)
    op.create_table('submission_drafts',
    sa.Column('milestone_id', sa.UUID(), nullable=False),
    sa.Column('professional_identity_id', sa.UUID(), nullable=False),
    sa.Column('note', sa.String(length=2000), nullable=False),
    sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['milestone_id'], ['contract.milestones.id'], name=op.f('fk_submission_drafts_milestone_id_milestones')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_submission_drafts')),
    sa.UniqueConstraint('milestone_id', name=op.f('uq_submission_drafts_milestone_id')),
    schema='contract'
    )
    op.create_table('submission_reviews',
    sa.Column('submission_id', sa.UUID(), nullable=False),
    sa.Column('milestone_id', sa.UUID(), nullable=False),
    sa.Column('reviewer_identity_id', sa.UUID(), nullable=False),
    sa.Column('verdicts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('outcome', sa.String(length=30), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['milestone_id'], ['contract.milestones.id'], name=op.f('fk_submission_reviews_milestone_id_milestones')),
    sa.ForeignKeyConstraint(['submission_id'], ['contract.submissions.id'], name=op.f('fk_submission_reviews_submission_id_submissions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_submission_reviews')),
    schema='contract'
    )
    op.create_index(op.f('ix_contract_submission_reviews_milestone_id'), 'submission_reviews', ['milestone_id'], unique=False, schema='contract')
    op.create_index(op.f('ix_contract_submission_reviews_submission_id'), 'submission_reviews', ['submission_id'], unique=False, schema='contract')
    # Deliveries and reviews are evidence: never edited or removed (after the numbering above).
    for table in ('contract.submissions', 'contract.submission_reviews'):
        for statement in ddl.append_only_trigger(table):
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_submission_reviews_append_only ON contract.submission_reviews")
    op.execute("DROP TRIGGER IF EXISTS trg_submissions_append_only ON contract.submissions")
    op.drop_index(op.f('ix_contract_submission_reviews_submission_id'), table_name='submission_reviews', schema='contract')
    op.drop_index(op.f('ix_contract_submission_reviews_milestone_id'), table_name='submission_reviews', schema='contract')
    op.drop_table('submission_reviews', schema='contract')
    op.drop_table('submission_drafts', schema='contract')
    op.drop_column('submissions', 'late_reason', schema='contract')
    op.drop_column('submissions', 'declaration', schema='contract')
    op.drop_column('submissions', 'items', schema='contract')
    op.drop_column('submissions', 'revision_number', schema='contract')
