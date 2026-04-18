# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for cache/redis_client.py TLS enforcement.

Covers:
- _enforce_tls() with IS_FORCE_TLS, REDIS_FORCE_TLS, APP_ENV=production
- IS_FORCE_TLS takes precedence over REDIS_FORCE_TLS
- Plaintext warning in non-production
- RuntimeError in production without TLS
- Auto-upgrade to rediss:// when force_tls is set
- reset_redis_client() clears singleton state
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enforce_tls(url: str, *, app_env: str = "development", is_force: str = "", redis_force: str = "false") -> str:
    """Call _enforce_tls with controlled env vars."""
    env = {
        "APP_ENV": app_env,
        "IS_FORCE_TLS": is_force,
        "REDIS_FORCE_TLS": redis_force,
    }
    with patch.dict(os.environ, env, clear=False):
        # Re-import to pick up patched env
        import importlib
        import cache.redis_client as rc
        importlib.reload(rc)
        return rc._enforce_tls(url)


# ---------------------------------------------------------------------------
# _enforce_tls — basic cases
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEnforceTLS:
    def test_already_tls_passthrough(self):
        """rediss:// URLs are returned unchanged."""
        from cache.redis_client import _enforce_tls
        url = "rediss://user:pass@redis:6380/0"
        with patch.dict(os.environ, {"APP_ENV": "development", "IS_FORCE_TLS": "", "REDIS_FORCE_TLS": "false"}):
            result = _enforce_tls(url)
        assert result == url

    def test_unix_socket_passthrough(self):
        """Unix socket URLs are returned unchanged."""
        from cache.redis_client import _enforce_tls
        url = "unix:///var/run/redis/redis.sock"
        with patch.dict(os.environ, {"APP_ENV": "development", "IS_FORCE_TLS": "", "REDIS_FORCE_TLS": "false"}):
            result = _enforce_tls(url)
        assert result == url

    def test_plaintext_dev_logs_warning(self, caplog):
        """Plaintext redis:// in development logs a WARNING (no exception)."""
        import logging
        from cache.redis_client import _enforce_tls
        url = "redis://localhost:6379/0"
        with patch.dict(os.environ, {"APP_ENV": "development", "IS_FORCE_TLS": "", "REDIS_FORCE_TLS": "false"}):
            with caplog.at_level(logging.WARNING, logger="cache.redis_client"):
                result = _enforce_tls(url)
        assert result == url  # URL unchanged
        assert any("plaintext" in r.message.lower() for r in caplog.records)

    def test_redis_force_tls_upgrades_url(self):
        """REDIS_FORCE_TLS=true upgrades redis:// → rediss://."""
        from cache.redis_client import _enforce_tls
        url = "redis://:secret@redis:6379/0"
        with patch.dict(os.environ, {"APP_ENV": "development", "IS_FORCE_TLS": "", "REDIS_FORCE_TLS": "true"}):
            result = _enforce_tls(url)
        assert result == "rediss://:secret@redis:6379/0"

    def test_is_force_tls_upgrades_url(self):
        """IS_FORCE_TLS=true upgrades redis:// → rediss://."""
        from cache.redis_client import _enforce_tls
        url = "redis://:secret@redis:6379/0"
        with patch.dict(os.environ, {"APP_ENV": "development", "IS_FORCE_TLS": "true", "REDIS_FORCE_TLS": "false"}):
            result = _enforce_tls(url)
        assert result == "rediss://:secret@redis:6379/0"

    def test_is_force_tls_takes_precedence(self):
        """IS_FORCE_TLS=true overrides REDIS_FORCE_TLS=false."""
        from cache.redis_client import _enforce_tls
        url = "redis://localhost:6379/0"
        with patch.dict(os.environ, {"APP_ENV": "development", "IS_FORCE_TLS": "true", "REDIS_FORCE_TLS": "false"}):
            result = _enforce_tls(url)
        assert result.startswith("rediss://")

    def test_production_plaintext_raises(self):
        """Plaintext redis:// in production raises RuntimeError."""
        from cache.redis_client import _enforce_tls
        url = "redis://localhost:6379/0"
        with patch.dict(os.environ, {"APP_ENV": "production", "IS_FORCE_TLS": "", "REDIS_FORCE_TLS": "false"}):
            with pytest.raises(RuntimeError, match="TLS required"):
                _enforce_tls(url)

    def test_production_force_tls_upgrades_not_raises(self):
        """In production, IS_FORCE_TLS=true upgrades URL instead of raising."""
        from cache.redis_client import _enforce_tls
        url = "redis://:secret@redis:6379/0"
        with patch.dict(os.environ, {"APP_ENV": "production", "IS_FORCE_TLS": "true", "REDIS_FORCE_TLS": "false"}):
            result = _enforce_tls(url)
        assert result == "rediss://:secret@redis:6379/0"

    def test_upgrade_preserves_credentials_and_path(self):
        """URL upgrade preserves user, password, host, port, and db."""
        from cache.redis_client import _enforce_tls
        url = "redis://user:p%40ss@myredis.internal:6380/3"
        with patch.dict(os.environ, {"APP_ENV": "development", "IS_FORCE_TLS": "true", "REDIS_FORCE_TLS": "false"}):
            result = _enforce_tls(url)
        assert result == "rediss://user:p%40ss@myredis.internal:6380/3"


# ---------------------------------------------------------------------------
# reset_redis_client
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestResetRedisClient:
    def test_reset_clears_singleton(self):
        """reset_redis_client() resets all module-level singletons."""
        from cache.redis_client import reset_redis_client, get_connection_mode
        reset_redis_client()
        assert get_connection_mode() == "none"

    def test_reset_idempotent(self):
        """Calling reset twice does not raise."""
        from cache.redis_client import reset_redis_client
        reset_redis_client()
        reset_redis_client()  # should not raise


# ---------------------------------------------------------------------------
# get_redis — no config → returns None gracefully
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
class TestGetRedisNoConfig:
    async def test_returns_none_when_unconfigured(self):
        """get_redis() returns None when no Redis env vars are set."""
        from cache.redis_client import reset_redis_client, get_redis
        reset_redis_client()
        env = {
            "REDIS_CLUSTER_HOSTS": "",
            "REDIS_SENTINEL_HOSTS": "",
            "REDIS_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            result = await get_redis()
        assert result is None

    async def test_no_config_warning_logged_once(self, caplog):
        """'no connection configured' warning is logged exactly once."""
        import logging
        from cache.redis_client import reset_redis_client, get_redis
        reset_redis_client()
        env = {
            "REDIS_CLUSTER_HOSTS": "",
            "REDIS_SENTINEL_HOSTS": "",
            "REDIS_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with caplog.at_level(logging.WARNING, logger="cache.redis_client"):
                await get_redis()
                await get_redis()  # second call — should NOT log again
        warning_msgs = [r for r in caplog.records if "no connection configured" in r.message.lower()]
        assert len(warning_msgs) == 1, f"Expected 1 warning, got {len(warning_msgs)}"
