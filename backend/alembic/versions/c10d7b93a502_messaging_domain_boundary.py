"""Keep messaging dispute references within the domain boundary.

Revision ID: c10d7b93a502
Revises: be71c832d10f
"""
from alembic import op

revision = "c10d7b93a502"
down_revision = "be71c832d10f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Earlier local databases may already have the original cross-domain FK.
    # The facade/event contract owns referential validation, not a schema FK.
    op.execute('ALTER TABLE messaging.dispute_contexts DROP CONSTRAINT IF EXISTS fk_dispute_contexts_contract_id_contracts')


def downgrade() -> None:
    # Restoring a prohibited cross-domain constraint would break the architecture.
    pass
