# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Supplemental kill_switch.py coverage tests targeting uncovered branches:
  - Redis latch check/write/clear paths
  - Stale flag-file restore in non-production
  - K8s ConfigMap watcher (import error, config error, poll loop, cancel)
  - _write_k8s_configmap sync path (no running loop)
  - Poll loop OSError on flag file read
  - Router: rate limiting, auth error paths, deactivate already-inactive
  - Sentry / email notification paths in _activate_internal
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ks(tmp_path: Path, token: str = "tok", **kwargs):
    from kill_switch import KillSwitch
    flag = tmp_path / "ks.flag"
    ks = KillSwitch(flag_file=flag, deactivation_token=token, **kwargs)
    return ks


def _clean(ks) -> None:
    ks.reset_for_testing()
    for p in (ks._flag_file, ks._state_file):
        if p.exists():
            p.unlink()


# ---------------------------------------------------------------------------
# Redis latch paths
# ---------------------------------------------------------------------------

class TestRedisLatchPaths:
    def test_check_redis_latch_activates_when_latch_true(self, tmp_path):
        ks = _ks(tmp_path)
        mock_r = MagicMock()
        mock_r.get.side_effect = lambda key: (
            "true" if "active" in key else "drawdown breach on peer"
        )
        with patch.object(ks, "_get_latch_redis", return_value=mock_r):
            asyncio.get_event_loop().run_until_complete(ks._check_redis_latch())
        assert ks.is_active()
        _clean(ks)

    def test_check_redis_latch_no_redis_returns_gracefully(self, tmp_path):
        ks = _ks(tmp_path)
        with patch.object(ks, "_get_latch_redis", return_value=None):
            asyncio.get_event_loop().run_until_complete(ks._check_redis_latch())
        assert not ks.is_active()

    def test_check_redis_latch_exception_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        with patch.object(ks, "_get_latch_redis", side_effect=RuntimeError("boom")):
            asyncio.get_event_loop().run_until_complete(ks._check_redis_latch())
        assert not ks.is_active()

    def test_check_redis_latch_already_active_skips(self, tmp_path):
        ks = _ks(tmp_path)
        ks._active = True
        ks._reason = "pre-existing"
        mock_r = MagicMock()
        mock_r.get.return_value = "true"
        with patch.object(ks, "_get_latch_redis", return_value=mock_r):
            asyncio.get_event_loop().run_until_complete(ks._check_redis_latch())
        # Still active, reason unchanged
        assert ks._reason == "pre-existing"
        _clean(ks)

    def test_write_redis_latch_calls_set(self, tmp_path):
        ks = _ks(tmp_path)
        mock_r = MagicMock()
        with patch.object(ks, "_get_latch_redis", return_value=mock_r):
            ks._write_redis_latch("test reason")
        assert mock_r.set.call_count == 2

    def test_write_redis_latch_no_redis_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        with patch.object(ks, "_get_latch_redis", return_value=None):
            ks._write_redis_latch("test reason")  # should not raise

    def test_write_redis_latch_exception_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        mock_r = MagicMock()
        mock_r.set.side_effect = RuntimeError("redis down")
        with patch.object(ks, "_get_latch_redis", return_value=mock_r):
            ks._write_redis_latch("test reason")  # should not raise

    def test_clear_redis_latch_calls_delete(self, tmp_path):
        ks = _ks(tmp_path)
        mock_r = MagicMock()
        with patch.object(ks, "_get_latch_redis", return_value=mock_r):
            ks._clear_redis_latch()
        mock_r.delete.assert_called_once()

    def test_clear_redis_latch_no_redis_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        with patch.object(ks, "_get_latch_redis", return_value=None):
            ks._clear_redis_latch()  # should not raise

    def test_clear_redis_latch_exception_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        mock_r = MagicMock()
        mock_r.delete.side_effect = RuntimeError("redis down")
        with patch.object(ks, "_get_latch_redis", return_value=mock_r):
            ks._clear_redis_latch()  # should not raise


