"""ai: risk observations for organisations as well as people

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-10-16 16:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a9b0c1d2e3f4'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('risk_observations', sa.Column('subject_type', sa.String(length=20), server_default='IDENTITY', nullable=False), schema='ai')


def downgrade() -> None:
    op.drop_column('risk_observations', 'subject_type', schema='ai')
