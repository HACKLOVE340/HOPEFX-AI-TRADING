# HOPEFX-AI-TRADING
# Tests for kill_switch.py — real unit tests, no mocks/stubs
"""Covers activate, deactivate, callbacks, status, flag file, token, router."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

UTC = timezone.utc


def _fresh_ks(**kwargs):
    """Return a fresh KillSwitch with no persisted state."""
    from kill_switch import KillSwitch

    ks = KillSwitch(**kwargs)
    ks.reset_for_testing()
    return ks


# ── basic activate / deactivate ───────────────────────────────────────────────


class TestKillSwitchActivate:
    def test_initially_inactive(self):
        ks = _fresh_ks()
        assert ks.is_active() is False

    def test_activate_sets_active(self):
        ks = _fresh_ks()
        ks.activate("unit test")
        assert ks.is_active() is True
        ks.reset_for_testing()

    def test_activate_stores_reason(self):
        ks = _fresh_ks()
        ks.activate("drawdown breach")
        assert ks.reason == "drawdown breach"
        ks.reset_for_testing()

    def test_activate_stores_timestamp(self):
        ks = _fresh_ks()
        before = datetime.now(UTC)
        ks.activate("test")
        assert ks.activated_at is not None
        assert ks.activated_at >= before
        ks.reset_for_testing()

    def test_activate_idempotent(self):
        ks = _fresh_ks()
        ks.activate("first")
        ks.activate("second")  # should not overwrite
        assert ks.reason == "first"
        ks.reset_for_testing()

    def test_deactivate_requires_token(self):
        # deactivate() always requires a configured token — no token = PermissionError
        ks = _fresh_ks()
        ks.activate("test")
        with pytest.raises(PermissionError):
            ks.deactivate()
        ks.reset_for_testing()

    def test_deactivate_with_token_clears_reason(self):
        from kill_switch import KillSwitch

        ks = KillSwitch(deactivation_token="tok")
        ks.reset_for_testing()
        ks.activate("test")
        ks.deactivate(token="tok")
        assert ks.reason == ""
        ks.reset_for_testing()

    def test_deactivate_with_token_clears_activated_at(self):
        from kill_switch import KillSwitch

        ks = KillSwitch(deactivation_token="tok")
        ks.reset_for_testing()
        ks.activate("test")
        ks.deactivate(token="tok")
        assert ks.activated_at is None
        ks.reset_for_testing()

    def test_deactivate_when_inactive_is_noop(self):
        ks = _fresh_ks()
        ks.deactivate()  # should not raise
        assert ks.is_active() is False

    def test_reset_for_testing_clears_state(self):
        ks = _fresh_ks()
        ks.activate("test")
        ks.reset_for_testing()
        assert ks.is_active() is False
        assert ks.reason == ""
        assert ks.activated_at is None


# ── deactivation token ────────────────────────────────────────────────────────


class TestKillSwitchToken:
    def test_wrong_token_raises(self):
        from kill_switch import KillSwitch

        ks = KillSwitch(deactivation_token="secret")
        ks.reset_for_testing()
        ks.activate("locked")
        with pytest.raises(PermissionError):
            ks.deactivate(token="wrong")
        ks.reset_for_testing()

    def test_correct_token_deactivates(self):
        from kill_switch import KillSwitch

        ks = KillSwitch(deactivation_token="secret")
        ks.reset_for_testing()
        ks.activate("locked")
        ks.deactivate(token="secret")
        assert ks.is_active() is False
        ks.reset_for_testing()

    def test_no_token_configured_raises_permission_error(self):
        # Without a configured token, deactivation is always refused
        ks = _fresh_ks()
        ks.activate("test")
        with pytest.raises(PermissionError):
            ks.deactivate(token=None)
        ks.reset_for_testing()


# ── callbacks ─────────────────────────────────────────────────────────────────


class TestKillSwitchCallbacks:
    def test_callback_called_on_activate(self):
        ks = _fresh_ks()
        received = []
        ks.register_callback(received.append)
        ks.activate("callback test")
        assert received == ["callback test"]
        ks.reset_for_testing()

    def test_multiple_callbacks_all_called(self):
        ks = _fresh_ks()
        log1, log2 = [], []
        ks.register_callback(log1.append)
        ks.register_callback(log2.append)
        ks.activate("multi")
        assert log1 == ["multi"]
        assert log2 == ["multi"]
        ks.reset_for_testing()

    def test_callback_exception_does_not_crash(self):
        ks = _fresh_ks()

        def bad_cb(reason):
            raise RuntimeError("callback error")

        ks.register_callback(bad_cb)
        ks.activate("test")  # should not raise
        ks.reset_for_testing()

    def test_callback_not_called_when_already_active(self):
        ks = _fresh_ks()
        received = []
        ks.activate("first")
        ks.register_callback(received.append)
        ks.activate("second")  # idempotent — callback not called again
        assert received == []
        ks.reset_for_testing()

    def test_reset_clears_callbacks(self):
        ks = _fresh_ks()
        received = []
        ks.register_callback(received.append)
        ks.reset_for_testing()
        ks.activate("after reset")
        assert received == []
        ks.reset_for_testing()


# ── status ────────────────────────────────────────────────────────────────────


class TestKillSwitchStatus:
    def test_status_inactive(self):
        ks = _fresh_ks()
        s = ks.status()
        assert s["active"] is False
        assert s["reason"] == ""

    def test_status_active(self):
        ks = _fresh_ks()
        ks.activate("status test")
        s = ks.status()
        assert s["active"] is True
        assert s["reason"] == "status test"
        assert s["activated_at"] is not None
        ks.reset_for_testing()

    def test_status_has_required_keys(self):
        ks = _fresh_ks()
        s = ks.status()
        for key in ("active", "reason", "activated_at", "flag_file"):
            assert key in s

    def test_status_token_configured_flag(self):
        from kill_switch import KillSwitch

        ks = KillSwitch(deactivation_token="tok")
        ks.reset_for_testing()
        s = ks.status()
        assert s["deactivation_token_configured"] is True
        ks.reset_for_testing()

    def test_status_no_token_flag(self, monkeypatch):
        monkeypatch.delenv("HOPEFX_KILL_SWITCH_TOKEN", raising=False)
        ks = _fresh_ks()
        s = ks.status()
        assert s["deactivation_token_configured"] is False


# ── flag file ─────────────────────────────────────────────────────────────────


class TestKillSwitchFlagFile:
    def test_flag_file_created_on_activate(self):
        with tempfile.TemporaryDirectory() as d:
            flag = Path(d) / "kill.flag"
            from kill_switch import KillSwitch

            ks = KillSwitch(flag_file=flag)
            ks.reset_for_testing()
            ks.activate("flag test")
            assert flag.exists()
            ks.reset_for_testing()

    def test_flag_file_contains_reason(self):
        with tempfile.TemporaryDirectory() as d:
            flag = Path(d) / "kill.flag"
            from kill_switch import KillSwitch

            ks = KillSwitch(flag_file=flag)
            ks.reset_for_testing()
            ks.activate("flag reason")
            content = flag.read_text()
            assert "flag reason" in content
            ks.reset_for_testing()

    def test_no_flag_file_by_default(self):
        ks = _fresh_ks()
        s = ks.status()
        # flag_file_exists should be False when no flag file configured
        assert s.get("flag_file_exists") is False

    def test_status_shows_flag_file_path(self):
        with tempfile.TemporaryDirectory() as d:
            flag = Path(d) / "kill.flag"
            from kill_switch import KillSwitch

            ks = KillSwitch(flag_file=flag)
            ks.reset_for_testing()
            s = ks.status()
            assert str(flag) in str(s["flag_file"])
            ks.reset_for_testing()


# ── event bus integration ─────────────────────────────────────────────────────


class TestKillSwitchEventBus:
    def test_set_event_bus(self):
        ks = _fresh_ks()

        class FakeBus:
            published = []

            def publish(self, event):
                self.published.append(event)

        bus = FakeBus()
        ks.set_event_bus(bus)
        assert ks._event_bus is bus

    def test_on_bus_event_activates(self):
        ks = _fresh_ks()

        class KillEvent:
            type = "kill_switch"
            reason = "bus triggered"

        ks.on_bus_event(KillEvent())
        assert ks.is_active() is True
        ks.reset_for_testing()

    def test_on_bus_event_always_activates(self):
        # on_bus_event activates regardless of event type — caller filters
        ks = _fresh_ks()

        class AnyEvent:
            pass

        ks.on_bus_event(AnyEvent())
        assert ks.is_active() is True
        ks.reset_for_testing()


# ── router factory ────────────────────────────────────────────────────────────


class TestCreateKillSwitchRouter:
    def test_router_created(self):
        from kill_switch import create_kill_switch_router

        ks = _fresh_ks()
        router = create_kill_switch_router(ks)
        assert router is not None

    def test_router_has_routes(self):
        from kill_switch import create_kill_switch_router

        ks = _fresh_ks()
        router = create_kill_switch_router(ks)
        routes = [r.path for r in router.routes]
        assert len(routes) > 0

    def test_router_has_status_route(self):
        from kill_switch import create_kill_switch_router

        ks = _fresh_ks()
        router = create_kill_switch_router(ks)
        paths = [r.path for r in router.routes]
        assert any("status" in p for p in paths)

    def test_router_has_activate_route(self):
        from kill_switch import create_kill_switch_router

        ks = _fresh_ks()
        router = create_kill_switch_router(ks)
        paths = [r.path for r in router.routes]
        assert any("activate" in p for p in paths)

    def test_router_has_deactivate_route(self):
        from kill_switch import create_kill_switch_router

        ks = _fresh_ks()
        router = create_kill_switch_router(ks)
        paths = [r.path for r in router.routes]
        assert any("deactivate" in p for p in paths)
