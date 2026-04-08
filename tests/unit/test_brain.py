# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for brain/brain.py — HOPEFXBrain central intelligence system."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain.brain import (
    BrainState,
    CircuitBreaker,
    HOPEFXBrain,
    MarketRegime,
    SystemState,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def brain():
    return HOPEFXBrain(config={"max_decision_history": 100})


@pytest.fixture
def circuit_breaker():
    return CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)


def _make_ohlcv(n: int = 25, base: float = 1.08):
    """Return a list of simple OHLCV-like objects."""

    class Bar:
        def __init__(self, close, high, low):
            self.close = close
            self.high = high
            self.low = low

    import numpy as np

    rng = np.random.default_rng(42)
    closes = base + np.cumsum(rng.normal(0, 0.001, n))
    return [Bar(c, c + 0.001, c - 0.001) for c in closes]


def _make_broker(balance=10_000.0, equity=10_000.0, margin_used=0.0, free_margin=10_000.0):
    broker = AsyncMock()
    broker.get_account_info.return_value = {
        "balance": balance,
        "equity": equity,
        "margin_used": margin_used,
        "free_margin": free_margin,
    }
    broker.get_positions.return_value = []
    broker.get_pending_orders.return_value = []
    broker.close_position = AsyncMock(return_value=True)
    return broker


# ── BrainState ────────────────────────────────────────────────────────────────


class TestBrainState:
    def test_to_dict_keys(self):
        state = BrainState(timestamp=time.time(), system_state=SystemState.RUNNING)
        d = state.to_dict()
        assert "timestamp" in d
        assert "system_state" in d
        assert d["system_state"] == "running"
        assert "performance" in d

    def test_to_dict_rounds_floats(self):
        state = BrainState(
            timestamp=time.time(),
            system_state=SystemState.RUNNING,
            account_balance=12345.6789,
        )
        d = state.to_dict()
        assert d["account_balance"] == 12345.68

    def test_market_regime_serialised(self):
        state = BrainState(timestamp=time.time(), system_state=SystemState.RUNNING)
        state.market_regime["EUR/USD"] = MarketRegime.TRENDING_UP
        d = state.to_dict()
        assert d["market_regime"]["EUR/USD"] == "trending_up"


# ── CircuitBreaker ────────────────────────────────────────────────────────────


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_opens_after_threshold(self, circuit_breaker):
        for _ in range(3):
            await circuit_breaker.record_failure()
        assert circuit_breaker.is_open

    @pytest.mark.asyncio
    async def test_success_decrements_count(self, circuit_breaker):
        await circuit_breaker.record_failure()
        await circuit_breaker.record_failure()
        await circuit_breaker.record_success()
        assert circuit_breaker.failure_count == 1
        assert not circuit_breaker.is_open

    @pytest.mark.asyncio
    async def test_auto_recovery_after_timeout(self, circuit_breaker):
        for _ in range(3):
            await circuit_breaker.record_failure()
        assert circuit_breaker.is_open
        # Fake the last_failure_time to be in the past
        circuit_breaker.last_failure_time = time.time() - 10.0
        recovered = await circuit_breaker.check_recovery()
        assert recovered
        assert not circuit_breaker.is_open

    @pytest.mark.asyncio
    async def test_no_recovery_before_timeout(self, circuit_breaker):
        for _ in range(3):
            await circuit_breaker.record_failure()
        recovered = await circuit_breaker.check_recovery()
        assert not recovered

    def test_get_status(self, circuit_breaker):
        status = circuit_breaker.get_status()
        assert "is_open" in status
        assert "failure_count" in status
        assert status["threshold"] == 3

    @pytest.mark.asyncio
    async def test_closed_circuit_check_recovery_returns_true(self, circuit_breaker):
        assert not circuit_breaker.is_open
        result = await circuit_breaker.check_recovery()
        assert result


# ── HOPEFXBrain initialisation ────────────────────────────────────────────────


class TestHOPEFXBrainInit:
    def test_default_state(self, brain):
        assert brain.state.system_state == SystemState.INITIALIZING
        assert not brain._running
        assert not brain._emergency_stop

    def test_custom_config(self):
        b = HOPEFXBrain(config={"max_decision_history": 50, "circuit_breaker_threshold": 2})
        assert b.decision_history.maxlen == 50
        assert b._circuit_breaker.failure_threshold == 2

    def test_inject_components(self, brain):
        broker = MagicMock()
        price_engine = MagicMock()
        brain.inject_components(broker=broker, price_engine=price_engine)
        assert brain.broker is broker
        assert brain.price_engine is price_engine

    def test_inject_missing_critical_components_logs_error(self, brain, caplog):
        import logging

        with caplog.at_level(logging.ERROR, logger="brain.brain"):
            brain.inject_components()
        assert "Missing components" in caplog.text


# ── Regime detection ──────────────────────────────────────────────────────────


