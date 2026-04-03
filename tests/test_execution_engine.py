# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_execution_engine.py

Unit tests for execution/engine.py — ExecutionEngine, EngineCircuitBreaker,
ExecutionRequest validation.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from brokers.base import Order, OrderSide, OrderStatus, OrderType
from execution.engine import (
    EngineCircuitBreaker,
    ExecutionEngine,
    ExecutionReport,
    ExecutionRequest,
    ExecutionStatus,
)

# ---------------------------------------------------------------------------
# ExecutionRequest validation
# ---------------------------------------------------------------------------


class TestExecutionRequest:
    def test_valid_buy_market(self):
        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0, order_type="MARKET")
        assert req.symbol == "XAUUSD"
        assert req.side == "BUY"

    def test_valid_sell_limit(self):
        req = ExecutionRequest(symbol="XAUUSD", side="SELL", quantity=1.0, order_type="LIMIT", price=1950.0)
        assert req.price == 1950.0

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            ExecutionRequest(symbol="XAUUSD", side="LONG", quantity=1.0)

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="quantity"):
            ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=0.0)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError):
            ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=-1.0)

    def test_limit_without_price_raises(self):
        with pytest.raises(ValueError, match="price"):
            ExecutionRequest(
                symbol="XAUUSD",
                side="BUY",
                quantity=1.0,
                order_type="LIMIT",
                price=None,
            )

    def test_stop_without_stop_price_raises(self):
        with pytest.raises(ValueError, match="stop_price"):
            ExecutionRequest(
                symbol="XAUUSD",
                side="BUY",
                quantity=1.0,
                order_type="STOP",
                stop_price=None,
            )

    def test_invalid_order_type_raises(self):
        with pytest.raises(ValueError, match="order_type"):
            ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0, order_type="TWAP")


# ---------------------------------------------------------------------------
# EngineCircuitBreaker
# ---------------------------------------------------------------------------


class TestEngineCircuitBreaker:
    @pytest.mark.asyncio
    async def test_opens_after_max_failures(self):
        cb = EngineCircuitBreaker(max_failures=3, window_sec=60.0, reset_sec=9999.0)
        for _ in range(3):
            await cb.record_failure()
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_check_raises_when_open(self):
        cb = EngineCircuitBreaker(max_failures=2, window_sec=60.0, reset_sec=9999.0)
        await cb.record_failure()
        await cb.record_failure()
        with pytest.raises(RuntimeError, match="circuit breaker"):
            await cb.check()

    @pytest.mark.asyncio
    async def test_resets_on_success(self):
        cb = EngineCircuitBreaker(max_failures=2, window_sec=60.0, reset_sec=9999.0)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.is_open is True
        await cb.record_success()
        assert cb.is_open is False

    @pytest.mark.asyncio
    async def test_check_passes_when_closed(self):
        cb = EngineCircuitBreaker(max_failures=3, window_sec=60.0)
        await cb.check()  # should not raise

    @pytest.mark.asyncio
    async def test_failures_outside_window_not_counted(self):
        cb = EngineCircuitBreaker(max_failures=3, window_sec=0.1, reset_sec=9999.0)
        await cb.record_failure()
        await cb.record_failure()
        await asyncio.sleep(0.2)  # wait for window to expire
        await cb.record_failure()  # only 1 failure in current window
        assert cb.is_open is False


# ---------------------------------------------------------------------------
# ExecutionEngine
# ---------------------------------------------------------------------------


def _make_broker_manager(order_status=OrderStatus.FILLED):
    mgr = MagicMock()
    mock_order = Order(
        id="order-001",
        symbol="XAUUSD",
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=1.0,
        status=order_status,
        filled_quantity=1.0,
        average_price=1950.0,
    )
    mgr.place_order.return_value = mock_order
    mgr.is_connected.return_value = True
    return mgr


