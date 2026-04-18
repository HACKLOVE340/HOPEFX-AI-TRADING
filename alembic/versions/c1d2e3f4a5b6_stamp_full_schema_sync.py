# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""stamp full schema sync

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-04-18 00:00:00.000000

Adds all tables defined in database/models.py that were not yet covered by
previous migrations:

  - chargebacks          (payment disputes from Stripe webhooks)
  - tax_reports          (periodic per-jurisdiction tax records)
  - reconciliation_records (expected vs actual per provider per period)
  - api_keys             (per-user programmatic API keys)
  - aml_alerts           (AML compliance flags from risk engine)
  - broker_connections   (live broker integration health records)

After this migration the alembic_version stamp equals the ORM metadata —
`alembic upgrade head` is a no-op on a fresh database.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    """Return True if *table_name* already exists in the target database."""
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def upgrade() -> None:
    """Create all tables that are in the ORM but not yet in the DB."""

    # ── chargebacks ───────────────────────────────────────────────────────────
    if not _table_exists("chargebacks"):
        op.create_table(
            "chargebacks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("chargeback_id", sa.String(100), nullable=False),
            sa.Column("payment_id", sa.String(100), nullable=False),
            sa.Column("user_id", sa.String(128), nullable=False),
            sa.Column("username", sa.String(255), nullable=True),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
            sa.Column("reason", sa.String(255), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="open"),
            sa.Column("provider", sa.String(50), nullable=False, server_default="stripe"),
            sa.Column("evidence_due_by", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "opened_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_payload", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("chargeback_id", name="uq_chargebacks_chargeback_id"),
        )
        op.create_index("ix_chargebacks_chargeback_id", "chargebacks", ["chargeback_id"], unique=True)
        op.create_index("ix_chargebacks_payment_id", "chargebacks", ["payment_id"], unique=False)
        op.create_index("ix_chargebacks_user_id", "chargebacks", ["user_id"], unique=False)
        op.create_index("ix_chargebacks_status", "chargebacks", ["status"], unique=False)

    # ── tax_reports ───────────────────────────────────────────────────────────
    if not _table_exists("tax_reports"):
        op.create_table(
            "tax_reports",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("report_id", sa.String(100), nullable=False),
            sa.Column("period", sa.String(20), nullable=False),
            sa.Column("jurisdiction", sa.String(100), nullable=False),
            sa.Column("total_revenue", sa.Float(), nullable=False, server_default="0"),
            sa.Column("taxable_amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("tax_rate_pct", sa.Float(), nullable=False, server_default="0"),
            sa.Column("tax_owed", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("report_id", name="uq_tax_reports_report_id"),
            sa.UniqueConstraint("period", "jurisdiction", name="uq_tax_report_period_jurisdiction"),
        )
        op.create_index("ix_tax_reports_report_id", "tax_reports", ["report_id"], unique=True)
        op.create_index("ix_tax_reports_status", "tax_reports", ["status"], unique=False)

    # ── reconciliation_records ────────────────────────────────────────────────
    if not _table_exists("reconciliation_records"):
        op.create_table(
            "reconciliation_records",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("recon_id", sa.String(100), nullable=False),
            sa.Column("period", sa.String(20), nullable=False),
            sa.Column("provider", sa.String(50), nullable=False),
            sa.Column("expected_amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("actual_amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("discrepancy", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
            sa.Column("transaction_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.String(128), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("recon_id", name="uq_recon_records_recon_id"),
            sa.UniqueConstraint("period", "provider", name="uq_recon_period_provider"),
        )
        op.create_index("ix_recon_records_recon_id", "reconciliation_records", ["recon_id"], unique=True)
        op.create_index("ix_recon_records_status", "reconciliation_records", ["status"], unique=False)

    # ── api_keys ──────────────────────────────────────────────────────────────
    if not _table_exists("api_keys"):
        op.create_table(
            "api_keys",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column("key_prefix", sa.String(12), nullable=False),
            sa.Column("scopes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        )
        op.create_index("idx_api_keys_user", "api_keys", ["user_id"], unique=False)
        op.create_index("idx_api_keys_hash", "api_keys", ["key_hash"], unique=False)

    # ── aml_alerts ────────────────────────────────────────────────────────────
    if not _table_exists("aml_alerts"):
        op.create_table(
            "aml_alerts",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("username", sa.String(100), nullable=True),
            sa.Column("alert_type", sa.String(50), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("reviewed_by", sa.String(128), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_aml_alerts_user", "aml_alerts", ["user_id"], unique=False)
        op.create_index("idx_aml_alerts_status", "aml_alerts", ["status"], unique=False)
        op.create_index("idx_aml_alerts_severity", "aml_alerts", ["severity"], unique=False)

    # ── broker_connections ────────────────────────────────────────────────────
    if not _table_exists("broker_connections"):
        op.create_table(
            "broker_connections",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("broker_name", sa.String(100), nullable=False),
            sa.Column("broker_type", sa.String(50), nullable=False, server_default="unknown"),
            sa.Column("status", sa.String(20), nullable=False, server_default="disconnected"),
            sa.Column("latency_ms", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("fill_rate_pct", sa.Float(), nullable=True, server_default="0"),
            sa.Column("slippage_avg_pips", sa.Float(), nullable=True, server_default="0"),
            sa.Column("orders_today", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("uptime_pct", sa.Float(), nullable=True, server_default="0"),
            sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_broker_conn_name", "broker_connections", ["broker_name"], unique=False)


def downgrade() -> None:
    """Drop tables added in this migration (reverse order of creation)."""
    op.drop_index("idx_broker_conn_name", table_name="broker_connections")
    op.drop_table("broker_connections")

    op.drop_index("idx_aml_alerts_severity", table_name="aml_alerts")
    op.drop_index("idx_aml_alerts_status", table_name="aml_alerts")
    op.drop_index("idx_aml_alerts_user", table_name="aml_alerts")
    op.drop_table("aml_alerts")

    op.drop_index("idx_api_keys_hash", table_name="api_keys")
    op.drop_index("idx_api_keys_user", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_recon_records_status", table_name="reconciliation_records")
    op.drop_index("ix_recon_records_recon_id", table_name="reconciliation_records")
    op.drop_table("reconciliation_records")

    op.drop_index("ix_tax_reports_status", table_name="tax_reports")
    op.drop_index("ix_tax_reports_report_id", table_name="tax_reports")
    op.drop_table("tax_reports")

    op.drop_index("ix_chargebacks_status", table_name="chargebacks")
    op.drop_index("ix_chargebacks_user_id", table_name="chargebacks")
    op.drop_index("ix_chargebacks_payment_id", table_name="chargebacks")
    op.drop_index("ix_chargebacks_chargeback_id", table_name="chargebacks")
    op.drop_table("chargebacks")