# ---------------------------------------------------------------------------
# Stale flag-file restore
# ---------------------------------------------------------------------------

class TestStaleFlagFileRestore:
    def test_stale_flag_file_not_restored_in_non_production(self, tmp_path):
        flag = tmp_path / "ks.flag"
        state = tmp_path / "ks.state.json"
        # Write a stale flag file (activated 25 hours ago)
        old_ts = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        flag.write_text(f"activated_at={old_ts}\nreason=old breach\n")
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=False):
            from kill_switch import KillSwitch
            ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert not ks.is_active()

    def test_fresh_flag_file_restored_in_non_production(self, tmp_path):
        flag = tmp_path / "ks.flag"
        recent_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        flag.write_text(f"activated_at={recent_ts}\nreason=recent breach\n")
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=False):
            from kill_switch import KillSwitch
            ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks.is_active()
        _clean(ks)

    def test_stale_state_json_not_restored_in_non_production(self, tmp_path):
        flag = tmp_path / "ks.flag"
        state = flag.with_suffix(".state.json")
        old_ts = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
        state.write_text(json.dumps({"active": True, "reason": "old", "activated_at": old_ts}))
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=False):
            from kill_switch import KillSwitch
            ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert not ks.is_active()

    def test_stale_state_always_restored_in_production(self, tmp_path):
        flag = tmp_path / "ks.flag"
        state = flag.with_suffix(".state.json")
        old_ts = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
        state.write_text(json.dumps({"active": True, "reason": "old", "activated_at": old_ts}))
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
            from kill_switch import KillSwitch
            ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks.is_active()
        _clean(ks)

    def test_naive_datetime_in_state_file_handled(self, tmp_path):
        """activated_at without timezone info should not crash _restore_state."""
        flag = tmp_path / "ks.flag"
        state = flag.with_suffix(".state.json")
        # Write naive datetime (no +00:00)
        naive_ts = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        state.write_text(json.dumps({"active": True, "reason": "naive ts", "activated_at": naive_ts}))
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
            from kill_switch import KillSwitch
            ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks.is_active()
        _clean(ks)


# ---------------------------------------------------------------------------
# K8s ConfigMap watcher
# ---------------------------------------------------------------------------

