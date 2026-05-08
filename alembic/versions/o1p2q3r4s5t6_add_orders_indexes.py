"""add orders indexes for user_id and status

Revision ID: o1p2q3r4s5t6
Revises: n1o2p3q4r5s6
Create Date: 2026-05-08 07:00:00.000000

Adds user_id and status columns to orders (if absent) then indexes them.
The orders table was created before these columns existed in some deployments,
so the upgrade is fully idempotent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "o1p2q3r4s5t6"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def _cols(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _idxs(table: str) -> set:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    cols = _cols("orders")

    # Add user_id if the orders table predates this column.
    # FK constraint omitted: SQLite does not support ADD COLUMN with constraints.
    if "user_id" not in cols:
        op.add_column(
            "orders",
            sa.Column("user_id", sa.String(36), nullable=True),
        )

    # Add status if missing.
    if "status" not in cols:
        op.add_column(
            "orders",
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="pending",
            ),
        )

    idxs = _idxs("orders")
    if "idx_orders_user_id" not in idxs:
        op.create_index("idx_orders_user_id", "orders", ["user_id"], unique=False)
    if "idx_orders_status" not in idxs:
        op.create_index("idx_orders_status", "orders", ["status"], unique=False)


def downgrade() -> None:
    idxs = _idxs("orders")
    if "idx_orders_status" in idxs:
        op.drop_index("idx_orders_status", table_name="orders")
    if "idx_orders_user_id" in idxs:
        op.drop_index("idx_orders_user_id", table_name="orders")
