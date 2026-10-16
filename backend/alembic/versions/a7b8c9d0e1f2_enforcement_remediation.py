"""enforcement: remediation tasks

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-15 09:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('enforcement_cases', sa.Column('remediation', postgresql.JSONB(astext_type=sa.Text()),
                                                 server_default='[]', nullable=False), schema='admin')


def downgrade() -> None:
    op.drop_column('enforcement_cases', 'remediation', schema='admin')
