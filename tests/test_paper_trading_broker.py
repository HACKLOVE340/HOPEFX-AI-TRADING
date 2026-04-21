# HOPEFX-AI-TRADING
# Tests for brokers/paper_trading.py (exported as PaperTradingBroker)
"""
Full branch coverage for PaperTradingBroker and related dataclasses.

Note: PaperTradingBroker.place_order uses brokers.base enums internally.
Tests must use brokers.base.OrderSide/OrderType to match the comparison.
"""

from __future__ import annotations


import pytest

from brokers import PaperTradingBroker
from brokers.base import (
    AccountInfo,
    OrderSide,
    OrderStatus,
    OrderType,
)

# brokers/__init__.py re-exports these — test them too
from brokers import Order as BrokerInitOrder
from brokers import Position as BrokerInitPosition
from brokers import OrderSide as BrokerInitOrderSide
from brokers import OrderStatus as BrokerInitOrderStatus
from brokers import OrderType as BrokerInitOrderType


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_broker(seed=42, initial_balance=100_000.0, **kwargs):
    return PaperTradingBroker(initial_balance=initial_balance, seed=seed, **kwargs)


def _connected_broker(**kwargs):
    b = _make_broker(**kwargs)
    b.connected = True
    return b


# ── connect / disconnect ──────────────────────────────────────────────────────


class TestConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_sets_connected(self):
        broker = _make_broker()
        result = await broker.connect()
        assert result is True
        assert broker.connected is True

    @pytest.mark.asyncio
    async def test_disconnect_sets_disconnected(self):
        broker = _make_broker()
        await broker.connect()
        result = await broker.disconnect()
        assert result is True
        assert broker.connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with PaperTradingBroker(seed=42) as broker:
            assert broker.connected is True
        assert broker.connected is False


# ── get_account_info ──────────────────────────────────────────────────────────


class TestGetAccountInfo:
    def test_returns_account_info_with_balance(self):
        broker = _connected_broker()
        info = broker.get_account_info()
        assert isinstance(info, AccountInfo)
        assert info.balance == pytest.approx(100_000.0)
        assert info.equity == pytest.approx(100_000.0)
        assert info.positions_count == 0

    def test_positions_count_reflects_open_positions(self):
        broker = _connected_broker()
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        info = broker.get_account_info()
        assert info.positions_count == 1


# ── place_order ───────────────────────────────────────────────────────────────


class TestPlaceOrder:
    def test_market_buy_fills_immediately(self):
        broker = _connected_broker()
        order = broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == pytest.approx(1.0)
        assert order.average_price is not None

    def test_market_sell_fills_immediately(self):
        broker = _connected_broker()
        order = broker.place_order("XAUUSD", OrderSide.SELL, OrderType.MARKET, 1.0)
        assert order.status == OrderStatus.FILLED

    def test_limit_order_is_open(self):
        broker = _connected_broker()
        order = broker.place_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 1.0, price=2000.0)
        assert order.status == OrderStatus.OPEN

    def test_raises_when_not_connected(self):
        broker = _make_broker()
        with pytest.raises(ConnectionError):
            broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_unknown_symbol_uses_default_price(self):
        broker = _connected_broker()
        order = broker.place_order("UNKNOWN_SYM_XYZ", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order.status == OrderStatus.FILLED
        assert order.average_price == pytest.approx(1000.0, rel=0.01)

    def test_order_stored_in_orders_dict(self):
        broker = _connected_broker()
        order = broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order.id in broker.orders

    def test_market_order_creates_position(self):
        broker = _connected_broker()
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert "XAUUSD" in broker.positions

    def test_commission_deducted_when_set(self):
        broker = _connected_broker(commission_per_lot=10.0)
        initial = broker.balance
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 100_000.0)
        assert broker.balance < initial

    def test_stop_order_is_open(self):
        broker = _connected_broker()
        order = broker.place_order("XAUUSD", OrderSide.SELL, OrderType.STOP, 1.0, stop_price=3200.0)
        assert order.status == OrderStatus.OPEN


