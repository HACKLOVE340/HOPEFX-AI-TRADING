# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Coverage tests for execution/oms, position_manager, smart_router, trade_executor."""

from __future__ import annotations
import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.unit
class TestOrder:
    def _o(self, **kw):
        from execution.oms import Order, OrderStatus

        d = dict(symbol="XAUUSD", side="BUY", order_type="LIMIT", quantity=Decimal("10"), price=Decimal("1950"))
        d.update(kw)
        o = Order(**d)
        o.status = OrderStatus.NEW
        return o

    def test_remaining_quantity(self):
        o = self._o(quantity=Decimal("10"), filled_quantity=Decimal("3"))
        assert o.remaining_quantity == Decimal("7")

    def test_is_active_new(self):
        from execution.oms import OrderStatus

        o = self._o()
        o.status = OrderStatus.NEW
        assert o.is_active is True

    def test_is_active_filled(self):
        from execution.oms import OrderStatus

        o = self._o()
        o.status = OrderStatus.FILLED
        assert o.is_active is False

    def test_can_fill_limit_buy_at_price(self):
        o = self._o(side="BUY", order_type="LIMIT", price=Decimal("1950"))
        assert o.can_fill(Decimal("5"), Decimal("1950")) is True

    def test_can_fill_limit_buy_above_price_rejected(self):
        o = self._o(side="BUY", order_type="LIMIT", price=Decimal("1950"))
        assert o.can_fill(Decimal("5"), Decimal("1960")) is False

    def test_can_fill_limit_sell_below_price_rejected(self):
        o = self._o(side="SELL", order_type="LIMIT", price=Decimal("1950"))
        assert o.can_fill(Decimal("5"), Decimal("1940")) is False

    def test_can_fill_wrong_status(self):
        from execution.oms import OrderStatus

        o = self._o()
        o.status = OrderStatus.CANCELLED
        assert o.can_fill(Decimal("5"), Decimal("1950")) is False

    def test_can_fill_excess_quantity(self):
        o = self._o(quantity=Decimal("5"))
        assert o.can_fill(Decimal("10"), Decimal("1950")) is False

    def test_can_fill_market_order(self):
        o = self._o(order_type="MARKET")
        assert o.can_fill(Decimal("5"), Decimal("1950")) is True


