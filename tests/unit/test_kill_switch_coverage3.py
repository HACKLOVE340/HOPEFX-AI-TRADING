# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0
"""
tests/unit/test_kill_switch_coverage3.py
Targeted coverage for kill_switch.py uncovered branches:
- env-var activation on construction
- flag file write/read
- _persist_state / _restore_state
- status() dict
- set_event_bus / on_bus_event
- stop() coroutine
- trigger_nuclear_mode
- create_kill_switch_router (FastAPI)
- _check_broker_cod branches
- _broker_cancel_all branches
"""
from __future__ import annotations

import asyncio



def _fresh_ks(**kwargs):
    from kill_switch import KillSwitch
    ks = KillSwitch(**kwargs)
    ks.reset_for_testing()
    return ks


# ── env-var activation on construction ───────────────────────────────────────


class TestEnvVarActivation:
    def test_env_var_activates_on_construction(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOPEFX_KILL_SWITCH", "1")
        from kill_switch import KillSwitch
        ks = KillSwitch(flag_file=tmp_path / "ks.flag")
        assert ks.is_active() is True
        ks.reset_for_testing()

    def test_env_var_0_does_not_activate(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOPEFX_KILL_SWITCH", "0")
        from kill_switch import KillSwitch
        ks = KillSwitch(flag_file=tmp_path / "ks.flag")
        ks.reset_for_testing()
        assert ks.is_active() is False


# ── status() ─────────────────────────────────────────────────────────────────


class TestStatus:
    def test_status_inactive(self):
        ks = _fresh_ks()
        s = ks.status()
        assert s["active"] is False
        assert "reason" in s

    def test_status_active(self):
        ks = _fresh_ks()
        ks.activate("status test")
        s = ks.status()
        assert s["active"] is True
        assert s["reason"] == "status test"
        ks.reset_for_testing()


# ── flag file ─────────────────────────────────────────────────────────────────


class TestFlagFile:
    def test_flag_file_written_on_activate(self, tmp_path):
        flag = tmp_path / "ks.flag"
        from kill_switch import KillSwitch
        ks = KillSwitch(flag_file=flag)
        ks.reset_for_testing()
        ks.activate("flag test")
        assert flag.exists()
        ks.reset_for_testing()

    def test_flag_file_removed_on_deactivate(self, tmp_path):
        flag = tmp_path / "ks.flag"
        from kill_switch import KillSwitch
        ks = KillSwitch(flag_file=flag, deactivation_token="tok")
        ks.reset_for_testing()
        ks.activate("flag test")
        ks.deactivate(token="tok")
        assert not flag.exists()
        ks.reset_for_testing()


# ── _persist_state / _restore_state ──────────────────────────────────────────


class TestPersistRestore:
    def test_persist_and_restore(self, tmp_path):
        flag = tmp_path / "ks.flag"
        from kill_switch import KillSwitch

        ks1 = KillSwitch(flag_file=flag)
        ks1.reset_for_testing()
        ks1.activate("persist test")

        # New instance reads persisted state
        ks2 = KillSwitch(flag_file=flag)
        assert ks2.is_active() is True
        ks2.reset_for_testing()

    def test_restore_stale_flag_non_production(self, tmp_path, monkeypatch):
        """Stale flag (>24h) in non-production should NOT auto-restore."""
        import json
        from datetime import datetime, timedelta, timezone

        monkeypatch.setenv("APP_ENV", "development")
        flag = tmp_path / "ks.flag"
        state_file = tmp_path / "ks.flag.state.json"

        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        state_file.write_text(json.dumps({"active": True, "reason": "old", "activated_at": old_time}))

        from kill_switch import KillSwitch
        ks = KillSwitch(flag_file=flag)
        # Stale flag in dev should not activate
        assert ks.is_active() is False
        ks.reset_for_testing()


# ── set_event_bus / on_bus_event ──────────────────────────────────────────────


class TestEventBus:
    def test_set_event_bus_subscribes(self):
        ks = _fresh_ks()
        subscribed = []

        class FakeBus:
            def subscribe(self, channel, fn):
                subscribed.append((channel, fn))

        ks.set_event_bus(FakeBus())
        assert any(ch == "KILL_SWITCH" for ch, _ in subscribed)

    def test_on_bus_event_activates(self):
        ks = _fresh_ks()

        class FakeEvent:
            def decode(self):
                return {"reason": "bus trigger"}

        ks.on_bus_event(FakeEvent())
        assert ks.is_active() is True
        ks.reset_for_testing()

    def test_on_bus_event_no_decode(self):
        ks = _fresh_ks()

        class BadEvent:
            pass

        ks.on_bus_event(BadEvent())
        assert ks.is_active() is True
        ks.reset_for_testing()

    def test_set_event_bus_subscribe_error(self):
        ks = _fresh_ks()

        class BrokenBus:
            def subscribe(self, *a, **kw):
                raise RuntimeError("bus error")

        # Should not raise
        ks.set_event_bus(BrokenBus())


# ── stop() ───────────────────────────────────────────────────────────────────


class TestStop:
    def test_stop_sets_running_false(self):
        ks = _fresh_ks()

        async def _run():
            await ks.stop()

        asyncio.run(_run())
        assert ks._running is False


# ── trigger_nuclear_mode ──────────────────────────────────────────────────────


class TestTriggerNuclearMode:
    def test_trigger_nuclear_mode(self):
        from kill_switch import trigger_nuclear_mode, kill_switch

        async def _run():
            await trigger_nuclear_mode("test nuclear")

        asyncio.run(_run())
        # Module-level singleton should be active
        assert kill_switch.is_active() is True
        kill_switch.reset_for_testing()


# ── create_kill_switch_router ─────────────────────────────────────────────────


class TestCreateRouter:
    def test_returns_router_or_none(self):
        from kill_switch import create_kill_switch_router
        ks = _fresh_ks()
        result = create_kill_switch_router(ks)
        # Either a FastAPI router or None (if FastAPI not available)
        assert result is None or hasattr(result, "routes")


# ── _check_broker_cod branches ────────────────────────────────────────────────


class TestCheckBrokerCod:
    def test_no_broker_available(self):
        ks = _fresh_ks()

        async def _run():
            await ks._check_broker_cod()

        asyncio.run(_run())  # should not raise

    def test_broker_with_cod_check(self):
        ks = _fresh_ks()

        class FakeBroker:
            name = "FakeBroker"

            def _check_cancel_on_disconnect(self):
                pass

        async def _run():
            import sys
            # Patch execution.engine to return our fake broker
            import types
            mod = types.ModuleType("execution.engine")
            mod.get_active_broker = lambda: FakeBroker()
            sys.modules["execution.engine"] = mod
            try:
                await ks._check_broker_cod()
            finally:
                del sys.modules["execution.engine"]

        asyncio.run(_run())

    def test_broker_without_cod_check(self):
        ks = _fresh_ks()

        class FakeBroker:
            name = "OANDABroker"

        async def _run():
            import sys
            import types
            mod = types.ModuleType("execution.engine")
            mod.get_active_broker = lambda: FakeBroker()
            sys.modules["execution.engine"] = mod
            try:
                await ks._check_broker_cod()
            finally:
                del sys.modules["execution.engine"]

        asyncio.run(_run())


# ── _broker_cancel_all branches ───────────────────────────────────────────────


class TestBrokerCancelAll:
    def test_no_broker_skips(self):
        ks = _fresh_ks()
        ks._broker_cancel_all("test")  # should not raise

    def test_broker_sync_cancel(self):
        ks = _fresh_ks()

        class FakeBroker:
            name = "SyncBroker"
            called = False

            def cancel_all_orders(self):
                FakeBroker.called = True
                return True

        import sys
        import types
        mod = types.ModuleType("execution.engine")
        mod.get_active_broker = lambda: FakeBroker()
        sys.modules["execution.engine"] = mod
        try:
            ks._broker_cancel_all("test")
        finally:
            del sys.modules["execution.engine"]
        assert FakeBroker.called

    def test_broker_no_cancel_method(self):
        ks = _fresh_ks()

        class FakeBroker:
            name = "NoCancelBroker"

        import sys
        import types
        mod = types.ModuleType("execution.engine")
        mod.get_active_broker = lambda: FakeBroker()
        sys.modules["execution.engine"] = mod
        try:
            ks._broker_cancel_all("test")  # should not raise
        finally:
            del sys.modules["execution.engine"]


# ── _check_broker_cod via smart_router fallback ───────────────────────────────


class TestCheckBrokerCodFallbacks:
    def test_via_smart_router(self):
        ks = _fresh_ks()

        class FakeBroker:
            name = "RouterBroker"

        class FakeRouter:
            broker = FakeBroker()

        async def _run():
            import sys
            import types
            # engine raises, router succeeds
            eng = types.ModuleType("execution.engine")
            eng.get_active_broker = lambda: (_ for _ in ()).throw(ImportError("no engine"))
            sys.modules["execution.engine"] = eng
            sr = types.ModuleType("execution.smart_router")
            sr.get_router = lambda: FakeRouter()
            sys.modules["execution.smart_router"] = sr
            try:
                await ks._check_broker_cod()
            finally:
                sys.modules.pop("execution.engine", None)
                sys.modules.pop("execution.smart_router", None)

        asyncio.run(_run())

    def test_broker_cod_raises_non_fatal(self):
        ks = _fresh_ks()

        class FakeBroker:
            name = "ErrorBroker"

            def _check_cancel_on_disconnect(self):
                raise RuntimeError("cod error")

        async def _run():
            import sys
            import types
            eng = types.ModuleType("execution.engine")
            eng.get_active_broker = lambda: FakeBroker()
            sys.modules["execution.engine"] = eng
            try:
                await ks._check_broker_cod()  # should not raise
            finally:
                sys.modules.pop("execution.engine", None)

        asyncio.run(_run())


# ── _broker_cancel_all async path ─────────────────────────────────────────────


class TestBrokerCancelAllAsync:
    def test_async_cancel_no_running_loop(self):
        ks = _fresh_ks()

        async def _async_cancel():
            pass

        class FakeBroker:
            name = "AsyncBroker"

            def cancel_all_orders(self):
                return _async_cancel()

        import sys
        import types
        mod = types.ModuleType("execution.engine")
        mod.get_active_broker = lambda: FakeBroker()
        sys.modules["execution.engine"] = mod
        try:
            # Called outside event loop — triggers asyncio.run() path
            ks._broker_cancel_all("async test")
        finally:
            sys.modules.pop("execution.engine", None)

    def test_broker_cancel_exception_swallowed(self):
        ks = _fresh_ks()

        class FakeBroker:
            name = "ExcBroker"

            def cancel_all_orders(self):
                raise RuntimeError("cancel failed")

        import sys
        import types
        mod = types.ModuleType("execution.engine")
        mod.get_active_broker = lambda: FakeBroker()
        sys.modules["execution.engine"] = mod
        try:
            ks._broker_cancel_all("exc test")  # should not raise
        finally:
            sys.modules.pop("execution.engine", None)


# ── callbacks ─────────────────────────────────────────────────────────────────


class TestCallbacks:
    def test_callback_called_on_activate(self):
        ks = _fresh_ks()
        called_with = []
        ks.register_callback(lambda r: called_with.append(r))
        ks.activate("callback test")
        assert called_with == ["callback test"]
        ks.reset_for_testing()

    def test_multiple_callbacks(self):
        ks = _fresh_ks()
        results = []
        ks.register_callback(lambda r: results.append(f"a:{r}"))
        ks.register_callback(lambda r: results.append(f"b:{r}"))
        ks.activate("multi")
        assert len(results) == 2
        ks.reset_for_testing()
