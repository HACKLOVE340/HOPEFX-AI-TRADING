# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""crypto_payments records the HD derivation index and path of its address

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1g2
Create Date: 2026-09-25

A crypto payment row stored the deposit address and nothing about how it was
derived, so reconciling an incoming deposit to a payment -- and sweeping the
funds -- meant re-deriving every index until one matched. It also hid the
defect this accompanies: every BTC deposit address was derived at index 0, and
nothing on the row could show it.

Both columns are nullable: rows written before this revision have no recorded
derivation, and inventing one would be worse than leaving it blank. New rows
always carry both -- ``api/payments.py::generate_deposit_address`` refuses to
issue an address whose derivation is unknown.

Idempotent in the style of this directory: a column that already exists (for
example on a database built by ``create_all()``) is left alone.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8d9e0f1a2b3"  # pragma: allowlist secret
down_revision = "b7c8d9e0f1g2"  # pragma: allowlist secret
branch_labels = None
depends_on = None

_TABLE = "crypto_payments"


def _existing_columns() -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return None
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    existing = _existing_columns()
    if existing is None:
        return
    if "derivation_index" not in existing:
        op.add_column(_TABLE, sa.Column("derivation_index", sa.Integer(), nullable=True))
    if "derivation_path" not in existing:
        op.add_column(_TABLE, sa.Column("derivation_path", sa.String(length=64), nullable=True))


def downgrade() -> None:
    existing = _existing_columns()
    if existing is None:
        return
    with op.batch_alter_table(_TABLE) as batch:
        if "derivation_path" in existing:
            batch.drop_column("derivation_path")
        if "derivation_index" in existing:
            batch.drop_column("derivation_index")
