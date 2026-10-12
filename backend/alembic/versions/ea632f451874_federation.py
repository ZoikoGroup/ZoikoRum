"""Provisioned federation accounts bound to a configured enterprise."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'ea632f451874'
down_revision = 'd9521e340763'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('federation_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('identity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('identity.identities.id'), nullable=False, unique=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject', sa.String(200), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('organization_id', 'subject', name='uq_federation_subject'), schema='identity')

def downgrade():
    op.drop_table('federation_accounts', schema='identity')
