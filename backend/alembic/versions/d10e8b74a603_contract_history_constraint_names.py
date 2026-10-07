"""Align existing contract history indexes and constraints with model naming.

Revision ID: d10e8b74a603
Revises: c10d7b93a502
"""
from alembic import op
import sqlalchemy as sa

revision = "d10e8b74a603"
down_revision = "c10d7b93a502"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER INDEX IF EXISTS contract.ix_contract_revisions_contract_id RENAME TO ix_contract_contract_revisions_contract_id')
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("contract_revisions", schema="contract")
    if any(c["name"] == "uq_contract_revisions_contract_version" for c in constraints):
        op.execute('ALTER TABLE contract.contract_revisions RENAME CONSTRAINT uq_contract_revisions_contract_version TO uq_contract_revisions_contract_id_contract_version')


def downgrade() -> None:
    # Names are cosmetic; keep the model-compatible names on older application versions.
    pass
