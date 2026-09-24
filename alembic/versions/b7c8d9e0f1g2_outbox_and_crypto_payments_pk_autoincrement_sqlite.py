# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""outbox_events.id and crypto_payments.id must autoincrement on sqlite

Revision ID: b7c8d9e0f1g2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-24

``r1s2t3u4v5w6`` ("bigint primary keys must autoincrement on sqlite",
2026-08-08) retyped thirteen tables' single-column integer primary keys from
``BIGINT`` to ``INTEGER`` on SQLite, because only the literal type word
``INTEGER`` aliases SQLite's rowid — a ``BIGINT PRIMARY KEY`` is an ordinary
NOT NULL column that the database will not assign a value to. Two tables have
the identical shape and were missed: ``outbox_events`` and ``crypto_payments``,
both created by
``alembic/versions/b2c3d4e5f6a7_idempotency_and_new_tables.py`` (2026-06-01,
already merged before ``r1s2t3u4v5w6`` ran) as::

    sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
    ...
    sa.PrimaryKeyConstraint("id"),

Neither table is in ``r1s2t3u4v5w6``'s ``_TABLES`` list, so on a SQLite
database built by ``alembic upgrade head`` every insert that lets the database
assign the id fails::

    sqlite3.IntegrityError: NOT NULL constraint failed: outbox_events.id
    sqlite3.IntegrityError: NOT NULL constraint failed: crypto_payments.id

Both production writers omit the id and swallow the resulting
``IntegrityError`` rather than raising — ``core/outbox.py::write_outbox_event``
/ ``write_outbox_event_standalone`` log and continue, and
``api/payments.py::_save_payment`` does the same — the identical
"action still executed" shape ``r1s2t3u4v5w6`` describes for the audit log.
On a SQLite deployment a kill-switch, AML-block or fill outbox event, or a
crypto payment record, silently fails to persist.

Found on the way while implementing owner decision A11 (enforce UNIQUE on
``outbox_events.idempotency_key``, migration ``a6b7c8d9e0f1``), recorded in
``docs/ai/MASTER_OUTSTANDING.md`` §A11's "found on the way, still open" note.

**PostgreSQL is untouched, and does not need to be.** The exact same column
definition already compiles to BIGSERIAL there — verified by compiling it
under the PostgreSQL dialect
(``tests/unit/test_outbox_and_crypto_payments_autoincrement_migration.py::test_still_bigserial_on_postgres``)
— because SQLAlchemy's autoincrement-PK detection does not require
``primary_key=True`` directly on the ``Column``; a single-column
``PrimaryKeyConstraint`` naming it is enough. This migration is a no-op on any
non-SQLite backend, exactly like ``r1s2t3u4v5w6``.

As with ``r1s2t3u4v5w6``, ``batch_alter_table`` rebuilds each table on SQLite
(create new, copy rows, swap) — the only way to change a column type on that
backend — so existing rows keep their ids across the retype.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7c8d9e0f1g2"  # pragma: allowlist secret
down_revision = "a6b7c8d9e0f1"  # pragma: allowlist secret
branch_labels = None
depends_on = None


_TABLES = (
    "outbox_events",
    "crypto_payments",
)


def _sqlite_only() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _retype(to_type: sa.types.TypeEngine) -> None:
    present = _existing_tables()
    for table in _TABLES:
        if table not in present:
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column("id", existing_type=sa.BigInteger(), type_=to_type, existing_nullable=False)


def upgrade() -> None:
    if not _sqlite_only():
        return
    _retype(sa.Integer())


def downgrade() -> None:
    if not _sqlite_only():
        return
    _retype(sa.BigInteger())
