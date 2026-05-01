"""Add audit log, KYC, and session columns

Revision ID: k1l2m3n4o5p6
Revises: j1k2l3m4n5o6
Create Date: 2026-04-25 00:00:00.000000

Changes
-------
1. audit_log: add created_at, event_type, user_id, detail, ip_address
2. users: add kyc_submitted_at, kyc_reviewed_at, kyc_reviewer_id,
          kyc_rejection_reason, kyc_document_type
3. user_sessions: add last_active_at
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "k1l2m3n4o5p6"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── audit_log ─────────────────────────────────────────────────────────────

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

    def _batch_add_col(table, col_name, col_def):
        """Add a column via batch_alter_table only if it doesn't exist."""
        try:
            existing = {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            existing = set()
        if col_name not in existing:
            with op.batch_alter_table(table) as batch_op:
                batch_op.add_column(col_def)

    _batch_add_col("audit_log", "created_at", sa.Column("created_at", sa.DateTime(), nullable=True))
    _batch_add_col("audit_log", "event_type", sa.Column("event_type", sa.String(100), nullable=True))
    _batch_add_col("audit_log", "user_id", sa.Column("user_id", sa.String(100), nullable=True))
    _batch_add_col("audit_log", "detail", sa.Column("detail", sa.Text(), nullable=True))
    _batch_add_col("audit_log", "ip_address", sa.Column("ip_address", sa.String(45), nullable=True))

    # Back-fill created_at from timestamp for existing rows.
    op.execute("UPDATE audit_log SET created_at = timestamp WHERE created_at IS NULL")

    # Create indexes for the new columns.
    _idx("idx_audit_event_type", "audit_log", ["event_type"])
    _idx("idx_audit_user_id", "audit_log", ["user_id"])
    _idx("idx_audit_created_at", "audit_log", ["created_at"])

    # ── users ─────────────────────────────────────────────────────────────────
    _batch_add_col("users", "kyc_submitted_at", sa.Column("kyc_submitted_at", sa.DateTime(), nullable=True))
    _batch_add_col("users", "kyc_reviewed_at", sa.Column("kyc_reviewed_at", sa.DateTime(), nullable=True))
    _batch_add_col("users", "kyc_reviewer_id", sa.Column("kyc_reviewer_id", sa.String(100), nullable=True))
    _batch_add_col("users", "kyc_rejection_reason", sa.Column("kyc_rejection_reason", sa.Text(), nullable=True))
    _batch_add_col("users", "kyc_document_type", sa.Column("kyc_document_type", sa.String(50), nullable=True))

    # ── user_sessions ─────────────────────────────────────────────────────────
    _batch_add_col("user_sessions", "last_active_at", sa.Column("last_active_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # ── user_sessions ─────────────────────────────────────────────────────────
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.drop_column("last_active_at")

    # ── users ─────────────────────────────────────────────────────────────────
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("kyc_document_type")
        batch_op.drop_column("kyc_rejection_reason")
        batch_op.drop_column("kyc_reviewer_id")
        batch_op.drop_column("kyc_reviewed_at")
        batch_op.drop_column("kyc_submitted_at")

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.drop_index("idx_audit_created_at", table_name="audit_log")
    op.drop_index("idx_audit_user_id", table_name="audit_log")
    op.drop_index("idx_audit_event_type", table_name="audit_log")

    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.drop_column("ip_address")
        batch_op.drop_column("detail")
        batch_op.drop_column("user_id")
        batch_op.drop_column("event_type")
        batch_op.drop_column("created_at")
