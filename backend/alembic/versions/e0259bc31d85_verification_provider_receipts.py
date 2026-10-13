"""Hosted verification references and immutable receipt fingerprints."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e0259bc31d85"
down_revision = "d9138fa20b74"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evidence_items", sa.Column("storage_version", sa.String(200)), schema="verification")
    op.create_table("provider_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("verification.cases.id"), nullable=False, unique=True),
        sa.Column("provider_ref", sa.String(120), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False), schema="verification")
    op.create_table("provider_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event_id", sa.String(120), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False), schema="verification")
    op.execute("CREATE TRIGGER trg_provider_events_append_only BEFORE UPDATE OR DELETE ON verification.provider_events FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation()")


def downgrade():
    op.drop_table("provider_events", schema="verification")
    op.drop_table("provider_sessions", schema="verification")
    op.drop_column("evidence_items", "storage_version", schema="verification")
