"""Stored files: uploaded files kept in the database

New table platform.stored_files (key, data, sha256, size_bytes). Used when ZK_STORAGE_PROVIDER=database, so files
are backed up and restored together with the rest of the data.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-10-28 10:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('stored_files',
    sa.Column('key', sa.String(length=500), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key'),
    schema='platform'
    )


def downgrade() -> None:
    op.drop_table('stored_files', schema='platform')
