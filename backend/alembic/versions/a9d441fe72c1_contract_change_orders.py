"""contract change orders

Revision ID: a9d441fe72c1
Revises: 8c77a4e3d921
Create Date: 2026-10-08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a9d441fe72c1"
down_revision = "8c77a4e3d921"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column("pending_change_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="contract",
    )
    op.create_table(
        "change_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposed_by_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposer_party", sa.String(length=20), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("delta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("impact", sa.String(length=1000), nullable=False),
        sa.Column("base_contract_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decided_by_identity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_reason", sa.String(length=1000), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_version", sa.Integer(), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["contract.contracts.id"],
            name=op.f("fk_change_orders_contract_id_contracts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_change_orders")),
        schema="contract",
    )
    op.create_index(
        "ix_change_orders_contract",
        "change_orders",
        ["contract_id", "created_at"],
        unique=False,
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index("ix_change_orders_contract", table_name="change_orders", schema="contract")
    op.drop_table("change_orders", schema="contract")
    op.drop_column("contracts", "pending_change_order_id", schema="contract")
