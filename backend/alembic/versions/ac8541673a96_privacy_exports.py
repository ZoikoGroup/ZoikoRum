"""Encrypted reviewed privacy exports with an explicit download expiry."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'ac8541673a96'
down_revision = 'fb7430562985'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('data_requests', sa.Column('export_payload_enc', sa.Text()), schema='identity')
    op.add_column('data_requests', sa.Column('export_expires_at', sa.DateTime(timezone=True)), schema='identity')
    op.add_column('data_requests', sa.Column('reviewed_by', postgresql.UUID(as_uuid=True)), schema='identity')
    op.add_column('data_requests', sa.Column('review_note', sa.String(2000)), schema='identity')

def downgrade():
    for column in ('review_note', 'reviewed_by', 'export_expires_at', 'export_payload_enc'):
        op.drop_column('data_requests', column, schema='identity')
