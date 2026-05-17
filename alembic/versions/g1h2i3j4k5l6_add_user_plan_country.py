# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""add plan and country columns to users

Revision ID: g1h2i3j4k5l6
Revises: c1d2e3f4a5b6
Create Date: 2026-04-19 00:00:00.000000

Adds two columns to the ``users`` table:

- ``plan`` (VARCHAR 30, NOT NULL, default 'free') — subscription tier set by
  the billing layer.  Existing rows are back-filled to 'free'.
- ``country`` (CHAR 2, nullable) — ISO 3166-1 alpha-2 country code populated
  at registration or KYC.  Existing rows default to NULL.

These columns replace the hardcoded stubs in the superadmin users API
(``plan: "free"``, ``country: None``) with real, queryable data.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g1h2i3j4k5l6"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _col_exists(table: str, col: str) -> bool:
        try:
            return col in {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            return False

    # Add ``plan`` with a server-side default so existing rows are back-filled
    # without a full table scan in application code.
    if not _col_exists("users", "plan"):
        op.add_column(
            "users",
            sa.Column(
                "plan",
                sa.String(30),
                nullable=False,
                server_default="free",
            ),
        )
    # Add ``country`` as nullable — we cannot infer it for existing accounts.
    if not _col_exists("users", "country"):
        op.add_column(
            "users",
            sa.Column("country", sa.String(2), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _col_exists(table: str, col: str) -> bool:
        try:
            return col in {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            return False

    if _col_exists("users", "country"):
        op.drop_column("users", "country")
    if _col_exists("users", "plan"):
        op.drop_column("users", "plan")
