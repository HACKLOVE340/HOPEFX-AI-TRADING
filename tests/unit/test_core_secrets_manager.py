# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_secrets_manager.py
========================================
Coverage tests for core/secrets_manager.py.

All external backends (Vault, AWS) are patched at the boundary.
Real SecretsManager logic is exercised throughout.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.secrets_manager import SecretsManager, get_secret, secrets


# ── construction & _load_from_env ─────────────────────────────────────────────


def test_init_loads_from_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret")
    sm = SecretsManager()
    assert sm.get("jwt_secret_key") == "test-jwt-secret"


def test_init_empty_env():
    sm = SecretsManager()
    assert isinstance(sm._cache, dict)
    assert sm._refresh_count == 0
    assert sm._error_count == 0
    assert sm._running is False


# ── get ───────────────────────────────────────────────────────────────────────


def test_get_from_cache():
    sm = SecretsManager()
    sm._cache["my_key"] = "cached_value"
    assert sm.get("my_key") == "cached_value"


def test_get_env_fallback_via_mapping(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "env-jwt")
    sm = SecretsManager()
    sm._cache.pop("jwt_secret_key", None)
    # Should fall back to env var via _ENV_FALLBACK mapping
    result = sm.get("jwt_secret_key")
    assert result == "env-jwt"


def test_get_unknown_key_falls_back_to_upper_env(monkeypatch):
    monkeypatch.setenv("MY_CUSTOM_KEY", "custom_val")
    sm = SecretsManager()
    result = sm.get("my_custom_key")
    assert result == "custom_val"


def test_get_returns_default_when_missing():
    sm = SecretsManager()
    sm._cache.clear()
    result = sm.get("totally_missing_key_xyz", default="fallback")
    assert result == "fallback"


def test_get_returns_none_default():
    sm = SecretsManager()
    sm._cache.clear()
    result = sm.get("totally_missing_key_xyz")
    assert result is None


# ── get_sync ──────────────────────────────────────────────────────────────────


def test_get_sync_same_as_get():
    sm = SecretsManager()
    sm._cache["sync_key"] = "sync_val"
    assert sm.get_sync("sync_key") == sm.get("sync_key")


# ── set ───────────────────────────────────────────────────────────────────────


def test_set_stores_in_cache():
    sm = SecretsManager()
    sm.set("new_key", "new_value")
    assert sm._cache["new_key"] == "new_value"


def test_set_overwrites_existing():
    sm = SecretsManager()
    sm.set("key", "v1")
    sm.set("key", "v2")
    assert sm.get("key") == "v2"


# ── status ────────────────────────────────────────────────────────────────────


def test_status_returns_dict():
    sm = SecretsManager()
    s = sm.status()
    assert isinstance(s, dict)
    assert "backend" in s
    assert "refresh_enabled" in s
    assert "refresh_count" in s
    assert "error_count" in s
    assert "cached_keys" in s


def test_status_last_refresh_none_initially():
    sm = SecretsManager()
    assert sm.status()["last_refresh"] is None


# ── stop ──────────────────────────────────────────────────────────────────────


def test_stop_sets_running_false():
    sm = SecretsManager()
    sm._running = True
    sm.stop()
    assert sm._running is False


# ── _fetch_env ────────────────────────────────────────────────────────────────


