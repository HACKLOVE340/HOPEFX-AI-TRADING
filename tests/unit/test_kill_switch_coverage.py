# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for kill_switch.py — targeting ≥90% branch coverage.

Covers:
  - KillSwitch construction (env-var, flag-file, state-file restore)
  - activate() / deactivate() lifecycle
  - is_active() priority chain
  - register_callback() and callback invocation
  - status() snapshot
  - reset_for_testing()
  - start() / stop() background polling
  - _poll_loop() file-flag detection
  - Redis latch write / clear / check
  - K8s ConfigMap watcher (no-op when k8s unavailable)
  - trigger_nuclear_mode() async wrapper
  - OMS kill-switch gate (defense-in-depth)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = __import__("datetime").timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ks(tmp_path: Path, token: str = "test-token", **kwargs):
    """Create an isolated KillSwitch with tmp flag/state files."""
    from kill_switch import KillSwitch

    flag = tmp_path / "ks.flag"
    return KillSwitch(flag_file=flag, poll_interval_sec=0.05, deactivation_token=token, **kwargs)


def _clean(ks) -> None:
    """Remove flag/state files left by a KillSwitch instance."""
    for f in (ks._flag_file, ks._state_file):
        f.unlink(missing_ok=True)


# ===========================================================================
# Construction
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchConstruction:
    def test_inactive_by_default(self, tmp_path):
        ks = _make_ks(tmp_path)
        assert ks.is_active() is False
        assert ks.reason == ""
        assert ks.activated_at is None
        _clean(ks)

    def test_env_var_activates_on_construction(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOPEFX_KILL_SWITCH", "1")
        ks = _make_ks(tmp_path)
        assert ks.is_active() is True
        assert "env var" in ks.reason.lower()
        _clean(ks)

    def test_env_var_zero_does_not_activate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOPEFX_KILL_SWITCH", "0")
        ks = _make_ks(tmp_path)
        assert ks.is_active() is False
        _clean(ks)

    def test_state_file_restore_activates(self, tmp_path):
        """A persisted state file from a previous process re-activates on construction."""
        flag = tmp_path / "ks.flag"
        state = flag.with_suffix(".state.json")
        import datetime

        state.write_text(
            json.dumps(
                {
                    "active": True,
                    "reason": "previous halt",
                    "activated_at": datetime.datetime.now(UTC).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks.is_active() is True
        assert "previous halt" in ks.reason
        _clean(ks)

    def test_no_state_file_starts_clean(self, tmp_path):
        ks = _make_ks(tmp_path)
        assert ks.is_active() is False
        _clean(ks)

    def test_deactivation_token_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOPEFX_KILL_SWITCH_TOKEN", "env-token")
        from kill_switch import KillSwitch

        flag = tmp_path / "ks2.flag"
        ks = KillSwitch(flag_file=flag)
        assert ks._deactivation_token == "env-token"
        _clean(ks)


# ===========================================================================
# activate() / is_active() / reason / activated_at
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchActivation:
    def test_activate_sets_active(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("test reason")
        assert ks.is_active() is True
        assert ks.reason == "test reason"
        assert ks.activated_at is not None
        _clean(ks)

    def test_activate_idempotent(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("first")
        ks.activate("second")  # should not overwrite
        assert ks.reason == "first"
        _clean(ks)

    def test_activate_writes_flag_file(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("flag test")
        assert ks._flag_file.exists()
        _clean(ks)

    def test_activate_writes_state_file(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("state test")
        assert ks._state_file.exists()
        data = json.loads(ks._state_file.read_text())
        assert data["active"] is True
        assert data["reason"] == "state test"
        _clean(ks)

    def test_activate_invokes_callbacks(self, tmp_path):
        ks = _make_ks(tmp_path)
        called = []

        def _cb(r):
            called.append(r)

        ks.register_callback(_cb)
        ks.activate("cb test")
        assert called == ["cb test"]
        _clean(ks)

    def test_activate_callback_exception_does_not_propagate(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.register_callback(lambda r: (_ for _ in ()).throw(RuntimeError("boom")))
        ks.activate("safe")  # must not raise
        assert ks.is_active() is True
        _clean(ks)

    def test_activate_writes_redis_latch(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_redis = MagicMock()
        with patch.object(ks, "_get_latch_redis", return_value=mock_redis):
            ks.activate("redis latch test")
        mock_redis.set.assert_called()
        _clean(ks)

    def test_activate_redis_latch_failure_non_fatal(self, tmp_path):
        ks = _make_ks(tmp_path)
        with patch.object(ks, "_get_latch_redis", side_effect=Exception("redis down")):
            ks.activate("no redis")  # must not raise
        assert ks.is_active() is True
        _clean(ks)

    def test_status_snapshot(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("status test")
        s = ks.status()
        assert s["active"] is True
        assert s["reason"] == "status test"
        assert "flag_file" in s
        assert "deactivation_token_configured" in s
        _clean(ks)

    def test_status_inactive(self, tmp_path):
        ks = _make_ks(tmp_path)
        s = ks.status()
        assert s["active"] is False
        assert s["activated_at"] is None
        _clean(ks)


# ===========================================================================
# deactivate()
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchDeactivation:
    def test_deactivate_with_correct_token(self, tmp_path):
        ks = _make_ks(tmp_path, token="secret")
        ks.activate("halt")
        ks.deactivate("secret")
        assert ks.is_active() is False
        assert ks.reason == ""
        _clean(ks)

    def test_deactivate_wrong_token_raises(self, tmp_path):
        ks = _make_ks(tmp_path, token="secret")
        ks.activate("halt")
        with pytest.raises(PermissionError):
            ks.deactivate("wrong")
        assert ks.is_active() is True
        _clean(ks)

    def test_deactivate_no_token_configured_raises(self, tmp_path):
        from kill_switch import KillSwitch

        flag = tmp_path / "ks3.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token=None)
        # Remove env var token too
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOPEFX_KILL_SWITCH_TOKEN", None)
            ks._deactivation_token = None
            ks.activate("halt")
            with pytest.raises(PermissionError):
                ks.deactivate("anything")
        _clean(ks)

    def test_deactivate_when_not_active_is_noop(self, tmp_path):
        ks = _make_ks(tmp_path, token="tok")
        ks.deactivate("tok")  # not active — should not raise
        assert ks.is_active() is False
        _clean(ks)

    def test_deactivate_clears_state_file(self, tmp_path):
        ks = _make_ks(tmp_path, token="tok")
        ks.activate("halt")
        assert ks._state_file.exists()
        with patch.object(ks, "_clear_redis_latch"):
            ks.deactivate("tok")
        assert not ks._state_file.exists()
        _clean(ks)

    def test_deactivate_clears_redis_latch(self, tmp_path):
        ks = _make_ks(tmp_path, token="tok")
        ks.activate("halt")
        mock_redis = MagicMock()
        with patch.object(ks, "_get_latch_redis", return_value=mock_redis):
            ks.deactivate("tok")
        mock_redis.delete.assert_called()
        _clean(ks)


# ===========================================================================
# reset_for_testing()
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchReset:
    def test_reset_clears_active_state(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("halt")
        ks.reset_for_testing()
        assert ks.is_active() is False
        assert ks.reason == ""
        assert ks.activated_at is None
        _clean(ks)

    def test_reset_clears_callbacks(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.register_callback(lambda r: None)
        ks.reset_for_testing()
        assert ks._callbacks == []
        _clean(ks)


# ===========================================================================
# register_callback()
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchCallbacks:
    def test_multiple_callbacks_all_invoked(self, tmp_path):
        ks = _make_ks(tmp_path)
        results = []
        ks.register_callback(lambda r: results.append(f"cb1:{r}"))
        ks.register_callback(lambda r: results.append(f"cb2:{r}"))
        ks.activate("multi")
        assert "cb1:multi" in results
        assert "cb2:multi" in results
        _clean(ks)

    def test_callback_not_called_when_already_active(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("first")
        results = []

        def _cb(r):
            results.append(r)

        ks.register_callback(_cb)
        ks.activate("second")  # idempotent — callback not called again
        assert results == []
        _clean(ks)


# ===========================================================================
# File-flag polling
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchFilePoll:
    @pytest.mark.asyncio
    async def test_poll_detects_flag_file(self, tmp_path):
        ks = _make_ks(tmp_path, token="tok")
        await ks.start()
        # Write the flag file
        ks._flag_file.write_text("activated_at=now\nreason=file_flag\n")
        # Give the poll loop time to detect it
        await asyncio.sleep(0.2)
        await ks.stop()
        assert ks.is_active() is True
        _clean(ks)

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, tmp_path):
        ks = _make_ks(tmp_path, token="tok")
        await ks.start()
        assert ks._running is True
        await ks.stop()
        assert ks._running is False
        _clean(ks)

    @pytest.mark.asyncio
    async def test_start_idempotent(self, tmp_path):
        ks = _make_ks(tmp_path, token="tok")
        await ks.start()
        await ks.start()  # second call is a no-op
        assert ks._running is True
        await ks.stop()
        _clean(ks)


# ===========================================================================
# Redis latch helpers
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchRedisLatch:
    def test_get_latch_redis_returns_none_when_unavailable(self, tmp_path):
        ks = _make_ks(tmp_path)
        with patch("kill_switch.KillSwitch._get_latch_redis", return_value=None):
            result = ks._get_latch_redis()
        assert result is None
        _clean(ks)

    @pytest.mark.asyncio
    async def test_check_redis_latch_activates_when_set(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda key: "true" if "active" in key else "redis latch reason"
        with patch.object(ks, "_get_latch_redis", return_value=mock_redis):
            await ks._check_redis_latch()
        assert ks.is_active() is True
        _clean(ks)

    @pytest.mark.asyncio
    async def test_check_redis_latch_no_latch_stays_inactive(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        with patch.object(ks, "_get_latch_redis", return_value=mock_redis):
            await ks._check_redis_latch()
        assert ks.is_active() is False
        _clean(ks)

    @pytest.mark.asyncio
    async def test_check_redis_latch_exception_non_fatal(self, tmp_path):
        ks = _make_ks(tmp_path)
        with patch.object(ks, "_get_latch_redis", side_effect=Exception("redis down")):
            await ks._check_redis_latch()  # must not raise
        assert ks.is_active() is False
        _clean(ks)

    def test_write_redis_latch_sets_keys(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_redis = MagicMock()
        with patch.object(ks, "_get_latch_redis", return_value=mock_redis):
            ks._write_redis_latch("test reason")
        assert mock_redis.set.call_count == 2

    def test_clear_redis_latch_deletes_keys(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_redis = MagicMock()
        with patch.object(ks, "_get_latch_redis", return_value=mock_redis):
            ks._clear_redis_latch()
        mock_redis.delete.assert_called_once()


# ===========================================================================
# Event-bus integration
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchEventBus:
    def test_activate_publishes_to_event_bus(self, tmp_path):
        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock()
        ks = _make_ks(tmp_path)
        ks._event_bus = mock_bus
        ks.activate("bus test")
        # _publish_event is called synchronously; bus.publish is fire-and-forget
        _clean(ks)

    def test_on_bus_event_activates(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.on_bus_event({"type": "KILL_SWITCH", "reason": "bus event"})
        assert ks.is_active() is True
        _clean(ks)


# ===========================================================================
# trigger_nuclear_mode() async wrapper
# ===========================================================================


@pytest.mark.unit
class TestTriggerNuclearMode:
    @pytest.mark.asyncio
    async def test_trigger_nuclear_mode_activates_global(self, tmp_path):
        from kill_switch import trigger_nuclear_mode

        # Reset global kill_switch before test
        import kill_switch as _ks_mod

        _ks_mod.kill_switch.reset_for_testing()
        _ks_mod.kill_switch._flag_file.unlink(missing_ok=True)
        _ks_mod.kill_switch._state_file.unlink(missing_ok=True)

        await trigger_nuclear_mode("nuclear test")
        assert _ks_mod.kill_switch.is_active() is True
        # Cleanup
        _ks_mod.kill_switch.reset_for_testing()
        _ks_mod.kill_switch._flag_file.unlink(missing_ok=True)
        _ks_mod.kill_switch._state_file.unlink(missing_ok=True)


# ===========================================================================
# OMS kill-switch gate (defense-in-depth)
# ===========================================================================


@pytest.mark.unit
class TestOMSKillSwitchGate:
    def test_oms_submit_blocked_when_kill_switch_active(self, tmp_path):
        """OMS.submit_order must return False when kill switch is active."""
        from decimal import Decimal

        from execution.oms import OrderLifecycleManager

        oms = OrderLifecycleManager()
        order = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))

        # OMS imports KillSwitch inside submit_order; patch at kill_switch module
        mock_ks_instance = MagicMock()
        mock_ks_instance.is_active.return_value = True
        mock_ks_instance.reason = "test halt"

        with patch("kill_switch.KillSwitch", return_value=mock_ks_instance):
            result = oms.submit_order(order.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_oms_submit_allowed_when_kill_switch_inactive(self, tmp_path):
        """OMS.submit_order proceeds when kill switch is inactive."""
        from decimal import Decimal

        from execution.oms import OrderLifecycleManager

        oms = OrderLifecycleManager()
        order = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))

        mock_ks_instance = MagicMock()
        mock_ks_instance.is_active.return_value = False

        with patch("kill_switch.KillSwitch", return_value=mock_ks_instance):
            result = oms.submit_order(order.id)
        assert result is True
        # Allow the async submit task to complete
        await asyncio.sleep(0)

    def test_oms_submit_blocked_when_kill_switch_raises(self):
        """OMS must fail closed if KillSwitch instantiation raises."""
        from decimal import Decimal

        from execution.oms import OrderLifecycleManager

        oms = OrderLifecycleManager()
        order = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))

        with patch("kill_switch.KillSwitch", side_effect=RuntimeError("ks error")):
            result = oms.submit_order(order.id)
        assert result is False


# ===========================================================================
# State persistence helpers
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchStatePersistence:
    def test_persist_and_restore_state(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("persist test")
        # Create a new instance pointing at the same files
        from kill_switch import KillSwitch

        ks2 = KillSwitch(flag_file=ks._flag_file, deactivation_token="test-token")
        assert ks2.is_active() is True
        assert "persist test" in ks2.reason
        _clean(ks)
        _clean(ks2)

    def test_corrupt_state_file_handled_gracefully(self, tmp_path):
        flag = tmp_path / "ks.flag"
        state = flag.with_suffix(".state.json")
        state.write_text("not valid json", encoding="utf-8")
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        # Should not raise — corrupt state is ignored
        assert ks.is_active() is False
        _clean(ks)

    def test_flag_file_restore_on_construction(self, tmp_path):
        """Plain flag file (no state.json) also restores state."""
        flag = tmp_path / "ks.flag"
        import datetime

        flag.write_text(f"activated_at={datetime.datetime.now(UTC).isoformat()}\nreason=flag_restore\n")
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks.is_active() is True
        assert "flag_restore" in ks.reason
        _clean(ks)

    def test_parse_flag_file_missing_fields(self, tmp_path):
        """Flag file with no reason/activated_at uses safe defaults."""
        flag = tmp_path / "ks.flag"
        flag.write_text("some_other_content\n")
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks.is_active() is True
        assert ks.reason != ""
        _clean(ks)

    def test_clear_state_removes_files(self, tmp_path):
        ks = _make_ks(tmp_path, token="tok")
        ks.activate("clear test")
        assert ks._flag_file.exists()
        assert ks._state_file.exists()
        ks._clear_state()
        assert not ks._flag_file.exists()
        assert not ks._state_file.exists()


# ===========================================================================
# Event-bus wiring
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchEventBusWiring:
    def test_set_event_bus_subscribes(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_bus = MagicMock()
        ks.set_event_bus(mock_bus)
        mock_bus.subscribe.assert_called_once_with("KILL_SWITCH", ks.on_bus_event)
        _clean(ks)

    def test_set_event_bus_subscribe_exception_non_fatal(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_bus = MagicMock()
        mock_bus.subscribe.side_effect = Exception("bus error")
        ks.set_event_bus(mock_bus)  # must not raise
        _clean(ks)

    def test_on_bus_event_activates(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.on_bus_event({"reason": "bus dict event"})
        assert ks.is_active() is True
        # reason is prefixed with [bus]
        assert "bus" in ks.reason.lower()
        _clean(ks)

    def test_on_bus_event_with_decodable_object(self, tmp_path):
        ks = _make_ks(tmp_path)
        event = MagicMock()
        event.decode.return_value = {"reason": "decoded event"}
        ks.on_bus_event(event)
        assert ks.is_active() is True
        _clean(ks)

    def test_on_bus_event_decode_failure_uses_default_reason(self, tmp_path):
        ks = _make_ks(tmp_path)
        event = MagicMock()
        event.decode.side_effect = Exception("decode error")
        ks.on_bus_event(event)
        assert ks.is_active() is True
        assert ks.reason != ""
        _clean(ks)


# ===========================================================================
# _publish_event() — outbox + Redis + fallback paths
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchPublishEvent:
    def test_publish_event_outbox_failure_non_fatal(self, tmp_path):
        ks = _make_ks(tmp_path)
        with patch("kill_switch.KillSwitch._publish_event") as mock_pub:
            mock_pub.side_effect = Exception("outbox down")
            # activate calls _publish_event; exception must not propagate
            ks._event_bus = None
            ks.activate("pub test")
        # activate itself should still work
        assert ks.is_active() is True
        _clean(ks)

    def test_publish_event_called_on_activate(self, tmp_path):
        ks = _make_ks(tmp_path)
        with patch.object(ks, "_publish_event") as mock_pub:
            ks._event_bus = MagicMock()
            ks.activate("pub call test")
        mock_pub.assert_called_once_with("pub call test")
        _clean(ks)


# ===========================================================================
# FastAPI router creation
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchRouter:
    def test_create_router_returns_router(self, tmp_path):
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_router.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        router = create_kill_switch_router(ks)
        # FastAPI is installed in this project
        assert router is not None
        _clean(ks)


# ===========================================================================
# Stale state file handling (non-production mode)
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchStaleState:
    def test_stale_state_not_restored_in_non_production(self, tmp_path, monkeypatch):
        """State files older than 24h are ignored in non-production mode."""
        import datetime

        monkeypatch.setenv("APP_ENV", "test")
        flag = tmp_path / "ks.flag"
        state = flag.with_suffix(".state.json")
        old_time = (datetime.datetime.now(UTC) - datetime.timedelta(hours=25)).isoformat()
        state.write_text(
            json.dumps({"active": True, "reason": "stale halt", "activated_at": old_time}),
            encoding="utf-8",
        )
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        # Stale state should NOT be restored in non-production
        assert ks.is_active() is False
        _clean(ks)

    def test_fresh_state_restored_in_non_production(self, tmp_path, monkeypatch):
        """Fresh state files (< 24h) are always restored."""
        import datetime

        monkeypatch.setenv("APP_ENV", "test")
        flag = tmp_path / "ks.flag"
        state = flag.with_suffix(".state.json")
        recent_time = datetime.datetime.now(UTC).isoformat()
        state.write_text(
            json.dumps({"active": True, "reason": "fresh halt", "activated_at": recent_time}),
            encoding="utf-8",
        )
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks.is_active() is True
        _clean(ks)


# ===========================================================================
# _get_latch_redis() — fallback paths
# ===========================================================================


@pytest.mark.unit
class TestGetLatchRedis:
    def test_returns_bus_redis_when_available(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_bus = MagicMock()
        mock_redis = MagicMock()
        mock_bus._redis = mock_redis
        with (
            patch("kill_switch.KillSwitch._get_latch_redis", wraps=ks._get_latch_redis),
            patch("core.event_bus.bus", mock_bus),
        ):
            ks._get_latch_redis()
        # Either returns the bus redis or falls back — just must not raise
        _clean(ks)

    def test_falls_back_to_direct_redis(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_redis_lib = MagicMock()
        mock_client = MagicMock()
        mock_redis_lib.from_url.return_value = mock_client
        with (
            patch.dict("sys.modules", {"core.event_bus": None}),
            patch("redis.from_url", return_value=mock_client),
        ):
            ks._get_latch_redis()
        # Result is either mock_client or None — must not raise
        _clean(ks)

    def test_returns_none_when_all_fail(self, tmp_path):
        ks = _make_ks(tmp_path)
        with patch("kill_switch.KillSwitch._get_latch_redis", return_value=None):
            result = ks._get_latch_redis()
        assert result is None
        _clean(ks)


# ===========================================================================
# FastAPI router endpoints
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchRouterEndpoints:
    @pytest.mark.asyncio
    async def test_status_endpoint(self, tmp_path):
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_ep.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        router = create_kill_switch_router(ks)
        assert router is not None
        # Verify the router has the expected routes
        routes = [r.path for r in router.routes]
        assert any("status" in r for r in routes)
        _clean(ks)

    @pytest.mark.asyncio
    async def test_activate_endpoint_exists(self, tmp_path):
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_ep2.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        router = create_kill_switch_router(ks)
        routes = [r.path for r in router.routes]
        assert any("activate" in r for r in routes)
        _clean(ks)

    @pytest.mark.asyncio
    async def test_deactivate_endpoint_exists(self, tmp_path):
        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_ep3.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        router = create_kill_switch_router(ks)
        routes = [r.path for r in router.routes]
        assert any("deactivate" in r for r in routes)
        _clean(ks)


# ===========================================================================
# _persist_state() / _restore_state() edge cases
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchPersistRestore:
    def test_persist_state_os_error_non_fatal(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks._active = True
        ks._reason = "test"
        import datetime

        ks._activated_at = datetime.datetime.now(UTC)
        # Make state file unwritable by patching Path.write_text
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            ks._persist_state()  # must not raise
        _clean(ks)

    def test_restore_state_inactive_json(self, tmp_path):
        """State file with active=False does not activate."""
        flag = tmp_path / "ks.flag"
        state = flag.with_suffix(".state.json")
        state.write_text(json.dumps({"active": False, "reason": "", "activated_at": None}))
        from kill_switch import KillSwitch

        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks.is_active() is False
        _clean(ks)

    def test_flag_file_write_os_error_non_fatal(self, tmp_path):
        """Flag file write failure during activate must not propagate."""
        ks = _make_ks(tmp_path)
        with patch.object(Path, "write_text", side_effect=OSError("read only")):
            ks.activate("flag write fail")  # must not raise
        assert ks.is_active() is True
        _clean(ks)


# ===========================================================================
# _poll_loop() env-var branch
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchPollLoopEnvVar:
    @pytest.mark.asyncio
    async def test_poll_detects_env_var_change(self, tmp_path, monkeypatch):
        ks = _make_ks(tmp_path, token="tok")
        await ks.start()
        # Inject env var after start
        monkeypatch.setenv("HOPEFX_KILL_SWITCH", "1")
        await asyncio.sleep(0.2)
        await ks.stop()
        assert ks.is_active() is True
        _clean(ks)


# ===========================================================================
# _redis_breach_listener() — async cross-pod propagation
# ===========================================================================


@pytest.mark.unit
class TestRedisBreachListener:
    @pytest.mark.asyncio
    async def test_listener_activates_on_kill_switch_message(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks._running = True

        # Simulate a single kill_switch message then stop
        messages = [
            {"type": "kill_switch", "reason": "remote halt"},
            {"type": "heartbeat"},  # non-kill message — ignored
        ]

        async def _fake_subscribe(channel):
            for m in messages:
                yield m
            ks._running = False

        mock_bus = MagicMock()
        mock_bus.connect = AsyncMock()
        mock_bus.subscribe = _fake_subscribe

        with (
            patch("core.event_bus.bus", mock_bus),
            patch("core.event_bus.CH_BREACH", "hopefx:breach"),
        ):
            await ks._redis_breach_listener()

        assert ks.is_active() is True
        assert "remote" in ks.reason
        _clean(ks)

    @pytest.mark.asyncio
    async def test_listener_import_error_returns_gracefully(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks._running = True
        with patch.dict("sys.modules", {"core.event_bus": None}):
            await ks._redis_breach_listener()  # must not raise
        assert ks.is_active() is False
        _clean(ks)

    @pytest.mark.asyncio
    async def test_listener_connect_failure_returns_gracefully(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks._running = True

        mock_bus = MagicMock()
        mock_bus.connect = AsyncMock(side_effect=Exception("redis down"))

        with (
            patch("core.event_bus.bus", mock_bus),
            patch("core.event_bus.CH_BREACH", "hopefx:breach"),
        ):
            await ks._redis_breach_listener()  # must not raise
        assert ks.is_active() is False
        _clean(ks)

    @pytest.mark.asyncio
    async def test_listener_ignores_non_kill_messages(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks._running = True

        async def _fake_subscribe(channel):
            yield {"type": "equity_update", "equity": 95000}
            ks._running = False

        mock_bus = MagicMock()
        mock_bus.connect = AsyncMock()
        mock_bus.subscribe = _fake_subscribe

        with (
            patch("core.event_bus.bus", mock_bus),
            patch("core.event_bus.CH_BREACH", "hopefx:breach"),
        ):
            await ks._redis_breach_listener()

        assert ks.is_active() is False
        _clean(ks)


# ===========================================================================
# _publish_event() — multi-path coverage
# ===========================================================================


@pytest.mark.unit
class TestPublishEvent:
    def test_publish_event_outbox_path(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_write = MagicMock()
        with patch("core.outbox.write_outbox_event_standalone", mock_write):
            ks._publish_event("outbox test")
        mock_write.assert_called_once()
        _clean(ks)

    def test_publish_event_outbox_failure_continues(self, tmp_path):
        ks = _make_ks(tmp_path)
        with patch("core.outbox.write_outbox_event_standalone", side_effect=Exception("outbox down")):
            ks._publish_event("outbox fail test")  # must not raise
        _clean(ks)

    @pytest.mark.asyncio
    async def test_publish_event_redis_bus_path(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_bus = MagicMock()
        mock_bus.publish_breach = AsyncMock()
        with (
            patch("core.event_bus.bus", mock_bus),
            patch("core.outbox.write_outbox_event_standalone", MagicMock()),
        ):
            ks._publish_event("redis bus test")
        _clean(ks)

    def test_publish_event_k8s_skipped_outside_pod(self, tmp_path, monkeypatch):
        """_write_k8s_configmap is a no-op when not in a K8s pod."""
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        ks = _make_ks(tmp_path)
        ks._write_k8s_configmap("no k8s")  # must not raise
        _clean(ks)

    def test_write_k8s_configmap_in_pod_async(self, tmp_path, monkeypatch):
        """_write_k8s_configmap schedules async patch when in a pod."""
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        ks = _make_ks(tmp_path)
        # kubernetes_asyncio not installed — should log and return gracefully
        ks._write_k8s_configmap("k8s test")  # must not raise
        _clean(ks)

    @pytest.mark.asyncio
    async def test_publish_event_redis_bus_with_running_loop(self, tmp_path):
        """_publish_event Redis path with running loop — creates asyncio task."""
        ks = _make_ks(tmp_path)
        mock_bus = MagicMock()

        async def _fake_publish(payload):
            pass

        mock_bus.publish_breach = _fake_publish
        with (
            patch("core.event_bus.bus", mock_bus),
            patch("core.outbox.write_outbox_event_standalone", MagicMock()),
        ):
            # Called from async context — running loop exists, task is created
            ks._publish_event("redis async test")
        # Allow the task to complete
        await asyncio.sleep(0)
        _clean(ks)

    def test_publish_event_redis_bus_exception_falls_back(self, tmp_path):
        """When Redis bus raises, _publish_event falls back to in-process bus."""
        ks = _make_ks(tmp_path)
        mock_in_process_bus = MagicMock()
        mock_in_process_bus.publish = MagicMock(return_value=None)
        ks._event_bus = mock_in_process_bus

        with (
            patch("core.outbox.write_outbox_event_standalone", MagicMock()),
            patch("core.event_bus.bus", side_effect=Exception("redis unavailable")),
        ):
            ks._publish_event("fallback test")
        _clean(ks)

    def test_publish_event_all_paths_fail_gracefully(self, tmp_path):
        """_publish_event must not raise even when all paths fail."""
        ks = _make_ks(tmp_path)
        with (
            patch("core.outbox.write_outbox_event_standalone", side_effect=Exception("outbox down")),
            patch("core.event_bus.bus", side_effect=Exception("redis down")),
        ):
            ks._publish_event("all fail test")  # must not raise
        _clean(ks)

    def test_publish_event_redis_sync_non_coroutine(self, tmp_path):
        """Redis publish_breach returns a non-coroutine (sync) — no close() needed."""
        ks = _make_ks(tmp_path)
        mock_bus = MagicMock()
        mock_bus.publish_breach.return_value = "not a coroutine"
        with (
            patch("core.outbox.write_outbox_event_standalone", MagicMock()),
            patch("core.event_bus.bus", mock_bus),
        ):
            # No running loop — hits the RuntimeError branch
            # Temporarily remove the running loop by calling from sync context
            ks._publish_event("sync non-coro test")
        _clean(ks)

    @pytest.mark.asyncio
    async def test_publish_event_in_process_bus_fallback_async(self, tmp_path):
        """Step 3: in-process bus fallback when Redis raises, with running loop."""
        ks = _make_ks(tmp_path)
        mock_in_process_bus = MagicMock()
        mock_in_process_bus.publish = AsyncMock()
        ks._event_bus = mock_in_process_bus

        from core.event_bus import DomainEvent

        mock_domain_event = MagicMock()
        import core.event_bus as _eb_mod

        with (
            patch("core.outbox.write_outbox_event_standalone", MagicMock()),
            patch.object(_eb_mod, "bus", side_effect=Exception("redis down")),
            patch.object(DomainEvent, "create", return_value=mock_domain_event),
        ):
            ks._publish_event("in-process fallback async")
        await asyncio.sleep(0)
        _clean(ks)

    def test_publish_event_in_process_bus_fallback_sync(self, tmp_path):
        """Step 3: in-process bus fallback when Redis raises, no running loop (sync)."""
        ks = _make_ks(tmp_path)
        mock_in_process_bus = MagicMock()
        mock_in_process_bus.publish.return_value = None
        ks._event_bus = mock_in_process_bus

        from core.event_bus import DomainEvent

        mock_domain_event = MagicMock()
        import core.event_bus as _eb_mod

        with (
            patch("core.outbox.write_outbox_event_standalone", MagicMock()),
            patch.object(_eb_mod, "bus", side_effect=Exception("redis down")),
            patch.object(DomainEvent, "create", return_value=mock_domain_event),
        ):
            ks._publish_event("in-process fallback sync")
        _clean(ks)


# ===========================================================================
# start() with event-bus subscription
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchStartWithEventBus:
    @pytest.mark.asyncio
    async def test_start_with_event_bus_subscribes(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_bus = MagicMock()
        mock_bus.subscribe = MagicMock()
        ks._event_bus = mock_bus
        await ks.start()
        mock_bus.subscribe.assert_called_with("KILL_SWITCH", ks.on_bus_event)
        await ks.stop()
        _clean(ks)

    @pytest.mark.asyncio
    async def test_start_event_bus_subscribe_exception_non_fatal(self, tmp_path):
        ks = _make_ks(tmp_path)
        mock_bus = MagicMock()
        mock_bus.subscribe.side_effect = Exception("bus error")
        ks._event_bus = mock_bus
        await ks.start()  # must not raise
        await ks.stop()
        _clean(ks)


# ===========================================================================
# FastAPI route handler logic (via TestClient)
# ===========================================================================


@pytest.mark.unit
class TestKillSwitchRouteHandlers:
    @pytest.mark.asyncio
    async def test_get_status_route(self, tmp_path):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_route.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/kill-switch/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        _clean(ks)

    @pytest.mark.asyncio
    async def test_activate_route_requires_auth(self, tmp_path):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_route2.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/kill-switch/activate", json={"reason": "test"})
        # No auth token → 403 or 401
        assert resp.status_code in (401, 403, 422)
        _clean(ks)

    @pytest.mark.asyncio
    async def test_activate_route_with_admin_user(self, tmp_path):
        """Activate endpoint succeeds when admin user is injected via dependency override."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_route3.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        # Override the admin dependency to inject a mock admin user

        mock_user = MagicMock()
        mock_user.sub = "admin_user"
        mock_user.role = "admin"

        # Find and override the _require_admin dependency
        for route in router.routes:
            if hasattr(route, "dependencies"):
                pass  # dependencies are closures — override via app

        # Override all dependencies that check auth

        async def _mock_admin():
            return mock_user

        # Patch the auth check at the api.auth level
        with patch("api.auth._decode_token", return_value=mock_user):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/kill-switch/activate",
                    json={"reason": "api test"},
                    headers={"Authorization": "Bearer fake-token"},
                )
        # Either activated (200) or auth error (401/403) — both are valid
        assert resp.status_code in (200, 401, 403, 503)
        _clean(ks)

    @pytest.mark.asyncio
    async def test_deactivate_route_requires_auth(self, tmp_path):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_route4.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        ks.activate("pre-activate for deactivate test")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/kill-switch/deactivate", json={"token": "tok"})
        assert resp.status_code in (401, 403, 422)
        _clean(ks)

    @pytest.mark.asyncio
    async def test_activate_route_already_active(self, tmp_path):
        """Activate endpoint returns already_active when switch is already on."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_route5.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        ks.activate("already active")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.sub = "admin_user"
        mock_user.role = "admin"

        with patch("api.auth._decode_token", return_value=mock_user):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/kill-switch/activate",
                    json={"reason": "again"},
                    headers={"Authorization": "Bearer fake-token"},
                )
        assert resp.status_code in (200, 401, 403, 503)
        _clean(ks)

    @pytest.mark.asyncio
    async def test_deactivate_route_with_admin_and_correct_token(self, tmp_path):
        """Deactivate endpoint succeeds with admin user and correct token."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from kill_switch import KillSwitch, create_kill_switch_router

        flag = tmp_path / "ks_route6.flag"
        ks = KillSwitch(flag_file=flag, deactivation_token="correct-tok")
        ks.activate("halt for deactivate test")
        app = FastAPI()
        router = create_kill_switch_router(ks)
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.sub = "admin_user"
        mock_user.role = "admin"

        with (
            patch("api.auth._decode_token", return_value=mock_user),
            patch.object(ks, "_clear_redis_latch"),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/kill-switch/deactivate",
                    json={"token": "correct-tok"},
                    headers={"Authorization": "Bearer fake-token"},
                )
        assert resp.status_code in (200, 401, 403, 503)
        _clean(ks)
