# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A failed migration at startup refuses to start. It never stamps head.

``core/startup_factories.py::init_database`` used to handle a failed
``alembic upgrade head`` like this: log a WARNING, ``alembic stamp head``, then
``Base.metadata.create_all()``, and carry on serving. Reproduced on PostgreSQL
16.13 on 2026-09-25, with a view in the way of ``outbox_events``:

    init_database: returned
    alembic_version: [('d9e0f1a2b3c4',)]      <- head  # pragma: allowlist secret
    crypto_hd_index sequences: []             <- d9e0f1a2b3c4 never ran  # pragma: allowlist secret
    tables: 50                                <- create_all() built them

The database now said "at head" with no migration applied, so the next boot's
upgrade was a no-op and the damage was permanent and silent. Address issuing
then refused with 503 for want of the sequences, and ids were 32-bit.

Held here, with the owner's decision (2026-09-25: refuse to start):

* outside development and test (``utils.production_guard.current_env``; UNSET is
  production), a failed upgrade raises, logs CRITICAL with the error and the
  current and target revisions, and leaves ``alembic_version`` exactly as it
  found it, with no ``create_all()``;
* what it raises is a ``SystemExit``, because ``ComponentRegistry`` and
  ``app.startup_event`` catch ``Exception`` and would otherwise leave a pod
  serving on a broken schema. ``app._on_startup_task_done`` turns a
  non-``Exception`` into ``os._exit`` so the pod is reported failed;
* development and test keep ``create_all()`` as the schema source when the
  upgrade fails, but still never stamp;
* a database whose version table says head but which lacks the objects the
  head migration creates is refused on PostgreSQL, pointing at runbook §6a;
* ``/ready`` answers 503 while the schema is unverified.

The PostgreSQL tests need ``TEST_POSTGRES_URL`` and skip LOUDLY without one, in
the pattern of ``test_migration_chain_runs_on_postgres.py``;
``HOPEFX_REQUIRE_POSTGRES=1`` makes the skip a failure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
import warnings
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
HEAD = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini"))).get_current_head()
# d9e0f1a2b3c4's parent: a real revision, one step short of head.
BEFORE_HEAD = "c8d9e0f1a2b3"  # pragma: allowlist secret
# A revision this codebase has never heard of: `alembic upgrade` genuinely fails.
UNKNOWN = "feedfacecafe"  # pragma: allowlist secret


# ── helpers ───────────────────────────────────────────────────────────────────


def _state(url: str) -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(database=SimpleNamespace(get_connection_string=lambda: url)))


def _run_init(url: str):
    from core.startup_factories import init_database

    state = _state(url)
    return state, asyncio.run(init_database(state))


def _run_init_catching(url: str) -> BaseException | None:
    """Run startup; return whatever escaped (None if it returned)."""
    try:
        _run_init(url)
    except BaseException as exc:  # the type is what is asserted
        return exc
    return None


def _versions(url: str) -> list[str] | None:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            if not sa.inspect(conn).has_table("alembic_version"):
                return None
            return [r[0] for r in conn.execute(sa.text("SELECT version_num FROM alembic_version"))]
    finally:
        engine.dispose()