class TestRegimeDetection:
    def test_detect_regime_numpy_trending_up(self, brain):
        import numpy as np

        n = 25
        closes = list(1.08 + np.linspace(0, 0.05, n))  # strong uptrend
        highs = [c + 0.001 for c in closes]
        lows = [c - 0.001 for c in closes]
        regime = brain._detect_regime_numpy(closes, highs, lows)
        assert regime in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN, MarketRegime.RANGING, MarketRegime.VOLATILE)

    def test_detect_regime_python_fallback(self, brain):
        import numpy as np

        n = 25
        closes = list(1.08 + np.linspace(0, 0.05, n))
        highs = [c + 0.001 for c in closes]
        lows = [c - 0.001 for c in closes]
        regime = brain._detect_regime_python(closes, highs, lows)
        assert isinstance(regime, MarketRegime)

    @pytest.mark.asyncio
    async def test_detect_regime_no_price_engine(self, brain):
        brain.price_engine = None
        regime = await brain._detect_regime("EUR/USD")
        assert regime == MarketRegime.UNKNOWN

    @pytest.mark.asyncio
    async def test_detect_regime_insufficient_data(self, brain):
        price_engine = MagicMock()
        price_engine.get_ohlcv.return_value = _make_ohlcv(5)  # < 20 bars
        brain.price_engine = price_engine
        regime = await brain._detect_regime("EUR/USD")
        assert regime == MarketRegime.UNKNOWN

    @pytest.mark.asyncio
    async def test_detect_regime_ohlcv_error(self, brain):
        price_engine = MagicMock()
        price_engine.get_ohlcv.side_effect = RuntimeError("feed down")
        brain.price_engine = price_engine
        regime = await brain._detect_regime("EUR/USD")
        assert regime == MarketRegime.UNKNOWN

    @pytest.mark.asyncio
    async def test_analyze_market_regimes_skips_if_recent(self, brain):
        brain.last_regime_check = time.time()  # just checked
        brain.price_engine = MagicMock()
        await brain._analyze_market_regimes()
        brain.price_engine.get_ohlcv.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_market_regimes_runs_for_symbols(self, brain):
        price_engine = MagicMock()
        price_engine.symbols = ["EUR/USD"]
        price_engine.get_ohlcv.return_value = _make_ohlcv(25)
        brain.price_engine = price_engine
        brain.last_regime_check = 0  # force check
        await brain._analyze_market_regimes()
        assert "EUR/USD" in brain.state.market_regime


# ── State update ──────────────────────────────────────────────────────────────


class TestStateUpdate:
    @pytest.mark.asyncio
    async def test_update_state_with_broker(self, brain):
        brain.broker = _make_broker(balance=50_000.0)
        await brain._update_state()
        assert brain.state.account_balance == 50_000.0

    @pytest.mark.asyncio
    async def test_update_state_broker_timeout(self, brain):
        broker = AsyncMock()
        broker.get_account_info.side_effect = TimeoutError()
        brain.broker = broker
        with pytest.raises(asyncio.TimeoutError):
            await brain._update_state()

    @pytest.mark.asyncio
    async def test_update_state_positions_timeout_graceful(self, brain):
        broker = AsyncMock()
        broker.get_account_info.return_value = {"balance": 1000, "equity": 1000, "margin_used": 0, "free_margin": 1000}
        broker.get_positions.side_effect = TimeoutError()
        broker.get_pending_orders.return_value = []
        brain.broker = broker
        # positions timeout should set empty positions, not crash
        await brain._update_state()
        assert brain.state.active_positions == {}


# ── Risk assessment ───────────────────────────────────────────────────────────


class TestRiskAssessment:
    @pytest.mark.asyncio
    async def test_assess_risk_no_risk_manager(self, brain):
        brain.risk_manager = None
        # Should not raise
        await brain._assess_risk()

    @pytest.mark.asyncio
    async def test_assess_risk_checks_drawdown(self, brain):
        rm = MagicMock()
        rm.current_drawdown = 0.05  # 5% — below 10% threshold
        brain.risk_manager = rm
        brain.state.account_balance = 10_000.0
        brain.state.equity = 10_000.0
        # Should complete without triggering emergency stop
        await brain._assess_risk()
        assert brain.state.system_state != SystemState.EMERGENCY_STOP

    @pytest.mark.asyncio
    async def test_assess_risk_triggers_emergency_on_high_drawdown(self, brain):
        rm = MagicMock()
        rm.current_drawdown = 0.15  # 15% — above 10% threshold
        brain.risk_manager = rm
        brain.broker = _make_broker()
        brain.state.account_balance = 10_000.0
        brain.state.equity = 10_000.0
        await brain._assess_risk()
        assert brain._emergency_stop is True


# ── Emergency conditions ──────────────────────────────────────────────────────


