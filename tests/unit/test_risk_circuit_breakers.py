# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/circuit_breakers.py — CircuitBreaker, RiskLimits, CircuitState."""

from __future__ import annotations

from datetime import timezone
from unittest.mock import MagicMock

import pytest

from risk.circuit_breakers import (
    CircuitBreaker,
    CircuitState,
    RiskLimits,
    get_circuit_breakers,
    register_circuit_breaker,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_broker(balance: float = 100_000.0) -> MagicMock:
    broker = MagicMock()
    broker.get_balance.return_value = balance
    broker.get_positions.return_value = []
    broker.cancel_all_orders.return_value = None
    broker.close_position.return_value = None
    return broker


def _make_cb(balance: float = 100_000.0) -> CircuitBreaker:
    broker = _make_broker(balance)
    return CircuitBreaker(broker=broker, redis_client=None)


# ---------------------------------------------------------------------------
# RiskLimits
# ---------------------------------------------------------------------------


class TestRiskLimits:
    def test_defaults(self):
        rl = RiskLimits()
        assert rl.max_daily_drawdown_pct == pytest.approx(0.03)
        assert rl.max_total_drawdown_pct == pytest.approx(0.10)
        assert rl.max_orders_per_minute == 10
        assert rl.max_leverage_ratio == pytest.approx(10.0)

    def test_custom_values(self):
        rl = RiskLimits(max_daily_drawdown_pct=0.05, max_orders_per_minute=20)
        assert rl.max_daily_drawdown_pct == pytest.approx(0.05)
        assert rl.max_orders_per_minute == 20


# ---------------------------------------------------------------------------
# CircuitState
# ---------------------------------------------------------------------------


class TestCircuitState:
    def test_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


# ---------------------------------------------------------------------------
# CircuitBreaker construction
# ---------------------------------------------------------------------------


class TestCircuitBreakerInit:
    def test_initial_state_closed(self):
        cb = _make_cb()
        assert cb.state == CircuitState.CLOSED

    def test_initial_pnl_zero(self):
        cb = _make_cb()
        assert cb.daily_pnl == 0.0
        assert cb.total_pnl == 0.0

    def test_peak_balance_set_from_broker(self):
        cb = _make_cb(balance=50_000.0)
        assert cb.peak_balance == pytest.approx(50_000.0)

    def test_no_redis_no_crash(self):
        cb = _make_cb()
        assert cb.redis is None


# ---------------------------------------------------------------------------
# pre_trade_check
# ---------------------------------------------------------------------------


class TestPreTradeCheck:
    def test_allows_normal_order(self):
        cb = _make_cb()
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1.0, "price": 1900.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is True
        assert reason is None

    def test_blocks_when_open(self):
        cb = _make_cb()
        cb.state = CircuitState.OPEN
        cb.breach_history.append({"reason": "TEST", "message": "test"})
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1.0, "price": 1900.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is False
        assert reason is not None

    def test_blocks_oversized_order(self):
        cb = _make_cb()
        # notional = 1000 * 2000 = 2_000_000 > default max_order_size 100_000
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1000.0, "price": 2000.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is False
        assert "size" in reason.lower() or "limit" in reason.lower()

    def test_records_order_timestamp(self):
        cb = _make_cb()
        order = {"symbol": "XAUUSD", "side": "buy", "size": 0.1, "price": 1900.0}
        cb.pre_trade_check(order)
        assert len(cb.orders_last_minute) == 1

    def test_half_open_reduces_size(self):
        cb = _make_cb()
        cb.state = CircuitState.HALF_OPEN
        order = {"symbol": "XAUUSD", "side": "buy", "size": 2.0, "price": 1900.0}
        allowed, _ = cb.pre_trade_check(order)
        assert allowed is True
        assert order["size"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# update_trade_result
# ---------------------------------------------------------------------------


class TestUpdateTradeResult:
    def test_loss_increments_streak(self):
        cb = _make_cb()
        cb.update_trade_result(-500.0)
        assert cb.consecutive_losses == 1
        assert cb.loss_streak_amount == pytest.approx(500.0)

    def test_win_resets_streak(self):
        cb = _make_cb()
        cb.update_trade_result(-500.0)
        cb.update_trade_result(200.0)
        assert cb.consecutive_losses == 0
        assert cb.loss_streak_amount == pytest.approx(0.0)

    def test_multiple_losses_accumulate(self):
        cb = _make_cb()
        cb.update_trade_result(-100.0)
        cb.update_trade_result(-200.0)
        assert cb.consecutive_losses == 2
        assert cb.loss_streak_amount == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# manual_override
# ---------------------------------------------------------------------------


class TestManualOverride:
    def test_enable_override(self):
        cb = _make_cb()
        cb.manual_override(enable=True, reason="ops decision", authorized_by="admin")
        assert cb._manual_override is True
        assert cb._override_reason == "ops decision"

    @pytest.mark.asyncio
    async def test_disable_override(self):
        cb = _make_cb()
        cb.manual_override(enable=True, reason="test", authorized_by="admin")
        cb.manual_override(enable=False, reason="cleared", authorized_by="admin")
        assert cb._manual_override is False
        assert cb._override_reason is None

    def test_audit_trail_recorded(self):
        cb = _make_cb()
        cb.manual_override(enable=True, reason="test", authorized_by="admin")
        assert len(cb.state_changes) >= 1
        assert cb.state_changes[-1]["authorized_by"] == "admin"


# ---------------------------------------------------------------------------
# async trigger
# ---------------------------------------------------------------------------


class TestAsyncTrigger:
    @pytest.mark.asyncio
    async def test_trigger_opens_circuit(self):
        cb = _make_cb()
        await cb._trigger_circuit_breaker("TEST", "unit test trigger")
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_trigger_records_breach(self):
        cb = _make_cb()
        await cb._trigger_circuit_breaker("DAILY_DRAWDOWN", "drawdown exceeded")
        assert len(cb.breach_history) == 1
        assert cb.breach_history[0]["reason"] == "DAILY_DRAWDOWN"

    @pytest.mark.asyncio
    async def test_double_trigger_no_duplicate(self):
        cb = _make_cb()
        await cb._trigger_circuit_breaker("TEST", "first")
        await cb._trigger_circuit_breaker("TEST", "second")
        # Second call is a no-op when already OPEN
        assert len(cb.breach_history) == 1


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_and_retrieve(self):
        cb = _make_cb()
        register_circuit_breaker("test_broker", cb)
        registry = get_circuit_breakers()
        assert "test_broker" in registry
        assert registry["test_broker"] is cb


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_keys(self):
        cb = _make_cb()
        s = cb.get_status()
        assert "state" in s
        assert "current_drawdown" in s
        assert "daily_pnl" in s
        assert "consecutive_losses" in s
        assert "open_positions" in s
        assert "manual_override" in s
        assert "last_breach" in s
        assert "limits" in s

    def test_status_state_value(self):
        cb = _make_cb()
        s = cb.get_status()
        assert s["state"] == "closed"

    def test_status_last_breach_none_initially(self):
        cb = _make_cb()
        assert cb.get_status()["last_breach"] is None

    @pytest.mark.asyncio
    async def test_status_last_breach_after_trigger(self):
        cb = _make_cb()
        await cb._trigger_circuit_breaker("TEST", "test breach")
        s = cb.get_status()
        assert s["last_breach"] is not None
        assert s["last_breach"]["reason"] == "TEST"


# ---------------------------------------------------------------------------
# _check_risk_limits — async monitoring paths
# ---------------------------------------------------------------------------


class TestCheckRiskLimits:
    @pytest.mark.asyncio
    async def test_daily_drawdown_triggers_circuit(self):
        broker = _make_broker(balance=97_000.0)  # 3% below peak
        cb = CircuitBreaker(broker=broker, redis_client=None)
        cb.peak_balance = 100_000.0
        cb.current_drawdown = 0.03  # at limit
        await cb._check_risk_limits()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_total_drawdown_triggers_circuit(self):
        broker = _make_broker(balance=89_000.0)  # 11% below peak
        cb = CircuitBreaker(broker=broker, redis_client=None)
        cb.peak_balance = 100_000.0
        cb.current_drawdown = 0.11  # above total limit
        await cb._check_risk_limits()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_order_rate_limit_triggers_circuit(self):
        from datetime import datetime, timezone

        cb = _make_cb()
        # Fill orders_last_minute with recent timestamps
        now = datetime.now(timezone.utc)
        for _ in range(cb.limits.max_orders_per_minute):
            cb.orders_last_minute.append(now)
        await cb._check_risk_limits()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_loss_streak_triggers_circuit(self):
        cb = _make_cb(balance=100_000.0)
        cb.consecutive_losses = cb.limits.max_consecutive_losses
        cb.loss_streak_amount = cb.limits.max_loss_streak_pct * 100_000.0 + 1
        await cb._check_risk_limits()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_no_breach_stays_closed(self):
        cb = _make_cb(balance=100_000.0)
        cb.peak_balance = 100_000.0
        await cb._check_risk_limits()
        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# _execute_kill_switch
# ---------------------------------------------------------------------------


class TestExecuteKillSwitch:
    @pytest.mark.asyncio
    async def test_closes_all_positions(self):
        broker = _make_broker()
        call_count = {"n": 0}

        def _get_positions():
            call_count["n"] += 1
            # First call: has positions; subsequent calls: empty
            if call_count["n"] == 1:
                return [{"symbol": "XAUUSD", "notional": 1000}]
            return []

        broker.get_positions.side_effect = _get_positions
        cb = CircuitBreaker(broker=broker, redis_client=None)
        await cb._execute_kill_switch("TEST")
        broker.cancel_all_orders.assert_called()
        broker.close_position.assert_called()

    @pytest.mark.asyncio
    async def test_no_positions_exits_early(self):
        broker = _make_broker()
        broker.get_positions.return_value = []
        cb = CircuitBreaker(broker=broker, redis_client=None)
        await cb._execute_kill_switch("TEST")
        broker.cancel_all_orders.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_position_exception_continues(self):
        broker = _make_broker()
        call_count = {"n": 0}

        def _get_positions():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{"symbol": "XAUUSD", "notional": 1000}]
            return []

        broker.get_positions.side_effect = _get_positions
        broker.close_position.side_effect = RuntimeError("broker error")
        cb = CircuitBreaker(broker=broker, redis_client=None)
        # Should not raise
        await cb._execute_kill_switch("TEST")

    @pytest.mark.asyncio
    async def test_remaining_positions_triggers_broker_level_cancel(self):
        broker = _make_broker()
        # Always returns positions — never clears
        broker.get_positions.return_value = [{"symbol": "XAUUSD", "notional": 1000}]
        cb = CircuitBreaker(broker=broker, redis_client=None)
        # Should not raise even with persistent positions
        await cb._execute_kill_switch("TEST")
        # cancel_all_orders called multiple times (retries + broker-level escalation)
        assert broker.cancel_all_orders.call_count >= 1


# ---------------------------------------------------------------------------
# _broker_level_cancel_all
# ---------------------------------------------------------------------------


class TestBrokerLevelCancelAll:
    def test_generic_fallback_calls_cancel_all_orders(self):
        # Use a plain object so MagicMock doesn't auto-create _ib
        class _Broker:
            def get_balance(self):
                return 100_000.0

            def get_positions(self):
                return []

            def cancel_all_orders(self):
                self._cancelled = True

            def get_daily_pnl(self):
                return 0.0

        broker = _Broker()
        cb = CircuitBreaker(broker=broker, redis_client=None)
        cb._broker_level_cancel_all("TEST")
        assert getattr(broker, "_cancelled", False) is True

    def test_ibkr_path_with_ib_object(self):
        broker = _make_broker()
        ib_mock = MagicMock()
        # Explicitly set _ib so getattr finds it
        broker._ib = ib_mock
        # Remove auto-spec so hasattr works correctly
        cb = CircuitBreaker(broker=broker, redis_client=None)
        cb._broker_level_cancel_all("TEST")
        ib_mock.reqGlobalCancel.assert_called_once()

    def test_ibkr_exception_falls_through_to_generic(self):
        broker = _make_broker()
        ib_mock = MagicMock()
        ib_mock.reqGlobalCancel.side_effect = RuntimeError("ib error")
        broker._ib = ib_mock
        cb = CircuitBreaker(broker=broker, redis_client=None)
        # Should not raise — falls through to generic cancel
        cb._broker_level_cancel_all("TEST")
        broker.cancel_all_orders.assert_called()

    def test_cancel_all_orders_exception_does_not_propagate(self):
        broker = _make_broker()
        broker.cancel_all_orders.side_effect = RuntimeError("broker down")
        cb = CircuitBreaker(broker=broker, redis_client=None)
        # Should not raise
        cb._broker_level_cancel_all("TEST")


# ---------------------------------------------------------------------------
# _persist_state / _load_state with Redis mock
# ---------------------------------------------------------------------------


class TestPersistAndLoadState:
    def test_persist_state_with_redis(self):
        redis_mock = MagicMock()
        broker = _make_broker()
        cb = CircuitBreaker(broker=broker, redis_client=redis_mock)
        cb._persist_state()
        redis_mock.hset.assert_called()
        redis_mock.expire.assert_called()

    def test_persist_state_redis_exception_no_crash(self):
        redis_mock = MagicMock()
        redis_mock.hset.side_effect = Exception("redis down")
        broker = _make_broker()
        cb = CircuitBreaker(broker=broker, redis_client=redis_mock)
        cb._persist_state()  # should not raise

    def test_load_state_with_redis_data(self):
        redis_mock = MagicMock()
        redis_mock.hgetall.return_value = {
            b"daily_pnl": b"-500.0",
            b"peak_balance": b"105000.0",
            b"consecutive_losses": b"2",
        }
        broker = _make_broker(balance=100_000.0)
        cb = CircuitBreaker(broker=broker, redis_client=redis_mock)
        # _load_state runs before _initialize_monitoring which sets peak_balance
        # from broker.get_balance(). So daily_pnl and consecutive_losses are loaded
        # but peak_balance is overwritten by _initialize_monitoring.
        assert cb.daily_pnl == pytest.approx(-500.0)
        assert cb.consecutive_losses == 2
        # peak_balance is set by _initialize_monitoring to broker.get_balance()
        assert cb.peak_balance == pytest.approx(100_000.0)

    def test_load_state_redis_exception_no_crash(self):
        redis_mock = MagicMock()
        redis_mock.hgetall.side_effect = Exception("redis down")
        broker = _make_broker()
        # Should not raise during construction
        cb = CircuitBreaker(broker=broker, redis_client=redis_mock)
        assert cb is not None

    def test_load_state_empty_data(self):
        redis_mock = MagicMock()
        redis_mock.hgetall.return_value = {}
        broker = _make_broker()
        cb = CircuitBreaker(broker=broker, redis_client=redis_mock)
        assert cb.daily_pnl == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _calculate_daily_pnl
# ---------------------------------------------------------------------------


class TestCalculateDailyPnl:
    def test_uses_broker_get_daily_pnl(self):
        broker = _make_broker()
        broker.get_daily_pnl.return_value = -1500.0
        cb = CircuitBreaker(broker=broker, redis_client=None)
        assert cb._calculate_daily_pnl() == pytest.approx(-1500.0)

    def test_returns_zero_when_no_get_daily_pnl(self):
        broker = _make_broker()
        del broker.get_daily_pnl  # remove the attribute
        cb = CircuitBreaker(broker=broker, redis_client=None)
        assert cb._calculate_daily_pnl() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _calculate_total_exposure
# ---------------------------------------------------------------------------


class TestCalculateTotalExposure:
    def test_sums_notional(self):
        broker = _make_broker()
        broker.get_positions.return_value = [
            {"symbol": "XAUUSD", "notional": 5000},
            {"symbol": "EURUSD", "notional": 3000},
        ]
        cb = CircuitBreaker(broker=broker, redis_client=None)
        assert cb._calculate_total_exposure() == pytest.approx(8000.0)

    def test_empty_positions_zero_exposure(self):
        cb = _make_cb()
        assert cb._calculate_total_exposure() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _would_breach_correlation_limit / _is_correlated
# ---------------------------------------------------------------------------


class TestCorrelation:
    def test_correlated_pairs_detected(self):
        cb = _make_cb()
        assert cb._is_correlated("EUR/USD", "GBP/USD") is True

    def test_uncorrelated_pairs(self):
        cb = _make_cb()
        assert cb._is_correlated("EUR/USD", "XAU/USD") is False

    def test_same_symbol_correlated(self):
        cb = _make_cb()
        assert cb._is_correlated("XAU/USD", "XAG/USD") is True

    def test_correlation_limit_not_breached_with_no_positions(self):
        cb = _make_cb()
        assert cb._would_breach_correlation_limit("EUR/USD") is False

    def test_correlation_limit_breached_with_max_correlated(self):
        broker = _make_broker()
        broker.get_positions.return_value = [
            {"symbol": "EUR/USD", "notional": 1000},
            {"symbol": "GBP/USD", "notional": 1000},
            {"symbol": "AUD/USD", "notional": 1000},
        ]
        cb = CircuitBreaker(broker=broker, redis_client=None)
        # max_correlated_positions=3, all 3 are correlated with NZD/USD
        assert cb._would_breach_correlation_limit("NZD/USD") is True


# ---------------------------------------------------------------------------
# pre_trade_check — exposure and correlation blocks
# ---------------------------------------------------------------------------


class TestPreTradeCheckAdvanced:
    def test_blocks_on_exposure_breach(self):
        broker = _make_broker(balance=100_000.0)
        broker.get_positions.return_value = [
            {"symbol": "XAUUSD", "notional": 19_000},  # 19% exposure
        ]
        cb = CircuitBreaker(broker=broker, redis_client=None)
        # New order: 5000 notional → total 24% > 20% limit
        order = {"symbol": "EURUSD", "size": 2.5, "price": 2000.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is False
        assert "exposure" in reason.lower()

    def test_blocks_on_correlation_breach(self):
        broker = _make_broker(balance=100_000.0)
        broker.get_positions.return_value = [
            {"symbol": "EUR/USD", "notional": 100},
            {"symbol": "GBP/USD", "notional": 100},
            {"symbol": "AUD/USD", "notional": 100},
        ]
        cb = CircuitBreaker(broker=broker, redis_client=None)
        order = {"symbol": "NZD/USD", "size": 0.01, "price": 0.65}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is False
        assert "correlation" in reason.lower()


# ---------------------------------------------------------------------------
# on_breach callback
# ---------------------------------------------------------------------------


class TestOnBreachCallback:
    @pytest.mark.asyncio
    async def test_callback_fired_on_trigger(self):
        cb = _make_cb()
        fired = []
        cb.on_breach = lambda breach: fired.append(breach)
        await cb._trigger_circuit_breaker("TEST", "test")
        assert len(fired) == 1
        assert fired[0]["reason"] == "TEST"

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_propagate(self):
        cb = _make_cb()
        cb.on_breach = lambda breach: (_ for _ in ()).throw(RuntimeError("boom"))
        # Should not raise
        await cb._trigger_circuit_breaker("TEST", "test")


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_sets_flag(self):
        cb = _make_cb()
        cb.shutdown()
        assert cb._shutdown is True

    @pytest.mark.asyncio
    async def test_shutdown_cancels_monitoring_task(self):
        import asyncio

        cb = _make_cb()

        async def _dummy():
            await asyncio.sleep(100)

        task = asyncio.create_task(_dummy())
        cb._monitoring_task = task
        cb.shutdown()
        # Give the event loop a chance to process the cancellation
        await asyncio.sleep(0)
        assert task.cancelled() or task.cancelling() > 0

    def test_shutdown_no_task_no_crash(self):
        cb = _make_cb()
        cb._monitoring_task = None
        cb.shutdown()  # should not raise
        assert cb._shutdown is True


# ---------------------------------------------------------------------------
# _get_last_breach_reason
# ---------------------------------------------------------------------------


class TestGetLastBreachReason:
    def test_no_history_returns_unknown(self):
        cb = _make_cb()
        assert cb._get_last_breach_reason() == "Unknown"

    def test_returns_last_reason(self):
        cb = _make_cb()
        cb.breach_history.append({"reason": "DAILY_DRAWDOWN", "message": "test"})
        assert cb._get_last_breach_reason() == "DAILY_DRAWDOWN"


# ---------------------------------------------------------------------------
# _monitoring_loop exception handling
# ---------------------------------------------------------------------------


class TestMonitoringLoop:
    @pytest.mark.asyncio
    async def test_monitoring_loop_handles_exception(self):
        cb = _make_cb()
        cb._shutdown = False
        call_count = {"n": 0}

        async def _bad_check():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient error")
            cb._shutdown = True  # stop after second iteration

        cb._check_risk_limits = _bad_check
        # Run one iteration — exception should be caught, not propagated
        await cb._monitoring_loop()
        assert call_count["n"] >= 1


# ---------------------------------------------------------------------------
# _schedule_recovery — manual override path
# ---------------------------------------------------------------------------


class TestScheduleRecovery:
    @pytest.mark.asyncio
    async def test_manual_override_skips_recovery(self):
        cb = _make_cb()
        cb.state = CircuitState.OPEN
        cb._manual_override = True
        # Patch cooldown to 0 so test doesn't wait 15 minutes
        cb.limits.circuit_breaker_cooldown_minutes = 0
        await cb._schedule_recovery()
        # State should remain OPEN (manual override prevented auto-recovery)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_recovery_transitions_to_half_open(self):
        cb = _make_cb()
        cb.state = CircuitState.OPEN
        cb._manual_override = False
        cb.limits.circuit_breaker_cooldown_minutes = 0
        await cb._schedule_recovery()
        assert cb.state == CircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# _check_recovery paths
# ---------------------------------------------------------------------------


class TestCheckRecovery:
    @pytest.mark.asyncio
    async def test_recovery_closes_circuit_when_drawdown_recovered(self):
        from unittest.mock import patch

        cb = _make_cb()
        cb.state = CircuitState.HALF_OPEN
        cb.current_drawdown = 0.001  # well below 50% of daily limit
        # Patch sleep to avoid waiting 5 minutes
        with patch("asyncio.sleep", return_value=None):
            await cb._check_recovery()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_recovery_reopens_circuit_when_drawdown_persists(self):
        from unittest.mock import patch

        cb = _make_cb()
        cb.state = CircuitState.HALF_OPEN
        cb.current_drawdown = 0.05  # above 50% of daily limit (0.03 * 0.5 = 0.015)
        with patch("asyncio.sleep", return_value=None):
            await cb._check_recovery()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_check_recovery_exits_if_not_half_open(self):
        from unittest.mock import patch

        cb = _make_cb()
        cb.state = CircuitState.CLOSED  # not HALF_OPEN
        with patch("asyncio.sleep", return_value=None):
            await cb._check_recovery()
        assert cb.state == CircuitState.CLOSED  # unchanged


# ---------------------------------------------------------------------------
# manual_override — disable path re-evaluates limits
# ---------------------------------------------------------------------------


class TestManualOverrideDisable:
    @pytest.mark.asyncio
    async def test_disable_override_triggers_risk_check(self):
        import asyncio

        cb = _make_cb()
        cb.manual_override(enable=True, reason="test", authorized_by="admin")
        # Disable — this creates an asyncio task for _check_risk_limits
        cb.manual_override(enable=False, reason="cleared", authorized_by="admin")
        assert cb._manual_override is False
        # Give event loop a tick to process the task
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# _send_circuit_breaker_telegram — module-level function
# ---------------------------------------------------------------------------


class TestSendCircuitBreakerTelegram:
    def test_no_alert_engine_no_crash(self):
        from unittest.mock import patch
        from risk.circuit_breakers import _send_circuit_breaker_telegram

        # Patch get_alert_engine inside the notifications module
        with patch("notifications.get_alert_engine", return_value=None):
            _send_circuit_breaker_telegram("TEST", "test message")

    def test_import_error_no_crash(self):
        import sys
        from risk.circuit_breakers import _send_circuit_breaker_telegram

        # Temporarily replace notifications with a broken module
        import types

        broken = types.ModuleType("notifications")
        broken.get_alert_engine = None  # not callable
        old = sys.modules.get("notifications")
        sys.modules["notifications"] = broken
        try:
            _send_circuit_breaker_telegram("TEST", "test message")
        finally:
            if old is not None:
                sys.modules["notifications"] = old
            else:
                sys.modules.pop("notifications", None)


# ---------------------------------------------------------------------------
# RiskLimits — additional fields
# ---------------------------------------------------------------------------


class TestRiskLimitsAdditional:
    def test_halt_on_volatility_spike_default(self):
        rl = RiskLimits()
        assert rl.halt_on_volatility_spike is True

    def test_max_consecutive_losses_default(self):
        rl = RiskLimits()
        assert rl.max_consecutive_losses == 5

    def test_circuit_breaker_cooldown_default(self):
        rl = RiskLimits()
        assert rl.circuit_breaker_cooldown_minutes == 15
