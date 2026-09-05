# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Comprehensive tests for execution/trade_executor.py.

Covers: ExecutionResult, OrderStatus, TradeExecutor — execute_signal,
_execute_open, _execute_close, drawdown/streak circuit breakers,
_clamp_size_to_risk_cap, callbacks, cancel_all_pending, get_risk_status.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution.trade_executor import (
    DRAWDOWN_HALT_PCT,
    MAX_RISK_PCT_PER_TRADE,
    STREAK_HALT_LOSSES,
    ExecutionResult,
    OrderStatus,
    TradeExecutor,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _mock_broker(filled=True, order_id="ord_1", price=2000.0, qty=1.0):
    broker = MagicMock()
    order = MagicMock()
    order.id = order_id
    order.status = MagicMock()
    order.status.value = "filled" if filled else "rejected"
    order.filled_quantity = qty
    order.average_fill_price = price
    order.commission = 1.0
    broker.place_market_order = AsyncMock(return_value=order)
    broker.close_position = AsyncMock(return_value=True)
    return broker


def _mock_risk_manager(
    halted=False,
    halt_reason=None,
    drawdown=0.0,
    equity=100_000.0,
):
    rm = MagicMock()
    rm._trading_halted = halted
    rm._halt_reason = halt_reason
    rm.current_drawdown = drawdown
    rm.current_equity = equity
    rm.daily_starting_equity = equity
    rm.validate_trade = MagicMock(return_value=(True, ""))
    rm.update_equity = MagicMock()
    rm.record_trade_outcome = MagicMock()
    return rm


def _mock_position_tracker(has_position=True, position_id="pos_1"):
    pt = MagicMock()
    pos = MagicMock()
    pos.id = position_id
    pos.symbol = "XAUUSD"
    pos.side = "long"
    pos.quantity = 1.0
    pos.entry_price = 2000.0
    pos.current_price = 2050.0
    pos.commission = 1.0
    pos.stop_loss = None
    pos.take_profit = None
    pos.realized_pnl = 50.0
    pt.get_position = MagicMock(return_value=pos if has_position else None)
    pt.add_position = AsyncMock()
    pt.close_position = AsyncMock(return_value=pos)
    return pt


def _make_executor(halted=False, drawdown=0.0, equity=100_000.0):
    broker = _mock_broker()
    rm = _mock_risk_manager(halted=halted, drawdown=drawdown, equity=equity)
    pt = _mock_position_tracker()
    return TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)


def _signal(**overrides):
    """Build an execution signal that carries a risk-approval token.

    TradeExecutor no longer manufactures a token when one is absent (audit
    finding S1-05) — an order with no proof it passed RiskManager.size_order()
    is rejected as unauthorized. Tests exercising the *execution* path must
    therefore supply one, exactly as the decision engine now does. Tests that
    want to assert the rejection should omit it deliberately.
    """
    sig = {
        "symbol": "XAUUSD",
        "action": "buy",
        "size": 1.0,
        "risk_approval_token": "rat-test-fixture",
    }
    sig.update(overrides)
    return sig


# ── ExecutionResult dataclass ──────────────────────────────────────────────────


class TestExecutionResult:
    def test_fields(self):
        r = ExecutionResult(
            success=True,
            order_id="o1",
            filled_quantity=1.0,
            average_price=2000.0,
            commission=1.0,
            status=OrderStatus.FILLED,
            message="ok",
        )
        assert r.success is True
        assert r.order_id == "o1"
        assert r.filled_quantity == pytest.approx(1.0)
        assert r.average_price == pytest.approx(2000.0)
        assert r.commission == pytest.approx(1.0)
        assert r.status == OrderStatus.FILLED
        assert r.message == "ok"
        assert r.latency_ms == pytest.approx(0.0)

    def test_default_latency_zero(self):
        r = ExecutionResult(
            success=False,
            order_id=None,
            filled_quantity=0,
            average_price=0,
            commission=0,
            status=OrderStatus.ERROR,
            message="err",
        )
        assert r.latency_ms == pytest.approx(0.0)


# ── OrderStatus enum ───────────────────────────────────────────────────────────


class TestOrderStatusEnum:
    def test_all_statuses(self):
        for s in ("pending", "submitted", "partial", "filled", "rejected", "cancelled", "error"):
            assert OrderStatus(s)


# ── execute_signal — validation ────────────────────────────────────────────────


