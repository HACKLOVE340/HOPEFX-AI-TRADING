# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""add missing position columns

Revision ID: a1b2c3d4e5f6
Revises: 746b2609eac5
Create Date: 2024-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"  # pragma: allowlist secret
down_revision = "746b2609eac5"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def _column_exists(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade():

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

    _col("positions", "account_id", sa.Column("account_id", sa.Integer(), nullable=True))
    _idx("ix_positions_account_id", "positions", ["account_id"])
    _col("positions", "size", sa.Column("size", sa.Float(), nullable=True))
    _col("positions", "market_value", sa.Column("market_value", sa.Float(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _tables = set(inspector.get_table_names())

    def _drop_idx(name, table):
        if table not in _tables:
            return
        if name in {i["name"] for i in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)

    def _live_cols(table: str) -> set:
        if bind.dialect.name == "sqlite":
            rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
            return {row[1] for row in rows}
        rows = bind.execute(
            sa.text("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :t"), {"t": table}
        ).fetchall()
        return {row[0] for row in rows}

    _drop_idx("ix_positions_account_id", "positions")
    if "positions" in _tables:
        cols_to_drop = [c for c in ("market_value", "size", "account_id")
                        if c in _live_cols("positions")]
        if cols_to_drop:
            with op.batch_alter_table("positions") as batch_op:
                for col in cols_to_drop:
                    batch_op.drop_column(col)
