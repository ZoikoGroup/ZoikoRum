"""reconciliation breaks (suspense) and the incident lifecycle

Payments: payments.reconciliation_breaks, one row per (day, check, currency) difference found by a reconciliation run,
OPEN -> EVIDENCE_GATHERING -> REVIEWED -> CLOSED (maker-checker on close). Existing MISMATCH days get their breaks
backfilled from the stored checks so they are not reported clean.

Admin: incidents move UNACKNOWLEDGED -> INVESTIGATING -> MITIGATING -> MONITORING -> RECOVERED -> CLOSED. Existing rows:
OPEN -> INVESTIGATING if anything beyond the opening entry is on its timeline, else UNACKNOWLEDGED; CONTAINED ->
MITIGATING; RESOLVED -> RECOVERED; CLOSED stays CLOSED.

Revision ID: a1c2e3f4a5b6
Revises: f0a1b2c3d4e5
Create Date: 2026-10-21 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a1c2e3f4a5b6'
down_revision = 'f0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('reconciliation_breaks',
    sa.Column('batch_id', sa.UUID(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('references', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=True),
    sa.Column('resolution_note', sa.String(length=2000), nullable=True),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_by', sa.UUID(), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('history', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reconciliation_breaks')),
    sa.UniqueConstraint('day', 'kind', 'currency', name='uq_reconciliation_break_day_kind_currency'),
    schema='payments'
    )
    op.create_index(op.f('ix_payments_reconciliation_breaks_batch_id'), 'reconciliation_breaks', ['batch_id'], unique=False, schema='payments')
    op.create_index(op.f('ix_payments_reconciliation_breaks_day'), 'reconciliation_breaks', ['day'], unique=False, schema='payments')
    # Backfill: every failed check of an existing run becomes an OPEN break (a MISMATCH day must not read as clean).
    op.execute("""
        INSERT INTO payments.reconciliation_breaks
            (id, batch_id, day, kind, currency, amount_minor, "references", status, history, created_at, updated_at)
        SELECT gen_random_uuid(), b.id, b.day, c->>'name', c->>'currency', (c->>'difference')::bigint,
               jsonb_build_object('batchId', b.id::text, 'ledger', c->'ledger', 'payments', c->'payments', 'provider', c->'provider'),
               'OPEN',
               jsonb_build_array(jsonb_build_object('at', now()::text, 'by', 'MIGRATION', 'fromStatus', NULL, 'toStatus', 'OPEN',
                                                    'note', 'Recorded from an existing reconciliation run')),
               now(), now()
        FROM payments.reconciliation_batches b, jsonb_array_elements(b.checks) c
        WHERE NOT (c->>'ok')::boolean
        ON CONFLICT (day, kind, currency) DO NOTHING
    """)

    op.add_column('incidents', sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True), schema='admin')
    op.add_column('incidents', sa.Column('monitoring_at', sa.DateTime(timezone=True), nullable=True), schema='admin')
    op.add_column('incidents', sa.Column('mitigated_by', sa.UUID(), nullable=True), schema='admin')
    op.add_column('incidents', sa.Column('recovery_note', sa.String(length=2000), nullable=True), schema='admin')
    op.add_column('incidents', sa.Column('recovery_verified_by', sa.UUID(), nullable=True), schema='admin')
    op.execute("""
        UPDATE admin.incidents SET
            status = CASE status
                WHEN 'OPEN' THEN CASE WHEN jsonb_array_length(timeline) > 1 THEN 'INVESTIGATING' ELSE 'UNACKNOWLEDGED' END
                WHEN 'CONTAINED' THEN 'MITIGATING'
                WHEN 'RESOLVED' THEN 'RECOVERED'
                ELSE status END,
            acknowledged_at = CASE WHEN status = 'OPEN' AND jsonb_array_length(timeline) <= 1 THEN NULL
                                   ELSE COALESCE(contained_at, detected_at) END
        WHERE status IN ('OPEN', 'CONTAINED', 'RESOLVED', 'CLOSED')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE admin.incidents SET status = CASE status
            WHEN 'UNACKNOWLEDGED' THEN 'OPEN' WHEN 'INVESTIGATING' THEN 'OPEN'
            WHEN 'MITIGATING' THEN 'CONTAINED' WHEN 'MONITORING' THEN 'CONTAINED'
            WHEN 'RECOVERED' THEN 'RESOLVED' ELSE status END
    """)
    op.drop_column('incidents', 'recovery_verified_by', schema='admin')
    op.drop_column('incidents', 'recovery_note', schema='admin')
    op.drop_column('incidents', 'mitigated_by', schema='admin')
    op.drop_column('incidents', 'monitoring_at', schema='admin')
    op.drop_column('incidents', 'acknowledged_at', schema='admin')
    op.drop_index(op.f('ix_payments_reconciliation_breaks_day'), table_name='reconciliation_breaks', schema='payments')
    op.drop_index(op.f('ix_payments_reconciliation_breaks_batch_id'), table_name='reconciliation_breaks', schema='payments')
    op.drop_table('reconciliation_breaks', schema='payments')