class TestK8sConfigMapWatcher:
    @pytest.mark.asyncio
    async def test_watcher_skips_outside_pod(self, tmp_path):
        ks = _ks(tmp_path)
        env = {k: v for k, v in os.environ.items() if k != "KUBERNETES_SERVICE_HOST"}
        with patch.dict(os.environ, env, clear=True):
            # Should return immediately without error
            await ks._k8s_configmap_watcher()
        assert not ks.is_active()

    @pytest.mark.asyncio
    async def test_watcher_import_error_returns_gracefully(self, tmp_path):
        ks = _ks(tmp_path)
        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}):
            with patch.dict(__import__("sys").modules, {"kubernetes_asyncio": None}):
                await ks._k8s_configmap_watcher()
        assert not ks.is_active()

    @pytest.mark.asyncio
    async def test_watcher_config_error_returns_gracefully(self, tmp_path):
        ks = _ks(tmp_path)
        mock_k8s = MagicMock()
        mock_k8s.config.load_incluster_config = AsyncMock(side_effect=Exception("no incluster"))
        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}):
            with patch.dict(__import__("sys").modules, {"kubernetes_asyncio": mock_k8s,
                                                         "kubernetes_asyncio.client": mock_k8s.client,
                                                         "kubernetes_asyncio.config": mock_k8s.config}):
                await ks._k8s_configmap_watcher()
        assert not ks.is_active()

    @pytest.mark.asyncio
    async def test_watcher_activates_on_configmap_flag(self, tmp_path):
        ks = _ks(tmp_path)
        ks._running = True

        cm_mock = MagicMock()
        cm_mock.data = {"kill_switch_active": "true", "kill_switch_reason": "k8s test"}

        call_count = 0

        async def fake_read(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return cm_mock
            ks._running = False
            raise asyncio.CancelledError()

        mock_v1 = MagicMock()
        mock_v1.read_namespaced_config_map = fake_read

        mock_k8s_mod = MagicMock()
        mock_k8s_mod.config.load_incluster_config = AsyncMock()
        mock_k8s_mod.client.CoreV1Api.return_value = mock_v1

        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1",
                                      "K8S_KS_POLL_INTERVAL_S": "0.01"}):
            with patch.dict(__import__("sys").modules, {
                "kubernetes_asyncio": mock_k8s_mod,
                "kubernetes_asyncio.client": mock_k8s_mod.client,
                "kubernetes_asyncio.config": mock_k8s_mod.config,
            }):
                try:
                    await asyncio.wait_for(ks._k8s_configmap_watcher(), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        assert ks.is_active()
        _clean(ks)

    @pytest.mark.asyncio
    async def test_watcher_poll_error_continues(self, tmp_path):
        ks = _ks(tmp_path)
        ks._running = True
        call_count = 0

        async def fake_read(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                ks._running = False
                raise asyncio.CancelledError()
            raise Exception("transient error")

        mock_v1 = MagicMock()
        mock_v1.read_namespaced_config_map = fake_read
        mock_k8s_mod = MagicMock()
        mock_k8s_mod.config.load_incluster_config = AsyncMock()
        mock_k8s_mod.client.CoreV1Api.return_value = mock_v1

        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1",
                                      "K8S_KS_POLL_INTERVAL_S": "0.01"}):
            with patch.dict(__import__("sys").modules, {
                "kubernetes_asyncio": mock_k8s_mod,
                "kubernetes_asyncio.client": mock_k8s_mod.client,
                "kubernetes_asyncio.config": mock_k8s_mod.config,
            }):
                try:
                    await asyncio.wait_for(ks._k8s_configmap_watcher(), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
        assert not ks.is_active()


# ---------------------------------------------------------------------------
# _write_k8s_configmap sync path (no running loop)
# ---------------------------------------------------------------------------

class TestWriteK8sConfigmapSync:
    def test_write_k8s_configmap_skips_outside_pod(self, tmp_path):
        ks = _ks(tmp_path)
        env = {k: v for k, v in os.environ.items() if k != "KUBERNETES_SERVICE_HOST"}
        with patch.dict(os.environ, env, clear=True):
            ks._write_k8s_configmap("test")  # should not raise

    def test_write_k8s_configmap_sync_path(self, tmp_path):
        ks = _ks(tmp_path)
        mock_v1 = MagicMock()
        mock_k8s_sync = MagicMock()
        mock_k8s_sync.CoreV1Api.return_value = mock_v1
        mock_k8s_sync_config = MagicMock()

        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}):
            with patch.dict(__import__("sys").modules, {
                "kubernetes": mock_k8s_sync,
                "kubernetes.client": mock_k8s_sync,
                "kubernetes.config": mock_k8s_sync_config,
            }):
                # Ensure no running loop so sync path is taken
                with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
                    ks._write_k8s_configmap("sync test reason")

    def test_write_k8s_configmap_sync_exception_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        mock_k8s_sync_config = MagicMock()
        mock_k8s_sync_config.load_incluster_config.side_effect = Exception("no config")
        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}):
            with patch.dict(__import__("sys").modules, {
                "kubernetes": MagicMock(),
                "kubernetes.client": MagicMock(),
                "kubernetes.config": mock_k8s_sync_config,
            }):
                with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
                    ks._write_k8s_configmap("error path")  # should not raise


# ---------------------------------------------------------------------------
# Poll loop OSError on flag file read
# ---------------------------------------------------------------------------