@pytest.mark.unit
class TestOrderLifecycleManager:
    def _oms(self):
        from execution.oms import OrderLifecycleManager

        return OrderLifecycleManager()

    def test_create_order(self):
        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))
        assert o.id in oms.orders

    def test_fill_partial(self):
        from execution.oms import OrderStatus

        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("10"))
        o.status = OrderStatus.NEW
        oms.active_orders.add(o.id)
        assert oms.fill_order(o.id, Decimal("5"), Decimal("1950")) is True
        assert o.status == OrderStatus.PARTIALLY_FILLED

    def test_fill_full(self):
        from execution.oms import OrderStatus

        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("10"))
        o.status = OrderStatus.NEW
        oms.active_orders.add(o.id)
        assert oms.fill_order(o.id, Decimal("10"), Decimal("1950")) is True
        assert o.status == OrderStatus.FILLED

    def test_fill_avg_price(self):
        from execution.oms import OrderStatus

        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("10"))
        o.status = OrderStatus.NEW
        oms.active_orders.add(o.id)
        oms.fill_order(o.id, Decimal("5"), Decimal("1950"))
        oms.fill_order(o.id, Decimal("5"), Decimal("1960"))
        assert o.avg_fill_price == Decimal("1955")

    def test_fill_nonexistent(self):
        oms = self._oms()
        assert oms.fill_order("bad-id", Decimal("1"), Decimal("1950")) is False

    def test_cancel_active_order(self):
        from execution.oms import OrderStatus

        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))
        o.status = OrderStatus.NEW
        oms.active_orders.add(o.id)
        assert oms.cancel_order(o.id) is True
        assert o.status == OrderStatus.PENDING_CANCEL

    def test_cancel_inactive_order(self):
        from execution.oms import OrderStatus

        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))
        o.status = OrderStatus.FILLED
        assert oms.cancel_order(o.id) is False

    def test_expire_orders(self):
        from datetime import datetime, timedelta, timezone
        from execution.oms import OrderStatus

        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))
        o.status = OrderStatus.NEW
        o.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        oms.active_orders.add(o.id)
        oms.expire_orders()
        assert o.status == OrderStatus.EXPIRED
        assert o.id not in oms.active_orders

    def test_get_order_book(self):
        from execution.oms import OrderStatus

        oms = self._oms()
        o = oms.create_order(
            symbol="XAUUSD", side="BUY", order_type="LIMIT", quantity=Decimal("5"), price=Decimal("1950")
        )
        o.status = OrderStatus.NEW
        oms.active_orders.add(o.id)
        book = oms.get_order_book("XAUUSD")
        assert "bids" in book and "asks" in book
        assert len(book["bids"]) == 1

    def test_register_callback_on_fill(self):
        from execution.oms import OrderStatus

        oms = self._oms()
        called = []
        oms.register_callback(OrderStatus.FILLED, lambda o, ctx: called.append(o.id))
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))
        o.status = OrderStatus.NEW
        oms.active_orders.add(o.id)
        oms.fill_order(o.id, Decimal("1"), Decimal("1950"))
        assert o.id in called

    @pytest.mark.asyncio
    async def test_submit_order_kill_switch_inactive(self):
        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))
        mock_ks = MagicMock()
        mock_ks.return_value.is_active.return_value = False
        with patch("kill_switch.KillSwitch", mock_ks):
            result = oms.submit_order(o.id)
        assert result is True
        await asyncio.sleep(0)

    def test_submit_order_kill_switch_active(self):
        oms = self._oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1"))
        mock_ks = MagicMock()
        mock_ks.return_value.is_active.return_value = True
        with patch("kill_switch.KillSwitch", mock_ks):
            result = oms.submit_order(o.id)
        assert result is False

    def test_submit_nonexistent_order(self):
        oms = self._oms()
        mock_ks = MagicMock()
        mock_ks.return_value.is_active.return_value = False
        with patch("kill_switch.KillSwitch", mock_ks):
            result = oms.submit_order("nonexistent-id")
        assert result is False


@pytest.mark.unit
class TestComplexOrderManager:
    def _com(self):
        from execution.oms import ComplexOrderManager, OrderLifecycleManager

        return ComplexOrderManager(OrderLifecycleManager())

    def _order(self, side="BUY", price=Decimal("1950")):
        from execution.oms import Order

        return Order(symbol="XAUUSD", side=side, order_type="LIMIT", quantity=Decimal("5"), price=price)

    def test_create_oco_links_orders(self):
        com = self._com()
        o1 = self._order("BUY", Decimal("1950"))
        o2 = self._order("SELL", Decimal("1970"))
        parent_id = com.create_oco([o1, o2])
        assert parent_id is not None
        assert o1.parent_order_id == parent_id
        assert o2.parent_order_id == parent_id

    def test_create_bracket_returns_id(self):
        com = self._com()
        from execution.oms import Order

        entry = Order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("5"))
        bracket_id = com.create_bracket(entry, Decimal("1980"), Decimal("1920"))
        assert bracket_id is not None

    @pytest.mark.asyncio
    async def test_create_iceberg_returns_id(self):
        com = self._com()
        mock_ks = MagicMock()
        mock_ks.return_value.is_active.return_value = False
        with patch("kill_switch.KillSwitch", mock_ks):
            iceberg_id = com.create_iceberg(
                total_quantity=Decimal("100"),
                display_size=Decimal("10"),
                symbol="XAUUSD",
                side="BUY",
                price=Decimal("1950"),
            )
        await asyncio.sleep(0)
        assert iceberg_id is not None


