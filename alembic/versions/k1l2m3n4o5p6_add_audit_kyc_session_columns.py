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
    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("event_type", sa.String(100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("user_id", sa.String(100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("detail", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ip_address", sa.String(45), nullable=True)
        )

    # Back-fill created_at from timestamp for existing rows.
    op.execute("UPDATE audit_log SET created_at = timestamp WHERE created_at IS NULL")

    # Create indexes for the new columns.
    op.create_index("idx_audit_event_type", "audit_log", ["event_type"])
    op.create_index("idx_audit_user_id", "audit_log", ["user_id"])
    op.create_index("idx_audit_created_at", "audit_log", ["created_at"])

    # ── users ─────────────────────────────────────────────────────────────────
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("kyc_submitted_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("kyc_reviewed_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("kyc_reviewer_id", sa.String(100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("kyc_rejection_reason", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("kyc_document_type", sa.String(50), nullable=True)
        )

    # ── user_sessions ─────────────────────────────────────────────────────────
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("last_active_at", sa.DateTime(), nullable=True)
        )


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
