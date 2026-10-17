"""merge open briefs and firm on search results heads

Revision ID: 8f9e49f8e7c1
Revises: 02b9113aa695, b7f3e91c4d20
Create Date: 2026-10-17 15:49:49.980963
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '8f9e49f8e7c1'
down_revision = ('02b9113aa695', 'b7f3e91c4d20')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
