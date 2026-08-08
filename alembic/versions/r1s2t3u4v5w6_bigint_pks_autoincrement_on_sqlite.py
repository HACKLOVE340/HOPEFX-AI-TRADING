# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""bigint primary keys must autoincrement on sqlite

Revision ID: r1s2t3u4v5w6
Revises: q1r2s3t4u5v6
Create Date: 2026-08-08

Thirteen tables were created with ``BIGINT PRIMARY KEY``. On PostgreSQL that is
BIGSERIAL and works. On SQLite only a column declared with the type word
``INTEGER`` is an alias for the implicit ``rowid``; ``BIGINT PRIMARY KEY`` is an
ordinary NOT NULL column, so every insert that lets the database assign the id
fails with ``NOT NULL constraint failed: <table>.id``.

Affected tables include ``audit_log`` and ``wallet_transactions``. The writers
caught the IntegrityError and continued — the superadmin audit writer logs
"action still executed" — so an append-only compliance log silently stopped
appending.

The models now use ``PKBigInt`` (``BigInteger().with_variant(Integer,
"sqlite")``), which fixes every schema built by ``create_all``. This migration
does the same for schemas built by Alembic.

**PostgreSQL is untouched.** The column is already BIGINT there and that is what
it should stay; this migration is a no-op on any non-SQLite backend. On SQLite
``batch_alter_table`` rebuilds each table (create new, copy rows, swap), which
is the only way to change a column type on that backend.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r1s2t3u4v5w6"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None


# Every table whose single-column integer primary key is assigned by the
# database. Kept explicit rather than reflected so this migration describes a
# fixed historical state and does not drift with the models.
_TABLES = (
    "account_snapshots",
    "ai_signals",
    "audit_log",
    "market_data",
    "news_data",
    "order_book_snapshots",
    "performance_metric_samples",
    "performance_metrics",
    "predictions",
    "system_events",
    "tick_data",
    "wallet_transactions",
    "watchlists",
)


def _sqlite_only() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _retype(to_type: sa.types.TypeEngine) -> None:
    """Rewrite each primary key to ``to_type``, skipping tables that are absent.

    A table can legitimately be missing: several were added by later migrations
    that a given database may not have reached, and ``watchlists`` is created
    conditionally. Failing the whole upgrade over one absent table would block
    boot on a partially-migrated dev database, which is exactly the environment
    this fixes.
    """
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
