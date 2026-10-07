"""immutable contract version history

Revision ID: be71c832d10f
Revises: a9d441fe72c1
Create Date: 2026-10-08
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "be71c832d10f"
down_revision = "a9d441fe72c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contract_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("change_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("terms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("milestones", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("terms_hash", sa.String(length=64), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["contract.contracts.id"],
            name=op.f("fk_contract_revisions_contract_id_contracts"),
        ),
        sa.ForeignKeyConstraint(
            ["change_order_id"],
            ["contract.change_orders.id"],
            name=op.f("fk_contract_revisions_change_order_id_change_orders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contract_revisions")),
        sa.UniqueConstraint("contract_id", "contract_version", name=op.f("uq_contract_revisions_contract_id_contract_version")),
        sa.UniqueConstraint("change_order_id", name=op.f("uq_contract_revisions_change_order_id")),
        schema="contract",
    )
    op.create_index(
        "ix_contract_contract_revisions_contract_id",
        "contract_revisions",
        ["contract_id"],
        unique=False,
        schema="contract",
    )
    op.create_foreign_key(
        op.f("fk_contracts_pending_change_order_id_change_orders"),
        "contracts",
        "change_orders",
        ["pending_change_order_id"],
        ["id"],
        source_schema="contract",
        referent_schema="contract",
    )

    bind = op.get_bind()
    contracts = sa.table(
        "contracts",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("contract_version", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("total_minor", sa.BigInteger()),
        sa.column("terms", postgresql.JSONB()),
        sa.column("terms_hash", sa.String()),
        sa.column("document", sa.Text()),
        sa.column("document_sha256", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        schema="contract",
    )
    milestones = sa.table(
        "milestones",
        sa.column("contract_id", postgresql.UUID(as_uuid=True)),
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("sequence", sa.Integer()),
        sa.column("title", sa.String()),
        sa.column("amount_minor", sa.BigInteger()),
        sa.column("currency", sa.String()),
        sa.column("due_date", sa.Date()),
        sa.column("deliverable_keys", postgresql.JSONB()),
        schema="contract",
    )
    revisions = sa.table(
        "contract_revisions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("contract_id", postgresql.UUID(as_uuid=True)),
        sa.column("contract_version", sa.Integer()),
        sa.column("change_order_id", postgresql.UUID(as_uuid=True)),
        sa.column("currency", sa.String()),
        sa.column("total_minor", sa.BigInteger()),
        sa.column("terms", postgresql.JSONB()),
        sa.column("milestones", postgresql.JSONB()),
        sa.column("terms_hash", sa.String()),
        sa.column("document", sa.Text()),
        sa.column("document_sha256", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        schema="contract",
    )
    contract_rows = bind.execute(sa.select(contracts)).mappings().all()
    milestone_rows = bind.execute(
        sa.select(milestones).order_by(milestones.c.contract_id, milestones.c.sequence)
    ).mappings().all()
    by_contract: dict[uuid.UUID, list[dict]] = {}
    for item in milestone_rows:
        by_contract.setdefault(item["contract_id"], []).append(
            {
                "id": str(item["id"]),
                "sequence": item["sequence"],
                "title": item["title"],
                "amountMinor": item["amount_minor"],
                "currency": item["currency"],
                "dueDate": item["due_date"].isoformat() if item["due_date"] else None,
                "deliverableKeys": list(item["deliverable_keys"]),
            }
        )
    for contract in contract_rows:
        bind.execute(
            sa.insert(revisions).values(
                id=uuid.uuid4(),
                contract_id=contract["id"],
                contract_version=contract["contract_version"],
                change_order_id=None,
                currency=contract["currency"],
                total_minor=contract["total_minor"],
                terms=contract["terms"],
                milestones=by_contract.get(contract["id"], []),
                terms_hash=contract["terms_hash"],
                document=contract["document"],
                document_sha256=contract["document_sha256"],
                created_at=contract["created_at"],
            )
        )

    op.execute(
        """
        CREATE TRIGGER trg_contract_revisions_append_only
        BEFORE UPDATE OR DELETE ON contract.contract_revisions
        FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION contract.guard_change_order_history() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'change orders are append-only';
            END IF;
            IF OLD.contract_id IS DISTINCT FROM NEW.contract_id
               OR OLD.proposed_by_identity_id IS DISTINCT FROM NEW.proposed_by_identity_id
               OR OLD.proposer_party IS DISTINCT FROM NEW.proposer_party
               OR OLD.change_type IS DISTINCT FROM NEW.change_type
               OR OLD.delta IS DISTINCT FROM NEW.delta
               OR OLD.impact IS DISTINCT FROM NEW.impact
               OR OLD.base_contract_version IS DISTINCT FROM NEW.base_contract_version
               OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'change order proposal details are immutable';
            END IF;
            IF OLD.status = 'PROPOSED' THEN
                IF NEW.status NOT IN ('APPROVED', 'REJECTED')
                   OR NEW.decided_by_identity_id IS NULL
                   OR NEW.decided_at IS NULL
                   OR (NEW.status = 'REJECTED' AND NEW.applied_version IS NOT NULL)
                   OR (NEW.applied_version IS NOT NULL AND NEW.applied_version <= NEW.base_contract_version) THEN
                    RAISE EXCEPTION 'invalid change order decision transition';
                END IF;
            ELSIF OLD.status = 'APPROVED' AND OLD.applied_version IS NULL THEN
                IF NEW.status <> 'APPROVED'
                   OR NEW.applied_version IS NULL
                   OR NEW.applied_version <= NEW.base_contract_version
                   OR NEW.decided_by_identity_id IS DISTINCT FROM OLD.decided_by_identity_id
                   OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
                   OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason THEN
                    RAISE EXCEPTION 'invalid change order execution transition';
                END IF;
            ELSE
                RAISE EXCEPTION 'change order decisions are final';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_change_orders_append_only
        BEFORE UPDATE OR DELETE ON contract.change_orders
        FOR EACH ROW EXECUTE FUNCTION contract.guard_change_order_history();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_change_orders_append_only ON contract.change_orders")
    op.execute("DROP FUNCTION IF EXISTS contract.guard_change_order_history()")
    op.execute("DROP TRIGGER IF EXISTS trg_contract_revisions_append_only ON contract.contract_revisions")
    op.drop_constraint(
        op.f("fk_contracts_pending_change_order_id_change_orders"),
        "contracts",
        schema="contract",
        type_="foreignkey",
    )
    op.drop_index("ix_contract_contract_revisions_contract_id", table_name="contract_revisions", schema="contract")
    op.drop_table("contract_revisions", schema="contract")
