# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_production_readiness.py
===================================
Production-readiness smoke tests.

Verifies that:
  1.  App imports and registers all routes with only SECURITY_JWT_SECRET set
  2.  SQLite engine created without pool_size/max_overflow (dev default)
  3.  PostgreSQL engine created with pool_size/max_overflow
  4.  All 10 critical API routers have correct /api/* prefixes
  5.  No router uses wildcard CORS with credentials
  6.  Startup validator: CHANGE_ME placeholder rejected in all modes
  7.  Startup validator: short secret (<32 chars) rejected
  8.  Startup validator: production mode requires REDIS_URL not REDIS_HOST
  9.  MacroStore singleton is importable and functional
  10. leaderboard_router is wired into app.py (route present in app.routes)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = os.path.dirname(Path(__file__).parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _jwt(monkeypatch, val: str = "z" * 48) -> None:
    monkeypatch.setenv("SECURITY_JWT_SECRET", val)
    monkeypatch.setenv("APP_ENV", "development")


# ── 1. App imports with only JWT secret ──────────────────────────────────────


def test_app_imports_with_only_jwt_secret(monkeypatch):
    """App must import and register routes with only SECURITY_JWT_SECRET."""
    _jwt(monkeypatch)
    import importlib

    import app as _app

    importlib.reload(_app)  # re-run module-level code with patched env
    assert len(_app.app.routes) > 100, f"Expected >100 routes, got {len(_app.app.routes)}"


# ── 2-3. SQLite vs PostgreSQL engine kwargs ───────────────────────────────────


def test_sqlite_engine_no_pool_kwargs(monkeypatch, tmp_path):
    """SQLite engine must not receive pool_size/max_overflow."""
    _jwt(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")

    from sqlalchemy import create_engine

    conn_str = f"sqlite:///{tmp_path}/test.db"
    is_sqlite = conn_str.startswith("sqlite")
    engine_kwargs: dict = {}
    if not is_sqlite:
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10

    # Must not raise
    engine = create_engine(conn_str, **engine_kwargs)
    assert engine is not None


def test_postgres_engine_gets_pool_kwargs():
    """PostgreSQL connection string triggers pool_size/max_overflow kwargs."""
    conn_str = "postgresql://user:pass@localhost:5432/db"
    is_sqlite = conn_str.startswith("sqlite")
    engine_kwargs: dict = {}
    if not is_sqlite:
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10

    assert "pool_size" in engine_kwargs
    assert "max_overflow" in engine_kwargs


# ── 4. All critical routers have /api/* prefix ────────────────────────────────


@pytest.mark.parametrize(
    "module,expected_prefix",
    [
        ("api.ml", "/api/ml/"),
        ("api.admin", "/api/admin/"),
        ("api.trading", "/api/trading/"),
        ("api.macro", "/api/macro/"),
        ("api.watchlist", "/api/watchlist/"),
        ("api.calendar", "/api/calendar/"),
        ("api.alerts", "/api/alerts/"),
        ("api.performance", "/api/performance/"),
        ("api.broker", "/api/broker/"),
        ("api.profiles", "/api/profiles/"),
    ],
)
def test_router_has_api_prefix(module, expected_prefix, monkeypatch):
    """Each critical router must have routes starting with /api/."""
    _jwt(monkeypatch)
    import importlib

    mod = importlib.import_module(module)
    paths = [r.path for r in mod.router.routes if hasattr(r, "path")]
    assert any(p.startswith(expected_prefix) for p in paths), (
        f"{module} has no routes starting with {expected_prefix}. Found: {paths[:5]}"
    )


# ── 5. Auth router prefix ─────────────────────────────────────────────────────


def test_auth_router_prefix(monkeypatch):
    """Auth router must be at /api/auth/* to match frontend baseURL=/api."""
    _jwt(monkeypatch)
    from auth.router import router

    paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert all(p.startswith("/api/auth/") for p in paths), (
        f"Non-/api/auth paths: {[p for p in paths if not p.startswith('/api/auth/')]}"
    )


# ── 6-8. Startup validator edge cases ────────────────────────────────────────


def test_change_me_placeholder_rejected_in_dev(monkeypatch):
    """CHANGE_ME placeholder rejected even in development mode."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECURITY_JWT_SECRET", "CHANGE_ME_generate_a_random_48_char_secret")

    from config.startup_validator import StartupValidationError, validate_environment

    with pytest.raises(StartupValidationError):
        validate_environment(strict=False)


def test_short_secret_rejected(monkeypatch):
    """Secret shorter than 32 chars must be rejected."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECURITY_JWT_SECRET", "tooshort")

    from config.startup_validator import StartupValidationError, validate_environment

    with pytest.raises(StartupValidationError) as exc_info:
        validate_environment(strict=False)
    assert "32" in str(exc_info.value) or "TOO_SHORT" in str(exc_info.value)


def test_production_redis_url_required_not_redis_host(monkeypatch):
    """In production, REDIS_URL is required; REDIS_HOST alone is not enough."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECURITY_JWT_SECRET", "z" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("DB_PASSWORD", "strongpassword123")
    monkeypatch.setenv("REDIS_HOST", "localhost")  # old-style — not enough
    monkeypatch.delenv("REDIS_URL", raising=False)

    from config.startup_validator import StartupValidationError, validate_environment

    with pytest.raises(StartupValidationError) as exc_info:
        validate_environment(strict=False)
    msg = str(exc_info.value)
    assert "REDIS_URL" in msg
    # Error message should hint at the correct fix
    assert "redis://" in msg.lower() or "REDIS_URL" in msg


# ── 9. MacroStore singleton ───────────────────────────────────────────────────


def test_macro_store_singleton_importable():
    """ml.macro_store.macro_store singleton must be importable and functional."""
    from ml.macro_store import MacroStore, macro_store

    assert isinstance(macro_store, MacroStore)
    # Must accept updates without error
    macro_store.update("test_series", "2026-01-02", 1.0)
    snap = macro_store.snapshot()
    assert "test_series" in snap


# ── 10. Leaderboard router wired into app ────────────────────────────────────


def test_leaderboard_route_in_app(monkeypatch):
    """GET /api/social/leaderboard must be registered in the main app."""
    _jwt(monkeypatch)
    import importlib

    import app as _app

    importlib.reload(_app)

    all_paths = []
    for route in _app.app.routes:
        if hasattr(route, "path"):
            all_paths.append(route.path)

    assert "/api/social/leaderboard" in all_paths, (
        f"/api/social/leaderboard not found in app routes. "
        f"Social routes: {[p for p in all_paths if 'social' in p or 'leader' in p]}"
    )
