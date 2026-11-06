"""assistant chat feedback

Revision ID: b2d3e4f5a6c7
Revises: c8d9e0f1a2b3
Create Date: 2026-10-30 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b2d3e4f5a6c7'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chat_feedback',
        sa.Column('inference_id', sa.UUID(), nullable=False),
        sa.Column('rating', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.String(length=40), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('requested_by', sa.UUID(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_feedback')),
        sa.UniqueConstraint('inference_id', 'requested_by', name=op.f('uq_chat_feedback_inference_id_requested_by')),
        schema='ai',
    )
    op.create_index(op.f('ix_ai_chat_feedback_requested_by'), 'chat_feedback', ['requested_by'], unique=False, schema='ai')


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_chat_feedback_requested_by'), table_name='chat_feedback', schema='ai')
    op.drop_table('chat_feedback', schema='ai')
