"""marketplace health: windowed queries over analytics.event_facts

Revision ID: 9d4b7e2c1a85
Revises: 3c5e8a1f2d47
Create Date: 2026-10-15 12:00:00.000000
"""
from __future__ import annotations

from alembic import op


revision = '9d4b7e2c1a85'
down_revision = '3c5e8a1f2d47'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_analytics_event_facts_occurred_at', 'event_facts', ['occurred_at'], unique=False, schema='analytics')
    op.create_index('ix_analytics_event_facts_event_type_occurred_at', 'event_facts', ['event_type', 'occurred_at'], unique=False, schema='analytics')


def downgrade() -> None:
    op.drop_index('ix_analytics_event_facts_event_type_occurred_at', table_name='event_facts', schema='analytics')
    op.drop_index('ix_analytics_event_facts_occurred_at', table_name='event_facts', schema='analytics')
