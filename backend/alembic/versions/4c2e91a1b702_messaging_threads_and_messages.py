"""messaging threads, messages and attachments

Revision ID: 4c2e91a1b702
Revises: 50b4309ca1b3
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "4c2e91a1b702"
down_revision = "50b4309ca1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "messaging"')
    op.create_table(
        "threads",
        sa.Column("context_type", sa.String(length=30), nullable=False),
        sa.Column("context_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("professional_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("lock_reason", sa.String(length=300), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_threads")),
        sa.UniqueConstraint("context_type", "context_id", name=op.f("uq_threads_context_type_context_id")),
        schema="messaging",
    )
    op.create_index(op.f("ix_messaging_threads_organization_id"), "threads", ["organization_id"], unique=False, schema="messaging")
    op.create_index(op.f("ix_messaging_threads_professional_id"), "threads", ["professional_id"], unique=False, schema="messaging")
    op.create_table(
        "read_positions",
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["messaging.threads.id"], name=op.f("fk_read_positions_thread_id_threads")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_read_positions")),
        sa.UniqueConstraint("thread_id", "identity_id", name=op.f("uq_read_positions_thread_id_identity_id")),
        schema="messaging",
    )
    op.create_table(
        "attachments",
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("file_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["messaging.threads.id"], name=op.f("fk_attachments_thread_id_threads")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        sa.UniqueConstraint("thread_id", "name", "file_version", name=op.f("uq_attachments_thread_id_name_file_version")),
        schema="messaging",
    )
    op.create_index(op.f("ix_messaging_attachments_thread_id"), "attachments", ["thread_id"], unique=False, schema="messaging")
    op.create_table(
        "messages",
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("sender_identity_id", sa.UUID(), nullable=True),
        sa.Column("sender_name", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachment_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.UUID(), nullable=True),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["messaging.threads.id"], name=op.f("fk_messages_thread_id_threads")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint("thread_id", "sequence", name=op.f("uq_messages_thread_id_sequence")),
        sa.UniqueConstraint("thread_id", "source_event_id", name=op.f("uq_messages_thread_id_source_event_id")),
        schema="messaging",
    )
    op.create_index("ix_messages_thread_created", "messages", ["thread_id", "created_at"], unique=False, schema="messaging")

    op.execute("""
        CREATE TRIGGER trg_messages_append_only
        BEFORE UPDATE OR DELETE ON messaging.messages
        FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();
    """)
    op.execute("""
        CREATE TRIGGER trg_attachments_append_only
        BEFORE UPDATE OR DELETE ON messaging.attachments
        FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_attachments_append_only ON messaging.attachments")
    op.execute("DROP TRIGGER IF EXISTS trg_messages_append_only ON messaging.messages")
    op.drop_index("ix_messages_thread_created", table_name="messages", schema="messaging")
    op.drop_table("messages", schema="messaging")
    op.drop_index(op.f("ix_messaging_attachments_thread_id"), table_name="attachments", schema="messaging")
    op.drop_table("attachments", schema="messaging")
    op.drop_table("read_positions", schema="messaging")
    op.drop_index(op.f("ix_messaging_threads_professional_id"), table_name="threads", schema="messaging")
    op.drop_index(op.f("ix_messaging_threads_organization_id"), table_name="threads", schema="messaging")
    op.drop_table("threads", schema="messaging")
