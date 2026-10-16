"""messaging meetings and engagement tasks

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-10-16 09:59:28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b6c7d8e9f0a1'
down_revision = 'a5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('tasks',
    sa.Column('contract_id', sa.UUID(), nullable=False),
    sa.Column('milestone_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('owner', sa.String(length=20), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('done_by', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['contract_id'], ['contract.contracts.id'], name=op.f('fk_tasks_contract_id_contracts')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tasks')),
    schema='contract'
    )
    op.create_index('ix_tasks_contract', 'tasks', ['contract_id', 'created_at'], unique=False, schema='contract')
    op.create_table('meetings',
    sa.Column('thread_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_minutes', sa.Integer(), nullable=False),
    sa.Column('join_url', sa.String(length=500), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['thread_id'], ['messaging.threads.id'], name=op.f('fk_meetings_thread_id_threads')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_meetings')),
    schema='messaging'
    )
    op.create_index('ix_meetings_thread_starts', 'meetings', ['thread_id', 'starts_at'], unique=False, schema='messaging')


def downgrade() -> None:
    op.drop_index('ix_meetings_thread_starts', table_name='meetings', schema='messaging')
    op.drop_table('meetings', schema='messaging')
    op.drop_index('ix_tasks_contract', table_name='tasks', schema='contract')
    op.drop_table('tasks', schema='contract')