# ── cancel_order ──────────────────────────────────────────────────────────────


class TestCancelOrder:
    def test_cancel_open_limit_order(self):
        broker = _connected_broker()
        order = broker.place_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 1.0, price=2000.0)
        result = broker.cancel_order(order.id)
        assert result is True
        assert broker.orders[order.id].status == OrderStatus.CANCELLED

    def test_cancel_nonexistent_order_returns_false(self):
        broker = _connected_broker()
        result = broker.cancel_order("nonexistent")
        assert result is False

    def test_cancel_filled_order_returns_false(self):
        broker = _connected_broker()
        order = broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        result = broker.cancel_order(order.id)
        assert result is False


# ── get_positions ─────────────────────────────────────────────────────────────


class TestGetPositions:
    def test_returns_empty_initially(self):
        broker = _connected_broker()
        assert broker.get_positions() == []

    def test_returns_position_after_buy(self):
        broker = _connected_broker()
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "XAUUSD"

    def test_position_price_updated_from_market_prices(self):
        broker = _connected_broker()
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        broker.market_prices["XAUUSD"] = 3500.0
        positions = broker.get_positions()
        assert positions[0].current_price == pytest.approx(3500.0)


# ── close_position ────────────────────────────────────────────────────────────


class TestClosePosition:
    def test_close_existing_position(self):
        broker = _connected_broker()
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        result = broker.close_position("XAUUSD")
        assert result is True
        assert "XAUUSD" not in broker.positions

    def test_close_nonexistent_position_returns_false(self):
        broker = _connected_broker()
        result = broker.close_position("NONEXISTENT")
        assert result is False

    def test_close_position_updates_balance(self):
        broker = _connected_broker()
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        initial_balance = broker.balance
        broker.market_prices["XAUUSD"] = 3400.0
        broker.close_position("XAUUSD")
        assert broker.balance != initial_balance


# ── place_market_order (async) ────────────────────────────────────────────────


class TestPlaceMarketOrderAsync:
    @pytest.mark.asyncio
    async def test_async_buy_fills(self):
        broker = _connected_broker()
        order = await broker.place_market_order("XAUUSD", "buy", 1.0)
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_async_sell_fills(self):
        broker = _connected_broker()
        order = await broker.place_market_order("XAUUSD", "sell", 1.0)
        assert order.status == OrderStatus.FILLED


# ── close_all_positions (async) ───────────────────────────────────────────────