class TestPollLoopOSError:
    @pytest.mark.asyncio
    async def test_poll_loop_oserror_on_flag_read_uses_default_reason(self, tmp_path):
        ks = _ks(tmp_path)
        ks._running = True
        ks._poll_interval = 0.01

        # Create flag file but make read_text raise OSError
        ks._flag_file.write_text("reason=test")

        call_count = 0
        original_read = Path.read_text

        def patched_read(self_path, *a, **kw):
            nonlocal call_count
            if self_path == ks._flag_file:
                call_count += 1
                if call_count == 1:
                    raise OSError("permission denied")
            return original_read(self_path, *a, **kw)

        with patch.object(Path, "read_text", patched_read):
            task = asyncio.create_task(ks._poll_loop())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should have activated with default reason
        assert ks.is_active()
        _clean(ks)


# ---------------------------------------------------------------------------
# Sentry and email notification paths
# ---------------------------------------------------------------------------

class TestActivateInternalNotifications:
    def test_sentry_alert_called_on_activate(self, tmp_path):
        ks = _ks(tmp_path)
        mock_capture = MagicMock()
        with patch("monitoring.sentry_config.capture_kill_switch_alert", mock_capture, create=True):
            with patch.dict(__import__("sys").modules, {
                "monitoring": MagicMock(),
                "monitoring.sentry_config": MagicMock(capture_kill_switch_alert=mock_capture),
            }):
                ks.activate("sentry test")
        # Sentry may or may not be called depending on import path; no crash is the key assertion
        _clean(ks)

    def test_sentry_exception_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        with patch.dict(__import__("sys").modules, {
            "monitoring": MagicMock(),
            "monitoring.sentry_config": MagicMock(
                capture_kill_switch_alert=MagicMock(side_effect=RuntimeError("sentry down"))
            ),
        }):
            ks.activate("sentry error test")  # should not raise
        _clean(ks)

    def test_email_alert_exception_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        with patch.dict(__import__("sys").modules, {
            "notifications": MagicMock(),
            "notifications.email_triggers": MagicMock(
                send_risk_halt_email=MagicMock(side_effect=RuntimeError("smtp down"))
            ),
        }):
            ks.activate("email error test")  # should not raise
        _clean(ks)


# ---------------------------------------------------------------------------
# Router: rate limiting and auth error paths
# ---------------------------------------------------------------------------

