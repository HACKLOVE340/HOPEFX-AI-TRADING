# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""add trade_journal, sub_accounts, billing_history, profiles tables

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2026-05-03 00:00:00.000000

Adds four new tables required by the API layer:
  - trade_journal      : per-trade notes, tags, and emotion tracking
  - sub_accounts       : team/prop-firm sub-account management
  - billing_history    : Stripe/Flutterwave payment records
  - user_profiles      : extended user profile (bio, avatar, preferences)

Also adds missing indexes on:
  - signals.strategy
  - outbox_events.status + created_at
  - users.plan
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "n1o2p3q4r5s6"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── trade_journal ─────────────────────────────────────────────────────────
    op.create_table(
        "trade_journal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "trade_id",
            sa.String(50),
            sa.ForeignKey("trades.trade_id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),          # JSON array of strings
        sa.Column("emotion", sa.String(50), nullable=True),   # "confident","fearful","neutral"
        sa.Column("rating", sa.Integer(), nullable=True),     # 1-5 self-assessment
        sa.Column("setup_quality", sa.String(20), nullable=True),  # "A","B","C"
        sa.Column("lessons_learned", sa.Text(), nullable=True),
        sa.Column("screenshot_url", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_journal_user_created", "trade_journal", ["user_id", "created_at"])
    op.create_index("idx_journal_trade", "trade_journal", ["trade_id"])

    # ── sub_accounts ──────────────────────────────────────────────────────────
    op.create_table(
        "sub_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("account_type", sa.String(30), nullable=False, server_default="personal"),
        # account_type: "personal" | "prop_firm" | "team" | "managed"
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("initial_balance", sa.Float(), nullable=True),
        sa.Column("current_balance", sa.Float(), nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("daily_loss_limit", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("broker", sa.String(50), nullable=True),
        sa.Column("broker_account_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_sub_accounts_owner", "sub_accounts", ["owner_id"])
    op.create_index("idx_sub_accounts_active", "sub_accounts", ["is_active"])

    # sub_account_members — many-to-many: users can be members of sub-accounts
    op.create_table(
        "sub_account_members",
        sa.Column(
            "sub_account_id",
            sa.String(36),
            sa.ForeignKey("sub_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(30), nullable=False, server_default="viewer"),
        # role: "owner" | "trader" | "viewer" | "risk_manager"
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("sub_account_id", "user_id"),
    )
    op.create_index(
        "idx_sub_account_members_user", "sub_account_members", ["user_id"]
    )

    # ── billing_history ───────────────────────────────────────────────────────
    op.create_table(
        "billing_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider", sa.String(30), nullable=False),  # "stripe" | "flutterwave"
        sa.Column("provider_payment_id", sa.String(200), nullable=True, unique=True),
        sa.Column("provider_subscription_id", sa.String(200), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        # event_type: "payment_succeeded" | "payment_failed" | "subscription_created"
        #             | "subscription_cancelled" | "refund" | "chargeback"
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True, server_default="USD"),
        sa.Column("plan", sa.String(30), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),  # raw provider payload
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_billing_user_created", "billing_history", ["user_id", "created_at"])
    op.create_index("idx_billing_provider_id", "billing_history", ["provider_payment_id"])
    op.create_index("idx_billing_status", "billing_history", ["status"])

    # ── user_profiles ─────────────────────────────────────────────────────────
    op.create_table(
        "user_profiles",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("timezone", sa.String(50), nullable=True, server_default="UTC"),
        sa.Column("locale", sa.String(10), nullable=True, server_default="en"),
        sa.Column("theme", sa.String(20), nullable=True, server_default="dark"),
        sa.Column("notification_prefs", sa.Text(), nullable=True),  # JSON
        sa.Column("trading_experience", sa.String(20), nullable=True),
        # trading_experience: "beginner" | "intermediate" | "advanced" | "professional"
        sa.Column("preferred_instruments", sa.Text(), nullable=True),  # JSON array
        sa.Column("risk_tolerance", sa.String(20), nullable=True),
        # risk_tolerance: "conservative" | "moderate" | "aggressive"
        sa.Column("referral_code", sa.String(20), nullable=True, unique=True),
        sa.Column("referred_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # ── Missing indexes on existing tables ────────────────────────────────────

    # signals.strategy — used by SignalRepository.get_by_strategy()
    _add_index_if_not_exists(
        "idx_signals_strategy", "signals", ["strategy"]
    )

    # outbox_events.status + created_at — used by OutboxRelay polling
    _add_column_if_not_exists(
        "outbox_events", "status",
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    )
    _add_column_if_not_exists(
        "outbox_events", "max_attempts",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
    )
    _add_column_if_not_exists(
        "outbox_events", "idempotency_key",
        sa.Column("idempotency_key", sa.String(128), nullable=True),
    )
    _add_index_if_not_exists(
        "idx_outbox_status_created", "outbox_events", ["status", "created_at"]
    )

    # users.plan — used by superadmin user listing filtered by plan
    _add_index_if_not_exists("idx_users_plan", "users", ["plan"])


def downgrade() -> None:
    # Drop indexes on existing tables
    _drop_index_if_exists("idx_users_plan", "users")
    _drop_index_if_exists("idx_outbox_status_created", "outbox_events")
    _drop_index_if_exists("idx_signals_strategy", "signals")

    # Drop new tables (reverse order for FK safety)
    op.drop_table("user_profiles")
    op.drop_table("billing_history")
    op.drop_table("sub_account_members")
    op.drop_table("sub_accounts")
    op.drop_table("trade_journal")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add_index_if_not_exists(index_name: str, table_name: str, columns: list) -> None:
    """Create index only if it does not already exist (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if index_name in existing:
        op.drop_index(index_name, table_name=table_name)


def _add_column_if_not_exists(table_name: str, column_name: str, column: sa.Column) -> None:
    """Add column only if it does not already exist (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
    if column_name not in existing_cols:
        op.add_column(table_name, column)
