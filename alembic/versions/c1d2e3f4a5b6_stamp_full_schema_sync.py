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

    """Create all tables that are in the ORM but not yet in the DB."""

    # ── chargebacks ───────────────────────────────────────────────────────────
    if not _table_exists("chargebacks"):
        _tbl(
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
        _idx("ix_chargebacks_chargeback_id", "chargebacks", ["chargeback_id"], unique=True)
        _idx("ix_chargebacks_payment_id", "chargebacks", ["payment_id"], unique=False)
        _idx("ix_chargebacks_user_id", "chargebacks", ["user_id"], unique=False)
        _idx("ix_chargebacks_status", "chargebacks", ["status"], unique=False)

    # ── tax_reports ───────────────────────────────────────────────────────────
    if not _table_exists("tax_reports"):
        _tbl(
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
        _idx("ix_tax_reports_report_id", "tax_reports", ["report_id"], unique=True)
        _idx("ix_tax_reports_status", "tax_reports", ["status"], unique=False)

    # ── reconciliation_records ────────────────────────────────────────────────
    if not _table_exists("reconciliation_records"):
        _tbl(
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
        _idx("ix_recon_records_recon_id", "reconciliation_records", ["recon_id"], unique=True)
        _idx("ix_recon_records_status", "reconciliation_records", ["status"], unique=False)

    # ── api_keys ──────────────────────────────────────────────────────────────
    if not _table_exists("api_keys"):
        _tbl(
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
        _idx("idx_api_keys_user", "api_keys", ["user_id"], unique=False)
        _idx("idx_api_keys_hash", "api_keys", ["key_hash"], unique=False)

    # ── aml_alerts ────────────────────────────────────────────────────────────
    if not _table_exists("aml_alerts"):
        _tbl(
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
        _idx("idx_aml_alerts_user", "aml_alerts", ["user_id"], unique=False)
        _idx("idx_aml_alerts_status", "aml_alerts", ["status"], unique=False)
        _idx("idx_aml_alerts_severity", "aml_alerts", ["severity"], unique=False)

    # ── broker_connections ────────────────────────────────────────────────────
    if not _table_exists("broker_connections"):
        _tbl(
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
        _idx("idx_broker_conn_name", "broker_connections", ["broker_name"], unique=False)


def downgrade() -> None:
    """Drop tables added in this migration (reverse order of creation)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _tables = set(inspector.get_table_names())

    def _drop_idx(name, table):
        if table not in _tables:
            return
        if name in {i["name"] for i in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)

    def _drop_tbl(name):
        if name in _tables:
            op.drop_table(name)

    _drop_idx("idx_broker_conn_name", "broker_connections")
    _drop_tbl("broker_connections")

    _drop_idx("idx_aml_alerts_severity", "aml_alerts")
    _drop_idx("idx_aml_alerts_status", "aml_alerts")
    _drop_idx("idx_aml_alerts_user", "aml_alerts")
    _drop_tbl("aml_alerts")

    _drop_idx("idx_api_keys_hash", "api_keys")
    _drop_idx("idx_api_keys_user", "api_keys")
    _drop_tbl("api_keys")

    _drop_idx("ix_recon_records_status", "reconciliation_records")
    _drop_idx("ix_recon_records_recon_id", "reconciliation_records")
    _drop_tbl("reconciliation_records")

    _drop_idx("ix_tax_reports_status", "tax_reports")
    _drop_idx("ix_tax_reports_report_id", "tax_reports")
    _drop_tbl("tax_reports")

    _drop_idx("ix_chargebacks_status", "chargebacks")
    _drop_idx("ix_chargebacks_user_id", "chargebacks")
    _drop_idx("ix_chargebacks_payment_id", "chargebacks")
    _drop_idx("ix_chargebacks_chargeback_id", "chargebacks")
    _drop_tbl("chargebacks")
