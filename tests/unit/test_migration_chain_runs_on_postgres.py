# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The whole Alembic chain runs on a fresh PostgreSQL, and builds the models' schema.

Production is PostgreSQL. Every other migration test in this repository runs the
chain on SQLite, which accepts things PostgreSQL refuses — so until 2026-09-25 the
chain could not reach head on an empty PostgreSQL database at all:

    psycopg2.errors.DatatypeMismatch: column "needs_human" is of type boolean
    but default expression is of type integer

``x3y4z5a6b7c8`` (2026-09-10) gave a ``Boolean`` column ``server_default=sa.text("0")``;
SQLite stores that happily, PostgreSQL will not coerce an integer to a boolean.
``alembic/env.py`` runs the whole upgrade in ONE transaction, so the failure
rolled back every table the earlier migrations had created: a new deployment, or a
restore from scratch, ended with an empty database. And the startup path
(``core/startup_factories.py``) then *stamps the database at head* and builds it
with ``create_all()`` — which, while the models declared ``Integer`` ids, gave
32-bit ``SERIAL`` keys where the migrations say ``BIGINT``.

Two things are held here, both against a real server:

* the full chain upgrades to head, downgrades to base, and upgrades again;
* the schema the migrations build and the schema ``create_all()`` builds agree on
  the type of every primary-key column — the check that would have seen
  ``outbox_events.id`` / ``crypto_payments.id`` as ``INTEGER`` vs ``BIGINT``.

Server: ``TEST_POSTGRES_URL`` (or ``HOPEFX_TEST_POSTGRES_URL``,
``HOPEFX_TEST_PG_URL``, or a ``postgresql`` ``DATABASE_URL`` — CI's). Each test
module creates and drops its own databases; the server's own database is never
written. With no server the tests SKIP, loudly, because a green run of a suite
that never touched PostgreSQL is exactly how this defect stayed hidden. Set
``HOPEFX_REQUIRE_POSTGRES=1`` (CI does) to turn that skip into a failure.
"""

from __future__ import annotations

import os
import uuid
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]

_URL_VARS = ("TEST_POSTGRES_URL", "HOPEFX_TEST_POSTGRES_URL", "HOPEFX_TEST_PG_URL", "DATABASE_URL")

_UNPROVEN = (
    "UNPROVEN ON POSTGRESQL — the Alembic chain and the create_all() schema were NOT "
    "checked against a real server. Production is PostgreSQL; SQLite accepts DDL "
    "PostgreSQL refuses. Set TEST_POSTGRES_URL=postgresql://user@host:port/db "
    "(HOPEFX_REQUIRE_POSTGRES=1 makes this a failure). Reason: "
)


def _admin_url() -> str | None:
    """A sync (psycopg2) URL for a PostgreSQL server, or None if none is configured."""
    for var in _URL_VARS:
        raw = os.getenv(var, "")
        if not raw:
            continue
        scheme = raw.split("://", 1)[0].split("+", 1)[0]
        if scheme not in ("postgresql", "postgres"):
            continue
        return sa.engine.make_url(raw.replace("postgres://", "postgresql://", 1)).set(drivername="postgresql")
    return None


def _unavailable(reason: str) -> None:
    message = _UNPROVEN + reason
    if os.getenv("HOPEFX_REQUIRE_POSTGRES", "").strip().lower() in ("1", "true", "yes"):
        pytest.fail(message, pytrace=False)
    # A warning as well as the skip: `-q` runs hide skip reasons unless -rs is
    # passed, and the warnings summary is printed regardless.
    warnings.warn(message, stacklevel=2)
    pytest.skip(message)


@pytest.fixture(scope="module")
def admin_engine() -> Iterator[sa.Engine]:
    url = _admin_url()
    if url is None:
        _unavailable(f"none of {', '.join(_URL_VARS)} names a postgresql:// server")
    engine = sa.create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except sa.exc.OperationalError as exc:
        engine.dispose()
        _unavailable(f"the configured server is not reachable: {exc.orig}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def make_database(admin_engine) -> Iterator:
    """Factory for fresh, empty databases, all dropped at module teardown."""
    created: list[str] = []

    def _make(tag: str) -> str:
        name = f"hopefx_{tag}_{uuid.uuid4().hex[:10]}"
        with admin_engine.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return admin_engine.url.set(database=name).render_as_string(hide_password=False)

    yield _make
    with admin_engine.connect() as conn:
        for name in created:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _alembic(url: str, action: str, target: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run an Alembic command against ``url`` exactly as a deployment does.

    ``alembic/env.py`` lets ``DATABASE_URL`` override the ini, so it is set rather
    than only the config option. The crypto-sequence migration seeds from a
    counter file; point it at an absent one so the repository's own file (if any)
    cannot change what this test builds.
    """
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(tmp_path / "no-counter.json"))
    getattr(command, action)(cfg, target)