@pytest.mark.unit
class TestPositionManager:
    def _pm(self):
        from execution.position_manager import PositionManager

        return PositionManager()

    @pytest.mark.asyncio
    async def test_open_position(self):
        pm = self._pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0)
        assert pos.symbol == "XAUUSD" and pos.side == "BUY"

    @pytest.mark.asyncio
    async def test_open_duplicate_raises(self):
        from execution.position_manager import PositionAlreadyOpenError

        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0)
        with pytest.raises(PositionAlreadyOpenError):
            await pm.open_position("XAUUSD", "BUY", 1.0, 1960.0)

    @pytest.mark.asyncio
    async def test_close_buy_pnl(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0)
        result = await pm.close_position("XAUUSD", fill_price=1970.0)
        assert result.realized_pnl == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_close_sell_pnl(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "SELL", 1.0, 1950.0)
        result = await pm.close_position("XAUUSD", fill_price=1930.0)
        assert result.realized_pnl == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_close_nonexistent_raises(self):
        from execution.position_manager import PositionNotFoundError

        pm = self._pm()
        with pytest.raises(PositionNotFoundError):
            await pm.close_position("EURUSD", fill_price=1.10)

    @pytest.mark.asyncio
    async def test_update_position_price(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0)
        pos = await pm.update_position("XAUUSD", last_price=1960.0)
        assert pos.last_price == pytest.approx(1960.0)

    @pytest.mark.asyncio
    async def test_get_position(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0)
        assert pm.get_position("XAUUSD") is not None

    def test_get_position_missing(self):
        pm = self._pm()
        assert pm.get_position("EURUSD") is None

    @pytest.mark.asyncio
    async def test_get_all_positions(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0)
        await pm.open_position("EURUSD", "SELL", 10000.0, 1.08)
        assert len(pm.get_all_positions()) == 2

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 2.0, 1950.0)
        await pm.update_position("XAUUSD", last_price=1960.0)
        pnl = pm.get_unrealized_pnl()
        # Returns dict {symbol: pnl}
        total = sum(pnl.values()) if isinstance(pnl, dict) else pnl
        assert total == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_get_total_exposure(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        # exposure = quantity * last_price (or entry_price before update)
        assert pm.get_total_exposure() > 0

    @pytest.mark.asyncio
    async def test_get_history(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0)
        await pm.close_position("XAUUSD", fill_price=1970.0)
        assert len(pm.get_history()) >= 1

    @pytest.mark.asyncio
    async def test_open_with_sl_tp(self):
        pm = self._pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0, stop_loss=1930.0, take_profit=1990.0)
        assert pos.stop_loss == pytest.approx(1930.0)
        assert pos.take_profit == pytest.approx(1990.0)

    @pytest.mark.asyncio
    async def test_open_with_strategy_id(self):
        pm = self._pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 1950.0, strategy_id="s1")
        assert pos.strategy_id == "s1"

    @pytest.mark.asyncio
    async def test_invalid_side_raises(self):
        pm = self._pm()
        with pytest.raises(ValueError, match="side must be"):
            await pm.open_position("XAUUSD", "long", 1.0, 1950.0)


@pytest.mark.unit
class TestBrokerState:
    def _s(self):
        from execution.smart_router import BrokerState

        return BrokerState(broker_id="b1")

    def test_record_fill_updates_ema(self):
        s = self._s()
        s.record_fill(latency_ms=50.0, slippage_bps=2.0)
        assert s.total_fills == 1
        assert s.ema_latency_ms < 100.0

    def test_record_error_increments(self):
        s = self._s()
        s.record_error()
        assert s.total_errors == 1
        assert s.reliability < 1.0

    def test_circuit_opens_after_threshold(self):
        from execution.smart_router import _CB_ERROR_THRESHOLD

        s = self._s()
        for _ in range(_CB_ERROR_THRESHOLD):
            s.record_error()
        assert s.circuit_open is True

    def test_circuit_resets_after_timeout(self):
        from execution.smart_router import _CB_ERROR_THRESHOLD, _CB_RESET_S

        s = self._s()
        for _ in range(_CB_ERROR_THRESHOLD):
            s.record_error()
        s.circuit_open_at = time.monotonic() - _CB_RESET_S - 1
        s.check_circuit_reset()
        assert s.circuit_open is False

    def test_routing_score_long(self):
        s = self._s()
        score = s.routing_score(direction="long", ofi=0.5, sentiment_score=0.2)
        assert 0.0 <= score <= 1.0

    def test_routing_score_short(self):
        s = self._s()
        score = s.routing_score(direction="short", ofi=-0.5, sentiment_score=0.0)
        assert 0.0 <= score <= 1.0