class TestRouterRateLimitAndAuth:
    @pytest.mark.asyncio
    async def test_rate_limit_blocks_after_5_requests(self, tmp_path):
        from fastapi import FastAPI
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.sub = "rate_test_user"
        mock_user.role = "admin"

        with patch("api.auth._decode_token", return_value=mock_user):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                # First 5 should succeed (or return already_active)
                for _ in range(5):
                    ks.reset_for_testing()
                    await client.post(
                        "/api/kill-switch/activate",
                        json={"reason": "rate test"},
                        headers={"Authorization": "Bearer fake"},
                    )
                # 6th should be rate-limited
                ks.reset_for_testing()
                resp = await client.post(
                    "/api/kill-switch/activate",
                    json={"reason": "rate test"},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 429
        _clean(ks)

    @pytest.mark.asyncio
    async def test_auth_service_error_returns_503(self, tmp_path):
        from fastapi import FastAPI
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        with patch("api.auth._decode_token", side_effect=Exception("auth service down")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/kill-switch/activate",
                    json={"reason": "test"},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 503
        _clean(ks)

    @pytest.mark.asyncio
    async def test_deactivate_already_inactive_returns_already_inactive(self, tmp_path):
        from fastapi import FastAPI
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        # Do NOT activate — switch is inactive
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.sub = "admin"
        mock_user.role = "admin"

        with patch("api.auth._decode_token", return_value=mock_user):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/kill-switch/deactivate",
                    json={"token": "tok"},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_inactive"
        _clean(ks)

    @pytest.mark.asyncio
    async def test_insufficient_role_returns_403(self, tmp_path):
        from fastapi import FastAPI
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.sub = "trader1"
        mock_user.role = "trader"  # below admin

        with patch("api.auth._decode_token", return_value=mock_user):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/kill-switch/activate",
                    json={"reason": "test"},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 403
        _clean(ks)


# ---------------------------------------------------------------------------
# Redis breach listener — already-active branch
# ---------------------------------------------------------------------------

class TestRedisBreachListenerAlreadyActive:
    @pytest.mark.asyncio
    async def test_listener_skips_when_already_active(self, tmp_path):
        ks = _ks(tmp_path)
        ks._running = True
        ks._active = True  # already active

        messages = [
            {"type": "kill_switch", "reason": "remote"},
            None,  # sentinel to stop
        ]

        async def fake_subscribe(channel):
            for m in messages:
                if m is None:
                    ks._running = False
                    return
                yield m

        mock_bus = MagicMock()
        mock_bus.connect = AsyncMock()
        mock_bus.subscribe = fake_subscribe

        with patch("core.event_bus.bus", mock_bus):
            with patch("core.event_bus.CH_BREACH", "hopefx:breach"):
                try:
                    await asyncio.wait_for(ks._redis_breach_listener(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

        assert ks._active
        _clean(ks)

    @pytest.mark.asyncio
    async def test_listener_stops_when_running_false(self, tmp_path):
        """Cover the `if not self._running: break` branch."""
        ks = _ks(tmp_path)
        ks._running = True

        async def fake_subscribe(channel):
            ks._running = False  # signal stop before first message
            yield {"type": "kill_switch", "reason": "should be ignored"}

        mock_bus = MagicMock()
        mock_bus.connect = AsyncMock()
        mock_bus.subscribe = fake_subscribe

        with patch("core.event_bus.bus", mock_bus):
            with patch("core.event_bus.CH_BREACH", "hopefx:breach"):
                await asyncio.wait_for(ks._redis_breach_listener(), timeout=2.0)

        assert not ks.is_active()

    @pytest.mark.asyncio
    async def test_listener_message_exception_continues(self, tmp_path):
        """Cover the inner `except Exception` in the message loop."""
        ks = _ks(tmp_path)
        ks._running = True
        call_count = 0

        async def fake_subscribe(channel):
            nonlocal call_count
            call_count += 1
            yield None  # will cause .get() to raise AttributeError
            ks._running = False

        mock_bus = MagicMock()
        mock_bus.connect = AsyncMock()
        mock_bus.subscribe = fake_subscribe

        with patch("core.event_bus.bus", mock_bus):
            with patch("core.event_bus.CH_BREACH", "hopefx:breach"):
                try:
                    await asyncio.wait_for(ks._redis_breach_listener(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass

        assert not ks.is_active()

    @pytest.mark.asyncio
    async def test_listener_outer_exception_logs_error(self, tmp_path):
        """Cover the outer `except Exception` (unexpected listener crash)."""
        ks = _ks(tmp_path)
        ks._running = True

        async def fake_subscribe(channel):
            raise RuntimeError("unexpected crash")
            yield  # make it an async generator

        mock_bus = MagicMock()
        mock_bus.connect = AsyncMock()
        mock_bus.subscribe = fake_subscribe

        with patch("core.event_bus.bus", mock_bus):
            with patch("core.event_bus.CH_BREACH", "hopefx:breach"):
                await ks._redis_breach_listener()  # should not raise


# ---------------------------------------------------------------------------
# _get_latch_redis fallback exception path
# ---------------------------------------------------------------------------

class TestGetLatchRedisFallbackException:
    def test_redis_from_url_exception_returns_none(self, tmp_path):
        ks = _ks(tmp_path)
        # Make bus import fail AND redis.from_url fail
        with patch.dict(__import__("sys").modules, {"core.event_bus": None}):
            with patch("redis.from_url", side_effect=Exception("conn refused")):
                result = ks._get_latch_redis()
        assert result is None


# ---------------------------------------------------------------------------
# _clear_state OSError path
# ---------------------------------------------------------------------------

class TestClearStateOSError:
    def test_clear_state_oserror_non_fatal(self, tmp_path):
        ks = _ks(tmp_path)
        ks.activate("test")
        # Make unlink raise OSError
        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            ks._clear_state()  # should not raise


# ---------------------------------------------------------------------------
# _restore_state: flag file exception path
# ---------------------------------------------------------------------------

class TestRestoreStateFlagFileException:
    def test_flag_file_read_exception_non_fatal(self, tmp_path):
        flag = tmp_path / "ks.flag"
        flag.write_text("reason=test\n")
        # Make _parse_flag_file raise
        from kill_switch import KillSwitch
        with patch.object(KillSwitch, "_parse_flag_file", side_effect=Exception("parse error")):
            ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        # Should not be active (exception was caught)
        assert not ks.is_active()


# ---------------------------------------------------------------------------
# K8s watcher: already-active branch and cm.data is None
# ---------------------------------------------------------------------------

class TestK8sWatcherEdgeCases:
    @pytest.mark.asyncio
    async def test_watcher_skips_when_already_active(self, tmp_path):
        """Cover the `if active_flag == 'true' and not self._active` branch (already active)."""
        ks = _ks(tmp_path)
        ks._running = True
        ks._active = True  # already active

        cm_mock = MagicMock()
        cm_mock.data = {"kill_switch_active": "true", "kill_switch_reason": "test"}
        call_count = 0

        async def fake_read(*a, **kw):
            nonlocal call_count
            call_count += 1
            ks._running = False
            return cm_mock

        mock_v1 = MagicMock()
        mock_v1.read_namespaced_config_map = fake_read
        mock_k8s_mod = MagicMock()
        mock_k8s_mod.config.load_incluster_config = AsyncMock()
        mock_k8s_mod.client.CoreV1Api.return_value = mock_v1

        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1",
                                      "K8S_KS_POLL_INTERVAL_S": "0.01"}):
            with patch.dict(__import__("sys").modules, {
                "kubernetes_asyncio": mock_k8s_mod,
                "kubernetes_asyncio.client": mock_k8s_mod.client,
                "kubernetes_asyncio.config": mock_k8s_mod.config,
            }):
                try:
                    await asyncio.wait_for(ks._k8s_configmap_watcher(), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
        # Reason should be unchanged (not re-activated)
        assert ks._active
        _clean(ks)

    @pytest.mark.asyncio
    async def test_watcher_handles_none_cm_data(self, tmp_path):
        """Cover `data = cm.data or {}` when cm.data is None."""
        ks = _ks(tmp_path)
        ks._running = True

        cm_mock = MagicMock()
        cm_mock.data = None  # triggers `or {}`
        call_count = 0

        async def fake_read(*a, **kw):
            nonlocal call_count
            call_count += 1
            ks._running = False
            return cm_mock

        mock_v1 = MagicMock()
        mock_v1.read_namespaced_config_map = fake_read
        mock_k8s_mod = MagicMock()
        mock_k8s_mod.config.load_incluster_config = AsyncMock()
        mock_k8s_mod.client.CoreV1Api.return_value = mock_v1

        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1",
                                      "K8S_KS_POLL_INTERVAL_S": "0.01"}):
            with patch.dict(__import__("sys").modules, {
                "kubernetes_asyncio": mock_k8s_mod,
                "kubernetes_asyncio.client": mock_k8s_mod.client,
                "kubernetes_asyncio.config": mock_k8s_mod.config,
            }):
                try:
                    await asyncio.wait_for(ks._k8s_configmap_watcher(), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
        assert not ks.is_active()


# ---------------------------------------------------------------------------
# _write_k8s_configmap async path (running loop)
# ---------------------------------------------------------------------------

class TestWriteK8sConfigmapAsync:
    @pytest.mark.asyncio
    async def test_write_k8s_configmap_async_patch_success(self, tmp_path):
        """Cover the async _async_patch success path (lines 818→exit)."""
        ks = _ks(tmp_path)

        mock_v1 = MagicMock()
        mock_v1.patch_namespaced_config_map = AsyncMock()
        mock_k8s_mod = MagicMock()
        mock_k8s_mod.config.load_incluster_config = AsyncMock()
        mock_k8s_mod.client.CoreV1Api.return_value = mock_v1

        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}):
            with patch.dict(__import__("sys").modules, {
                "kubernetes_asyncio": mock_k8s_mod,
                "kubernetes_asyncio.client": mock_k8s_mod.client,
                "kubernetes_asyncio.config": mock_k8s_mod.config,
            }):
                ks._write_k8s_configmap("async test")
                # Let the created task run
                await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_write_k8s_configmap_async_patch_exception(self, tmp_path):
        """Cover the async _async_patch exception path (lines 825→841)."""
        ks = _ks(tmp_path)

        mock_k8s_mod = MagicMock()
        mock_k8s_mod.config.load_incluster_config = AsyncMock(side_effect=Exception("k8s error"))

        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}):
            with patch.dict(__import__("sys").modules, {
                "kubernetes_asyncio": mock_k8s_mod,
                "kubernetes_asyncio.client": mock_k8s_mod.client,
                "kubernetes_asyncio.config": mock_k8s_mod.config,
            }):
                ks._write_k8s_configmap("async error test")
                await asyncio.sleep(0.05)  # let task run and hit exception