class TestExecuteSignalValidation:
    @pytest.mark.asyncio
    async def test_missing_symbol_returns_error(self):
        ex = _make_executor()
        result = await ex.execute_signal({"action": "buy", "size": 1.0})
        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "Missing" in result.message

    @pytest.mark.asyncio
    async def test_missing_action_returns_error(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "size": 1.0})
        assert result.success is False
        assert "Missing" in result.message

    @pytest.mark.asyncio
    async def test_missing_size_returns_error(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy"})
        assert result.success is False
        assert "Missing" in result.message

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "hold", "size": 1.0})
        assert result.success is False
        assert "Invalid action" in result.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("size", [0, -1, float("nan"), float("inf"), "not-a-number"])
    async def test_invalid_size_is_rejected_before_risk_gate(self, size):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": size})
        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "Invalid size" in result.message

    @pytest.mark.asyncio
    async def test_latency_recorded_on_success(self):
        ex = _make_executor()
        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(return_value=None)
            result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.latency_ms >= 0.0


# ── execute_signal — buy path ──────────────────────────────────────────────────


class TestExecuteSignalBuy:
    @pytest.mark.asyncio
    async def test_buy_signal_success(self):
        ex = _make_executor()
        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(return_value=None)
            result = await ex.execute_signal(_signal(action="buy"))
        assert result.success is True
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_sell_signal_success(self):
        ex = _make_executor()
        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(return_value=None)
            result = await ex.execute_signal(_signal(action="sell"))
        assert result.success is True

    @pytest.mark.asyncio
    async def test_broker_rejected_order(self):
        broker = _mock_broker(filled=False)
        rm = _mock_risk_manager()
        pt = _mock_position_tracker()
        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(return_value=None)
            result = await ex.execute_signal(_signal(action="buy"))
        assert result.success is False
        # Must fail because the *broker* rejected it, not because the order was
        # unauthorized — otherwise this passes for the wrong reason.
        assert "UNAUTHORIZED" not in (result.message or "")

    @pytest.mark.asyncio
    async def test_order_without_risk_approval_token_is_rejected(self):
        """An order that never passed sizing must not reach the broker (S1-05)."""
        broker = _mock_broker()
        ex = TradeExecutor(
            broker=broker,
            risk_manager=_mock_risk_manager(),
            position_tracker=_mock_position_tracker(),
        )
        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(return_value=None)
            result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False
        assert "UNAUTHORIZED" in (result.message or "")
        broker.place_market_order.assert_not_awaited()


# ── execute_signal — close path ────────────────────────────────────────────────


class TestExecuteSignalClose:
    @pytest.mark.asyncio
    async def test_close_no_position_id_returns_error(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0})
        assert result.success is False
        assert "position_id" in result.message

    @pytest.mark.asyncio
    async def test_close_position_not_found_returns_error(self):
        ex = _make_executor()
        ex.position_tracker.get_position = MagicMock(return_value=None)
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0, "position_id": "ghost"})
        assert result.success is False
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_close_success(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0, "position_id": "pos_1"})
        assert result.success is True
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_close_broker_failure(self):
        ex = _make_executor()
        ex.broker.close_position = AsyncMock(return_value=False)
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0, "position_id": "pos_1"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_close_updates_risk_manager_equity(self):
        ex = _make_executor()
        await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0, "position_id": "pos_1"})
        ex.risk_manager.update_equity.assert_called_once()


# ── Drawdown circuit breaker ───────────────────────────────────────────────────


class TestDrawdownCircuitBreaker:
    def test_no_drawdown_not_blocked(self):
        ex = _make_executor(drawdown=0.0)
        blocked, msg = ex._check_drawdown_circuit_breaker()
        assert blocked is False
        assert msg == ""

    def test_drawdown_at_threshold_blocked(self):
        ex = _make_executor(drawdown=DRAWDOWN_HALT_PCT)
        blocked, msg = ex._check_drawdown_circuit_breaker()
        assert blocked is True
        assert "Drawdown" in msg

    def test_drawdown_above_threshold_blocked(self):
        ex = _make_executor(drawdown=DRAWDOWN_HALT_PCT + 0.01)
        blocked, msg = ex._check_drawdown_circuit_breaker()
        assert blocked is True

    def test_trading_halted_flag_blocks(self):
        ex = _make_executor(halted=True)
        ex.risk_manager._halt_reason = "manual halt"
        blocked, msg = ex._check_drawdown_circuit_breaker()
        assert blocked is True
        assert "halt" in msg.lower()

    def test_trigger_halt_sets_flag(self):
        ex = _make_executor(drawdown=DRAWDOWN_HALT_PCT)
        ex._trigger_drawdown_halt_if_needed()
        assert ex.risk_manager._trading_halted is True

    def test_trigger_halt_idempotent(self):
        ex = _make_executor(drawdown=DRAWDOWN_HALT_PCT)
        ex._trigger_drawdown_halt_if_needed()
        ex._trigger_drawdown_halt_if_needed()  # second call — no error
        assert ex.risk_manager._trading_halted is True

    def test_trigger_halt_below_threshold_no_op(self):
        ex = _make_executor(drawdown=0.01)
        ex._trigger_drawdown_halt_if_needed()
        # Should not set halted since drawdown < threshold
        assert ex.risk_manager._trading_halted is False

    @pytest.mark.asyncio
    async def test_drawdown_blocks_execute_signal(self):
        ex = _make_executor(drawdown=DRAWDOWN_HALT_PCT)
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False
        assert "DRAWDOWN" in result.message


