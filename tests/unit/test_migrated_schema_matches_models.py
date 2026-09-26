# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The schema Alembic builds must be the schema the models declare.

`Base.metadata.create_all()` creates a missing table and **never alters an
existing one**. Every deployment that has run for a while was built by
`alembic upgrade head`, so anything the migrations do not create simply is not
there — and nothing announces it. The application finds out at query time, on
the oldest deployment, which is the worst place to find out.

F218 measured this at table granularity and reported 14 tables with no
migration. That count is closed: all 44 model tables are created by migrations
today. What was never measured is the granularity that actually bites, because
a table can be covered while its columns are not:

    sqlite3.OperationalError: no such column: tick_data.quality

`tick_data` is created by the initial migration in an eight-column shape.
Six columns were added to the model afterwards with no migration behind them,
`ts_ns` among them — the column every insert in
`database/repositories/tick_data_repository.py` writes and every ordering query
reads. On a migrated database that repository could not write a single row.

So these tests build a database the way a deployment does — `alembic upgrade
head` against an empty database, no `create_all()` anywhere — and compare it to
the models column by column. The table-level check is kept as a regression guard
so F218's original finding cannot come back.
"""

from __future__ import annotations

import sqlite3

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.ddl.impl import DefaultImpl
from alembic.operations.batch import ApplyBatchImpl
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateColumn

import database.user_models  # noqa: F401 — registers its tables on Base
from database.models import Base

pytestmark = [pytest.mark.unit, pytest.mark.slow]

#: Columns present in the migrated schema but not in any model. An extra column
#: is not the failure this module is about — it is dead weight, not a crash —
#: but it is worth seeing, so it is asserted rather than ignored.
KNOWN_EXTRA_COLUMNS: dict[str, set[str]] = {}


@pytest.fixture(scope="module")
def migration_run(tmp_path_factory):
    """A database built only by the migrations, exactly as a deployment is —
    plus every ``sa.Table`` the migrations handed to ``create_table``.

    DATABASE_URL is set, not just the ini option: `alembic/env.py` reads that
    env var and *overrides* `sqlalchemy.url` with it. Setting only the config
    lets any other test that exports DATABASE_URL redirect this migration to a
    different database, and the assertions below then describe that one — which
    is how this fixture first failed, under `-k` selection rather than alone.

    The recorded tables carry the types the migration *declared*, before SQLite
    flattened them. That is what lets a SQLite run see a PostgreSQL-only drift:
    ``BigInteger().with_variant(Integer, "sqlite")`` and ``Integer`` both read
    back from SQLite as ``INTEGER``, but compile differently for PostgreSQL.
    """
    db = tmp_path_factory.mktemp("migrated") / "schema.db"
    cfg = Config("alembic.ini")
    url = f"sqlite:///{db}"
    cfg.set_main_option("sqlalchemy.url", url)
    created: dict[str, sa.Table] = {}
    #: (table, column) -> the type each migration declared for it, last write
    #: wins. Populated by `create_table` (initial shape), `add_column` (a
    #: column that arrived later) and `alter_column` — both the direct form
    #: and the one `batch_alter_table` uses, which never reaches
    #: `DefaultImpl.alter_column` at all: `ApplyBatchImpl.alter_column`
    #: mutates the column object in place instead. Missing that second hook
    #: was tried first and is why it is called out here — it silently made
    #: every `batch.alter_column(..., type_=...)` invisible to this capture,
    #: including the NUMERIC conversion in t1u2v3w4x5y6.
    column_types: dict[tuple[str, str], sa.types.TypeEngine] = {}
    real_create_table = DefaultImpl.create_table
    real_add_column = DefaultImpl.add_column
    real_alter_column = DefaultImpl.alter_column
    real_batch_alter_column = ApplyBatchImpl.alter_column
    real_drop_column = DefaultImpl.drop_column

    def recording_create_table(self, table, **kw):
        # First creation wins: batch_alter_table's SQLite rebuilds go through
        # `_alembic_tmp_<name>` with the SQLite-only retyped columns — those
        # are reflected off the live SQLite table, which loses type fidelity
        # for every column the rebuild did NOT explicitly retype (a BigInteger
        # PK reflects back as plain Integer, matching SQLite's rowid alias).
        # Recording only the first, migration-declared shape avoids importing
        # that reflection noise into `column_types` for untouched columns.
        if not table.name.startswith("_alembic_tmp_"):
            created.setdefault(table.name, table)
            for column in table.columns:
                column_types.setdefault((table.name, column.name), column.type)
        return real_create_table(self, table, **kw)

    def recording_add_column(self, table_name, column, **kw):
        column_types[(table_name, column.name)] = column.type
        return real_add_column(self, table_name, column, **kw)

    def recording_alter_column(self, table_name, column_name, *, type_=None, **kw):
        if type_ is not None:
            column_types[(table_name, column_name)] = type_
        return real_alter_column(self, table_name, column_name, type_=type_, **kw)

    def recording_batch_alter_column(self, table_name, column_name, *args, type_=None, **kw):
        # The column object `self.table` refers to here is the real table
        # name being batch-altered, not the `_alembic_tmp_...` copy it will
        # briefly become — no canonicalisation needed, unlike create_table.
        if type_ is not None:
            column_types[(self.table.name, column_name)] = type_
        return real_batch_alter_column(self, table_name, column_name, *args, type_=type_, **kw)

    def recording_drop_column(self, table_name, column, **kw):
        column_types.pop((table_name, column.name), None)
        return real_drop_column(self, table_name, column, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        mp.setattr(DefaultImpl, "create_table", recording_create_table)
        mp.setattr(DefaultImpl, "add_column", recording_add_column)
        mp.setattr(DefaultImpl, "alter_column", recording_alter_column)
        mp.setattr(ApplyBatchImpl, "alter_column", recording_batch_alter_column)
        mp.setattr(DefaultImpl, "drop_column", recording_drop_column)
        command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    yield con, created, column_types
    con.close()


@pytest.fixture(scope="module")
def migrated_db(migration_run) -> sqlite3.Connection:
    return migration_run[0]


def migrated_tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in rows} - {"alembic_version"}


def migrated_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}


def test_every_model_table_is_created_by_a_migration(migrated_db):
    """F218's original finding, kept as a regression guard."""
    missing = sorted(set(Base.metadata.tables) - migrated_tables(migrated_db))
    assert not missing, (
        f"{len(missing)} model tables are not created by any migration, so they "
        f"exist only on databases built by create_all(): {missing}"
    )