def _tables(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()


def _seed_version_table(url: str, revision: str) -> None:
    """A database that says it is at *revision* and holds nothing else."""
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES (:r)"), {"r": revision})
    finally:
        engine.dispose()


def _failing_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `alembic upgrade` raise, as a migration that raises does."""
    import alembic.command

    def _boom(*_a, **_k):
        raise RuntimeError("migration x9 raised: relation already exists")

    monkeypatch.setattr(alembic.command, "upgrade", _boom)


@pytest.fixture()
def repo_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    # init_database reads "alembic.ini" relative to the working directory, as
    # the container does from /app.
    monkeypatch.chdir(REPO)


@pytest.fixture()
def production(monkeypatch: pytest.MonkeyPatch, repo_cwd) -> None:
    """APP_ENV unset: `current_env()` reads that as production."""
    monkeypatch.delenv("APP_ENV", raising=False)


@pytest.fixture()
def sqlite_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'hopefx.db'}"
    # alembic/env.py lets DATABASE_URL override the ini, as it does in the pod.
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    return url


# ── (a) production: a failed upgrade refuses, and touches nothing ─────────────


class TestAFailedUpgradeRefusesToStartInProduction:
    def test_a_real_alembic_failure_escapes_startup(self, production, sqlite_url) -> None:
        """alembic cannot locate the database's revision: a genuine upgrade failure."""
        _seed_version_table(sqlite_url, UNKNOWN)
        escaped = _run_init_catching(sqlite_url)
        assert escaped is not None, "startup carried on after `alembic upgrade head` failed"

    def test_what_escapes_is_not_an_exception_so_nothing_catches_it(self, production, sqlite_url) -> None:
        """ComponentRegistry.start_all and app.startup_event both `except Exception`.

        Anything that IS an Exception leaves the API up with initialized=False
        (app._on_startup_task_done says so), which is a pod serving on a broken
        schema. A SystemExit reaches os._exit and k8s sees a failed pod.
        """
        _seed_version_table(sqlite_url, UNKNOWN)
        escaped = _run_init_catching(sqlite_url)
        assert isinstance(escaped, SystemExit)
        assert escaped.code not in (0, None)

    def test_the_registry_does_not_swallow_it(self, production, sqlite_url) -> None:
        from core.component_registry import ComponentRegistry
        from core.startup_factories import init_database

        _seed_version_table(sqlite_url, UNKNOWN)
        registry = ComponentRegistry()
        registry.register("database", init_database, required=True)
        with pytest.raises(SystemExit):
            asyncio.run(registry.start_all(_state(sqlite_url)))

    def test_the_version_row_is_left_exactly_as_found(self, production, sqlite_url, monkeypatch) -> None:
        """The pre-fix code stamped head here, and the next boot skipped the upgrade."""
        _seed_version_table(sqlite_url, BEFORE_HEAD)
        _failing_upgrade(monkeypatch)
        _run_init_catching(sqlite_url)
        assert _versions(sqlite_url) == [BEFORE_HEAD]

    def test_create_all_does_not_build_the_schema(self, production, sqlite_url, monkeypatch) -> None:
        _seed_version_table(sqlite_url, BEFORE_HEAD)
        _failing_upgrade(monkeypatch)
        _run_init_catching(sqlite_url)
        assert _tables(sqlite_url) == {"alembic_version"}

    def test_it_logs_critical_with_the_error_and_both_revisions(
        self, production, sqlite_url, monkeypatch, caplog
    ) -> None:
        _seed_version_table(sqlite_url, BEFORE_HEAD)
        _failing_upgrade(monkeypatch)
        with caplog.at_level(logging.CRITICAL, logger="core.startup_factories"):
            _run_init_catching(sqlite_url)
        critical = [r.getMessage() for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert critical, "a refused migration must be logged at CRITICAL"
        text = "\n".join(critical)
        assert "migration x9 raised" in text
        assert BEFORE_HEAD in text
        assert HEAD in text

    def test_no_alembic_installed_is_refused_too(self, production, sqlite_url, monkeypatch) -> None:
        """Without alembic there is no schema source in production but create_all()."""
        for mod in [m for m in list(sys.modules) if m == "alembic" or m.startswith("alembic.")]:
            monkeypatch.setitem(sys.modules, mod, None)
        monkeypatch.setitem(sys.modules, "alembic", None)
        escaped = _run_init_catching(sqlite_url)
        assert isinstance(escaped, SystemExit)
        assert _tables(sqlite_url) == set()


# ── (b) development and test: create_all() is still the schema source ─────────


@pytest.mark.parametrize("env", ["development", "test"])
class TestDevelopmentAndTestStillStart:
    def test_a_failed_upgrade_falls_back_to_create_all_without_stamping(
        self, env, sqlite_url, repo_cwd, monkeypatch, caplog
    ) -> None:
        monkeypatch.setenv("APP_ENV", env)
        _seed_version_table(sqlite_url, BEFORE_HEAD)
        _failing_upgrade(monkeypatch)
        with caplog.at_level(logging.ERROR, logger="core.startup_factories"):
            state, engine = _run_init(sqlite_url)
        assert engine is not None
        assert state.db_engine is engine
        # Never stamped: the next boot tries the upgrade again.
        assert _versions(sqlite_url) == [BEFORE_HEAD]
        # create_all() built the tables, so a developer can still work.
        assert {"users", "trades", "outbox_events"} <= _tables(sqlite_url)
        assert state.schema_state.verified is False
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_a_fresh_database_migrates_to_head_and_is_verified(self, env, sqlite_url, repo_cwd, monkeypatch) -> None:
        monkeypatch.setenv("APP_ENV", env)
        state, engine = _run_init(sqlite_url)
        assert engine is not None
        assert _versions(sqlite_url) == [HEAD]
        assert state.schema_state.verified is True
        assert state.schema_state.current == HEAD


# ── readiness: an unverified schema is not ready ──────────────────────────────


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, _stmt):
        return None


class _Engine:
    def connect(self):
        return _Conn()


class _KillSwitch:
    def is_active(self) -> bool:
        return False


def _ready(**state):
    from fastapi import FastAPI

    from core.health import register_health_routes

    app = FastAPI()
    base = dict(config=None, db_engine=_Engine(), cache=None, initialized=True)
    base.update(state)
    register_health_routes(app, SimpleNamespace(**base), _KillSwitch())
    route = next(r for r in app.routes if getattr(r, "path", None) == "/ready")
    return asyncio.run(route.endpoint())


class TestReadinessReflectsTheSchema:
    def test_an_unverified_schema_is_not_ready(self) -> None:
        response = _ready(schema_state=SimpleNamespace(verified=False))
        assert response.status_code == 503
        assert b"schema_unverified" in response.body

    def test_a_database_with_no_recorded_schema_state_is_not_ready(self) -> None:
        """Absent is not verified: a pod whose startup never checked is not ready."""
        response = _ready()
        assert response.status_code == 503
        assert b"schema_unverified" in response.body

    def test_a_verified_schema_is_ready(self, monkeypatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
        assert _ready(schema_state=SimpleNamespace(verified=True)) == {"ready": True}

    def test_health_reports_the_schema_component(self) -> None:
        from core.health import _probe_components

        state = SimpleNamespace(
            config=None, db_engine=_Engine(), cache=None, schema_state=SimpleNamespace(verified=False)
        )
        assert _probe_components(state, _KillSwitch())["schema"] == "unverified"
        state.schema_state = SimpleNamespace(verified=True)
        assert _probe_components(state, _KillSwitch())["schema"] == "healthy"


# ── (c) PostgreSQL: head by content, not by the version table ─────────────────

_URL_VARS = ("TEST_POSTGRES_URL", "HOPEFX_TEST_POSTGRES_URL", "HOPEFX_TEST_PG_URL", "DATABASE_URL")
_UNPROVEN = (
    "UNPROVEN ON POSTGRESQL — startup's refusal of a stamped-but-unmigrated database was "
    "NOT checked against a real server. Set TEST_POSTGRES_URL=postgresql://user@host:port/db "
    "(HOPEFX_REQUIRE_POSTGRES=1 makes this a failure). Reason: "
)


def _admin_url():
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
    warnings.warn(message, stacklevel=2)
    pytest.skip(message)


@pytest.fixture(scope="module")
def pg_admin() -> Iterator[sa.Engine]:
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


@pytest.fixture()
def pg_url(pg_admin, monkeypatch, tmp_path) -> Iterator[str]:
    name = f"hopefx_refuse_{uuid.uuid4().hex[:10]}"
    with pg_admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = pg_admin.url.set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    # d9e0f1a2b3c4 seeds its sequences from the counter file; keep it out of the repo's data/.
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(tmp_path / "counters.json"))
    yield url
    with pg_admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


class TestPostgresHeadIsCheckedByContent:
    def test_version_says_head_but_the_sequences_are_missing_is_refused(self, production, pg_url, caplog) -> None:
        """The exact shape the old stamp-and-create_all fallback left behind."""
        _seed_version_table(pg_url, HEAD)
        with caplog.at_level(logging.CRITICAL, logger="core.startup_factories"):
            escaped = _run_init_catching(pg_url)
        assert isinstance(escaped, SystemExit)
        text = str(escaped) + "\n".join(r.getMessage() for r in caplog.records)
        assert "crypto_hd_index_btc" in text
        assert "§6a" in text
        assert _versions(pg_url) == [HEAD]
        assert _tables(pg_url) == {"alembic_version"}

    def test_a_real_failed_upgrade_is_refused_and_nothing_is_stamped(self, production, pg_url) -> None:
        """The 2026-09-25 reproduction: a view where a migration creates a table."""
        engine = sa.create_engine(pg_url)
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE VIEW outbox_events AS SELECT 1 AS id"))
        engine.dispose()
        escaped = _run_init_catching(pg_url)
        assert isinstance(escaped, SystemExit)
        # env.py runs the upgrade in one transaction, so it rolled back entirely;
        # the old code then stamped head and create_all() built 50 tables.
        assert _versions(pg_url) is None
        assert _tables(pg_url) == set()

    def test_a_properly_migrated_database_starts_and_is_verified(self, production, pg_url) -> None:
        """The check must not refuse the database it exists to protect."""
        state, engine = _run_init(pg_url)
        assert engine is not None
        assert _versions(pg_url) == [HEAD]
        assert state.schema_state.verified is True
        engine.dispose()
        # And the second boot, which skips the upgrade, still verifies by content.
        state, engine = _run_init(pg_url)
        assert state.schema_state.verified is True
        engine.dispose()


# ── the content check names the objects the head migration really creates ─────


def test_the_checked_sequences_are_the_ones_the_migration_creates_and_issuing_uses() -> None:
    """Three copies of one list: the migration's, address issuing's, the check's."""
    import importlib.util

    from database.schema_state import HD_INDEX_REVISION, HD_INDEX_SEQUENCES
    from payments.crypto.address_generator import _SEQUENCE

    path = REPO / "alembic" / "versions" / "d9e0f1a2b3c4_crypto_hd_index_sequences.py"
    spec = importlib.util.spec_from_file_location("_hd_index_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == HD_INDEX_REVISION
    assert set(HD_INDEX_SEQUENCES) == set(migration.SEQUENCES) == set(_SEQUENCE.values())


def test_the_content_check_does_not_apply_to_sqlite(tmp_path) -> None:
    """SQLite keeps the file counter; there are no sequences to demand."""
    from database.schema_state import missing_head_objects

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'x.db'}")
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    with engine.connect() as conn:
        assert missing_head_objects(conn, script, HEAD) == []
    engine.dispose()


# ── the same rule on the other create_all() paths ─────────────────────────────


def _load_script(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_script_{name}", REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDatabaseInitFollowsTheSameRule:
    """``database_init.initialize_database`` ran create_all() and then treated a
    failed upgrade as "non-fatal in dev" — in every environment."""

    def test_production_refuses_a_failed_upgrade_and_builds_nothing(self, production, sqlite_url, monkeypatch) -> None:
        from database_init import initialize_database

        _seed_version_table(sqlite_url, BEFORE_HEAD)
        _failing_upgrade(monkeypatch)
        with pytest.raises(RuntimeError, match="migration x9 raised"):
            initialize_database(sqlite_url)
        assert _versions(sqlite_url) == [BEFORE_HEAD]
        assert _tables(sqlite_url) == {"alembic_version"}

    def test_development_still_builds_with_create_all(self, sqlite_url, repo_cwd, monkeypatch) -> None:
        from database_init import initialize_database

        monkeypatch.setenv("APP_ENV", "development")
        _seed_version_table(sqlite_url, BEFORE_HEAD)
        _failing_upgrade(monkeypatch)
        initialize_database(sqlite_url)
        assert {"users", "trades"} <= _tables(sqlite_url)
        assert _versions(sqlite_url) == [BEFORE_HEAD]


class TestAdminToolsDoNotBuildAProductionSchema:
    """create_superadmin / create_admin ran create_all() on whatever DATABASE_URL
    named. On an empty production database that made create_all() the schema
    source, and a later upgrade over it could reach head with create_all() types.

    ~~Both scripts ``setdefault("APP_ENV", "development")`` at import, so they
    treat an UNSET APP_ENV as development — unlike ``current_env()``.~~ **Fixed**:
    neither script touches ``APP_ENV`` any more, so an unset value falls through
    to ``current_env()``'s own fail-safe default of production, exactly like
    every other codepath here. ``test_an_unset_app_env_builds_no_tables_*``
    below pins that directly; the other tests in this class always set
    ``APP_ENV`` explicitly and would have passed under the old, broken default
    too, which is why the gap needed a test that leaves it unset.
    """

    def test_create_superadmin_builds_no_tables_in_production(self, sqlite_url, monkeypatch) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        module = _load_script("create_superadmin")
        with pytest.raises(sa.exc.OperationalError):
            module._create_or_update("ops@example.com", "ops", "Aa1!aaaaaaaaaaaa", reset=False)
        assert _tables(sqlite_url) == set()

    def test_create_admin_builds_no_tables_in_production(self, sqlite_url, monkeypatch) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        module = _load_script("create_admin")
        with pytest.raises(sa.exc.OperationalError):
            module.create_or_update_admin("ops@example.com", "ops", "Aa1!aaaaaaaaaaaa", reset=False)
        assert _tables(sqlite_url) == set()

    def test_create_superadmin_still_builds_tables_in_development(self, sqlite_url, monkeypatch) -> None:
        monkeypatch.setenv("APP_ENV", "development")
        module = _load_script("create_superadmin")
        module._create_or_update("ops@example.com", "ops", "Aa1!aaaaaaaaaaaa", reset=False)
        assert "users" in _tables(sqlite_url)

    def test_create_superadmin_builds_no_tables_with_app_env_unset(self, production, sqlite_url) -> None:
        """The gap the old default hid: nobody exported APP_ENV at all."""
        module = _load_script("create_superadmin")
        with pytest.raises(sa.exc.OperationalError):
            module._create_or_update("ops@example.com", "ops", "Aa1!aaaaaaaaaaaa", reset=False)
        assert _tables(sqlite_url) == set()

    def test_create_admin_builds_no_tables_with_app_env_unset(self, production, sqlite_url) -> None:
        module = _load_script("create_admin")
        with pytest.raises(sa.exc.OperationalError):
            module.create_or_update_admin("ops@example.com", "ops", "Aa1!aaaaaaaaaaaa", reset=False)
        assert _tables(sqlite_url) == set()


def test_the_local_create_all_helper_only_builds_in_dev_and_test(tmp_path, monkeypatch) -> None:
    from database.models import Base
    from database.schema_state import create_all_for_local_use

    for env, expected in (("production", False), ("staging", False), ("development", True), ("test", True)):
        monkeypatch.setenv("APP_ENV", env)
        url = f"sqlite:///{tmp_path / (env + '.db')}"
        engine = sa.create_engine(url)
        assert create_all_for_local_use(Base.metadata, engine, caller="t") is expected
        engine.dispose()
        assert ("users" in _tables(url)) is expected
    monkeypatch.delenv("APP_ENV")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'unset.db'}")
    assert create_all_for_local_use(Base.metadata, engine, caller="t") is False
    engine.dispose()


class _FakePgConn:
    """Enough of a PostgreSQL connection to drive the content check without a server."""

    def __init__(self, present: set[str]) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.present = present
        self.asked: list[str] = []

    def execute(self, _stmt, params):
        self.asked.append(params["n"])
        kind = "S" if params["n"] in self.present else None
        return SimpleNamespace(scalar=lambda: kind)


def test_the_content_check_names_each_missing_sequence() -> None:
    from database.schema_state import missing_head_objects

    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    conn = _FakePgConn({"crypto_hd_index_btc"})
    assert missing_head_objects(conn, script, HEAD) == ["crypto_hd_index_eth", "crypto_hd_index_trc20"]


def test_the_content_check_asks_nothing_of_a_database_before_the_sequence_migration() -> None:
    """At c8d9e0f1a2b3 the sequences are not due yet; demanding them would refuse a valid database."""
    from database.schema_state import missing_head_objects

    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    conn = _FakePgConn(set())
    assert missing_head_objects(conn, script, BEFORE_HEAD) == []
    assert missing_head_objects(conn, script, None) == []
    assert conn.asked == []


def test_the_refusal_reads_as_its_message_and_exits_non_zero() -> None:
    from database.schema_state import SchemaRefused

    refusal = SchemaRefused("REFUSING TO START: because")
    assert str(refusal) == "REFUSING TO START: because"
    assert refusal.code == 1
    assert not isinstance(refusal, Exception)
