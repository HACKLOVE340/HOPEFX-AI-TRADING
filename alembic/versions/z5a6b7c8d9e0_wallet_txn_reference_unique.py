"""wallet_transactions — one external payment moves money once

ADR 0021 makes the fiat wallet the ledger the money path writes through, so
`payment_intent.succeeded` credits a wallet. Stripe delivers webhooks AT LEAST
once: retries and replays are normal, not exceptional. A repeated delivery that
credits twice creates capital out of nothing.

`transaction_id` is already unique, but it is generated per call
(`WalletManager._new_transaction_id`), so it deduplicates nothing. The key that
identifies the PAYMENT is the provider's own id, carried in `reference` as
e.g. "stripe:pi_3ABC...". This constraint is what makes the credit path
idempotent.

It is a database constraint rather than a read-then-write check in Python
because that check races: two concurrent deliveries of the same event both read
"not present" and both credit. The application still checks first — that is the
normal path and gives a clean answer — and this is the backstop that makes the
race safe rather than merely unlikely.

NULL references are left unconstrained. Every internal movement (fees,
commissions, transfers) has one, and both PostgreSQL and SQLite treat NULLs as
distinct, so the constraint applies only to rows naming an external payment.
Stated explicitly rather than relied upon silently.

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "z5a6b7c8d9e0"
down_revision = "y4z5a6b7c8d9"
branch_labels = None
depends_on = None

_TABLE = "wallet_transactions"
_CONSTRAINT = "uq_wallet_txn_user_reference"


def _has_table(name: str) -> bool:
    """Idempotent guard, matching the convention in the preceding migrations."""
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _has_constraint(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        existing = {c.get("name") for c in inspector.get_unique_constraints(table)}
    except Exception:
        return False
    return name in existing


def upgrade() -> None:
    if not _has_table(_TABLE) or _has_constraint(_TABLE, _CONSTRAINT):
        return

    # SQLite cannot ALTER TABLE ADD CONSTRAINT; batch_alter_table rebuilds the
    # table for it and emits a plain ALTER on PostgreSQL.
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_unique_constraint(_CONSTRAINT, ["user_id", "reference"])


def downgrade() -> None:
    if not _has_table(_TABLE) or not _has_constraint(_TABLE, _CONSTRAINT):
        return

    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CONSTRAINT, type_="unique")