def test_every_model_column_exists_in_the_migrated_schema(migrated_db):
    """The granularity that actually bites: a covered table, an absent column."""
    gaps: dict[str, list[str]] = {}
    for table, model_table in sorted(Base.metadata.tables.items()):
        if table not in migrated_tables(migrated_db):
            continue  # reported by the table-level test; not double-counted here
        declared = {c.name for c in model_table.columns}
        absent = declared - migrated_columns(migrated_db, table)
        if absent:
            gaps[table] = sorted(absent)
    assert not gaps, (
        "Columns declared by a model that no migration creates. Every query "
        "touching one of these fails at runtime on a migrated database:\n"
        + "\n".join(f"  {t}: {cols}" for t, cols in gaps.items())
    )


def test_migrated_schema_has_no_columns_the_models_dropped(migrated_db):
    """The other direction — a column the models no longer declare."""
    extras: dict[str, list[str]] = {}
    for table in sorted(migrated_tables(migrated_db) & set(Base.metadata.tables)):
        declared = {c.name for c in Base.metadata.tables[table].columns}
        left = migrated_columns(migrated_db, table) - declared - KNOWN_EXTRA_COLUMNS.get(table, set())
        if left:
            extras[table] = sorted(left)
    assert not extras, (
        "Columns the migrations create that no model declares. Harmless at "
        "runtime, but it means the migration and the model have diverged and "
        "one of them is wrong:\n" + "\n".join(f"  {t}: {c}" for t, c in extras.items())
    )


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("tick_data", "ts_ns"),  # every insert writes it; every ordering query reads it
        ("tick_data", "quality"),
        ("tick_data", "confidence"),
        ("tick_data", "lineage_id"),
        ("accounts", "account_name"),
        ("orders", "account_id"),
    ],
)
def test_the_specific_columns_that_were_missing(migrated_db, table, column):
    """Named individually so a regression says which column came back."""
    assert column in migrated_columns(migrated_db, table), (
        f"{table}.{column} is declared by the model and created by no migration"
    )


