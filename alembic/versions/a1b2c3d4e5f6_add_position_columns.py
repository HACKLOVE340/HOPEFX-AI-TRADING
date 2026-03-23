"""add missing position columns

Revision ID: a1b2c3d4e5f6
Revises: 746b2609eac5
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '746b2609eac5'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c['name'] == column for c in insp.get_columns(table))


def upgrade():
    if not _column_exists('positions', 'account_id'):
        op.add_column('positions', sa.Column('account_id', sa.Integer(), nullable=True))
        op.create_index('ix_positions_account_id', 'positions', ['account_id'])
    if not _column_exists('positions', 'size'):
        op.add_column('positions', sa.Column('size', sa.Float(), nullable=True))
    if not _column_exists('positions', 'market_value'):
        op.add_column('positions', sa.Column('market_value', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('positions', 'market_value')
    op.drop_column('positions', 'size')
    op.drop_index('ix_positions_account_id', table_name='positions')
    op.drop_column('positions', 'account_id')
