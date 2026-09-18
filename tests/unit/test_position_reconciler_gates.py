# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`core/position_reconciler.py` — the escalations, not the happy cycle.

The module measured 79%, and what was missing was every path that fires when
something is wrong: the kill switch on a reconciliation breach, the exposure and
VaR invariants, the drift halt and its three notification routes, the price
fetch that returns nothing, and the module-level starter.

The reconciler is constructed in production at `core/startup_factories.py:2829`,
so these are live paths.

Every enforcement method here is deliberately fail-safe — it swallows its own
exceptions so a bug in the invariant layer cannot kill the reconciliation loop.
That is a reasonable trade and it is tested as such: swallowed, *and* reported
at a level somebody sees.
"""

from __future__ import annotations

import logging
import sys
import types

import pytest

import core.position_reconciler as pr

pytestmark = pytest.mark.unit


class _Result:
    """What `invariants.enforcement` hands back."""

    def __init__(self, should_halt=False, violations=(), reason="") -> None:
        self.should_halt = should_halt
        self.violations = list(violations)
        self.reason = reason


def _reconciler(**kwargs):
    return pr.PositionReconciler(session_factory=lambda: None, **kwargs)


@pytest.fixture
def enforcement(monkeypatch: pytest.MonkeyPatch):
    """A stand-in `invariants.enforcement` the tests drive."""
    module = types.ModuleType("invariants.enforcement")
    module.calls = {}

    def _make(name, result_attr):
        def _fn(*args, **kwargs):
            module.calls[name] = {"args": args, "kwargs": kwargs}
            return getattr(module, result_attr)

        return _fn

    module.reconciliation_result = _Result()
    module.exposure_result = _Result()
    module.var_result = _Result()
    module.enforce_reconciliation = _make("reconciliation", "reconciliation_result")
    module.enforce_exposure = _make("exposure", "exposure_result")
    module.enforce_var = _make("var", "var_result")
    monkeypatch.setitem(sys.modules, "invariants.enforcement", module)
    return module


# ---------------------------------------------------------------------------
# Reconciliation invariant and the kill switch
# ---------------------------------------------------------------------------


class TestReconciliationInvariant:
    @pytest.mark.asyncio
    async def test_the_configured_tolerance_is_what_gets_enforced(self, enforcement) -> None:
        """The invariant is handed `value_tol=self._drift_value`. If that ever
        stops matching the configured threshold, the halt fires at a different
        number than the one an operator set."""
        reconciler = _reconciler(drift_value_threshold=250.0)

        await reconciler._enforce_reconciliation(10_000.0, 9_900.0)

        assert enforcement.calls["reconciliation"]["kwargs"] == {
            "internal_value": 10_000.0,
            "external_value": 9_900.0,
            "value_tol": 250.0,
        }

    @pytest.mark.asyncio
    async def test_a_clean_book_trips_nothing(self, enforcement, monkeypatch) -> None:
        activated: list[str] = []
        monkeypatch.setitem(sys.modules, "kill_switch", _kill_switch_module(activated))

        await _reconciler()._enforce_reconciliation(10_000.0, 10_000.0)

        assert activated == []

    @pytest.mark.asyncio
    async def test_a_breach_activates_the_kill_switch_with_both_figures(
        self, enforcement, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The escalation this module exists for, and it had never run."""
        enforcement.reconciliation_result = _Result(should_halt=True, reason="book values diverge")
        activated: list[str] = []
        monkeypatch.setitem(sys.modules, "kill_switch", _kill_switch_module(activated))

        with caplog.at_level(logging.CRITICAL):
            await _reconciler()._enforce_reconciliation(10_000.0, 9_000.0)

        assert len(activated) == 1, "the kill switch was not activated on a reconciliation breach"
        # The operator reading the reason must be able to see both sides of it.
        assert "10000.00" in activated[0]
        assert "9000.00" in activated[0]
        assert "book values diverge" in activated[0]
        assert [r for r in caplog.records if r.levelname == "CRITICAL"]

    @pytest.mark.asyncio
    async def test_a_kill_switch_that_cannot_activate_is_reported_at_error(
        self, enforcement, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Failing to halt is the most important thing this module can fail at,
        so it must not be logged quietly."""
        enforcement.reconciliation_result = _Result(should_halt=True, reason="diverged")

        broken = types.ModuleType("kill_switch")

        class _Broken:
            def activate(self, _reason):
                raise RuntimeError("redis is down")

        broken.KillSwitch = _Broken
        monkeypatch.setitem(sys.modules, "kill_switch", broken)

        with caplog.at_level(logging.ERROR):
            await _reconciler()._enforce_reconciliation(10_000.0, 9_000.0)

        assert any("Could not activate kill switch" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_a_broken_invariant_layer_does_not_kill_the_loop(
        self, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        broken = types.ModuleType("invariants.enforcement")

        def _raise(**_kwargs):
            raise RuntimeError("invariant module is broken")

        broken.enforce_reconciliation = _raise
        monkeypatch.setitem(sys.modules, "invariants.enforcement", broken)

        with caplog.at_level(logging.WARNING):
            await _reconciler()._enforce_reconciliation(1.0, 2.0)  # must not raise

        assert any("Reconciliation invariant check failed" in r.message for r in caplog.records)


def _kill_switch_module(recorder: list[str]) -> types.ModuleType:
    module = types.ModuleType("kill_switch")

    class _KS:
        def activate(self, reason):
            recorder.append(reason)

    module.KillSwitch = _KS
    return module


# ---------------------------------------------------------------------------
# Exposure and VaR invariants
# ---------------------------------------------------------------------------


class TestExposureInvariant:
    def test_every_symbol_is_given_the_same_limit(self, enforcement) -> None:
        _reconciler()._enforce_exposure({"XAUUSD": 500_000.0, "EURUSD": 10_000.0})

        exposures, limits = enforcement.calls["exposure"]["args"]
        assert exposures == {"XAUUSD": 500_000.0, "EURUSD": 10_000.0}
        assert set(limits) == {"XAUUSD", "EURUSD"}
        assert set(limits.values()) == {pr._MAX_SYMBOL_EXPOSURE_USD}

    def test_a_breach_is_reported(self, enforcement, caplog: pytest.LogCaptureFixture) -> None:
        enforcement.exposure_result = _Result(violations=["XAUUSD"], reason="XAUUSD over limit")
        with caplog.at_level(logging.WARNING):
            _reconciler()._enforce_exposure({"XAUUSD": 9_000_000.0})
        assert any("XAUUSD over limit" in r.message for r in caplog.records)

    def test_a_clean_book_is_quiet(self, enforcement, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            _reconciler()._enforce_exposure({"XAUUSD": 1.0})
        assert not [r for r in caplog.records if "EXPOSURE" in r.message]

    def test_a_broken_invariant_layer_does_not_kill_the_loop(
        self, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        broken = types.ModuleType("invariants.enforcement")
        broken.enforce_exposure = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
        monkeypatch.setitem(sys.modules, "invariants.enforcement", broken)
        with caplog.at_level(logging.WARNING):
            _reconciler()._enforce_exposure({"XAUUSD": 1.0})
        assert any("Exposure invariant check failed" in r.message for r in caplog.records)


class TestVarInvariant:
    def test_no_risk_manager_means_nothing_to_check(self, enforcement, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "core.app_state", _app_state(None))
        _reconciler()._enforce_var()
        assert "var" not in enforcement.calls

    def test_a_risk_manager_without_var_is_skipped(self, enforcement, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "core.app_state", _app_state(object()))
        _reconciler()._enforce_var()
        assert "var" not in enforcement.calls

    def test_var_is_compared_as_a_positive_loss_magnitude(self, enforcement, monkeypatch) -> None:
        """The limit is a positive USD figure; a risk manager reporting a
        negative VaR must not read as "within limit" by sign alone."""

        class _RM:
            def value_at_risk(self):
                return -5_000.0

        monkeypatch.setitem(sys.modules, "core.app_state", _app_state(_RM()))
        monkeypatch.setattr(pr, "_APPROVED_VAR_USD", 1_000.0)

        _reconciler()._enforce_var()

        assert enforcement.calls["var"]["args"][0] == 5_000.0

    def test_a_breach_is_reported(self, enforcement, monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
        class _RM:
            def value_at_risk(self):
                return 9_000.0

        monkeypatch.setitem(sys.modules, "core.app_state", _app_state(_RM()))
        enforcement.var_result = _Result(violations=["var"], reason="VaR 9000 over 1000")
        with caplog.at_level(logging.WARNING):
            _reconciler()._enforce_var()
        assert any("VaR 9000 over 1000" in r.message for r in caplog.records)

    def test_a_raising_risk_manager_does_not_kill_the_loop(
        self, enforcement, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _RM:
            def value_at_risk(self):
                raise RuntimeError("risk manager is down")

        monkeypatch.setitem(sys.modules, "core.app_state", _app_state(_RM()))
        with caplog.at_level(logging.WARNING):
            _reconciler()._enforce_var()
        assert any("VaR invariant check failed" in r.message for r in caplog.records)


def _app_state(risk_manager) -> types.ModuleType:
    module = types.ModuleType("core.app_state")
    module.app_state = types.SimpleNamespace(risk_manager=risk_manager)
    return module


# ---------------------------------------------------------------------------
# The drift halt
# ---------------------------------------------------------------------------


class _Alerts:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple] = []
        self._fail = fail

    async def send_alert(self, level, message, data):
        if self._fail:
            raise RuntimeError("alert engine is down")
        self.sent.append((level, message, data))


DRIFT = {
    "symbol": "XAUUSD",
    "db_qty": 3.0,
    "broker_qty": 1.0,
    "qty_diff": 2.0,
    "db_value": 5700.0,
    "broker_value": 1900.0,
    "value_diff": 3800.0,
}


class TestDriftHalt:
    @pytest.mark.asyncio
    async def test_it_alerts_with_the_positional_signature_the_engine_has(self) -> None:
        """F248: this call once passed `title=`, which is not a parameter, so
        every drift alert raised TypeError into the handler below and notified
        nobody. A specless mock would accept either spelling — `_Alerts` does
        not."""
        alerts = _Alerts()
        await _reconciler(alert_engine=alerts)._trigger_drift_halt(**DRIFT)

        (level, message, data) = alerts.sent[0]
        assert level == "critical"
        assert "XAUUSD" in message
        assert data["event"] == "position_drift"

    @pytest.mark.asyncio
    async def test_the_same_symbol_is_not_halted_twice(self) -> None:
        """The loop runs every 10s; a drift that persists must not re-alert on
        every cycle."""
        alerts = _Alerts()
        reconciler = _reconciler(alert_engine=alerts)

        await reconciler._trigger_drift_halt(**DRIFT)
        await reconciler._trigger_drift_halt(**DRIFT)

        assert len(alerts.sent) == 1

    @pytest.mark.asyncio
    async def test_a_different_symbol_still_halts(self) -> None:
        alerts = _Alerts()
        reconciler = _reconciler(alert_engine=alerts)

        await reconciler._trigger_drift_halt(**DRIFT)
        await reconciler._trigger_drift_halt(**{**DRIFT, "symbol": "XAGUSD"})

        assert len(alerts.sent) == 2

    @pytest.mark.asyncio
    async def test_the_reason_carries_both_quantities_and_the_value_gap(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR):
            await _reconciler()._trigger_drift_halt(**DRIFT)
        reason = " ".join(r.getMessage() for r in caplog.records)
        assert "3.0000" in reason and "1.0000" in reason and "3800.00" in reason

    @pytest.mark.asyncio
    async def test_a_failing_alert_engine_does_not_stop_the_halt(
        self, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The risk-manager halt below it is the part that actually stops
        trading, so an alert failure must not skip it."""
        halted: list[tuple] = []
        monkeypatch.setitem(sys.modules, "core.app_state", _app_state(_HaltingRM(halted)))

        with caplog.at_level(logging.ERROR):
            await _reconciler(alert_engine=_Alerts(fail=True))._trigger_drift_halt(**DRIFT)

        assert any("Alert engine notification failed" in r.message for r in caplog.records)
        assert halted, "the risk manager was never asked to halt"

    @pytest.mark.asyncio
    async def test_the_risk_manager_is_told_to_halt(self, monkeypatch) -> None:
        halted: list[tuple] = []
        monkeypatch.setitem(sys.modules, "core.app_state", _app_state(_HaltingRM(halted)))

        await _reconciler()._trigger_drift_halt(**DRIFT)

        (reason, hours) = halted[0]
        assert "XAUUSD" in reason
        assert hours == 1.0

    @pytest.mark.asyncio
    async def test_a_risk_manager_that_cannot_halt_is_reported(
        self, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _Broken:
            def _halt_trading(self, *_a, **_k):
                raise RuntimeError("risk manager is wedged")

        monkeypatch.setitem(sys.modules, "core.app_state", _app_state(_Broken()))

        with caplog.at_level(logging.WARNING):
            await _reconciler()._trigger_drift_halt(**DRIFT)

        assert any("Could not halt risk manager" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_alert_engine_is_not_an_error(self) -> None:
        await _reconciler(alert_engine=None)._trigger_drift_halt(**DRIFT)  # must not raise


class _HaltingRM:
    def __init__(self, recorder: list[tuple]) -> None:
        self._recorder = recorder

    def _halt_trading(self, reason, duration_hours):
        self._recorder.append((reason, duration_hours))


# ---------------------------------------------------------------------------
# Price fetch, stats, and the module-level starter
# ---------------------------------------------------------------------------


class TestGetPrice:
    @pytest.mark.asyncio
    async def test_an_unreachable_feed_yields_no_price_rather_than_raising(self, monkeypatch) -> None:
        """`_reconcile_once` does `if price is None: continue`, so this
        returning None skips the position entirely — no P&L update, no drift
        check, no invariant. See MASTER_OUTSTANDING A10."""
        broken = types.ModuleType("yfinance")

        def _ticker(_symbol):
            raise RuntimeError("network unreachable")

        broken.Ticker = _ticker
        monkeypatch.setitem(sys.modules, "yfinance", broken)

        assert await _reconciler()._get_price("XAUUSD") is None

    @pytest.mark.asyncio
    async def test_an_empty_history_yields_no_price(self, monkeypatch) -> None:
        import pandas as pd

        stub = types.ModuleType("yfinance")

        class _T:
            def __init__(self, _symbol):
                pass

            def history(self, **_kwargs):
                return pd.DataFrame()

        stub.Ticker = _T
        monkeypatch.setitem(sys.modules, "yfinance", stub)

        assert await _reconciler()._get_price("XAUUSD") is None

    @pytest.mark.asyncio
    async def test_the_last_close_is_returned(self, monkeypatch) -> None:
        import pandas as pd

        stub = types.ModuleType("yfinance")

        class _T:
            def __init__(self, _symbol):
                pass

            def history(self, **_kwargs):
                return pd.DataFrame({"Close": [1900.0, 1925.5, 1950.25]})

        stub.Ticker = _T
        monkeypatch.setitem(sys.modules, "yfinance", stub)

        assert await _reconciler()._get_price("XAUUSD") == pytest.approx(1950.25, abs=0.01)


class TestStats:
    def test_it_reports_cycles_mismatches_and_whether_it_is_running(self) -> None:
        reconciler = _reconciler()
        assert reconciler.stats == {"cycles": 0, "mismatches": 0, "running": False}

        reconciler._cycles, reconciler._mismatches, reconciler._running = 7, 2, True
        assert reconciler.stats == {"cycles": 7, "mismatches": 2, "running": True}


class TestTheStarter:
    @pytest.mark.asyncio
    async def test_it_returns_a_running_reconciler(self) -> None:
        import asyncio

        reconciler = pr.start_reconciler(session_factory=lambda: None, interval_seconds=3600)
        try:
            assert isinstance(reconciler, pr.PositionReconciler)
            assert reconciler._interval == 3600
            await asyncio.sleep(0)  # let the scheduled start run
            assert reconciler._running is True
        finally:
            await reconciler.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_the_running_flag(self) -> None:
        reconciler = _reconciler()
        await reconciler.start()
        assert reconciler._running is True
        await reconciler.stop()
        assert reconciler._running is False