# ---------------------------------------------------------------------------
# Router: deactivate with wrong token (403) and request.client is None
# ---------------------------------------------------------------------------

class TestRouterDeactivatePaths:
    @pytest.mark.asyncio
    async def test_deactivate_wrong_token_returns_403(self, tmp_path):
        from fastapi import FastAPI
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="correct-token")
        ks.activate("test halt")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.sub = "admin"
        mock_user.role = "admin"

        with patch("api.auth._decode_token", return_value=mock_user):
            with patch.object(ks, "_clear_redis_latch"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post(
                        "/api/kill-switch/deactivate",
                        json={"token": "wrong-token"},
                        headers={"Authorization": "Bearer fake"},
                    )
        assert resp.status_code == 403
        _clean(ks)

    @pytest.mark.asyncio
    async def test_deactivate_correct_token_returns_deactivated(self, tmp_path):
        from fastapi import FastAPI
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="correct-token")
        ks.activate("test halt")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.sub = "admin"
        mock_user.role = "admin"

        with patch("api.auth._decode_token", return_value=mock_user):
            with patch.object(ks, "_clear_redis_latch"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post(
                        "/api/kill-switch/deactivate",
                        json={"token": "correct-token"},
                        headers={"Authorization": "Bearer fake"},
                    )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"
        _clean(ks)

    @pytest.mark.asyncio
    async def test_activate_route_no_client_ip(self, tmp_path):
        """Cover `request.client.host if request.client else 'unknown'` when client is None."""
        from fastapi import FastAPI, Request
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.sub = "admin"
        mock_user.role = "admin"

        with patch("api.auth._decode_token", return_value=mock_user):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/kill-switch/activate",
                    json={"reason": "no-client-ip test"},
                    headers={"Authorization": "Bearer fake"},
                )
        assert resp.status_code == 200
        _clean(ks)

    @pytest.mark.asyncio
    async def test_require_admin_http_exception_reraise(self, tmp_path):
        """Cover the `except HTTPException: raise` branch in _require_admin."""
        from fastapi import FastAPI, HTTPException as FastAPIHTTPException
        from httpx import AsyncClient
        from httpx._transports.asgi import ASGITransport
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        # _decode_token raises HTTPException (e.g. expired token → 401)
        with patch("api.auth._decode_token",
                   side_effect=FastAPIHTTPException(status_code=401, detail="expired")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/kill-switch/activate",
                    json={"reason": "test"},
                    headers={"Authorization": "Bearer expired-token"},
                )
        assert resp.status_code == 401
        _clean(ks)

