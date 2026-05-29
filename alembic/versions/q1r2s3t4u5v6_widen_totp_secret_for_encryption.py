"""Widen totp_secret column to TEXT for AES-256-GCM encrypted storage.

The EncryptedString TypeDecorator stores: base64(nonce ‖ ciphertext ‖ tag).
A 32-character plaintext secret expands to roughly 80 characters after
encryption, which exceeds String(64).  Widening to TEXT (unlimited length)
accommodates any future secret size without requiring further migrations.

Existing rows that hold a TOTP secret will be treated as legacy plaintext
by the TypeDecorator on the next read and returned as-is.  Writes after
this migration (when DB_ENCRYPTION_KEY is set) will store encrypted blobs.

Revision ID: q1r2s3t4u5v6
Revises: p1q2r3s4t5u6
Create Date: 2026-05-29 19:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "q1r2s3t4u5v6"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widen totp_secret from VARCHAR(64) to TEXT so the AES-GCM blob fits.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "totp_secret",
            existing_type=sa.String(64),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Truncate back to VARCHAR(64); any encrypted values longer than 64 bytes
    # will be silently truncated — plaintext TOTP secrets are at most 32 chars.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "totp_secret",
            existing_type=sa.Text(),
            type_=sa.String(64),
            existing_nullable=True,
        )
