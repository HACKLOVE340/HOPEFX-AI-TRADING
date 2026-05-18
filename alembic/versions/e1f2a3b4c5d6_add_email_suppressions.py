# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""add email_suppressions table

Revision ID: e1f2a3b4c5d6
Revises: d9ffd7d4576b
Create Date: 2025-01-01 00:00:00.000000

Stores addresses suppressed due to bounce, spam_report, or unsubscribe events
received from the SendGrid Event Webhook (POST /api/email/webhook).
EmailChannel.send() checks this table before every dispatch.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d9ffd7d4576b"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        """Create index only if it does not already exist.

        Re-inspects the live schema so indexes on tables created earlier in
        this same upgrade() call are handled correctly.
        """
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

    _tbl(
        "email_suppressions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column(
            "reason",
            sa.String(64),
            nullable=False,
            comment="bounce | spam_report | unsubscribe | group_unsubscribe",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),  # pylint: disable=not-callable
        ),
    )
    _idx(
        "ix_email_suppressions_email",
        "email_suppressions",
        ["email"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _tables = set(inspector.get_table_names())
    if "email_suppressions" in _tables:
        existing_idx = {i["name"] for i in inspector.get_indexes("email_suppressions")}
        if "ix_email_suppressions_email" in existing_idx:
            op.drop_index("ix_email_suppressions_email", table_name="email_suppressions")
        op.drop_table("email_suppressions")
