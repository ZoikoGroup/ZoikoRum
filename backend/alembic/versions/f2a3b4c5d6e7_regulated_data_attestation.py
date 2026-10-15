"""professionals: can handle regulated data (attestation)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-15 17:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('professionals', sa.Column('regulated_data_attested_at', sa.DateTime(timezone=True), nullable=True), schema='professional')


def downgrade() -> None:
    op.drop_column('professionals', 'regulated_data_attested_at', schema='professional')
