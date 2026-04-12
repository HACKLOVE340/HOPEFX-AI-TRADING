# tests/unit/test_execution_coverage11.py
"""Targeted coverage for trade_executor._execute_open success path and _execute_close."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_rm(drawdown=0.0, halted=False):
    rm = MagicMock()
    rm.current_drawdown = drawdown
    rm._trading_halted = halted
    rm._halt_reason = None
    rm.current_equity = 100000.0
    rm.current_balance = 100000.0
    rm.initial_balance = 100000.0
    rm.daily_starting_equity = 100000.0
    rm.update_equity = MagicMock()
    rm.record_trade_outcome = MagicMock()
    return rm


def _make_broker_filled(fill_price=2350.0):
    broker = MagicMock()
    order_result = MagicMock()
    order_result.status.value = "filled"
    order_result.id = "ord_filled"
    order_result.filled_quantity = 0.01
    order_result.average_fill_price = fill_price
    order_result.commission = 0.5
    broker.place_market_order = AsyncMock(return_value=order_result)
    broker.close_position = AsyncMock(return_value=True)
    return broker


def _make_pt(has_position=False, current_price=2360.0):
    pt = MagicMock()
    if has_position:
        pos = MagicMock()
        pos.quantity = 0.01
        pos.current_price = current_price
        pos.commission = 0.5
        pos.entry_price = 2350.0
        pos.side = "long"
        pos.signal_confidence = 0.8
        pos.symbol = "XAUUSD"
        pt.get_position = MagicMock(return_value=pos)
        closed = MagicMock()
        closed.realized_pnl = 100.0
        closed.entry_price = 2350.0
        closed.side = "long"
        closed.symbol = "XAUUSD"
        closed.signal_confidence = 0.8
        pt.close_position = AsyncMock(return_value=closed)
    else:
        pt.get_position = MagicMock(return_value=None)
        pt.close_position = AsyncMock(return_value=None)
    pt.add_position = AsyncMock()
    pt.update_position = MagicMock()
    pt.get_all_positions = MagicMock(return_value={})
    return pt


class TestExecuteOpenSuccessPath:
    """Patch PreTradeGate.check to pass so the broker placement path is covered."""

    @pytest.mark.asyncio
    async def test_buy_order_filled(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt()

        with patch("risk.pre_trade_gate.PreTradeGate.check", return_value=None):
            ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
            result = await ex.execute_signal(
                {
                    "action": "buy",
                    "symbol": "XAUUSD",
                    "size": 0.01,
                    "entry_price": 2350.0,
                    "stop_loss": 2340.0,
                    "take_profit": 2370.0,
                    "confidence": 0.8,
                }
            )
        assert result.success is True
        assert result.order_id == "ord_filled"

    @pytest.mark.asyncio
    async def test_sell_order_filled(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt()

        with patch("risk.pre_trade_gate.PreTradeGate.check", return_value=None):
            ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
            result = await ex.execute_signal(
                {
                    "action": "sell",
                    "symbol": "XAUUSD",
                    "size": 0.01,
                    "entry_price": 2350.0,
                    "stop_loss": 2360.0,
                    "take_profit": 2330.0,
                    "confidence": 0.75,
                }
            )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_partial_fill_result(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = MagicMock()
        order_result = MagicMock()
        order_result.status.value = "partial"
        order_result.id = "ord_partial"
        order_result.filled_quantity = 0.005
        order_result.average_fill_price = 2350.0
        order_result.commission = 0.25
        broker.place_market_order = AsyncMock(return_value=order_result)
        pt = _make_pt()

        with patch("risk.pre_trade_gate.PreTradeGate.check", return_value=None):
            ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
            result = await ex.execute_signal(
                {
                    "action": "buy",
                    "symbol": "XAUUSD",
                    "size": 0.01,
                    "entry_price": 2350.0,
                    "confidence": 0.8,
                }
            )
        assert result.success is True  # partial counts as success

    @pytest.mark.asyncio
    async def test_rejected_fill_result(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = MagicMock()
        order_result = MagicMock()
        order_result.status.value = "rejected"
        order_result.id = "ord_rej"
        order_result.filled_quantity = 0.0
        order_result.average_fill_price = 0.0
        order_result.commission = 0.0
        broker.place_market_order = AsyncMock(return_value=order_result)
        pt = _make_pt()

        with patch("risk.pre_trade_gate.PreTradeGate.check", return_value=None):
            ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
            result = await ex.execute_signal(
                {
                    "action": "buy",
                    "symbol": "XAUUSD",
                    "size": 0.01,
                    "entry_price": 2350.0,
                    "confidence": 0.8,
                }
            )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_gate_blocks_trade_blocked_error(self):
        from execution.trade_executor import TradeExecutor
        from risk.pre_trade_gate import TradeBlockedError

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt()

        err = TradeBlockedError(reason_code="MAX_POSITIONS", detail="too many open")
        with patch("risk.pre_trade_gate.PreTradeGate.check", side_effect=err):
            ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
            result = await ex.execute_signal(
                {
                    "action": "buy",
                    "symbol": "XAUUSD",
                    "size": 0.01,
                    "entry_price": 2350.0,
                    "confidence": 0.8,
                }
            )
        assert result.success is False
        assert "MAX_POSITIONS" in result.message

    @pytest.mark.asyncio
    async def test_gate_risk_manager_error(self):
        from execution.trade_executor import TradeExecutor
        from risk.pre_trade_gate import RiskManagerError

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt()

        err = RiskManagerError("internal error")
        with patch("risk.pre_trade_gate.PreTradeGate.check", side_effect=err):
            ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
            result = await ex.execute_signal(
                {
                    "action": "buy",
                    "symbol": "XAUUSD",
                    "size": 0.01,
                    "entry_price": 2350.0,
                    "confidence": 0.8,
                }
            )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_missing_fields_returns_error(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt()
        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        result = await ex.execute_signal({"symbol": "XAUUSD"})  # missing action, size
        assert result.success is False
        assert "Missing" in result.message

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt()
        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        result = await ex.execute_signal({"action": "open", "symbol": "XAUUSD", "size": 0.01})
        assert result.success is False
        assert "Invalid action" in result.message

    @pytest.mark.asyncio
    async def test_callback_fires_on_success(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt()
        fired = []

        with patch("risk.pre_trade_gate.PreTradeGate.check", return_value=None):
            ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
            ex.register_callback(lambda r, s: fired.append(r))
            await ex.execute_signal(
                {
                    "action": "buy",
                    "symbol": "XAUUSD",
                    "size": 0.01,
                    "entry_price": 2350.0,
                    "confidence": 0.8,
                }
            )
        assert len(fired) == 1
        assert fired[0].success is True


class TestExecuteClose:
    @pytest.mark.asyncio
    async def test_close_success(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt(has_position=True)

        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        result = await ex.execute_signal(
            {
                "action": "close",
                "symbol": "XAUUSD",
                "size": 0.01,
                "position_id": "pos1",
            }
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_close_position_not_found(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt(has_position=False)

        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        result = await ex.execute_signal(
            {
                "action": "close",
                "symbol": "XAUUSD",
                "size": 0.01,
                "position_id": "nonexistent",
            }
        )
        assert result is not None
        assert result.success is False

    @pytest.mark.asyncio
    async def test_close_updates_streak(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = _make_broker_filled()
        pt = _make_pt(has_position=True)

        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        await ex.execute_signal(
            {
                "action": "close",
                "symbol": "XAUUSD",
                "size": 0.01,
                "position_id": "pos1",
            }
        )
        # Winning trade → consecutive_losses reset to 0
        assert ex._consecutive_losses == 0

    @pytest.mark.asyncio
    async def test_close_broker_returns_false(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = MagicMock()
        broker.close_position = AsyncMock(return_value=False)
        pt = _make_pt(has_position=True)

        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        result = await ex.execute_signal(
            {
                "action": "close",
                "symbol": "XAUUSD",
                "size": 0.01,
                "position_id": "pos1",
            }
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_cancel_all_pending_calls_broker(self):
        from execution.trade_executor import TradeExecutor

        rm = _make_rm()
        broker = MagicMock()
        broker.cancel_all_orders = AsyncMock(return_value=["ord1", "ord2"])
        pt = _make_pt()

        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        result = await ex.cancel_all_pending()
        assert isinstance(result, list)
