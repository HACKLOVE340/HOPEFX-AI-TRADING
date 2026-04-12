# tests/unit/test_execution_coverage9.py
"""Coverage tests for execution/trade_executor.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_risk_manager(allow=True, drawdown=0.0, balance=100000.0, halted=False):
    rm = MagicMock()
    rm.check_pre_trade = MagicMock(return_value=(allow, "ok" if allow else "blocked"))
    rm.get_account_balance = MagicMock(return_value=balance)
    rm.current_drawdown = drawdown  # attribute, not method
    rm._trading_halted = halted
    rm._halt_reason = None
    rm.validate_trade = MagicMock(return_value=(True, "ok"))
    rm.get_daily_loss = MagicMock(return_value=0.0)
    rm.get_open_positions_count = MagicMock(return_value=0)
    rm.get_cvar = MagicMock(return_value=0.0)
    rm.get_max_drawdown = MagicMock(return_value=0.0)
    return rm


def _make_broker(fill_price=2350.0, success=True):
    broker = MagicMock()
    result = MagicMock()
    result.fill_price = fill_price
    result.order_id = "ord_test"
    result.status = "filled" if success else "rejected"
    broker.place_order = AsyncMock(return_value=result if success else None)
    broker.close_position = AsyncMock(return_value=result)
    broker.get_open_positions = AsyncMock(return_value=[])
    return broker


def _make_position_tracker():
    pt = MagicMock()
    pt.get_position = MagicMock(return_value=None)
    pt.open_position = MagicMock()
    pt.close_position = MagicMock(return_value=MagicMock(realized_pnl=100.0))
    pt.update_position = MagicMock()
    pt.get_all_positions = MagicMock(return_value={})
    return pt


def _executor(allow=True, drawdown=0.0, halted=False):
    from execution.trade_executor import TradeExecutor

    rm = _make_risk_manager(allow=allow, drawdown=drawdown, halted=halted)
    broker = _make_broker()
    pt = _make_position_tracker()
    return TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)


class TestTradeExecutorBasic:
    @pytest.mark.asyncio
    async def test_execute_buy_signal(self):
        ex = _executor()
        result = await ex.execute_signal(
            {
                "action": "open",
                "symbol": "XAUUSD",
                "direction": "long",
                "size": 0.01,
                "entry_price": 2350.0,
                "stop_loss": 2340.0,
                "take_profit": 2370.0,
                "confidence": 0.8,
            }
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_sell_signal(self):
        ex = _executor()
        result = await ex.execute_signal(
            {
                "action": "open",
                "symbol": "XAUUSD",
                "direction": "short",
                "size": 0.01,
                "entry_price": 2350.0,
                "stop_loss": 2360.0,
                "take_profit": 2330.0,
                "confidence": 0.75,
            }
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_close_signal(self):
        ex = _executor()
        await ex.execute_signal(
            {
                "action": "open",
                "symbol": "XAUUSD",
                "direction": "long",
                "size": 0.01,
                "entry_price": 2350.0,
                "confidence": 0.8,
            }
        )
        result = await ex.execute_signal(
            {
                "action": "close",
                "symbol": "XAUUSD",
                "direction": "long",
                "close_price": 2360.0,
            }
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_risk_blocked_returns_failure(self):
        ex = _executor(allow=False)
        result = await ex.execute_signal(
            {
                "action": "open",
                "symbol": "XAUUSD",
                "direction": "long",
                "size": 0.01,
                "entry_price": 2350.0,
                "confidence": 0.8,
            }
        )
        assert result is not None
        assert not result.success

    @pytest.mark.asyncio
    async def test_kill_switch_blocks(self):
        ex = _executor()
        with patch("kill_switch.KillSwitch") as MockKS:
            ks_instance = MagicMock()
            ks_instance.is_active.return_value = True
            ks_instance.reason = "manual halt"
            MockKS.return_value = ks_instance
            result = await ex.execute_signal(
                {
                    "action": "open",
                    "symbol": "XAUUSD",
                    "direction": "long",
                    "size": 0.01,
                    "entry_price": 2350.0,
                    "confidence": 0.8,
                }
            )
            assert result is not None
            assert not result.success

    def test_get_risk_status(self):
        ex = _executor()
        status = ex.get_risk_status()
        assert isinstance(status, dict)

    def test_register_callback(self):
        ex = _executor()
        cb = MagicMock()
        ex.register_callback(cb)
        # callback registered — no error

    @pytest.mark.asyncio
    async def test_cancel_all_pending(self):
        ex = _executor()
        result = await ex.cancel_all_pending()
        assert isinstance(result, list)

    def test_check_drawdown_circuit_breaker_ok(self):
        ex = _executor(drawdown=0.01)
        halted, reason = ex._check_drawdown_circuit_breaker()
        assert not halted

    def test_check_drawdown_circuit_breaker_triggered(self):
        ex = _executor(drawdown=0.10)
        halted, reason = ex._check_drawdown_circuit_breaker()
        assert halted

    def test_check_drawdown_halted_flag(self):
        ex = _executor(halted=True)
        halted, reason = ex._check_drawdown_circuit_breaker()
        assert halted

    def test_check_streak_circuit_breaker_no_streak(self):
        ex = _executor()
        halted, reason = ex._check_streak_circuit_breaker()
        assert not halted

    def test_update_streak_win(self):
        ex = _executor()
        ex._update_streak(100.0)
        assert ex._consecutive_losses == 0

    def test_update_streak_loss(self):
        ex = _executor()
        ex._update_streak(-100.0)
        assert ex._consecutive_losses == 1

    def test_clamp_size_to_risk_cap(self):
        ex = _executor()
        signal = {"size": 100.0, "entry_price": 2350.0, "stop_loss": 2340.0}
        clamped = ex._clamp_size_to_risk_cap(signal, 100.0)
        assert clamped <= 100.0

    @pytest.mark.asyncio
    async def test_notify_callbacks(self):
        from execution.trade_executor import ExecutionResult, OrderStatus

        ex = _executor()
        fired = []
        ex.register_callback(lambda r, s: fired.append(r))
        result = ExecutionResult(
            success=True,
            order_id="o1",
            filled_quantity=0.01,
            average_price=2350.0,
            commission=0.5,
            status=OrderStatus.FILLED,
            message="ok",
        )
        await ex._notify_callbacks(result, {"symbol": "XAUUSD"})
        assert len(fired) == 1

    @pytest.mark.asyncio
    async def test_broker_exception_returns_failure(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_risk_manager(allow=True)
        broker = MagicMock()
        broker.place_order = AsyncMock(side_effect=ConnectionError("broker down"))
        pt = _make_position_tracker()
        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        result = await ex.execute_signal(
            {
                "action": "open",
                "symbol": "XAUUSD",
                "direction": "long",
                "size": 0.01,
                "entry_price": 2350.0,
                "confidence": 0.8,
            }
        )
        assert result is not None
        assert not result.success

    def test_trigger_drawdown_halt_if_needed(self):
        ex = _executor(drawdown=0.10)
        ex._trigger_drawdown_halt_if_needed()  # should not raise

    def test_streak_halt_after_losses(self):
        ex = _executor()
        for _ in range(10):
            ex._update_streak(-100.0)
        halted, reason = ex._check_streak_circuit_breaker()
        assert halted
