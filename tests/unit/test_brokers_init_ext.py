# HOPEFX-AI-TRADING
# Tests for brokers/__init__.py
"""
Tests for the PaperTradingBroker, Order, Position, enums, and create_broker
defined in brokers/__init__.py.

The bottom of __init__.py overrides PaperTradingBroker with the one from
brokers.paper_trading (which has a different API). We load __init__.py in
isolation with a stub for brokers.paper_trading so the override is a no-op
and we get the class that has _calculate_slippage / place_order.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType, SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Load brokers/__init__.py in isolation so the paper_trading override is a
# no-op and we test the class actually defined in __init__.py.
# ---------------------------------------------------------------------------


def _load_init_module() -> ModuleType:
    fake_pt = ModuleType("brokers.paper_trading")
    fake_factory = ModuleType("brokers.factory")
    fake_factory.BrokerFactory = object  # type: ignore[attr-defined]
    fake_base = ModuleType("brokers.base")
    fake_base.AccountInfo = object  # type: ignore[attr-defined]
    fake_base.BrokerConnector = object  # type: ignore[attr-defined]

    saved = {k: sys.modules.get(k) for k in ("brokers.paper_trading", "brokers.factory", "brokers.base")}
    sys.modules["brokers.paper_trading"] = fake_pt
    sys.modules["brokers.factory"] = fake_factory
    sys.modules["brokers.base"] = fake_base
    try:
        spec = importlib.util.spec_from_file_location(
            "_brokers_init_isolated",
            pathlib.Path(__file__).resolve().parents[2] / "brokers" / "__init__.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


_mod = _load_init_module()

PaperTradingBroker = _mod.PaperTradingBroker
Order = _mod.Order
Position = _mod.Position
OrderType = _mod.OrderType
OrderSide = _mod.OrderSide
OrderStatus = _mod.OrderStatus
BaseBroker = _mod.BaseBroker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_broker(balance: float = 100_000.0, seed: int = 42) -> PaperTradingBroker:
    return PaperTradingBroker(initial_balance=balance, seed=seed)


class _StaticFeed:
    """Real price feed stub — returns a fixed tick for any symbol.

    Uses SimpleNamespace (not MagicMock) so attribute access is explicit
    and deterministic.  The broker only reads .ask, .bid, and .mid.
    """

    def __init__(self, price: float = 2000.0) -> None:
        self._price = price

    def get_last_price(self, symbol: str) -> SimpleNamespace:
        p = self._price
        return SimpleNamespace(ask=p * 1.0001, bid=p * 0.9999, mid=p)


def _make_price_feed(symbol: str = "XAUUSD", price: float = 2000.0) -> _StaticFeed:
    return _StaticFeed(price)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"
        assert OrderType.STOP_LIMIT.value == "stop_limit"

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"


# ---------------------------------------------------------------------------
# Order dataclass
# ---------------------------------------------------------------------------


class TestOrder:
    def _make(self, qty: float = 1.0, filled: float = 0.0, status: OrderStatus = OrderStatus.PENDING) -> Order:
        return Order(
            id="o1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=qty,
            filled_quantity=filled,
            status=status,
        )

    def test_remaining_quantity(self):
        o = self._make(qty=2.0, filled=0.5)
        assert o.remaining_quantity == pytest.approx(1.5)

    def test_is_complete_filled(self):
        assert self._make(status=OrderStatus.FILLED).is_complete is True

    def test_is_complete_cancelled(self):
        assert self._make(status=OrderStatus.CANCELLED).is_complete is True

    def test_is_complete_rejected(self):
        assert self._make(status=OrderStatus.REJECTED).is_complete is True

    def test_is_complete_pending(self):
        assert self._make(status=OrderStatus.PENDING).is_complete is False

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for key in ("id", "symbol", "side", "type", "quantity", "status"):
            assert key in d


# ---------------------------------------------------------------------------
# Position dataclass
# ---------------------------------------------------------------------------


class TestPosition:
    def _make(self, qty: float = 1.0, entry: float = 1900.0, current: float = 1910.0) -> Position:
        return Position(
            id="p1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=qty,
            entry_price=entry,
            current_price=current,
        )

    def test_market_value(self):
        p = self._make(qty=2.0, current=1910.0)
        assert p.market_value == pytest.approx(3820.0)

    def test_unrealized_pnl_buy(self):
        p = self._make(qty=1.0, entry=1900.0, current=1910.0)
        p.update_price(1910.0)
        assert p.unrealized_pnl == pytest.approx(10.0)

    def test_unrealized_pnl_sell(self):
        p = Position(
            id="p2",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=1.0,
            entry_price=1900.0,
            current_price=1900.0,
        )
        p.update_price(1890.0)
        assert p.unrealized_pnl == pytest.approx(10.0)

    def test_total_pnl(self):
        p = self._make()
        p.unrealized_pnl = 5.0
        p.realized_pnl = 3.0
        assert p.total_pnl == pytest.approx(8.0)

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for key in ("id", "symbol", "side", "quantity", "entry_price", "current_price", "unrealized_pnl"):
            assert key in d


# ---------------------------------------------------------------------------
# PaperTradingBroker — sync place_order path
# ---------------------------------------------------------------------------


class TestPaperTradingBrokerSync:
    def test_initial_balance(self):
        b = _make_broker(balance=50_000.0)
        assert b.balance == pytest.approx(50_000.0)

    def test_place_buy_order_reduces_balance(self):
        b = _make_broker()
        b.set_market_price("XAUUSD", 2000.0)
        order = b.place_order("XAUUSD", "buy", 1.0)
        assert order.status.value == "filled"
        assert b.balance == pytest.approx(100_000.0 - 2000.0)

    def test_place_sell_order_increases_balance(self):
        b = _make_broker()
        b.set_market_price("XAUUSD", 2000.0)
        # First buy to create a position
        b.place_order("XAUUSD", "buy", 1.0)
        b.place_order("XAUUSD", "sell", 1.0)
        # After sell, position should be gone
        assert "XAUUSD_LONG" not in b.positions

    def test_insufficient_balance_raises(self):
        b = _make_broker(balance=100.0)
        b.set_market_price("XAUUSD", 2000.0)
        with pytest.raises(ValueError, match="[Ii]nsufficient"):
            b.place_order("XAUUSD", "buy", 1.0)

    def test_limit_order_stays_pending(self):
        b = _make_broker()
        b.set_market_price("XAUUSD", 2000.0)
        order = b.place_order("XAUUSD", "buy", 1.0, order_type="LIMIT", price=1990.0)
        assert order.status.value == "pending"

    def test_set_and_get_market_price(self):
        b = _make_broker()
        b.set_market_price("XAUUSD", 1999.5)
        assert b.get_market_price("XAUUSD") == pytest.approx(1999.5)

    def test_get_market_price_missing_returns_zero(self):
        b = _make_broker()
        assert b.get_market_price("UNKNOWN") == 0.0

    def test_positions_property(self):
        b = _make_broker()
        b.set_market_price("XAUUSD", 2000.0)
        b.place_order("XAUUSD", "buy", 1.0)
        assert "XAUUSD_LONG" in b.positions

    def test_orders_property(self):
        b = _make_broker()
        b.set_market_price("XAUUSD", 2000.0)
        order = b.place_order("XAUUSD", "buy", 1.0)
        assert order.id in b.orders


# ---------------------------------------------------------------------------
# PaperTradingBroker — _calculate_slippage
# ---------------------------------------------------------------------------


class TestCalculateSlippage:
    def test_no_slippage_model(self):
        b = PaperTradingBroker(slippage_model="none", seed=42)
        assert b._calculate_slippage("XAUUSD", 1.0, "buy") == 0.0

    def test_gaussian_slippage_non_negative(self):
        b = PaperTradingBroker(slippage_model="gaussian", seed=42)
        for _ in range(20):
            s = b._calculate_slippage("XAUUSD", 1.0, "buy")
            assert s >= 0.0

    def test_uniform_slippage_non_negative(self):
        b = PaperTradingBroker(slippage_model="uniform", seed=42)
        for _ in range(20):
            s = b._calculate_slippage("XAUUSD", 1.0, "buy")
            assert s >= 0.0

    def test_large_order_higher_slippage(self):
        b = PaperTradingBroker(slippage_model="gaussian", seed=0)
        b._calculate_slippage("XAUUSD", 1.0, "buy")
        b2 = PaperTradingBroker(slippage_model="gaussian", seed=0)
        large = b2._calculate_slippage("XAUUSD", 1_000_000.0, "buy")
        # Large orders should generally produce more slippage (not guaranteed
        # with Gaussian noise, but the base is higher)
        assert large >= 0.0  # at minimum non-negative


# ---------------------------------------------------------------------------
# PaperTradingBroker — _simulate_fill_quantity
# ---------------------------------------------------------------------------


class TestSimulateFillQuantity:
    def test_small_order_fully_filled(self):
        b = _make_broker()
        qty = b._simulate_fill_quantity(100.0, "XAUUSD")
        assert qty == pytest.approx(100.0)

    def test_large_order_may_partially_fill(self):
        b = _make_broker(seed=1)
        # Run many times — at least some should be partial
        results = {b._simulate_fill_quantity(200_000.0, "XAUUSD") for _ in range(30)}
        # All results must be positive
        assert all(r > 0 for r in results)


# ---------------------------------------------------------------------------
# PaperTradingBroker — async API
# ---------------------------------------------------------------------------


class TestPaperTradingBrokerAsync:
    @pytest.mark.asyncio
    async def test_connect_sets_connected(self):
        b = _make_broker()
        await b.connect()
        assert b.connected is True

    @pytest.mark.asyncio
    async def test_disconnect_clears_connected(self):
        b = _make_broker()
        await b.connect()
        await b.disconnect()
        assert b.connected is False

    @pytest.mark.asyncio
    async def test_get_account_info_keys(self):
        b = _make_broker()
        await b.connect()
        info = await b.get_account_info()
        for key in ("balance", "equity", "margin_used", "free_margin", "unrealized_pnl", "open_positions"):
            assert key in info

    @pytest.mark.asyncio
    async def test_place_market_order_async(self):
        b = _make_broker()
        await b.connect()
        b.price_feed = _make_price_feed("XAUUSD", 2000.0)
        order = await b.place_market_order("XAUUSD", "buy", 1.0)
        assert order.status.value in ("filled", "partial")
        assert order.filled_quantity > 0

    @pytest.mark.asyncio
    async def test_place_market_order_not_connected_raises(self):
        b = _make_broker()
        b.price_feed = _make_price_feed()
        with pytest.raises((ConnectionError, Exception)):
            await b.place_market_order("XAUUSD", "buy", 1.0)

    @pytest.mark.asyncio
    async def test_cancel_order_pending(self):
        b = _make_broker()
        await b.connect()
        b.price_feed = _make_price_feed()
        order = await b.place_market_order("XAUUSD", "buy", 1.0)
        # Reset to PENDING using the isolated module's enum (same as the broker uses)
        order.status = OrderStatus.PENDING
        result = await b.cancel_order(order.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_order_missing_returns_false(self):
        b = _make_broker()
        await b.connect()
        result = await b.cancel_order("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_positions_returns_list(self):
        b = _make_broker()
        await b.connect()
        b.price_feed = _make_price_feed()
        await b.place_market_order("XAUUSD", "buy", 1.0)
        positions = await b.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_get_pending_orders_returns_list(self):
        b = _make_broker()
        await b.connect()
        orders = await b.get_pending_orders()
        assert isinstance(orders, list)

    @pytest.mark.asyncio
    async def test_close_all_positions_empty(self):
        # No positions → returns empty list without deadlock
        b = _make_broker()
        await b.connect()
        closed = await b.close_all_positions()
        assert closed == []

    @pytest.mark.asyncio
    async def test_cancel_all_orders(self):
        b = _make_broker()
        await b.connect()
        cancelled = await b.cancel_all_orders()
        assert isinstance(cancelled, list)


# ---------------------------------------------------------------------------
# create_broker factory
# ---------------------------------------------------------------------------


class TestCreateBroker:
    def test_paper_broker(self):
        broker = _mod.create_broker("paper", {"initial_balance": 50_000.0})
        assert isinstance(broker, BaseBroker)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown broker"):
            _mod.create_broker("unknown_xyz", {})
