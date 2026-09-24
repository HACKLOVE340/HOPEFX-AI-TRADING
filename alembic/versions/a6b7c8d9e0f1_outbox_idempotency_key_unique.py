"""outbox_events.idempotency_key — enforce the UNIQUE the model declares

`database/models.py::OutboxEvent.idempotency_key` declares `unique=True`, but
`alembic/versions/n1o2p3q4r5s6_...py` added the column to an existing
`outbox_events` table without a unique constraint. So the guarantee the ORM
model claims held only under `Base.metadata.create_all()` (a from-scratch
deploy, or the test suite) and not on any database actually built by
`alembic upgrade head` — every long-running deployment. The relay's
duplicate-skip branch in `core/outbox.py` (a `SELECT ... WHERE
idempotency_key = :key` guard) was therefore the ONLY thing standing between
a replayed at-least-once producer and two rows racing to be delivered twice.
Owner decision A11 (docs/ai/MASTER_OUTSTANDING.md §A11,
docs/audit/CORRECTION_REGISTER.md): enforce UNIQUE via a migration.

Outbox events are real operational data — a kill-switch activation, an AML
block, an order fill awaiting delivery — so this migration never deletes a
row to make room for the constraint. If duplicate keys already exist on a
database this runs against, `upgrade()` refuses outright and names the exact
count and the keys involved, so an operator can decide how to reconcile them
(the same shape a NOT NULL backfill migration would want, but the safe
resolution here is not "pick one and drop the rest" — a compliance record was
about to describe two different actual attempts to publish).

NULLs are left unconstrained, matching `z5a6b7c8d9e0`'s wallet_transactions
precedent: only rows carrying an explicit idempotency key are deduplicated,
and both PostgreSQL and SQLite treat NULL != NULL under a unique index.

Revision ID: a6b7c8d9e0f1
Revises: z5a6b7c8d9e0
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a6b7c8d9e0f1"  # pragma: allowlist secret
down_revision = "z5a6b7c8d9e0"  # pragma: allowlist secret
branch_labels = None
depends_on = None

_TABLE = "outbox_events"
_CONSTRAINT = "uq_outbox_events_idempotency_key"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _has_constraint(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        existing = {c.get("name") for c in inspector.get_unique_constraints(table)}
    except Exception:
        return False
    if name in existing:
        return True
    # SQLite (and some PostgreSQL setups) surface a UNIQUE constraint as a
    # plain unique index instead of a named table constraint.
    try:
        existing_indexes = {i.get("name") for i in inspector.get_indexes(table) if i.get("unique")}
    except Exception:
        existing_indexes = set()
    return name in existing_indexes


def _duplicate_idempotency_keys(bind) -> list[tuple[str, int]]:
    """(key, count) for every idempotency_key used by more than one row."""
    rows = bind.execute(
        sa.text(
            f"SELECT idempotency_key, COUNT(*) AS n FROM {_TABLE} "
            "WHERE idempotency_key IS NOT NULL "
            "GROUP BY idempotency_key HAVING COUNT(*) > 1"
        )
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def upgrade() -> None:
    if not _has_table(_TABLE) or _has_constraint(_TABLE, _CONSTRAINT):
        return

    bind = op.get_bind()
    duplicates = _duplicate_idempotency_keys(bind)
    if duplicates:
        sample_limit = 10
        total_rows = sum(count for _key, count in duplicates)
        sample = ", ".join(f"{key!r} x{count}" for key, count in duplicates[:sample_limit])
        more = "" if len(duplicates) <= sample_limit else f", and {len(duplicates) - sample_limit} more key(s)"
        raise RuntimeError(
            f"Refusing to add a UNIQUE constraint on {_TABLE}.idempotency_key: "
            f"{len(duplicates)} duplicate key(s) covering {total_rows} row(s) "
            f"already exist ({sample}{more}). These are live outbox events — "
            "this migration will not delete rows to make room for the "
            "constraint. Reconcile the duplicates by hand (decide which row "
            "of each pair is the delivery of record) and re-run the upgrade."
        )

    # SQLite cannot ALTER TABLE ADD CONSTRAINT; batch_alter_table rebuilds the
    # table for it and emits a plain ALTER on PostgreSQL.
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_unique_constraint(_CONSTRAINT, ["idempotency_key"])


def downgrade() -> None:
    if not _has_table(_TABLE) or not _has_constraint(_TABLE, _CONSTRAINT):
        return

    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CONSTRAINT, type_="unique")