# ── Streak circuit breaker ─────────────────────────────────────────────────────


class TestStreakCircuitBreaker:
    def test_no_streak_not_blocked(self):
        ex = _make_executor()
        blocked, msg = ex._check_streak_circuit_breaker()
        assert blocked is False

    def test_streak_halted_blocks(self):
        ex = _make_executor()
        ex._streak_halted_until = time.monotonic() + 3600
        blocked, msg = ex._check_streak_circuit_breaker()
        assert blocked is True
        assert "cooldown" in msg.lower() or "streak" in msg.lower()

    def test_streak_cooldown_expired_resets(self):
        ex = _make_executor()
        ex._streak_halted_until = time.monotonic() - 1  # already expired
        ex._consecutive_losses = 3
        blocked, msg = ex._check_streak_circuit_breaker()
        assert blocked is False
        assert ex._streak_halted_until is None
        assert ex._consecutive_losses == 0

    def test_update_streak_win_resets_counter(self):
        ex = _make_executor()
        ex._consecutive_losses = 2
        ex._update_streak(100.0)
        assert ex._consecutive_losses == 0

    def test_update_streak_loss_increments(self):
        ex = _make_executor()
        ex._update_streak(-50.0)
        assert ex._consecutive_losses == 1

    def test_update_streak_triggers_halt_at_threshold(self):
        ex = _make_executor()
        for _ in range(STREAK_HALT_LOSSES):
            ex._update_streak(-10.0)
        assert ex._streak_halted_until is not None
        assert ex._streak_halted_until > time.monotonic()

    def test_update_streak_win_after_losses_resets(self):
        ex = _make_executor()
        ex._consecutive_losses = 2
        ex._update_streak(50.0)
        assert ex._consecutive_losses == 0

    @pytest.mark.asyncio
    async def test_streak_blocks_execute_signal(self):
        ex = _make_executor()
        ex._streak_halted_until = time.monotonic() + 3600
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False
        assert "STREAK" in result.message


# ── _clamp_size_to_risk_cap ────────────────────────────────────────────────────


class TestClampSizeToRiskCap:
    def test_no_equity_returns_original_size(self):
        ex = _make_executor()
        ex.risk_manager.current_equity = 0
        ex.risk_manager.current_balance = 0
        ex.risk_manager.initial_balance = 0
        result = ex._clamp_size_to_risk_cap({"symbol": "XAUUSD"}, 10.0)
        assert result == pytest.approx(10.0)

    def test_with_sl_clamps_size(self):
        ex = _make_executor(equity=100_000.0)
        # entry=2000, sl=1900 → sl_pct=5%, max_loss=1000, max_size=1000/(2000*0.05)=10
        signal = {"symbol": "XAUUSD", "price": 2000.0, "stop_loss": 1900.0}
        result = ex._clamp_size_to_risk_cap(signal, 100.0)
        assert result < 100.0  # clamped

    def test_with_sl_below_cap_unchanged(self):
        ex = _make_executor(equity=100_000.0)
        signal = {"symbol": "XAUUSD", "price": 2000.0, "stop_loss": 1900.0}
        result = ex._clamp_size_to_risk_cap(signal, 0.001)
        assert result == pytest.approx(0.001)

    def test_notional_fallback_no_sl(self):
        ex = _make_executor(equity=100_000.0)
        signal = {"symbol": "XAUUSD", "price": 2000.0}
        result = ex._clamp_size_to_risk_cap(signal, 1000.0)
        # max_notional = 100000 * 0.01 = 1000, max_size = 1000/2000 = 0.5
        assert result < 1000.0

    def test_no_price_returns_original(self):
        ex = _make_executor(equity=100_000.0)
        result = ex._clamp_size_to_risk_cap({"symbol": "XAUUSD"}, 5.0)
        assert result == pytest.approx(5.0)

    def test_zero_sl_distance_returns_original(self):
        ex = _make_executor(equity=100_000.0)
        # SL == entry → zero distance
        signal = {"symbol": "XAUUSD", "price": 2000.0, "stop_loss": 2000.0}
        result = ex._clamp_size_to_risk_cap(signal, 5.0)
        assert result == pytest.approx(5.0)


