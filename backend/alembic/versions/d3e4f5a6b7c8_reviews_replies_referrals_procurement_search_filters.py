"""review replies, referral codes, procurement requests, on-site regions and search filter columns

Review: review.review_replies, the reviewed professional's one public reply per review (editable; every version is in
the audit ledger).
Marketplace: marketplace.referral_attributions (the optional code typed at sign-up, one per account) and
marketplace.procurement_requests (public procurement-pack / security-review requests, a lead for the Zoikorum team).
Professional: professionals.onsite_regions (where on-site work is offered).
Search: professional_documents.currencies and .enterprise_engagements (filters "accepts multiple currencies" and
"prior enterprise engagements"); existing documents are filled on the next rebuild (POST /v1/admin/search/reindex).

Revision ID: d3e4f5a6b7c8
Revises: a1c2e3f4a5b6
Create Date: 2026-10-23 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd3e4f5a6b7c8'
down_revision = 'a1c2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('review_replies',
    sa.Column('review_id', sa.UUID(), nullable=False),
    sa.Column('professional_id', sa.UUID(), nullable=False),
    sa.Column('author_identity_id', sa.UUID(), nullable=False),
    sa.Column('body', sa.String(length=1500), nullable=False),
    sa.Column('edit_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['review_id'], ['review.reviews.id'], name=op.f('fk_review_replies_review_id_reviews')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_review_replies')),
    sa.UniqueConstraint('review_id', name=op.f('uq_review_replies_review_id')),
    schema='review'
    )
    op.create_index(op.f('ix_review_review_replies_professional_id'), 'review_replies', ['professional_id'], unique=False, schema='review')

    op.create_table('referral_attributions',
    sa.Column('identity_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_referral_attributions')),
    sa.UniqueConstraint('identity_id', name=op.f('uq_referral_attributions_identity_id')),
    schema='marketplace'
    )
    op.create_index(op.f('ix_marketplace_referral_attributions_code'), 'referral_attributions', ['code'], unique=False, schema='marketplace')

    op.create_table('procurement_requests',
    sa.Column('reference', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('professional_id', sa.UUID(), nullable=True),
    sa.Column('requester_identity_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('organization', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('message', sa.String(length=2000), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_procurement_requests')),
    sa.UniqueConstraint('reference', name=op.f('uq_procurement_requests_reference')),
    schema='marketplace'
    )
    op.create_index(op.f('ix_marketplace_procurement_requests_professional_id'), 'procurement_requests', ['professional_id'],
                    unique=False, schema='marketplace')

    op.add_column('professionals', sa.Column('onsite_regions', postgresql.ARRAY(sa.String(length=100)), server_default='{}',
                                             nullable=False), schema='professional')
    op.add_column('professional_documents', sa.Column('currencies', postgresql.ARRAY(sa.String(length=3)), server_default='{}',
                                                      nullable=False), schema='search')
    op.add_column('professional_documents', sa.Column('enterprise_engagements', sa.Integer(), server_default='0', nullable=False),
                  schema='search')


def downgrade() -> None:
    op.drop_column('professional_documents', 'enterprise_engagements', schema='search')
    op.drop_column('professional_documents', 'currencies', schema='search')
    op.drop_column('professionals', 'onsite_regions', schema='professional')
    op.drop_index(op.f('ix_marketplace_procurement_requests_professional_id'), table_name='procurement_requests', schema='marketplace')
    op.drop_table('procurement_requests', schema='marketplace')
    op.drop_index(op.f('ix_marketplace_referral_attributions_code'), table_name='referral_attributions', schema='marketplace')
    op.drop_table('referral_attributions', schema='marketplace')
    op.drop_index(op.f('ix_review_review_replies_professional_id'), table_name='review_replies', schema='review')
    op.drop_table('review_replies', schema='review')