class TestCloseAllPositions:
    @pytest.mark.asyncio
    async def test_closes_all_positions(self):
        broker = _connected_broker()
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        broker.place_order("EURUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        closed = await broker.close_all_positions()
        assert isinstance(closed, list)
        assert len(closed) == 2
        assert set(closed) == {"XAUUSD", "EURUSD"}
        assert len(broker.positions) == 0


# ── equity history ────────────────────────────────────────────────────────────


class TestEquityHistory:
    def test_equity_history_seeded_at_init(self):
        broker = _make_broker()
        assert len(broker._equity_history) >= 1
        assert broker._equity_history[0][1] == pytest.approx(100_000.0)

    def test_equity_snapshot_after_fill(self):
        broker = _connected_broker()
        initial_len = len(broker._equity_history)
        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert len(broker._equity_history) >= initial_len

    def test_get_equity_history_returns_list(self):
        broker = _make_broker()
        history = broker.get_equity_history()
        assert isinstance(history, list)
        assert len(history) >= 1


# ── _deduct_commission ────────────────────────────────────────────────────────


class TestDeductCommission:
    def test_zero_commission_per_lot_returns_zero(self):
        broker = _connected_broker(commission_per_lot=0.0)
        initial = broker.balance
        commission = broker._deduct_commission(100_000.0)
        assert commission == 0.0
        assert broker.balance == initial

    def test_commission_deducted_from_balance(self):
        broker = _connected_broker(commission_per_lot=10.0)
        initial = broker.balance
        commission = broker._deduct_commission(100_000.0)
        assert commission == pytest.approx(10.0)
        assert broker.balance == pytest.approx(initial - 10.0)


# ── get_market_data ───────────────────────────────────────────────────────────


class TestGetMarketData:
    def test_returns_list_of_ohlcv(self):
        broker = _connected_broker()
        data = broker.get_market_data("XAUUSD", "1h", 10)
        assert isinstance(data, list)
        assert len(data) == 10
        assert "open" in data[0]
        assert "close" in data[0]


# ── Order/Position dataclasses from brokers/__init__.py ──────────────────────


class TestBrokerInitDataclasses:
    """Tests for the Order/Position classes re-exported from brokers/__init__.py."""

    def test_order_remaining_quantity(self):
        o = BrokerInitOrder(
            id="x",
            symbol="X",
            side=BrokerInitOrderSide.BUY,
            type=BrokerInitOrderType.MARKET,
            quantity=10.0,
            filled_quantity=3.0,
        )
        assert o.remaining_quantity == pytest.approx(7.0)

    def test_order_is_complete_filled(self):
        o = BrokerInitOrder(
            id="x",
            symbol="X",
            side=BrokerInitOrderSide.BUY,
            type=BrokerInitOrderType.MARKET,
            quantity=1.0,
            status=BrokerInitOrderStatus.FILLED,
        )
        assert o.is_complete is True

    def test_order_is_complete_pending(self):
        o = BrokerInitOrder(
            id="x",
            symbol="X",
            side=BrokerInitOrderSide.BUY,
            type=BrokerInitOrderType.LIMIT,
            quantity=1.0,
            status=BrokerInitOrderStatus.PENDING,
        )
        assert o.is_complete is False

    def test_order_to_dict(self):
        o = BrokerInitOrder(
            id="x",
            symbol="XAUUSD",
            side=BrokerInitOrderSide.BUY,
            type=BrokerInitOrderType.MARKET,
            quantity=1.0,
            status=BrokerInitOrderStatus.FILLED,
            filled_quantity=1.0,
            average_fill_price=2000.0,
        )
        d = o.to_dict()
        assert d["id"] == "x"
        assert d["symbol"] == "XAUUSD"

    def test_position_market_value(self):
        p = BrokerInitPosition(
            id="p1",
            symbol="X",
            side=BrokerInitOrderSide.BUY,
            quantity=2.0,
            entry_price=100.0,
            current_price=110.0,
        )
        assert p.market_value == pytest.approx(220.0)

    def test_position_total_pnl(self):
        p = BrokerInitPosition(
            id="p1",
            symbol="X",
            side=BrokerInitOrderSide.BUY,
            quantity=1.0,
            entry_price=100.0,
            current_price=110.0,
            unrealized_pnl=10.0,
            realized_pnl=5.0,
        )
        assert p.total_pnl == pytest.approx(15.0)

    def test_position_update_price_long(self):
        p = BrokerInitPosition(
            id="p1",
            symbol="X",
            side=BrokerInitOrderSide.BUY,
            quantity=1.0,
            entry_price=100.0,
            current_price=100.0,
        )
        p.update_price(110.0)
        assert p.current_price == pytest.approx(110.0)
        assert p.unrealized_pnl == pytest.approx(10.0)

    def test_position_update_price_short(self):
        p = BrokerInitPosition(
            id="p1",
            symbol="X",
            side=BrokerInitOrderSide.SELL,
            quantity=1.0,
            entry_price=100.0,
            current_price=100.0,
        )
        p.update_price(90.0)
        assert p.unrealized_pnl == pytest.approx(10.0)

    def test_position_to_dict(self):
        p = BrokerInitPosition(
            id="p1",
            symbol="XAUUSD",
            side=BrokerInitOrderSide.BUY,
            quantity=1.0,
            entry_price=2000.0,
            current_price=2010.0,
            unrealized_pnl=10.0,
        )
        d = p.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert d["unrealized_pnl"] == pytest.approx(10.0)
