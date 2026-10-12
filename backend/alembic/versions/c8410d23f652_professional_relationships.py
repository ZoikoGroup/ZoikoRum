"""Professional buyer bookmarks and organisation follows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'c8410d23f652'
down_revision = 'b7309c12e541'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('buyer_relationships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('professional_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('professional.professionals.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email_alerts', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('in_app_alerts', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint('professional_id', 'kind', 'target_id', name='uq_professional_relationship'), schema='professional')
    op.create_index('ix_professional_buyer_relationships_professional_id', 'buyer_relationships', ['professional_id'], schema='professional')

def downgrade():
    op.drop_table('buyer_relationships', schema='professional')
