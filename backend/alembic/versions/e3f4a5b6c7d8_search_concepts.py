"""search: concept vectors for semantic matching

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-17 13:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('professional_documents', sa.Column('concepts', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
                  schema='search')
    op.create_index('ix_professional_documents_concepts', 'professional_documents', ['concepts'], unique=False,
                    schema='search', postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_professional_documents_concepts', table_name='professional_documents', schema='search')
    op.drop_column('professional_documents', 'concepts', schema='search')
