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
    # "timestamp" is a reserved word in PostgreSQL — must be double-quoted.
    op.execute('UPDATE audit_log SET created_at = "timestamp" WHERE created_at IS NULL')

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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _live_cols(table: str) -> set:
        """Return current column names, bypassing SQLAlchemy inspector cache."""
        if bind.dialect.name == "sqlite":
            rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
            return {row[1] for row in rows}
        rows = bind.execute(
            sa.text("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :t"), {"t": table}
        ).fetchall()
        return {row[0] for row in rows}

    def _batch_drop_cols(table: str, cols: list) -> None:
        """Drop columns that exist; skip missing ones (idempotent)."""
        to_drop = [c for c in cols if c in _live_cols(table)]
        if to_drop:
            with op.batch_alter_table(table) as batch_op:
                for col in to_drop:
                    batch_op.drop_column(col)

    # ── user_sessions ─────────────────────────────────────────────────────────
    _batch_drop_cols("user_sessions", ["last_active_at"])

    # ── users ─────────────────────────────────────────────────────────────────
    _batch_drop_cols("users", [
        "kyc_document_type", "kyc_rejection_reason", "kyc_reviewer_id",
        "kyc_reviewed_at", "kyc_submitted_at",
    ])

    # ── audit_log ─────────────────────────────────────────────────────────────
    _audit_idx = {i["name"] for i in inspector.get_indexes("audit_log")}
    for idx in ("idx_audit_created_at", "idx_audit_user_id", "idx_audit_event_type"):
        if idx in _audit_idx:
            op.drop_index(idx, table_name="audit_log")

    _batch_drop_cols("audit_log", ["ip_address", "detail", "user_id", "event_type", "created_at"])
