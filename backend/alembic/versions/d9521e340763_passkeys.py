"""Verified passkeys and short-lived server-side challenges."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'd9521e340763'
down_revision = 'c8410d23f652'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('identities', sa.Column('passkey_enabled', sa.Boolean(), nullable=False, server_default=sa.false()), schema='identity')
    op.create_table('passkeys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('identity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('identity.identities.id'), nullable=False),
        sa.Column('credential_id', sa.LargeBinary(), nullable=False, unique=True),
        sa.Column('public_key', sa.LargeBinary(), nullable=False),
        sa.Column('sign_count', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(100), nullable=False), schema='identity')
    op.create_index('ix_identity_passkeys_identity_id', 'passkeys', ['identity_id'], schema='identity')
    op.create_table('auth_challenges',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('identity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('identity.identities.id')),
        sa.Column('session_id', postgresql.UUID(as_uuid=True)),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('challenge', sa.LargeBinary(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True)), schema='identity')

def downgrade():
    op.drop_table('auth_challenges', schema='identity')
    op.drop_table('passkeys', schema='identity')
    op.drop_column('identities', 'passkey_enabled', schema='identity')
