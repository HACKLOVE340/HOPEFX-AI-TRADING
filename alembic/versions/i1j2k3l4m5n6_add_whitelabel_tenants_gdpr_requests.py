"""add whitelabel_tenants and gdpr_requests tables

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2026-04-20 00:00:00.000000

Adds durable DB-backed storage for:
  - whitelabel_tenants  (replaces in-memory WhiteLabelManager._tenants dict)
  - gdpr_requests       (replaces Redis-only GDPR store in superadmin/infrastructure.py)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "i1j2k3l4m5n6"
down_revision = "h1i2j3k4l5m6"
branch_labels = None
depends_on = None


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

    _tbl(
        "whitelabel_tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_email", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="trial"),
        sa.Column("tier", sa.String(30), nullable=False, server_default="starter"),
        sa.Column("features_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("primary_color", sa.String(20), nullable=True),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("company_name", sa.String(200), nullable=True),
        sa.Column("custom_domain", sa.String(255), nullable=True, unique=True),
        sa.Column("api_key_hash", sa.String(64), nullable=True),
        sa.Column("revenue_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("user_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _idx("idx_wl_tenant_status", "whitelabel_tenants", ["status"])
    _idx("idx_wl_tenant_owner", "whitelabel_tenants", ["owner_email"])

    _tbl(
        "gdpr_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("request_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("processed_by", sa.String(128), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _idx("idx_gdpr_user", "gdpr_requests", ["user_id"])
    _idx("idx_gdpr_status", "gdpr_requests", ["status"])
    _idx("idx_gdpr_type", "gdpr_requests", ["request_type"])


def downgrade() -> None:
    op.drop_index("idx_gdpr_type", table_name="gdpr_requests")
    op.drop_index("idx_gdpr_status", table_name="gdpr_requests")
    op.drop_index("idx_gdpr_user", table_name="gdpr_requests")
    op.drop_table("gdpr_requests")

    op.drop_index("idx_wl_tenant_owner", table_name="whitelabel_tenants")
    op.drop_index("idx_wl_tenant_status", table_name="whitelabel_tenants")
    op.drop_table("whitelabel_tenants")