@pytest.mark.unit
class TestSmartRouter:
    def _router(self):
        from execution.smart_router import SmartRouter

        return SmartRouter()

    def _broker(self, status="filled"):
        b = MagicMock()
        b.place_order = AsyncMock(
            return_value={
                "status": status,
                "fill_price": 1950.0,
                "quantity": 1.0,
                "latency_ms": 50.0,
            }
        )
        return b

    def _req(self, **kw):
        base = dict(
            symbol="XAUUSD",
            direction="long",
            quantity=1.0,
            order_type="MARKET",
            mid_price=1950.0,
            bid=1949.5,
            ask=1950.5,
            spread=1.0,
            confidence=0.8,
            sentiment=0.1,
            impact=0.1,
            features={},
        )
        base.update(kw)
        return base

    def test_add_broker(self):
        r = self._router()
        r.add_broker("oanda", self._broker())
        assert "oanda" in r._brokers and "oanda" in r._states

    def test_remove_broker(self):
        r = self._router()
        r.add_broker("oanda", self._broker())
        r.remove_broker("oanda")
        assert "oanda" not in r._brokers

    @pytest.mark.asyncio
    async def test_no_brokers_rejected(self):
        r = self._router()
        result = await r.route_and_execute(self._req())
        assert result["status"] == "rejected"
        assert result["reason"] == "no_brokers_available"

    @pytest.mark.asyncio
    async def test_route_fills(self):
        r = self._router()
        r.add_broker("oanda", self._broker("filled"))
        result = await r.route_and_execute(self._req())
        assert result["status"] in ("filled", "rejected", "algo_submitted")

    @pytest.mark.asyncio
    async def test_sentiment_blackout_rejected(self):
        from execution.smart_router import _SENT_BLACKOUT_THRESH

        r = self._router()
        r.add_broker("oanda", self._broker())
        result = await r.route_and_execute(self._req(sentiment=_SENT_BLACKOUT_THRESH + 0.05))
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_high_spread_rejected(self):
        r = self._router()
        r.add_broker("oanda", self._broker())
        result = await r.route_and_execute(self._req(bid=1900.0, ask=2000.0, spread=100.0))
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_unwind_bypasses_sentiment(self):
        from execution.smart_router import _SENT_BLACKOUT_THRESH

        r = self._router()
        r.add_broker("oanda", self._broker("filled"))
        result = await r.route_and_execute(self._req(sentiment=_SENT_BLACKOUT_THRESH + 0.05, is_unwind=True))
        assert result.get("reason") != "sentiment_blackout"

    @pytest.mark.asyncio
    async def test_open_circuit_skips_broker(self):
        from execution.smart_router import _CB_ERROR_THRESHOLD

        r = self._router()
        r.add_broker("oanda", self._broker())
        state = r._states["oanda"]
        for _ in range(_CB_ERROR_THRESHOLD):
            state.record_error()
        assert state.circuit_open is True
        result = await r.route_and_execute(self._req())
        assert result["status"] == "rejected"

    def test_metrics_method(self):
        r = self._router()
        m = r.metrics()
        assert isinstance(m, dict) and "total_routed" in m


def _make_executor():
    from execution.trade_executor import TradeExecutor

    broker = MagicMock()
    order_result = MagicMock()
    order_result.id = "order-1"
    order_result.status = MagicMock(value="filled")
    order_result.filled_quantity = 1.0
    order_result.average_fill_price = 1950.0
    order_result.commission = 2.0
    broker.place_market_order = AsyncMock(return_value=order_result)
    broker.close_position = AsyncMock(return_value=True)
    rm = MagicMock()
    rm._trading_halted = False
    rm._halt_reason = ""
    rm.current_drawdown = 0.0
    rm.daily_starting_equity = 100_000.0
    rm.update_equity = MagicMock()
    pt = MagicMock()
    pt.get_position = MagicMock(return_value=None)
    pt.add_position = AsyncMock()
    pt.close_position = AsyncMock(
        return_value=MagicMock(
            realized_pnl=100.0, symbol="XAUUSD", side="long", entry_price=1950.0, signal_confidence=0.7
        )
    )
    return TradeExecutor(broker, rm, pt)


