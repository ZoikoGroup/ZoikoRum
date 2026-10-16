"""merge open briefs and analytics heads

Revision ID: 02b9113aa695
Revises: a0b1c2d3e4f5, c7d8e9f0a1b2
Create Date: 2026-10-16 14:10:21.797960
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '02b9113aa695'
down_revision = ('a0b1c2d3e4f5', 'c7d8e9f0a1b2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
