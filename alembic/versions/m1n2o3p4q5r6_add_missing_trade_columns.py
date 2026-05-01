"""add missing trade columns: account_id, trade_type, size, timestamp

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2026-04-28 00:00:00.000000

These columns exist in the Trade ORM model but were never added via
migration — they were only present in databases created from scratch via
Base.metadata.create_all().  This migration adds them idempotently so
existing databases (created before these columns were in the model) are
brought in sync without data loss.
"""
from alembic import op
import sqlalchemy as sa

revision = "m1n2o3p4q5r6"
down_revision = "l1m2n3o4p5q6"
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    from sqlalchemy import inspect as _inspect
    return {c["name"] for c in _inspect(bind).get_columns(table)}


def upgrade() -> None:

    # ── Idempotency helpers ───────────────────────────────────────────────────
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _existing_tables = set(inspector.get_table_names())

    def _tbl(name, *args, **kwargs):
        """Create table only if it does not already exist."""
        if name not in _existing_tables:
            op.create_table(name, *args, **kwargs)

    def _idx(index_name, table_name, *args, **kwargs):
        """Create index only if it does not already exist."""
        if table_name not in _existing_tables:
            return
        try:
            existing = {i["name"] for i in inspector.get_indexes(table_name)}
        except Exception:
            existing = set()
        if index_name not in existing:
            op.create_index(index_name, table_name, *args, **kwargs)

    def _col(table_name, col_name, *args, **kwargs):
        """Add column only if it does not already exist."""
        try:
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        except Exception:
            existing_cols = set()
        if col_name not in existing_cols:
            op.add_column(table_name, *args, **kwargs)

    # ── End idempotency helpers ───────────────────────────────────────────────

    existing = _existing_columns("trades")

    with op.batch_alter_table("trades") as batch_op:
        if "account_id" not in existing:
            batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        if "trade_type" not in existing:
            batch_op.add_column(sa.Column("trade_type", sa.String(20), nullable=True))
        if "size" not in existing:
            batch_op.add_column(sa.Column("size", sa.Float(), nullable=True))
        if "timestamp" not in existing:
            batch_op.add_column(sa.Column("timestamp", sa.DateTime(), nullable=True))

    # Create index on account_id only if it doesn't already exist
    from sqlalchemy import inspect as _inspect
    existing_indexes = {idx["name"] for idx in _inspect(op.get_bind()).get_indexes("trades")}
    if "ix_trades_account_id" not in existing_indexes:
        _idx("ix_trades_account_id", "trades", ["account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_trades_account_id", table_name="trades")
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_column("timestamp")
        batch_op.drop_column("size")
        batch_op.drop_column("trade_type")
        batch_op.drop_column("account_id")
