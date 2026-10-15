"""professionals and search: industries served

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-10-15 18:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a3b4c5d6e7f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for schema, table in (('professional', 'professionals'), ('search', 'professional_documents')):
        op.add_column(table, sa.Column('industries', postgresql.ARRAY(sa.String(length=40)), server_default='{}', nullable=False), schema=schema)


def downgrade() -> None:
    for schema, table in (('professional', 'professionals'), ('search', 'professional_documents')):
        op.drop_column(table, 'industries', schema=schema)
