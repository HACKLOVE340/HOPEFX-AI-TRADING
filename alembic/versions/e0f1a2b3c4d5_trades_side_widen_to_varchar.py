# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""trades.side widens from the orderside enum to VARCHAR(20)

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-09-25

`database/models.py::Trade.side` has been a plain ``String(20)`` since before
this session; the migrated schema never followed it. `1b0666c43575` declared
``trades.side`` as ``sa.Enum("BUY", "SELL", name="orderside")``, a native
PostgreSQL ENUM, and no later migration touched its type — only its
nullability (`j1k2l3m4n5o6`). Measured against a real PostgreSQL 16 server on
2026-09-25 (`information_schema.columns`): the migrated column is
``USER-DEFINED`` / ``orderside``; the model's is ``character varying(20)``.
``tests/unit/test_migrated_schema_matches_models.py`` now compares every
column's PostgreSQL-rendered type, not just primary keys, and failed on this
one (plus two others fixed the same way, in the model, needing no migration:
`accounts.user_id` widens 36→50, `users.kyc_rejection_reason` becomes `Text`).

**Widen, not narrow.** VARCHAR(20) accepts every value the two-label enum
does, plus anything else up to 20 characters — a pre-trade write of 'BUY' or
'SELL' round-trips unchanged. The `orderside` type itself is left in place:
`orders.side` (`Column(Enum(OrderSide), ...)`) still uses it, and dropping it
would break that table.

**PostgreSQL** needs `USING side::text` — an enum has no implicit cast to
varchar. **SQLite** never had a real enum (Enum renders as a plain
VARCHAR(<longest label>) there), so the ALTER is a type-affinity relabel with
no data effect; `batch_alter_table` still recreates the table, which is how
SQLite performs any ALTER at all.

**Downgrade** re-narrows to the enum. That can fail on data a widened column
now legitimately holds (anything other than 'BUY'/'SELL'), so it checks first
and refuses with a clear error instead of letting PostgreSQL raise an opaque
invalid-input-value error mid-conversion — the same shape as the
`outbox_events.idempotency_key` migration's refusal (a6b7c8d9e0f1).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e0f1a2b3c4d5"  # pragma: allowlist secret
down_revision = "d9e0f1a2b3c4"  # pragma: allowlist secret
branch_labels = None
depends_on = None

_ENUM_TYPE = sa.Enum("BUY", "SELL", name="orderside")
_ALLOWED = ("BUY", "SELL")


def _table_present(name: str) -> bool:
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _table_present("trades"):
        return
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    with op.batch_alter_table("trades") as batch:
        if is_postgres:
            batch.alter_column(
                "side",
                existing_type=_ENUM_TYPE,
                type_=sa.String(20),
                existing_nullable=False,
                postgresql_using="side::text",
            )
        else:
            batch.alter_column(
                "side",
                existing_type=sa.String(4),
                type_=sa.String(20),
                existing_nullable=False,
            )


def downgrade() -> None:
    if not _table_present("trades"):
        return
    bind = op.get_bind()

    placeholders = ", ".join(f"'{v}'" for v in _ALLOWED)
    bad_rows = bind.execute(sa.text(f"SELECT DISTINCT side FROM trades WHERE side NOT IN ({placeholders})")).fetchall()
    if bad_rows:
        sample = ", ".join(repr(row[0]) for row in bad_rows[:5])
        raise RuntimeError(
            f"Refusing to narrow trades.side back to the orderside enum "
            f"({', '.join(_ALLOWED)}): {len(bad_rows)} distinct value(s) stored "
            f"fall outside it (sample: {sample}). A narrowing ALTER on that data "
            f"would fail on PostgreSQL (invalid input value for enum) or silently "
            f"be accepted and later misread elsewhere. Reconcile or reclassify "
            f"those rows before downgrading."
        )

    is_postgres = bind.dialect.name == "postgresql"
    with op.batch_alter_table("trades") as batch:
        if is_postgres:
            batch.alter_column(
                "side",
                existing_type=sa.String(20),
                type_=_ENUM_TYPE,
                existing_nullable=False,
                postgresql_using="side::orderside",
            )
        else:
            batch.alter_column(
                "side",
                existing_type=sa.String(20),
                type_=sa.String(4),
                existing_nullable=False,
            )
