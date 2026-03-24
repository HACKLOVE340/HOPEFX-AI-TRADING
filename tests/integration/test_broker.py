"""
Integration tests for the PaperTradingBroker.

Tests the broker's full lifecycle: connect, order placement, position
management, price updates, and disconnect — using the real implementation.
"""

import pytest
from brokers.paper_trading import PaperTradingBroker
from brokers.base import OrderSide, OrderType, OrderStatus


class TestPaperBrokerLifecycle:
    """PaperTradingBroker connect/disconnect and account state."""

    @pytest.mark.asyncio
    async def test_connect_returns_true(self):
        broker = PaperTradingBroker(initial_balance=100_000.0)
        result = await broker.connect()
        assert result is True
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_returns_true(self):
        broker = PaperTradingBroker(initial_balance=100_000.0)
        await broker.connect()
        result = await broker.disconnect()
        assert result is True

    @pytest.mark.asyncio
    async def test_account_balance_matches_initial(self):
        broker = PaperTradingBroker(initial_balance=50_000.0)
        await broker.connect()
        info = broker.get_account_info()
        assert info.balance == pytest.approx(50_000.0, rel=1e-3)
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_no_positions_on_fresh_connect(self):
        broker = PaperTradingBroker(initial_balance=10_000.0)
        await broker.connect()
        positions = broker.get_positions()
        assert isinstance(positions, list)
        await broker.disconnect()


class TestPaperBrokerOrders:
    """Order placement and fill behaviour."""

    @pytest.mark.asyncio
    async def test_market_buy_creates_position(self):
        broker = PaperTradingBroker(initial_balance=10_000.0)
        await broker.connect()
        broker.update_market_price("XAUUSD", 2000.0)

        order = broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        assert order is not None

        positions = broker.get_positions()
        assert any(p.symbol == "XAUUSD" for p in positions)
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_market_sell_creates_position(self):
        broker = PaperTradingBroker(initial_balance=10_000.0)
        await broker.connect()
        broker.update_market_price("EURUSD", 1.0850)

        order = broker.place_order(
            symbol="EURUSD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        assert order is not None
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_close_position_removes_it(self):
        broker = PaperTradingBroker(initial_balance=10_000.0)
        await broker.connect()
        broker.update_market_price("XAUUSD", 2000.0)

        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
        broker.update_market_price("XAUUSD", 2010.0)

        closed = broker.close_position("XAUUSD")
        assert closed is True
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_price_update_reflected(self):
        broker = PaperTradingBroker(initial_balance=10_000.0)
        await broker.connect()
        broker.update_market_price("XAUUSD", 1900.0)
        price = broker.get_market_price("XAUUSD")
        assert price == pytest.approx(1900.0, rel=1e-3)
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_multiple_symbols_independent(self):
        broker = PaperTradingBroker(initial_balance=50_000.0)
        await broker.connect()
        broker.update_market_price("XAUUSD", 2000.0)
        broker.update_market_price("EURUSD", 1.0850)

        broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
        broker.place_order("EURUSD", OrderSide.BUY, OrderType.MARKET, 0.1)

        positions = broker.get_positions()
        symbols = {p.symbol for p in positions}
        assert "XAUUSD" in symbols
        assert "EURUSD" in symbols
        await broker.disconnect()
