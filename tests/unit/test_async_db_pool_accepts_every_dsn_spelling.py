"""
tests/unit/test_async_db_pool_accepts_every_dsn_spelling.py
===========================================================
The deployed app logs, on every boot::

    Async DB pool init failed (non-fatal): ...

``_resolve_async_db_url`` rewrote exactly two shapes — ``sqlite://`` and bare
``postgresql://`` — and passed everything else to ``create_async_engine``
unchanged. Every other spelling of a PostgreSQL DSN that a real deployment
produces then failed inside SQLAlchemy:

* ``postgresql+psycopg2://`` — what a sync SQLAlchemy setup writes;
  ``InvalidRequestError: The asyncio extension requires an async driver to be used``
* ``postgresql+psycopg://``  — psycopg 3, same failure
* ``postgres://``            — legacy scheme, dropped in SQLAlchemy 2.x;
  ``NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres``

The warning that resulted named none of this. It printed the exception's own
text, asserted "non-fatal" without saying what stops working, and omitted the
DSN it had actually resolved — so a reader could not tell whether the DSN, the
driver or the database was at fault, and those need three different fixes.

These tests exercise the real resolver against every spelling.
"""

from __future__ import annotations

import importlib

import pytest


def _resolve(monkeypatch, database_url=None, async_url=None) -> str:
    """Resolve a DSN with the environment set exactly as a deployment would."""
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if database_url is not None:
        monkeypatch.setenv("DATABASE_URL", database_url)
    if async_url is not None:
        monkeypatch.setenv("ASYNC_DATABASE_URL", async_url)

    import database.async_connection as mod

    importlib.reload(mod)
    return mod._resolve_async_db_url()


# ── Every PostgreSQL spelling ends up on an async driver ──────────────────────


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),  # pragma: allowlist secret
        ("postgresql+psycopg2://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),  # pragma: allowlist secret
        ("postgresql+psycopg://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),  # pragma: allowlist secret
        ("postgresql+pg8000://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),  # pragma: allowlist secret
        ("postgres://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),  # pragma: allowlist secret
        # Already async — left alone.
        ("postgresql+asyncpg://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),  # pragma: allowlist secret
    ],
)
def test_postgres_dsn_is_rewritten_to_asyncpg(monkeypatch, given, expected):
    assert _resolve(monkeypatch, database_url=given) == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("sqlite:///hopefx.db", "sqlite+aiosqlite:///hopefx.db"),
        ("sqlite+aiosqlite:///hopefx.db", "sqlite+aiosqlite:///hopefx.db"),
    ],
)
def test_sqlite_dsn_is_rewritten_to_aiosqlite(monkeypatch, given, expected):
    assert _resolve(monkeypatch, database_url=given) == expected


def test_no_resolved_dsn_ever_names_a_sync_driver(monkeypatch):
    """The property that matters, independent of the table above."""
    for given in [
        "postgresql://u:p@h/d",  # pragma: allowlist secret
        "postgresql+psycopg2://u:p@h/d",  # pragma: allowlist secret
        "postgresql+psycopg://u:p@h/d",  # pragma: allowlist secret
        "postgresql+pg8000://u:p@h/d",  # pragma: allowlist secret
        "postgresql+psycopg2cffi://u:p@h/d",  # pragma: allowlist secret
        "postgres://u:p@h/d",  # pragma: allowlist secret
        "sqlite:///x.db",
    ]:
        resolved = _resolve(monkeypatch, database_url=given)
        for sync_driver in ("psycopg2", "psycopg://", "pg8000", "psycopg2cffi"):
            assert sync_driver not in resolved, f"{given} resolved to {resolved}"
        assert resolved.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite:///"))


# ── The explicit override still wins ──────────────────────────────────────────


def test_async_database_url_takes_priority(monkeypatch):
    resolved = _resolve(
        monkeypatch,
        database_url="postgresql+psycopg2://ignored:me@h/d",  # pragma: allowlist secret
        async_url="postgresql+asyncpg://real:dsn@h/d",  # pragma: allowlist secret
    )
    assert resolved == "postgresql+asyncpg://real:dsn@h/d"  # pragma: allowlist secret


def test_an_unset_environment_falls_back_to_a_usable_async_dsn(monkeypatch):
    resolved = _resolve(monkeypatch)
    assert resolved.startswith("postgresql+asyncpg://")


# ── The failure message says what actually broke ──────────────────────────────


def test_the_failure_warning_is_diagnostic():
    """It used to print the exception text and the word "non-fatal", nothing else."""
    from tests.support.source_text import python_code_only

    code = python_code_only("app.py")
    start = code.index("Async DB pool init failed")
    message = code[start : start + 700]

    # Names the resolved DSN, so DSN-vs-driver-vs-database is distinguishable.
    assert "resolved DSN" in message
    # Redacted — the DSN carries the Postgres password.
    assert "_redact(" in message
    # Says what stops working rather than asserting "non-fatal" and stopping.
    assert "health/ready" in message
    assert "get_async_db()" in message


def test_the_dsn_in_the_failure_warning_is_redacted():
    """The message includes the DSN; the DSN includes the database password."""
    from utils.redaction import redact_url

    dsn = "postgresql+asyncpg://hopefx:hunter2@postgres:5432/hopefx"  # pragma: allowlist secret
    assert "hunter2" not in redact_url(dsn)


def test_the_pools_own_redactor_delegates_to_the_shared_one():
    """One redaction implementation, not two that can drift."""
    from database.async_connection import AsyncConnectionPool
    from utils.redaction import redact_url

    for url in [
        "postgresql+asyncpg://u:pw@h:5432/d",  # pragma: allowlist secret
        "redis://:pw@r:6379/0",  # pragma: allowlist secret
        "postgresql://h:5432/d",
    ]:
        assert AsyncConnectionPool._redact_url(url) == redact_url(url)
