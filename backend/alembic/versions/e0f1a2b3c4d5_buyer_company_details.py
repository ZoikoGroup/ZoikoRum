"""buyer: company details from sign-up on the organization

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-11-06 13:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e0f1a2b3c4d5'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None

COLUMNS = [('company_type', 60), ('company_size', 40), ('state', 100), ('city', 100), ('registered_address', 300), ('tax_id', 60)]


def upgrade() -> None:
    for name, length in COLUMNS:
        op.add_column('organizations', sa.Column(name, sa.String(length=length), nullable=True), schema='buyer')


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column('organizations', name, schema='buyer')
