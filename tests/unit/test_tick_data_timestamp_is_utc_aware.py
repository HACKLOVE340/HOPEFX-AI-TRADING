# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""`tick_data.timestamp` round-trips a known UTC instant on a migrated schema.

Companion to `test_migrated_schema_matches_models.py`'s column-type check:
that test proves the *declared* type matches; this proves the *instant*
survives — write a known UTC datetime through the repository, read it back
through a fresh session, and the instant must be unchanged.

Runs on SQLite always (the fast, always-available leg) and, when a real
PostgreSQL 16 server is configured, against it too — including the case the
schema check cannot see at all: a NAIVE row written before migration
`f2a3b4c5d6e7` upgrades in place and keeps its instant, not just its label.

Server: `TEST_POSTGRES_URL` (or `HOPEFX_TEST_POSTGRES_URL`,
`HOPEFX_TEST_PG_URL`, or a `postgresql` `DATABASE_URL`). With no server the
PostgreSQL cases SKIP loudly; set `HOPEFX_REQUIRE_POSTGRES=1` to make that a
failure instead, exactly as the sibling migration-chain test does.
"""

from __future__ import annotations

import os
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.unit]

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[2]
KNOWN_INSTANT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

_URL_VARS = ("TEST_POSTGRES_URL", "HOPEFX_TEST_POSTGRES_URL", "HOPEFX_TEST_PG_URL", "DATABASE_URL")
_UNPROVEN = (
    "UNPROVEN ON POSTGRESQL — set TEST_POSTGRES_URL=postgresql://user@host:port/db "
    "(HOPEFX_REQUIRE_POSTGRES=1 makes this a failure). Reason: "
)


def _admin_url() -> str | None:
    for var in _URL_VARS:
        raw = os.getenv(var, "")
        if not raw:
            continue
        scheme = raw.split("://", 1)[0].split("+", 1)[0]
        if scheme not in ("postgresql", "postgres"):
            continue
        return sa.engine.make_url(raw.replace("postgres://", "postgresql://", 1)).set(drivername="postgresql")
    return None


def _require_postgres(reason: str) -> None:
    message = _UNPROVEN + reason
    if os.getenv("HOPEFX_REQUIRE_POSTGRES", "").strip().lower() in ("1", "true", "yes"):
        pytest.fail(message, pytrace=False)
    warnings.warn(message, stacklevel=2)
    pytest.skip(message)


def _alembic_upgrade(url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str = "head") -> None:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(tmp_path / "no-counter.json"))
    command.upgrade(cfg, target)


# ── SQLite: always runs ──────────────────────────────────────────────────────


def test_sqlite_round_trip_preserves_the_instant(tmp_path, monkeypatch):
    """Write a known UTC instant through the repository, read it back — equal."""
    import asyncio

    db = tmp_path / "schema.db"
    _alembic_upgrade(f"sqlite:///{db}", monkeypatch, tmp_path)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from database.repositories.tick_data_repository import TickDataRepository

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    repo = TickDataRepository()
    ts_ns = int(KNOWN_INSTANT.timestamp() * 1_000_000_000)

    async def _write_and_read():
        async with factory() as session:
            await repo.insert_tick(session, symbol="XAUUSD", bid=2000.0, ask=2000.5, ts_ns=ts_ns)
            await session.commit()
        async with factory() as session:
            tick = await repo.get_latest_tick(session, symbol="XAUUSD")
        return tick

    tick = asyncio.run(_write_and_read())
    asyncio.run(engine.dispose())

    assert tick is not None
    # SQLite has no timezone-aware storage; the value that comes back is naive
    # but must be the same wall-clock instant that was written as UTC.
    assert tick.timestamp.replace(tzinfo=UTC) == KNOWN_INSTANT


# ── PostgreSQL: real server, skips loudly without one ────────────────────────


@pytest.fixture
def pg_database(monkeypatch, tmp_path) -> str:
    admin_url = _admin_url()
    if admin_url is None:
        _require_postgres(f"none of {', '.join(_URL_VARS)} names a postgresql:// server")

    admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin_engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except sa.exc.OperationalError as exc:
        admin_engine.dispose()
        _require_postgres(f"the configured server is not reachable: {exc.orig}")

    name = f"hopefx_ticktz_{uuid.uuid4().hex[:10]}"
    with admin_engine.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = admin_url.set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin_engine.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()


def test_postgres_round_trip_preserves_the_instant(pg_database, monkeypatch, tmp_path):
    """Same proof as the SQLite case, against a real server — the async driver
    that could not even accept the write before this migration."""
    import asyncio

    _alembic_upgrade(pg_database, monkeypatch, tmp_path)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from database.repositories.tick_data_repository import TickDataRepository

    async_url = pg_database.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    repo = TickDataRepository()
    ts_ns = int(KNOWN_INSTANT.timestamp() * 1_000_000_000)

    async def _write_and_read():
        async with factory() as session:
            await repo.insert_tick(session, symbol="XAUUSD", bid=2000.0, ask=2000.5, ts_ns=ts_ns)
            await session.commit()
        async with factory() as session:
            tick = await repo.get_latest_tick(session, symbol="XAUUSD")
        return tick

    tick = asyncio.run(_write_and_read())
    asyncio.run(engine.dispose())

    assert tick is not None
    assert tick.timestamp.tzinfo is not None, "timestamptz must come back timezone-aware"
    assert tick.timestamp == KNOWN_INSTANT


def test_postgres_upgrade_preserves_preexisting_naive_rows(pg_database, monkeypatch, tmp_path):
    """A row written as NAIVE UTC before this migration keeps its instant after
    the column becomes timestamptz.

    Upgrades to the revision just before f2a3b4c5d6e7, inserts a plain naive
    timestamp directly (the shape every row on a pre-fix production database
    is in), upgrades the rest of the way, and reads it back through the ORM.
    """
    _alembic_upgrade(pg_database, monkeypatch, tmp_path, target="d9e0f1a2b3c4")  # pragma: allowlist secret

    sync_engine = sa.create_engine(pg_database)
    naive_instant = datetime(2025, 6, 15, 9, 30, 0)  # no tzinfo — the pre-fix shape
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tick_data (ts_ns, symbol, bid, ask, timestamp, quality) "
                "VALUES (:ts_ns, :symbol, :bid, :ask, :ts, :quality)"
            ),
            {
                "ts_ns": int(naive_instant.replace(tzinfo=UTC).timestamp() * 1_000_000_000),
                "symbol": "XAUUSD",
                "bid": 1999.0,
                "ask": 1999.5,
                "ts": naive_instant,
                "quality": "unknown",
            },
        )
    sync_engine.dispose()

    _alembic_upgrade(pg_database, monkeypatch, tmp_path, target="head")

    verify_engine = sa.create_engine(pg_database)
    with verify_engine.connect() as conn:
        row = conn.execute(sa.text("SELECT timestamp FROM tick_data WHERE symbol = 'XAUUSD'")).fetchone()
    verify_engine.dispose()

    assert row is not None
    stored = row[0]
    assert stored.tzinfo is not None, "the column must be timestamptz after upgrade"
    assert stored == naive_instant.replace(tzinfo=UTC), (
        f"pre-existing naive row changed instant across the upgrade: {stored!r} != "
        f"{naive_instant.replace(tzinfo=UTC)!r}"
    )
