"""identity: sign-up company and contact details

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-11-06 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd9e0f1a2b3c4'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('identities', sa.Column('signup_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='identity')


def downgrade() -> None:
    op.drop_column('identities', 'signup_profile', schema='identity')
