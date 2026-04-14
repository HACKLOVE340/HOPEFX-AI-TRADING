# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""add watchlists table

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-03-25 00:00:00.000000

Replaces the key-value store approach (configurations table keyed by
"watchlist:{user_id}") with a proper relational table. Each row is one
symbol in one user's watchlist, with a unique constraint on (user_id, symbol)
and an index on user_id for fast per-user lookups.

The old key-value rows are NOT migrated automatically — they will be
ignored once the app switches to this table. Run a one-off data migration
script if you need to preserve existing watchlists.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the watchlists table."""
    op.create_table(
        "watchlists",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
    )
    # Fast lookup of all symbols for a given user
    op.create_index(
        "ix_watchlists_user_id",
        "watchlists",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the watchlists table."""
    op.drop_index("ix_watchlists_user_id", table_name="watchlists")
    op.drop_table("watchlists")
