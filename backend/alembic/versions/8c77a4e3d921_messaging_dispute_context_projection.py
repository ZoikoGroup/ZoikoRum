"""messaging dispute context event projection

Revision ID: 8c77a4e3d921
Revises: 4c2e91a1b702
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "8c77a4e3d921"
down_revision = "4c2e91a1b702"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispute_contexts",
        sa.Column("dispute_id", sa.UUID(), nullable=False),
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("initiated_by_identity_id", sa.UUID(), nullable=True),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("dispute_id", name=op.f("pk_dispute_contexts")),
        schema="messaging",
    )
    op.create_index(
        "ix_messaging_dispute_contract_open",
        "dispute_contexts",
        ["contract_id", "is_open"],
        unique=False,
        schema="messaging",
    )


def downgrade() -> None:
    op.drop_index("ix_messaging_dispute_contract_open", table_name="dispute_contexts", schema="messaging")
    op.drop_table("dispute_contexts", schema="messaging")
