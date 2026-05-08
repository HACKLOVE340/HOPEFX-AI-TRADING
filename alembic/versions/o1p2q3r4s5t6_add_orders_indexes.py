"""add orders indexes for user_id and status

Revision ID: o1p2q3r4s5t6
Revises: n1o2p3q4r5s6
Create Date: 2026-05-08 07:00:00.000000
"""

from alembic import op

revision = "o1p2q3r4s5t6"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_orders_user_id", "orders", ["user_id"], unique=False)
    op.create_index("idx_orders_status", "orders", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_orders_status", table_name="orders")
    op.drop_index("idx_orders_user_id", table_name="orders")