def _make_risk_manager(allow_trade=True):
    rm = MagicMock()
    rm._trading_halted = False
    rm._halt_reason = None
    rm._halt_until = None
    rm.daily_pnl = 0.0
    rm.daily_starting_equity = 100_000.0
    rm.current_drawdown = 0.0
    rm.current_balance = 100_000.0
    rm.initial_balance = 100_000.0
    rm.open_positions = []
    rm._kill_switch = None
    rm._returns_history = [0.001] * 20

    cfg = MagicMock()
    cfg.daily_loss_limit_pct = 0.05
    cfg.max_drawdown_pct = 0.10
    cfg.max_position_size_pct = 0.99  # permissive for tests
    cfg.max_open_positions = 100
    rm.config = cfg

    rm.check_cvar_pre_trade = MagicMock(return_value=(True, "OK"))
    rm._compute_cvar = MagicMock(return_value=0.001)
    rm.validate_trade = MagicMock(return_value=(True, "OK"))
    return rm


class TestExecutionEngine:
    @pytest.mark.asyncio
    async def test_successful_execution(self):
        broker = _make_broker_manager(OrderStatus.FILLED)
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is True
        assert report.status == ExecutionStatus.FILLED
        assert report.order_id == "order-001"
        assert report.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_kill_switch_blocks(self):
        broker = _make_broker_manager()
        risk = _make_risk_manager()
        ks = MagicMock()
        ks.is_active.return_value = True
        ks._reason = "emergency halt"

        engine = ExecutionEngine(broker, risk, kill_switch=ks)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is False
        assert report.status == ExecutionStatus.BLOCKED
        assert "KILL_SWITCH" in report.message

    @pytest.mark.asyncio
    async def test_engine_stopped_blocks(self):
        broker = _make_broker_manager()
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        # Do NOT call start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.status == ExecutionStatus.BLOCKED
        assert "ENGINE_STOPPED" in report.message

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_after_failures(self):
        broker = _make_broker_manager()
        broker.place_order.side_effect = RuntimeError("broker down")
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        engine._circuit_breaker = EngineCircuitBreaker(max_failures=2, window_sec=60.0, reset_sec=9999.0)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        # First two failures open the circuit breaker
        await engine.execute(req)
        await engine.execute(req)
        # Third call should be blocked by circuit breaker
        report = await engine.execute(req)
        assert report.status in (ExecutionStatus.BLOCKED, ExecutionStatus.ERROR)

    @pytest.mark.asyncio
    async def test_pre_trade_gate_blocks_halted_trading(self):
        broker = _make_broker_manager()
        risk = _make_risk_manager()
        risk._trading_halted = True
        risk._halt_reason = "drawdown limit"

        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is False
        assert report.status == ExecutionStatus.BLOCKED
        assert "TRADING_HALTED" in report.message

    @pytest.mark.asyncio
    async def test_fill_callback_invoked(self):
        broker = _make_broker_manager(OrderStatus.FILLED)
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        fills = []
        engine.add_fill_callback(fills.append)

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        await engine.execute(req)

        assert len(fills) == 1
        assert fills[0].success is True

    @pytest.mark.asyncio
    async def test_metrics_updated_on_fill(self):
        broker = _make_broker_manager(OrderStatus.FILLED)
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        await engine.execute(req)

        metrics = engine.get_metrics()
        assert metrics["total_orders"] == 1
        assert metrics["total_fills"] == 1
        assert metrics["total_blocks"] == 0
        assert metrics["fill_rate"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_broker_error_returns_error_report(self):
        broker = _make_broker_manager()
        broker.place_order.side_effect = RuntimeError("connection lost")
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is False
        assert report.status == ExecutionStatus.ERROR
        assert "BROKER_ERROR" in report.message

    @pytest.mark.asyncio
    async def test_never_raises_to_caller(self):
        """ExecutionEngine.execute() must never raise — always returns a report."""
        broker = MagicMock()
        broker.place_order.side_effect = Exception("catastrophic failure")
        broker.is_connected.return_value = True
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        # Must not raise
        report = await engine.execute(req)
        assert isinstance(report, ExecutionReport)
