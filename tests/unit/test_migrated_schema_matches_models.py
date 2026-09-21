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
from alembic import command
from alembic.config import Config

from database.models import Base

pytestmark = [pytest.mark.unit, pytest.mark.slow]

#: Columns present in the migrated schema but not in any model. An extra column
#: is not the failure this module is about — it is dead weight, not a crash —
#: but it is worth seeing, so it is asserted rather than ignored.
KNOWN_EXTRA_COLUMNS: dict[str, set[str]] = {}


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory) -> sqlite3.Connection:
    """A database built only by the migrations, exactly as a deployment is.

    DATABASE_URL is set, not just the ini option: `alembic/env.py` reads that
    env var and *overrides* `sqlalchemy.url` with it. Setting only the config
    lets any other test that exports DATABASE_URL redirect this migration to a
    different database, and the assertions below then describe that one — which
    is how this fixture first failed, under `-k` selection rather than alone.
    """
    db = tmp_path_factory.mktemp("migrated") / "schema.db"
    cfg = Config("alembic.ini")
    url = f"sqlite:///{db}"
    cfg.set_main_option("sqlalchemy.url", url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    yield con
    con.close()


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
