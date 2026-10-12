"""Durable signed email receipts and address suppression."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'fb7430562985'
down_revision = 'ea632f451874'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('email_receipts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('provider_event_id', sa.String(200), nullable=False, unique=True),
        sa.Column('notification_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('notification.notifications.id'), nullable=False),
        sa.Column('event_type', sa.String(30), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False), schema='notification')
    op.create_table('email_suppressions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('address_sha256', sa.String(64), nullable=False, unique=True),
        sa.Column('reason', sa.String(30), nullable=False), schema='notification')

def downgrade():
    op.drop_table('email_suppressions', schema='notification')
    op.drop_table('email_receipts', schema='notification')
