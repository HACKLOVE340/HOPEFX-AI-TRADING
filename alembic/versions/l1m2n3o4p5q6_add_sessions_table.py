# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Add sessions table

Revision ID: l1m2n3o4p5q6
Revises: k1l2m3n4o5p6
Create Date: 2026-04-27 00:00:00.000000

Creates the ``sessions`` table used by database/models.py Session model
and master_control for server-side session tracking.

Columns
-------
id         — integer primary key
user_id    — FK → users.id (NOT NULL, indexed)
token      — VARCHAR(512), unique, NOT NULL
expires_at — DATETIME, NOT NULL
created_at — DATETIME, defaults to current UTC timestamp
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l1m2n3o4p5q6"  # pragma: allowlist secret
down_revision: str | None = "k1l2m3n4o5p6"  # pragma: allowlist secret
branch_labels = None
depends_on = None

_TABLE = "sessions"


def upgrade() -> None:

    # ── Idempotency helpers ───────────────────────────────────────────────────
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _existing_tables = set(inspector.get_table_names())
    # users.id is String(36) in the canonical base schema; use that as
    # fallback when introspection is unavailable.
    user_id_type: sa.types.TypeEngine = sa.String(length=36)

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
    # Align sessions.user_id type with users.id to avoid FK type mismatches
    # (e.g. integer -> varchar incompatibility on PostgreSQL).
    try:
        users_cols = {c["name"]: c for c in inspector.get_columns("users")}
        user_id_type = users_cols.get("id", {}).get("type", user_id_type)
    except (sa.exc.NoSuchTableError, sa.exc.NoInspectionAvailable):  # nosec B110
        # Introspection unavailable — keep String(36) default (intentional fallback).
        pass

    _tbl(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", user_id_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_sessions_token"),
    )
    _idx("ix_sessions_user_id", _TABLE, ["user_id"])
    _idx("ix_sessions_expires_at", _TABLE, ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_expires_at", table_name=_TABLE)
    op.drop_index("ix_sessions_user_id", table_name=_TABLE)
    op.drop_table(_TABLE)
