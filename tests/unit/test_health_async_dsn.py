# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_health_async_dsn.py
===================================
`/api/health/ready` reported the database down while the database was fine.

`api/health.py` read `DATABASE_URL` straight from the environment and handed it
to `create_async_engine`. But `DATABASE_URL` is the *sync* DSN —
docker-compose.yml sets `postgresql://…` — and SQLAlchemy's asyncio extension
needs an async driver, so every call failed with:

    health.py: could not create DB engine: The asyncio extension requires an
    async driver to be used.

The failure was invisible for as long as readiness was already 503 for larger
reasons. Once the database wiring was fixed (#249) — alembic running under
PostgresqlImpl, auth initialising, OHLCV flowing for every symbol — this became
the remaining thing keeping the readiness probe red, and it was reporting a
component down that was actually healthy. A health check that lies in this
direction is worse than none: it makes a working deploy look broken, and it
trains whoever is on call to ignore the probe.

`database/async_connection._resolve_async_db_url` already performed exactly the
translation needed. `health.py` now reuses it rather than reimplementing it, so
the two cannot drift and `ASYNC_DATABASE_URL` is honoured in both places.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("env", "expected_prefix"),
    [
        # What docker-compose.yml actually sets — the case that was broken.
        ("postgresql://hopefx:pw@postgres:5432/hopefx", "postgresql+asyncpg://"),  # pragma: allowlist secret
        # Already async: must pass through untouched, not double-prefixed.
        ("postgresql+asyncpg://hopefx:pw@postgres:5432/hopefx", "postgresql+asyncpg://"),  # pragma: allowlist secret
        # SQLite, for local development.
        ("sqlite:///hopefx.db", "sqlite+aiosqlite:///"),
        ("sqlite+aiosqlite:///hopefx.db", "sqlite+aiosqlite:///"),
    ],
)
async def test_the_health_probe_resolves_an_async_dsn(monkeypatch, env, expected_prefix):
    from api import health

    monkeypatch.setenv("DATABASE_URL", env)
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)
    # Reset the module-level cache so each case resolves fresh.
    monkeypatch.setattr(health, "_db_engine", None, raising=False)
    monkeypatch.setattr(health, "_db_engine_url", None, raising=False)
    monkeypatch.setattr(health, "_db_engine_lock", None, raising=False)

    _engine, url = await health._get_db_engine()

    assert url is not None
    assert url.startswith(expected_prefix), f"{env!r} resolved to {url!r}"
    # The precise failure this fixes: a bare sync driver reaching the async engine.
    assert not url.startswith("postgresql://"), "sync DSN would fail create_async_engine"


async def test_an_explicit_async_url_takes_precedence(monkeypatch):
    """`ASYNC_DATABASE_URL` is the documented override and was ignored here."""
    from api import health

    monkeypatch.setenv("DATABASE_URL", "postgresql://sync:pw@a:5432/db")  # pragma: allowlist secret
    monkeypatch.setenv("ASYNC_DATABASE_URL", "postgresql+asyncpg://async:pw@b:5432/db")  # pragma: allowlist secret
    monkeypatch.setattr(health, "_db_engine", None, raising=False)
    monkeypatch.setattr(health, "_db_engine_url", None, raising=False)
    monkeypatch.setattr(health, "_db_engine_lock", None, raising=False)

    _engine, url = await health._get_db_engine()

    assert url is not None
    assert "async:pw@b" in url, f"ASYNC_DATABASE_URL was not honoured: {url!r}"


async def test_no_database_configured_yields_no_engine(monkeypatch):
    """Neither variable set — return cleanly rather than building a default."""
    from api import health

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)
    monkeypatch.setattr(health, "_db_engine", None, raising=False)
    monkeypatch.setattr(health, "_db_engine_url", None, raising=False)
    monkeypatch.setattr(health, "_db_engine_lock", None, raising=False)

    engine, url = await health._get_db_engine()

    assert engine is None
    assert url is None


def test_health_reuses_the_shared_resolver_rather_than_its_own_copy():
    """Two copies of this translation would drift; that is how the bug started."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "api" / "health.py").read_text(encoding="utf-8")

    assert "from database.async_connection import _resolve_async_db_url" in src, (
        "health.py is not using the shared resolver"
    )
    assert "db_url = _resolve_async_db_url()" in src, "the resolver is imported but never called"
