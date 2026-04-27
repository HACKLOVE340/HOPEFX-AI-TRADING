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
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_sessions_token"),
    )
    op.create_index("ix_sessions_user_id", _TABLE, ["user_id"])
    op.create_index("ix_sessions_expires_at", _TABLE, ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_expires_at", table_name=_TABLE)
    op.drop_index("ix_sessions_user_id", table_name=_TABLE)
    op.drop_table(_TABLE)