# ── Callbacks ──────────────────────────────────────────────────────────────────


class TestCallbacks:
    def test_register_callback(self):
        ex = _make_executor()
        cb = MagicMock()
        ex.register_callback(cb)
        assert cb in ex._execution_callbacks

    @pytest.mark.asyncio
    async def test_sync_callback_called_on_success(self):
        ex = _make_executor()
        calls = []
        ex.register_callback(lambda r, s: calls.append(r))
        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(return_value=None)
            await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_async_callback_called(self):
        ex = _make_executor()
        calls = []

        async def async_cb(r, s):
            calls.append(r)

        ex.register_callback(async_cb)
        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(return_value=None)
            await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_callback_error_does_not_propagate(self):
        ex = _make_executor()

        def bad_cb(r, s):
            raise RuntimeError("callback boom")

        ex.register_callback(bad_cb)
        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(return_value=None)
            result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        # Should not raise — error is swallowed
        assert result is not None


# ── cancel_all_pending ─────────────────────────────────────────────────────────


class TestCancelAllPending:
    @pytest.mark.asyncio
    async def test_cancel_all_empty(self):
        ex = _make_executor()
        result = await ex.cancel_all_pending()
        assert result == []

    @pytest.mark.asyncio
    async def test_cancel_all_with_pending(self):
        ex = _make_executor()
        ex._pending_orders["ord_1"] = {"symbol": "XAUUSD", "side": "buy"}
        ex.broker.cancel_order = AsyncMock(return_value=True)
        result = await ex.cancel_all_pending()
        assert isinstance(result, list)


# ── get_risk_status ────────────────────────────────────────────────────────────


class TestGetRiskStatus:
    def test_returns_dict(self):
        ex = _make_executor()
        status = ex.get_risk_status()
        assert isinstance(status, dict)

    def test_contains_expected_keys(self):
        ex = _make_executor()
        status = ex.get_risk_status()
        assert "drawdown_halt_pct" in status
        assert "max_risk_pct_per_trade" in status
        assert "trading_halted" in status

    def test_drawdown_halt_pct_matches_constant(self):
        ex = _make_executor()
        status = ex.get_risk_status()
        assert status["drawdown_halt_pct"] == pytest.approx(DRAWDOWN_HALT_PCT)

    def test_max_risk_pct_matches_constant(self):
        ex = _make_executor()
        status = ex.get_risk_status()
        assert status["max_risk_pct_per_trade"] == pytest.approx(MAX_RISK_PCT_PER_TRADE)

    def test_trading_halted_false_when_normal(self):
        ex = _make_executor()
        status = ex.get_risk_status()
        assert status["trading_halted"] is False

    def test_trading_halted_true_when_halted(self):
        ex = _make_executor(halted=True)
        status = ex.get_risk_status()
        assert status["trading_halted"] is True

    def test_streak_halted_reflected(self):
        ex = _make_executor()
        ex._streak_halted_until = time.monotonic() + 3600
        status = ex.get_risk_status()
        assert status.get("streak_halted") is True

    def test_consecutive_losses_in_status(self):
        ex = _make_executor()
        ex._consecutive_losses = 2
        status = ex.get_risk_status()
        assert status.get("consecutive_losses") == 2


# ── Pre-trade gate integration ─────────────────────────────────────────────────


class TestPreTradeGateIntegration:
    @pytest.mark.asyncio
    async def test_trade_blocked_error_returns_rejected(self):
        ex = _make_executor()
        from risk.pre_trade_gate import TradeBlockedError

        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            err = TradeBlockedError("KILL_SWITCH", "kill switch active")
            MockGate.return_value.check = MagicMock(side_effect=err)
            result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "KILL_SWITCH" in result.message

    @pytest.mark.asyncio
    async def test_risk_manager_error_returns_rejected(self):
        ex = _make_executor()
        from risk.pre_trade_gate import RiskManagerError

        with patch("risk.pre_trade_gate.PreTradeGate") as MockGate:
            MockGate.return_value.check = MagicMock(side_effect=RiskManagerError("rm error"))
            result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_zero_size_after_risk_cap_rejected(self):
        ex = _make_executor(equity=100_000.0)
        with patch.object(ex, "_clamp_size_to_risk_cap", return_value=0.0):
            result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False
        assert "RISK_CAP" in result.message
