"""success criteria, tracked scope changes, payment protection setup, release approval SLA

Proposal: requests get structured success criteria (success_definition, success_measures); proposals get the professional's
tracked scope suggestions (scope_changes, each PENDING -> ACCEPTED | REJECTED by the buyer).

Escrow: accounts record the payment protection setup made after both signatures (release_model, the release approver,
when and by whom it was confirmed); allocations remember when a release waiting for the buyer's approval is due
(release_approval_due_at). The new terminal allocation state EXPIRED and account status EXPIRED need no schema change.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-10-23 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('requests', sa.Column('success_definition', sa.String(length=1000), nullable=True), schema='proposal')
    op.add_column('requests', sa.Column('success_measures', postgresql.JSONB(astext_type=sa.Text()),
                                        server_default='[]', nullable=False), schema='proposal')
    op.add_column('proposals', sa.Column('scope_changes', postgresql.JSONB(astext_type=sa.Text()),
                                         server_default='[]', nullable=False), schema='proposal')
    op.add_column('accounts', sa.Column('release_model', sa.String(length=20), nullable=True), schema='escrow')
    op.add_column('accounts', sa.Column('release_approver_identity_id', sa.UUID(), nullable=True), schema='escrow')
    op.add_column('accounts', sa.Column('protection_confirmed_at', sa.DateTime(timezone=True), nullable=True), schema='escrow')
    op.add_column('accounts', sa.Column('protection_confirmed_by', sa.UUID(), nullable=True), schema='escrow')
    op.add_column('allocations', sa.Column('release_approval_due_at', sa.DateTime(timezone=True), nullable=True), schema='escrow')


def downgrade() -> None:
    op.drop_column('allocations', 'release_approval_due_at', schema='escrow')
    op.drop_column('accounts', 'protection_confirmed_by', schema='escrow')
    op.drop_column('accounts', 'protection_confirmed_at', schema='escrow')
    op.drop_column('accounts', 'release_approver_identity_id', schema='escrow')
    op.drop_column('accounts', 'release_model', schema='escrow')
    op.drop_column('proposals', 'scope_changes', schema='proposal')
    op.drop_column('requests', 'success_measures', schema='proposal')
    op.drop_column('requests', 'success_definition', schema='proposal')