# ── Types, not just names ───────────────────────────────────────────────────
#
# Everything above compares column NAMES on SQLite. It could not see the drift
# found on 2026-09-25: `outbox_events.id` and `crypto_payments.id` were `Integer`
# in the models and `BigInteger` in the migrations. SQLite reads both back as
# INTEGER — deliberately, since only that word aliases the rowid — so no
# SQLite-reflected comparison can tell them apart. On PostgreSQL the startup
# `create_all()` fallback built them as 32-bit SERIAL.
#
# This compares the PostgreSQL rendering of each primary-key column as the
# migration declared it with the PostgreSQL rendering of the model's column.
# `tests/unit/test_migration_chain_runs_on_postgres.py` holds the same property
# against a real server; this one runs anywhere.


def _pg_pk_spec(table: sa.Table) -> dict[str, str]:
    """pk column → its PostgreSQL type as CREATE TABLE would render it (SERIAL/BIGSERIAL/…)."""
    dialect = postgresql.dialect()
    specs = {}
    for column in table.primary_key.columns:
        rendered = str(CreateColumn(column).compile(dialect=dialect))
        specs[column.name] = rendered.split()[1]  # "<name> <TYPE> ..." → TYPE
    return specs


def test_primary_key_types_match_the_models_as_postgresql_renders_them(migration_run):
    _, created, _ = migration_run
    compared = sorted(set(created) & set(Base.metadata.tables))
    # Harness-is-live guard: the recording hook must actually have seen the
    # chain's CREATE TABLEs, or an empty loop below would pass.
    assert len(compared) > 40, f"recorded only {len(compared)} migration-created model tables"

    drift = []
    for name in compared:
        declared = _pg_pk_spec(created[name])
        modelled = _pg_pk_spec(Base.metadata.tables[name])
        if declared != modelled:
            drift.append(f"  {name}: migrations={declared}  models={modelled}")
    assert not drift, (
        "Primary-key types differ between the migrations and the models when "
        "rendered for PostgreSQL — a schema built by create_all() is not the "
        "migrated schema:\n" + "\n".join(drift)
    )


# ── Every other column, not just the primary key ────────────────────────────
#
# The PK check above exists because a SQLite-reflected comparison cannot tell
# Integer from BigInteger. The same blind spot applies to every non-PK column,
# and a full comparison — every column's PostgreSQL-rendered type against the
# model's — found four real drifts (MASTER_OUTSTANDING §A11 context, measured
# 2026-09-25 against both this offline capture and a real PostgreSQL 16
# server): `accounts.user_id` VARCHAR(50) vs VARCHAR(36), `trades.side` a
# native `orderside` ENUM vs VARCHAR(20), `users.kyc_rejection_reason` TEXT vs
# a bare (unbounded) VARCHAR, and `tick_data.timestamp` TIMESTAMP WITHOUT TIME
# ZONE vs WITH TIME ZONE. `trades.status` — reported elsewhere as a fifth
# candidate — is NOT a drift: both sides render as the same `tradestatus`
# native enum.
#
# The widen-only rule applies to the first and third: the model is corrected
# to the more permissive of the two. It does NOT apply to `trades.side`: an
# earlier version of this fix widened the database to VARCHAR(20), and that
# was wrong. The `orderside` ENUM is a real integrity constraint on a
# money-critical column, and the model's side (`String(20),
# server_default="unknown"`) is the looser one — widening the DB would have
# let 'unknown', 'LONG' or any other spelling in, which is exactly the vocabulary
# drift MASTER_OUTSTANDING §A9 already tracks ("long" has three spellings in
# this codebase). Resolving §A9 is what should decide this column's type, not
# a schema-consistency pass — it stays KNOWN, not fixed.
#
# `tick_data.timestamp` is CLOSED (2026-09-25, migration f2a3b4c5d6e7): the
# owner approved storing it as UTC, timezone-aware, and both live writers were
# verified to construct aware UTC datetimes before the fix, not assumed. See
# that migration's docstring for the evidence, including what a real
# PostgreSQL 16 server actually did with an aware write against the old
# naive column on each driver this codebase uses.
KNOWN_COLUMN_TYPE_DRIFT: dict[tuple[str, str], str] = {
    ("trades", "side"): (
        "genuine drift, deliberately NOT widened: the database enforces the "
        "`orderside` ENUM(BUY, SELL) — a real integrity constraint on a "
        "money-critical column. The model is the looser side "
        "(String(20), server_default='unknown'); widening the database to "
        "match it would remove that constraint and let 'unknown', 'LONG' or "
        "any other spelling into the DB. Resolution belongs to "
        "MASTER_OUTSTANDING §A9 (one side vocabulary — 'long' already has "
        "three spellings in this codebase), not to a schema-consistency pass. "
        "Measured 2026-09-25 against a real PostgreSQL 16 server: every "
        "current production write path already fails against the ENUM as it "
        "stands — brokers/__init__.py and brokers/paper_trading.py pass a raw "
        "`OrderSide` enum member and get `can't adapt type 'OrderSide'`; "
        "scripts/seed_demo_trades.py writes lowercase 'buy'/'sell' and gets "
        "`invalid input value for enum orderside`; relying on the model's "
        "declared server_default (omitting side) gets a NOT NULL violation, "
        "because no migration ever added that default to the actual column. "
        "Only literal uppercase 'BUY'/'SELL' succeeds. The ENUM is not an "
        "inconvenience to widen away — it is already the thing keeping bad "
        "values out, and every write path that reaches it is currently broken "
        "in a different, unrelated way that widening would have papered over."
    ),
    ("positions", "user_id"): (
        "SQLite-only artifact of this offline capture, not a real drift: "
        "p1q2r3s4t5u6 narrows positions.user_id from VARCHAR(50) to "
        "VARCHAR(36) on PostgreSQL to match the model, but does it inside "
        '`if dialect != "sqlite":` — a real guard against SQLite\'s lack of '
        "ADD CONSTRAINT, not a mistake, but it means the narrowing ALTER never "
        "runs while this fixture drives the chain over SQLite, so the capture "
        "below still shows VARCHAR(50). Verified equal (both VARCHAR(36)) "
        "against a real PostgreSQL 16 server on 2026-09-25 — do not widen the "
        "model to 50 to silence this: that would create a real drift where "
        "none exists today."
    ),
}


