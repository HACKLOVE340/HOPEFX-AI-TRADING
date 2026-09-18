# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A database built by `create_all()` must be able to reach migration head.

`Base.metadata.create_all()` is called from five places —
`database/connection.py`, `database/models.py`, `cli.py` (twice),
`scripts/bootstrap_dev.py` and `scripts/create_superadmin.py`. So the ordinary
developer path is: bootstrap, get 47 tables, then run `alembic upgrade head`.

That failed:

    INFO  [alembic.runtime.migration] Running upgrade m1n2o3p4q5r6 -> n1o2p3q4r5s6
    sqlite3.OperationalError: table trade_journal already exists

Most migrations define a local `_tbl(name, *args, **kwargs)` that calls
`op.create_table` only when the table is absent, for exactly this reason. Two do
not, and `n1o2p3q4r5s6` is simply the first one reached — `s1t2u3v4w5x6` would
have failed next.

The consequence is not a developer annoyance. A deployment first stood up with
`create_all()` can **never** be brought under migration control: every attempt
dies at the same commit, so the schema stays frozen at whatever the ORM looked
like on the day it was created, and every later migration — including column
additions the application already depends on — is unreachable.

`docs/audit/TODO.md` recorded this as *"still open, found while verifying and
deliberately not fixed here"*, which was the right call at the time and left it
measured by nothing. Tracked as MIGRATE-OVER-CREATEALL.

The fix is to give the two migrations the guard their siblings already use, not
to change what `create_all()` does. Adding an existence check to a migration
that has already run is safe in both directions: where the table exists it
skips, and the end state is identical.
"""

from __future__ import annotations

import sqlite3

import pytest
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.unit


def _create_all_database(path) -> str:
    """A schema built the way `bootstrap_dev.py` builds one."""
    from sqlalchemy import create_engine

    from database.models import Base

    url = f"sqlite:///{path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


def test_the_fixture_really_builds_a_create_all_schema(tmp_path):
    """The positive control.

    If `create_all()` produced nothing, `upgrade head` below would succeed for
    the wrong reason — there would be no collision to collide with — and the
    real assertion would pass vacuously.
    """
    db = tmp_path / "schema.db"
    _create_all_database(db)

    con = sqlite3.connect(db)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()

    assert len(tables) > 40, f"create_all() produced only {len(tables)} tables"
    assert "trade_journal" in tables, "the table the collision was on is not being created"


def test_upgrade_head_reaches_head_over_a_create_all_database(tmp_path):
    """The regression. Red before the guards; `table trade_journal already exists`."""
    db = tmp_path / "schema.db"
    url = _create_all_database(db)

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    with pytest.MonkeyPatch.context() as mp:
        # alembic/env.py OVERRIDES sqlalchemy.url with DATABASE_URL, so setting
        # only the ini option lets any other test that exports it redirect this
        # upgrade at a different database.
        mp.setenv("DATABASE_URL", url)
        command.upgrade(cfg, "head")

    con = sqlite3.connect(db)
    try:
        stamped = con.execute("SELECT version_num FROM alembic_version").fetchall()
    finally:
        con.close()

    assert stamped, "upgrade completed but stamped no revision"


def test_upgrade_head_is_idempotent_over_a_create_all_database(tmp_path):
    """Running it twice must not fail either.

    The guards make each `create_table` conditional; a guard that only worked on
    the first pass would leave the second run failing, which is the state an
    operator re-running a failed deploy is in.
    """
    db = tmp_path / "schema.db"
    url = _create_all_database(db)

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")


def test_upgrade_head_still_works_on_an_empty_database(tmp_path):
    """The control that matters most: the guards must not skip a real creation.

    A guard written as `if table in existing: return` with `existing` computed
    wrongly would make every create_table a no-op, and a fresh install would end
    with an empty schema and a green migration run.
    """
    db = tmp_path / "schema.db"
    url = f"sqlite:///{db}"

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        command.upgrade(cfg, "head")

    con = sqlite3.connect(db)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()

    assert len(tables) > 40, f"a fresh migration run produced only {len(tables)} tables"
    for name in ("trade_journal", "sub_accounts", "billing_history", "creator_balances"):
        assert name in tables, f"{name} was skipped on a fresh database — the guard is too eager"
