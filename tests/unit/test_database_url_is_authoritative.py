# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_database_url_is_authoritative.py
================================================
One process, one database.

``DATABASE_URL`` is what a deployment sets, and most of the codebase reads it:
``database/connection.py`` resolves its engine from it, docker-compose.yml sets
it on every service, and ``core.startup_factories._ConfigDatabaseDefaults``
returns it verbatim. ``config.config_manager.DatabaseConfig`` did not — it
composed a URL from its own dataclass fields, whose defaults are
``sqlite:///hopefx.db``.

A container therefore ran two databases at once: ``database/connection.py`` on
Postgres, and everything built from ``AppConfig`` — the session factory behind
auth, the outbox relay, the alembic run in ``init_database`` — on a
container-local SQLite file that is wiped on every rebuild.

Nothing in the resulting failures named the database. The CI stack smoke test
showed ``/api/health/ready`` 503 with ``failed_critical: ["orchestrator",
"db_pool"]``, ``POST /api/auth/login`` 503 "Auth service not initialised", and
``OutboxRelay._relay_batch error: no such table: outbox_events`` — three
symptoms of one silent misconfiguration.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


PG_URL = "postgresql://hopefx:pw@postgres:5432/hopefx"  # pragma: allowlist secret


def test_database_url_wins_over_the_dataclass_defaults(monkeypatch):
    """The bug: defaults said SQLite while the deployment said Postgres."""
    from config.config_manager import DatabaseConfig

    monkeypatch.setenv("DATABASE_URL", PG_URL)

    assert DatabaseConfig().get_connection_string() == PG_URL


def test_the_two_config_layers_agree(monkeypatch):
    """`AppConfig` and the `_ConfigNamespace` shim must not disagree.

    Which one a process gets depends on whether `initialize_config()` returns a
    dict or an `AppConfig`. That is an implementation detail; it must not decide
    which database the app writes to.
    """
    from config.config_manager import DatabaseConfig
    from core.startup_factories import _ConfigDatabaseDefaults

    monkeypatch.setenv("DATABASE_URL", PG_URL)

    assert DatabaseConfig().get_connection_string() == _ConfigDatabaseDefaults().get_connection_string()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql+asyncpg://u:pw@h:5432/d",  # pragma: allowlist secret
            "postgresql+psycopg2://u:pw@h:5432/d",  # pragma: allowlist secret
        ),
        ("sqlite+aiosqlite:///hopefx.db", "sqlite:///hopefx.db"),
    ],
)
def test_async_driver_prefixes_are_normalised(monkeypatch, url, expected):
    """Callers hand this to the sync `create_engine`, which has no async driver."""
    from config.config_manager import DatabaseConfig

    monkeypatch.setenv("DATABASE_URL", url)

    assert DatabaseConfig().get_connection_string() == expected


def test_an_unset_or_blank_url_falls_back_to_the_configured_fields(monkeypatch):
    """Local development, and any deployment driving the config file instead."""
    from config.config_manager import DatabaseConfig

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert DatabaseConfig().get_connection_string() == "sqlite:///hopefx.db"

    # Blank is treated as unset — an empty compose variable must not resolve to
    # an empty connection string.
    monkeypatch.setenv("DATABASE_URL", "   ")
    cfg = DatabaseConfig(db_type="postgresql", username="u", password="pw", host="h", database="d")
    assert cfg.get_connection_string().startswith("postgresql://u:pw@h:5432/d")  # pragma: allowlist secret