def _head() -> str:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"expected one Alembic head, found {heads}"
    return heads[0]


def _version(url: str) -> list[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            if not sa.inspect(conn).has_table("alembic_version"):
                return []
            return [r[0] for r in conn.execute(sa.text("SELECT version_num FROM alembic_version"))]
    finally:
        engine.dispose()


def _public_tables(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()


# ── 1. The chain runs, both ways ────────────────────────────────────────────


def test_full_chain_upgrades_downgrades_and_upgrades_again(make_database, monkeypatch, tmp_path):
    """upgrade head → downgrade base → upgrade head, on an empty PostgreSQL database."""
    url = make_database("chain")
    head = _head()

    _alembic(url, "upgrade", "head", monkeypatch, tmp_path)
    assert _version(url) == [head]
    built = _public_tables(url) - {"alembic_version"}
    # Harness-is-live guard: an upgrade that did nothing would also "reach head"
    # on a database stamped by someone else. It must have built the schema.
    assert len(built) > 40, f"upgrade reached head but built only {sorted(built)}"

    _alembic(url, "downgrade", "base", monkeypatch, tmp_path)
    assert _version(url) == []
    left = _public_tables(url) - {"alembic_version"}
    assert not left, f"downgrade to base left tables behind: {sorted(left)}"

    _alembic(url, "upgrade", "head", monkeypatch, tmp_path)
    assert _version(url) == [head]
    assert _public_tables(url) - {"alembic_version"} == built


# ── 2. Migrations and create_all() build the same primary keys ───────────────


def _pk_shapes(url: str) -> dict[str, dict[str, tuple[str, bool]]]:
    """table → {pk column → (type as PostgreSQL names it, database-assigned?)}."""
    engine = sa.create_engine(url)
    shapes: dict[str, dict[str, tuple[str, bool]]] = {}
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            for table in insp.get_table_names():
                if table == "alembic_version":
                    continue
                pk = set(insp.get_pk_constraint(table)["constrained_columns"])
                cols = {}
                for col in insp.get_columns(table):
                    if col["name"] not in pk:
                        continue
                    default = str(col.get("default") or "")
                    assigned = "nextval(" in default or bool(col.get("identity"))
                    cols[col["name"]] = (str(col["type"]), assigned)
                shapes[table] = cols
    finally:
        engine.dispose()
    return shapes


@pytest.fixture(scope="module")
def migrated_and_created(make_database, tmp_path_factory):
    """Two databases: one built by `alembic upgrade head`, one by `create_all()`."""
    migrated = make_database("migrated")
    with pytest.MonkeyPatch.context() as mp:
        _alembic(migrated, "upgrade", "head", mp, tmp_path_factory.mktemp("counter"))

    import database.user_models  # noqa: F401 — registers its tables on Base
    from database.models import Base

    created = make_database("createall")
    engine = sa.create_engine(created)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    return _pk_shapes(migrated), _pk_shapes(created)


def test_create_all_builds_the_primary_keys_the_migrations_build(migrated_and_created):
    """A PostgreSQL schema built by the startup create_all() fallback must match
    the migrated one on the type of every primary-key column.

    ``INTEGER`` where the migrations say ``BIGINT`` is a table that stops
    accepting rows at 2,147,483,647 — on exactly the append-only tables
    (outbox events, payments, audit rows) that grow without bound.
    """
    migrated, created = migrated_and_created
    common = sorted(set(migrated) & set(created))
    assert len(common) > 40, f"compared only {len(common)} tables — the harness is not seeing the schema"

    drift = []
    for table in common:
        for column in sorted(set(migrated[table]) | set(created[table])):
            m = migrated[table].get(column)
            c = created[table].get(column)
            if m != c:
                drift.append(f"  {table}.{column}: migrations={m}  create_all={c}")
    assert not drift, (
        "Primary keys differ between `alembic upgrade head` and `create_all()` on "
        "PostgreSQL — (type, database-assigned):\n" + "\n".join(drift)
    )


@pytest.mark.parametrize("table", ["outbox_events", "crypto_payments"])
def test_the_named_append_only_ids_are_64_bit_under_create_all(migrated_and_created, table):
    """The two ids MASTER_OUTSTANDING §A11 names, so a regression says which."""
    _, created = migrated_and_created
    assert created[table]["id"] == ("BIGINT", True), (
        f"create_all() on PostgreSQL gives {table}.id {created[table]['id']}, not a 64-bit database-assigned id"
    )