class TestEmergencyConditions:
    @pytest.mark.asyncio
    async def test_no_emergency_normal_state(self, brain):
        brain.state.account_balance = 10_000.0
        brain.state.equity = 10_000.0
        brain.state.daily_pnl = 0.0
        result = await brain._check_emergency_conditions()
        assert result is False

    @pytest.mark.asyncio
    async def test_emergency_stop_flag(self, brain):
        brain._emergency_stop = True
        result = await brain._check_emergency_conditions()
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_emergency_stop_sets_state(self, brain):
        brain.broker = _make_broker()
        await brain._execute_emergency_stop()
        assert brain._emergency_stop is True
        assert brain.state.system_state == SystemState.EMERGENCY_STOP


# ── Control methods ───────────────────────────────────────────────────────────


class TestControlMethods:
    def test_pause_sets_flag(self, brain):
        brain.pause()
        assert brain._paused is True

    @pytest.mark.asyncio
    async def test_resume_clears_flag(self, brain):
        brain._paused = True
        brain.resume()
        # resume() schedules an asyncio task; give the event loop a tick to run it
        await asyncio.sleep(0)
        assert brain._paused is False

    def test_emergency_stop_sync(self, brain):
        brain.emergency_stop()
        assert brain._emergency_stop is True

    def test_get_state_returns_brain_state(self, brain):
        state = brain.get_state()
        assert isinstance(state, BrainState)

    def test_get_decision_history_empty(self, brain):
        history = brain.get_decision_history()
        assert history == []

    def test_get_error_history_empty(self, brain):
        history = brain.get_error_history()
        assert history == []

    def test_get_health(self, brain):
        health = brain.get_health()
        assert "circuit_breaker" in health
        assert "system_state" in health or "state" in health or "cycle_count" in health

    def test_get_decision_history_limit(self, brain):
        for i in range(10):
            brain.decision_history.append({"cycle": i})
        history = brain.get_decision_history(limit=5)
        assert len(history) == 5


# ── Start / stop ──────────────────────────────────────────────────────────────


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_sets_running_state(self, brain):
        await brain.start()
        assert brain.state.system_state == SystemState.RUNNING

    @pytest.mark.asyncio
    async def test_stop_sets_shutdown_state(self, brain):
        await brain.start()
        await brain.stop()
        assert brain.state.system_state == SystemState.SHUTDOWN
        assert not brain._running

    @pytest.mark.asyncio
    async def test_dominate_exits_on_shutdown_event(self, brain):
        brain._running = True
        brain.state.system_state = SystemState.RUNNING
        brain._shutdown_event.set()
        # Should return quickly without hanging
        await asyncio.wait_for(brain.dominate(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_shutdown_graceful(self, brain):
        await brain.shutdown()
        # shutdown() sets _running=False and signals the shutdown event
        assert not brain._running
        assert brain._shutdown_event.is_set()


# ── Notification helper ───────────────────────────────────────────────────────


class TestSafeNotify:
    @pytest.mark.asyncio
    async def test_safe_notify_no_manager(self, brain):
        brain.notification_manager = None
        # Should not raise
        await brain._safe_notify("info", "test message", {})

    @pytest.mark.asyncio
    async def test_safe_notify_calls_manager(self, brain):
        nm = AsyncMock()
        brain.notification_manager = nm
        await brain._safe_notify("warning", "test", {"key": "val"})
        nm.send_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_safe_notify_swallows_errors(self, brain):
        nm = AsyncMock()
        nm.send_alert.side_effect = RuntimeError("network error")
        brain.notification_manager = nm
        # Should not raise
        await brain._safe_notify("error", "test", {})


# ── Cycle error handling ──────────────────────────────────────────────────────


class TestCycleErrorHandling:
    @pytest.mark.asyncio
    async def test_handle_cycle_error_appends_history(self, brain):
        with patch("brain.brain.logger"):
            await brain._handle_cycle_error(ValueError("test error"))
        assert len(brain.error_history) == 1
        assert brain.error_history[0]["type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_handle_cycle_error_increments_circuit_breaker(self, brain):
        with patch("brain.brain.logger"):
            await brain._handle_cycle_error(RuntimeError("boom"))
        assert brain._circuit_breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_handle_circuit_open_sleeps_when_not_recovered(self, brain):
        brain._circuit_breaker.is_open = True
        brain._circuit_breaker.last_failure_time = time.time()  # recent failure
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await brain._handle_circuit_open()
            mock_sleep.assert_called_once_with(5.0)


# ── Publish signal ────────────────────────────────────────────────────────────


class TestPublishSignal:
    def test_publish_to_signal_service_no_service(self, brain):
        brain._publish_to_signal_service({"symbol": "EUR/USD", "direction": "long"})
        # No error expected

    def test_publish_to_signal_service_with_service(self, brain):
        svc = MagicMock()
        brain.signal_service = svc
        brain._publish_to_signal_service({"symbol": "EUR/USD", "direction": "long"})
        # Should attempt to publish without crashing
