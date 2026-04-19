"""add user_id to trades table

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-04-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h1i2j3k4l5m6"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.add_column(
            sa.Column("user_id", sa.String(100), nullable=True, index=True)
        )
    op.create_index("ix_trades_user_id", "trades", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_trades_user_id", table_name="trades")
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_column("user_id")
