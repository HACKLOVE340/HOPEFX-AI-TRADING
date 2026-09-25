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
    real_create_table = DefaultImpl.create_table

    def recording_create_table(self, table, **kw):
        # First creation wins: batch_alter_table's SQLite rebuilds go through
        # `_alembic_tmp_<name>` with the SQLite-only retyped columns.
        if not table.name.startswith("_alembic_tmp_"):
            created.setdefault(table.name, table)
        return real_create_table(self, table, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        mp.setattr(DefaultImpl, "create_table", recording_create_table)
        command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    yield con, created
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
    _, created = migration_run
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