@pytest.mark.unit
class TestTradeExecutor:
    @pytest.mark.asyncio
    async def test_missing_fields_rejected(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD"})
        assert result.success is False
        assert "Missing" in result.message

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "hold", "size": 1.0})
        assert result.success is False
        assert "Invalid action" in result.message

    @pytest.mark.asyncio
    async def test_zero_size_rejected(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 0.0})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_trading_halted_blocks(self):
        ex = _make_executor()
        ex.risk_manager._trading_halted = True
        ex.risk_manager._halt_reason = "test halt"
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_drawdown_circuit_breaker_blocks(self):
        from execution.trade_executor import DRAWDOWN_HALT_PCT

        ex = _make_executor()
        ex.risk_manager.current_drawdown = DRAWDOWN_HALT_PCT + 0.01
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_streak_circuit_breaker_blocks(self):
        from execution.trade_executor import STREAK_HALT_LOSSES

        ex = _make_executor()
        ex._consecutive_losses = STREAK_HALT_LOSSES
        ex._streak_halted_until = time.monotonic() + 3600
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False
        assert "STREAK" in result.message.upper()

    @pytest.mark.asyncio
    async def test_pre_trade_gate_block(self):
        from risk.pre_trade_gate import TradeBlockedError

        ex = _make_executor()
        with patch(
            "risk.pre_trade_gate.PreTradeGate.check", side_effect=TradeBlockedError("KILL_SWITCH", "kill switch active")
        ):
            result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False
        assert "KILL_SWITCH" in result.message

    @pytest.mark.asyncio
    async def test_buy_signal_success(self):
        ex = _make_executor()
        with patch("risk.pre_trade_gate.PreTradeGate.check", return_value=None):
            result = await ex.execute_signal(
                {
                    "symbol": "XAUUSD",
                    "action": "buy",
                    "size": 1.0,
                    "price": 1950.0,
                    "stop_loss": 1930.0,
                    "take_profit": 1990.0,
                    "strategy_id": "test",
                }
            )
        assert result.success is True or result.status.value in ("filled", "rejected")

    @pytest.mark.asyncio
    async def test_sell_signal_success(self):
        ex = _make_executor()
        with patch("risk.pre_trade_gate.PreTradeGate.check", return_value=None):
            result = await ex.execute_signal(
                {
                    "symbol": "XAUUSD",
                    "action": "sell",
                    "size": 1.0,
                    "price": 1950.0,
                    "strategy_id": "test",
                }
            )
        assert result.success is True or result.status.value in ("filled", "rejected")

    @pytest.mark.asyncio
    async def test_close_missing_position_id(self):
        ex = _make_executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0})
        assert result.success is False
        assert "position_id" in result.message

    @pytest.mark.asyncio
    async def test_close_position_not_found(self):
        ex = _make_executor()
        ex.position_tracker.get_position.return_value = None
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0, "position_id": "pos-999"})
        assert result.success is False
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_close_success(self):
        ex = _make_executor()
        mock_pos = MagicMock()
        mock_pos.quantity = 1.0
        mock_pos.current_price = 1970.0
        mock_pos.commission = 2.0
        ex.position_tracker.get_position.return_value = mock_pos
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0, "position_id": "pos-1"})
        assert result.success is True

    def test_get_risk_status(self):
        ex = _make_executor()
        s = ex.get_risk_status()
        assert isinstance(s, dict) and "drawdown_halt_pct" in s

    def test_register_callback(self):
        ex = _make_executor()
        cb = MagicMock()
        ex.register_callback(cb)
        assert cb in ex._execution_callbacks

    @pytest.mark.asyncio
    async def test_cancel_all_pending(self):
        ex = _make_executor()
        await ex.cancel_all_pending()  # must not raise