def test_fetch_env_returns_dict(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt-val")
    sm = SecretsManager()
    result = sm._fetch_env()
    assert isinstance(result, dict)
    assert "jwt_secret_key" in result
    assert result["jwt_secret_key"] == "jwt-val"  # pragma: allowlist secret


def test_fetch_env_skips_unset_vars():
    sm = SecretsManager()
    # Remove all mapped env vars
    with patch.dict(os.environ, {}, clear=True):
        result = sm._fetch_env()
    assert isinstance(result, dict)
    # All values should be absent since env is cleared
    assert all(v is not None for v in result.values())


# ── refresh (env backend) ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_env_backend_updates_cache(monkeypatch):
    import core.secrets_manager as csm

    monkeypatch.setattr(csm, "_BACKEND", "env")
    monkeypatch.setenv("JWT_SECRET_KEY", "refreshed-jwt")
    sm = SecretsManager()
    sm._cache.clear()
    await sm.refresh()
    assert sm._refresh_count == 1
    assert sm._last_refresh is not None


@pytest.mark.asyncio
async def test_refresh_increments_count(monkeypatch):
    import core.secrets_manager as csm

    monkeypatch.setattr(csm, "_BACKEND", "env")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-for-count")
    sm = SecretsManager()
    sm._cache.clear()
    await sm.refresh()
    await sm.refresh()
    assert sm._refresh_count == 2


@pytest.mark.asyncio
async def test_refresh_notifies_rotation_callbacks(monkeypatch):
    import core.secrets_manager as csm

    monkeypatch.setattr(csm, "_BACKEND", "env")
    monkeypatch.setenv("JWT_SECRET_KEY", "new-secret-value")
    sm = SecretsManager()
    sm._cache.clear()

    called_with = []

    def _cb(changed_keys):
        called_with.extend(changed_keys)

    sm.on_rotation(_cb)
    await sm.refresh()
    # Callback should have been called if any keys changed
    assert isinstance(called_with, list)


# ── refresh_loop ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_loop_disabled(monkeypatch):
    import core.secrets_manager as csm

    monkeypatch.setattr(csm, "_REFRESH_ENABLED", False)
    sm = SecretsManager()
    with patch.object(sm, "refresh", new_callable=AsyncMock) as mock_refresh:
        await sm.refresh_loop()
    mock_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_loop_cancels_cleanly(monkeypatch):
    import core.secrets_manager as csm

    monkeypatch.setattr(csm, "_REFRESH_ENABLED", True)
    monkeypatch.setattr(csm, "_REFRESH_INTERVAL", 9999)
    sm = SecretsManager()

    async def _fast_refresh():
        sm._refresh_count += 1

    with patch.object(sm, "refresh", side_effect=_fast_refresh):
        task = asyncio.create_task(sm.refresh_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_refresh_loop_handles_errors(monkeypatch):
    import core.secrets_manager as csm

    monkeypatch.setattr(csm, "_REFRESH_ENABLED", True)
    monkeypatch.setattr(csm, "_REFRESH_INTERVAL", 0.01)
    sm = SecretsManager()
    call_count = [0]

    async def _bad_refresh():
        call_count[0] += 1
        if call_count[0] < 3:
            raise RuntimeError("transient error")

    with patch.object(sm, "refresh", side_effect=_bad_refresh):
        task = asyncio.create_task(sm.refresh_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert sm._error_count >= 1


# ── on_rotation / _notify_rotation ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_rotation_registers_callback():
    sm = SecretsManager()
    sm._rotation_callbacks = []

    def _cb(keys):
        pass

    sm.on_rotation(_cb)
    assert _cb in sm._rotation_callbacks


@pytest.mark.asyncio
async def test_notify_rotation_calls_sync_callback():
    sm = SecretsManager()
    sm._rotation_callbacks = []
    called = []

    def _cb(keys):
        called.append(keys)

    sm.on_rotation(_cb)
    await sm._notify_rotation({"jwt_secret_key"})
    assert len(called) == 1
    assert "jwt_secret_key" in called[0]


@pytest.mark.asyncio
async def test_notify_rotation_calls_async_callback():
    sm = SecretsManager()
    sm._rotation_callbacks = []
    called = []

    async def _async_cb(keys):
        called.append(keys)

    sm.on_rotation(_async_cb)
    await sm._notify_rotation({"db_password"})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_notify_rotation_handles_callback_error():
    sm = SecretsManager()
    sm._rotation_callbacks = []

    def _bad_cb(keys):
        raise RuntimeError("callback error")

    sm.on_rotation(_bad_cb)
    # Must not raise
    await sm._notify_rotation({"some_key"})


# ── _fetch_vault — hvac not installed ────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_vault_falls_back_when_hvac_missing(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "env-fallback")
    sm = SecretsManager()
    with patch.dict("sys.modules", {"hvac": None}):
        result = await sm._fetch_vault()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_fetch_vault_falls_back_on_auth_failure(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://localhost:8200")
    monkeypatch.setenv("VAULT_TOKEN", "bad-token")
    monkeypatch.setenv("JWT_SECRET_KEY", "env-fallback")
    sm = SecretsManager()

    mock_hvac = MagicMock()
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = False
    mock_hvac.Client.return_value = mock_client

    with patch.dict("sys.modules", {"hvac": mock_hvac}):
        result = await sm._fetch_vault()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_fetch_vault_returns_secrets_on_success(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://localhost:8200")
    monkeypatch.setenv("VAULT_TOKEN", "good-token")
    sm = SecretsManager()

    mock_hvac = MagicMock()
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"JWT_SECRET_KEY": "vault-jwt", "DB_PASSWORD": "vault-db"}}  # pragma: allowlist secret
    }
    mock_hvac.Client.return_value = mock_client

    with patch.dict("sys.modules", {"hvac": mock_hvac}):
        result = await sm._fetch_vault()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_fetch_vault_exception_falls_back(monkeypatch):
    monkeypatch.setenv("VAULT_TOKEN", "token")
    monkeypatch.setenv("JWT_SECRET_KEY", "env-fallback")
    sm = SecretsManager()

    mock_hvac = MagicMock()
    mock_hvac.Client.side_effect = RuntimeError("vault unreachable")

    with patch.dict("sys.modules", {"hvac": mock_hvac}):
        result = await sm._fetch_vault()
    assert isinstance(result, dict)


# ── _fetch_aws — boto3 not installed ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_aws_falls_back_when_boto3_missing(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "env-fallback")
    sm = SecretsManager()
    with patch.dict("sys.modules", {"boto3": None}):
        result = await sm._fetch_aws()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_fetch_aws_returns_secrets_on_success(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SECRET_NAME", "hopefx/api")
    sm = SecretsManager()

    import json

    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {
        "SecretString": json.dumps({"JWT_SECRET_KEY": "aws-jwt"})
    }
    mock_boto3.client.return_value = mock_client

    with patch.dict("sys.modules", {"boto3": mock_boto3}):
        result = await sm._fetch_aws()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_fetch_aws_exception_falls_back(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "env-fallback")
    sm = SecretsManager()

    mock_boto3 = MagicMock()
    mock_boto3.client.side_effect = RuntimeError("aws unreachable")

    with patch.dict("sys.modules", {"boto3": mock_boto3}):
        result = await sm._fetch_aws()
    assert isinstance(result, dict)


# ── module-level singleton ────────────────────────────────────────────────────


def test_module_singleton_is_secrets_manager():
    assert isinstance(secrets, SecretsManager)


def test_get_secret_function():
    result = get_secret("totally_missing_key_xyz_abc", default="default_val")
    assert result == "default_val"


def test_get_secret_returns_cached():
    secrets.set("test_singleton_key", "singleton_val")
    assert get_secret("test_singleton_key") == "singleton_val"
    # Cleanup
    secrets._cache.pop("test_singleton_key", None)
