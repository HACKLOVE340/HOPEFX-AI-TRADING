# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for brokers/__init__.py

Covers: Order dataclass, Position dataclass, BaseBroker abstract interface,
        PaperTradingBroker (sync place_order path), create_broker factory,
        close_all_positions and cancel_all_orders default implementations.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Order dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOrderDataclass:
    def _make_order(self, status=None):
        from brokers import Order, OrderSide, OrderStatus, OrderType
        return Order(
            id="ord-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=1.0,
            price=1950.0,
            status=status or OrderStatus.PENDING,
        )

    def test_remaining_quantity_unfilled(self):
        order = self._make_order()
        assert order.remaining_quantity == pytest.approx(1.0)

    def test_remaining_quantity_partial(self):
        from brokers import Order, OrderSide, OrderStatus, OrderType
        order = Order(
            id="ord-002", symbol="XAUUSD",
            side=OrderSide.BUY, type=OrderType.MARKET,
            quantity=10.0, filled_quantity=4.0,
            status=OrderStatus.PARTIAL,
        )
        assert order.remaining_quantity == pytest.approx(6.0)

    def test_is_complete_filled(self):
        from brokers import OrderStatus
        order = self._make_order(status=OrderStatus.FILLED)
        assert order.is_complete is True

    def test_is_complete_cancelled(self):
        from brokers import OrderStatus
        order = self._make_order(status=OrderStatus.CANCELLED)
        assert order.is_complete is True

    def test_is_complete_rejected(self):
        from brokers import OrderStatus
        order = self._make_order(status=OrderStatus.REJECTED)
        assert order.is_complete is True

    def test_is_complete_pending(self):
        from brokers import OrderStatus
        order = self._make_order(status=OrderStatus.PENDING)
        assert order.is_complete is False

    def test_to_dict_keys(self):
        order = self._make_order()
        d = order.to_dict()
        for key in ("id", "symbol", "side", "type", "quantity", "status",
                    "filled_quantity", "average_fill_price", "commission"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_side_is_string(self):
        order = self._make_order()
        d = order.to_dict()
        assert isinstance(d["side"], str)

    def test_to_dict_status_is_string(self):
        order = self._make_order()
        d = order.to_dict()
        assert isinstance(d["status"], str)


# ---------------------------------------------------------------------------
# Position dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPositionDataclass:
    def _make_position(self, side=None, qty=10.0, entry=1950.0, current=1950.0):
        from brokers import OrderSide, Position
        return Position(
            id="pos-001",
            symbol="XAUUSD",
            side=side or OrderSide.BUY,
            quantity=qty,
            entry_price=entry,
            current_price=current,
        )

    def test_market_value(self):
        pos = self._make_position(qty=10.0, current=1960.0)
        assert pos.market_value == pytest.approx(19600.0)

    def test_total_pnl(self):
        from brokers import OrderSide, Position
        pos = Position(
            id="p1", symbol="XAUUSD", side=OrderSide.BUY,
            quantity=10.0, entry_price=1950.0, current_price=1960.0,
            unrealized_pnl=100.0, realized_pnl=50.0,
        )
        assert pos.total_pnl == pytest.approx(150.0)

    def test_update_price_long(self):
        from brokers import OrderSide
        pos = self._make_position(side=OrderSide.BUY, qty=10.0, entry=1950.0, current=1950.0)
        pos.update_price(1960.0)
        assert pos.unrealized_pnl == pytest.approx(100.0)
        assert pos.current_price == pytest.approx(1960.0)

    def test_update_price_short(self):
        from brokers import OrderSide
        pos = self._make_position(side=OrderSide.SELL, qty=10.0, entry=1950.0, current=1950.0)
        pos.update_price(1940.0)
        assert pos.unrealized_pnl == pytest.approx(100.0)

    def test_update_price_adverse_long(self):
        from brokers import OrderSide
        pos = self._make_position(side=OrderSide.BUY, qty=10.0, entry=1950.0, current=1950.0)
        pos.update_price(1940.0)
        assert pos.unrealized_pnl == pytest.approx(-100.0)

    def test_to_dict_keys(self):
        pos = self._make_position()
        d = pos.to_dict()
        for key in ("id", "symbol", "side", "quantity", "entry_price",
                    "current_price", "unrealized_pnl", "total_pnl", "market_value"):
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# BaseBroker — abstract interface
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBaseBrokerAbstract:
    def test_cannot_instantiate_directly(self):
        from brokers import BaseBroker
        with pytest.raises(TypeError):
            BaseBroker()

    def test_concrete_subclass_without_methods_raises(self):
        from brokers import BaseBroker
        class IncompleteBroker(BaseBroker):
            pass
        with pytest.raises(TypeError):
            IncompleteBroker()

    def test_close_all_positions_calls_close_position(self):
        """close_all_positions iterates get_positions and calls close_position."""
        from brokers import BaseBroker, OrderSide, Position

        class MockBroker(BaseBroker):
            async def connect(self): pass
            async def disconnect(self): pass
            async def get_account_info(self): return {}
            async def place_market_order(self, *a, **kw): return None
            async def cancel_order(self, order_id): return True
            async def get_positions(self):
                return [
                    Position("p1", "XAUUSD", OrderSide.BUY, 1.0, 1950.0, 1950.0),
                    Position("p2", "EURUSD", OrderSide.SELL, 1.0, 1.10, 1.10),
                ]
            async def close_position(self, position_id): return True
            async def get_pending_orders(self): return []

        broker = MockBroker()
        closed = asyncio.run(broker.close_all_positions())
        assert set(closed) == {"p1", "p2"}

    def test_cancel_all_orders_calls_cancel_order(self):
        """cancel_all_orders iterates get_pending_orders and calls cancel_order."""
        from brokers import BaseBroker, Order, OrderSide, OrderStatus, OrderType

        class MockBroker(BaseBroker):
            async def connect(self): pass
            async def disconnect(self): pass
            async def get_account_info(self): return {}
            async def place_market_order(self, *a, **kw): return None
            async def cancel_order(self, order_id): return True
            async def get_positions(self): return []
            async def close_position(self, position_id): return True
            async def get_pending_orders(self):
                return [
                    Order("o1", "XAUUSD", OrderSide.BUY, OrderType.LIMIT, 1.0),
                    Order("o2", "EURUSD", OrderSide.SELL, OrderType.LIMIT, 1.0),
                ]

        broker = MockBroker()
        cancelled = asyncio.run(broker.cancel_all_orders())
        assert set(cancelled) == {"o1", "o2"}


# ---------------------------------------------------------------------------
# PaperTradingBroker — sync place_order path
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPaperTradingBrokerSync:
    @pytest.fixture
    def broker(self):
        from brokers.paper_trading import PaperTradingBroker
        b = PaperTradingBroker(initial_balance=100_000.0, commission_per_lot=3.5)
        asyncio.run(b.connect())
        return b

    def test_initial_balance(self, broker):
        assert broker.balance == pytest.approx(100_000.0)

    def test_place_market_buy(self, broker):
        from brokers.base import OrderSide, OrderStatus, OrderType
        order = broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=10_000,
            price=1.1000,
        )
        assert order is not None
        assert order.status == OrderStatus.FILLED

    def test_place_market_sell(self, broker):
        from brokers.base import OrderSide, OrderStatus, OrderType
        order = broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.SELL,
            quantity=10_000,
            price=1.1000,
        )
        assert order is not None
        assert order.status == OrderStatus.FILLED

    def test_place_limit_order_open(self, broker):
        from brokers.base import OrderSide, OrderStatus, OrderType
        order = broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=10_000,
            price=1.0900,
        )
        assert order is not None
        assert order.status == OrderStatus.OPEN

    def test_cancel_limit_order(self, broker):
        from brokers.base import OrderSide, OrderStatus, OrderType
        order = broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=10_000,
            price=1.0900,
        )
        result = broker.cancel_order(order.id)
        assert result is True

    def test_balance_decreases_after_buy(self, broker):
        from brokers.base import OrderSide, OrderType
        initial = broker.balance
        broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=10_000,
            price=1.1000,
        )
        # Balance should decrease by commission at minimum
        assert broker.balance <= initial


# ---------------------------------------------------------------------------
# create_broker factory
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCreateBrokerFactory:
    def test_creates_paper_broker(self):
        from brokers import create_broker
        broker = create_broker("paper", {"initial_balance": 50_000.0})
        assert broker is not None

    def test_paper_broker_type(self):
        from brokers import create_broker
        broker = create_broker("paper", {})
        # Should be some kind of broker object
        assert hasattr(broker, "connect") or hasattr(broker, "balance")

    def test_unknown_type_raises(self):
        from brokers import create_broker
        with pytest.raises((ValueError, ImportError, Exception)):
            create_broker("unknown_broker_xyz", {})

    def test_paper_broker_case_insensitive(self):
        from brokers import create_broker
        broker = create_broker("PAPER", {"initial_balance": 10_000.0})
        assert broker is not None