def _pg_column_type(column: sa.Column | sa.types.TypeEngine) -> str:
    """Just the PostgreSQL-rendered type, e.g. VARCHAR(20) — not NOT NULL/DEFAULT.

    Those belong to the Column, not the type, and comparing full `CreateColumn`
    text (as the PK check above does) mixes them in: a migration-side type
    wrapped fresh in a throwaway Column is always nullable with no default,
    while the model's real Column usually is not, so every row would show a
    spurious NOT NULL/DEFAULT difference alongside — or instead of — any real
    type difference. Compiling the type alone avoids that entirely.
    """
    dialect = postgresql.dialect()
    the_type = column.type if isinstance(column, sa.Column) else column
    return str(the_type.compile(dialect=dialect))


def test_column_types_match_the_models_as_postgresql_renders_them(migration_run):
    """Every column, not just the primary key — see the section banner above."""
    _, created, column_types = migration_run
    # Harness-is-live guard, mirroring the PK test: the capture must have
    # actually recorded something, or an empty comparison below would pass
    # vacuously.
    assert len(column_types) > 500, f"recorded only {len(column_types)} migrated columns"

    drift = []
    for table, model_table in sorted(Base.metadata.tables.items()):
        if table not in created:
            continue  # reported by test_every_model_table_is_created_by_a_migration
        pk_columns = {c.name for c in model_table.primary_key.columns}
        for model_column in model_table.columns:
            if model_column.name in pk_columns:
                continue  # covered by test_primary_key_types_match_...
            key = (table, model_column.name)
            if key not in column_types:
                continue  # reported by test_every_model_column_exists_in_the_migrated_schema
            if key in KNOWN_COLUMN_TYPE_DRIFT:
                continue
            declared = _pg_column_type(column_types[key])
            modelled = _pg_column_type(model_column)
            if declared != modelled:
                drift.append(f"  {table}.{model_column.name}: migrations={declared}  models={modelled}")
    assert not drift, (
        "Non-primary-key column types differ between the migrations and the "
        "models when rendered for PostgreSQL — a schema built by create_all() "
        "is not the migrated schema, and production runs PostgreSQL. Widen "
        "the narrower side, or list the column in KNOWN_COLUMN_TYPE_DRIFT with "
        "a reason if a plain widen is not the right call:\n" + "\n".join(drift)
    )
