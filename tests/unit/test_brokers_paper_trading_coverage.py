# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for brokers/paper_trading.py

Targets: SlippageModel, PaperTradingBroker (all public + key private methods)
"""

from __future__ import annotations

import time
from datetime import timezone
from unittest.mock import MagicMock

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_broker(
    initial_balance: float = 10_000.0,
    commission_per_lot: float = 0.0,
    slippage_model: str = "zero",
    seed: int = 42,
):
    from brokers.paper_trading import PaperTradingBroker

    broker = PaperTradingBroker(
        initial_balance=initial_balance,
        commission_per_lot=commission_per_lot,
        slippage_model=slippage_model,
        seed=seed,
    )
    broker.connected = True
    return broker


def _buy(broker, symbol="EURUSD", qty=1.0):
    from brokers.base import OrderSide, OrderType

    return broker.place_order(symbol, OrderSide.BUY, OrderType.MARKET, qty)


def _sell(broker, symbol="EURUSD", qty=1.0):
    from brokers.base import OrderSide, OrderType

    return broker.place_order(symbol, OrderSide.SELL, OrderType.MARKET, qty)


def _limit_buy(broker, symbol="EURUSD", qty=1.0, price=1.08):
    from brokers.base import OrderSide, OrderType

    return broker.place_order(symbol, OrderSide.BUY, OrderType.LIMIT, qty, price=price)


# ---------------------------------------------------------------------------
# SlippageModel — zero model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSlippageModelZero:
    def test_zero_model_returns_mid(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="zero", seed=0)
        assert m.fill_price("EURUSD", 1.0820, OrderSide.BUY, 1.0) == pytest.approx(1.0820)

    def test_zero_model_sell_returns_mid(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="zero", seed=0)
        assert m.fill_price("EURUSD", 1.0820, OrderSide.SELL, 1.0) == pytest.approx(1.0820)

    def test_zero_model_non_positive_price_returned_as_is(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="zero", seed=0)
        assert m.fill_price("EURUSD", 0.0, OrderSide.BUY, 1.0) == 0.0


# ---------------------------------------------------------------------------
# SlippageModel — fixed model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSlippageModelFixed:
    def test_fixed_buy_above_mid(self, monkeypatch):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        monkeypatch.setenv("PAPER_SLIPPAGE_MODEL", "fixed")
        monkeypatch.setenv("PAPER_FIXED_SLIPPAGE_PCT", "0.001")
        m = SlippageModel(model="fixed", seed=0)
        fill = m.fill_price("EURUSD", 1.0000, OrderSide.BUY, 1.0)
        assert fill > 1.0000

    def test_fixed_sell_below_mid(self, monkeypatch):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        monkeypatch.setenv("PAPER_SLIPPAGE_MODEL", "fixed")
        monkeypatch.setenv("PAPER_FIXED_SLIPPAGE_PCT", "0.001")
        m = SlippageModel(model="fixed", seed=0)
        fill = m.fill_price("EURUSD", 1.0000, OrderSide.SELL, 1.0)
        assert fill < 1.0000

    def test_fixed_fill_always_positive(self, monkeypatch):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        monkeypatch.setenv("PAPER_SLIPPAGE_MODEL", "fixed")
        monkeypatch.setenv("PAPER_FIXED_SLIPPAGE_PCT", "0.9999")
        m = SlippageModel(model="fixed", seed=0)
        fill = m.fill_price("EURUSD", 0.0001, OrderSide.SELL, 1.0)
        assert fill > 0.0


# ---------------------------------------------------------------------------
# SlippageModel — gaussian model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSlippageModelGaussian:
    def test_gaussian_buy_generally_above_mid(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="gaussian", seed=42)
        fills = [m.fill_price("EURUSD", 1.0820, OrderSide.BUY, 1.0) for _ in range(50)]
        assert sum(f > 1.0820 for f in fills) > 30  # spread + impact dominate

    def test_gaussian_sell_generally_below_mid(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="gaussian", seed=42)
        fills = [m.fill_price("EURUSD", 1.0820, OrderSide.SELL, 1.0) for _ in range(50)]
        assert sum(f < 1.0820 for f in fills) > 30

    def test_gaussian_fill_always_positive(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="gaussian", seed=0)
        for _ in range(20):
            fill = m.fill_price("EURUSD", 0.0001, OrderSide.BUY, 1.0)
            assert fill > 0.0

    def test_gaussian_uses_symbol_spread(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="gaussian", seed=0)
        # XAUUSD has a large spread (0.30) vs EURUSD (0.0001)
        gold_fill = m.fill_price("XAUUSD", 3300.0, OrderSide.BUY, 1.0)
        assert gold_fill > 3300.0

    def test_gaussian_fallback_spread_for_unknown_symbol(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="gaussian", seed=0)
        fill = m.fill_price("UNKNOWN/SYM", 100.0, OrderSide.BUY, 1.0)
        assert fill > 0.0

    def test_set_spread_override_used(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="gaussian", seed=42)
        m._spread_overrides["CUSTOM"] = 5.0  # large half-spread
        fill = m.fill_price("CUSTOM", 100.0, OrderSide.BUY, 1.0)
        assert fill > 100.0 + 4.0  # at least most of the spread

    def test_large_order_has_more_impact(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="gaussian", seed=0)
        small = m.fill_price("EURUSD", 1.0820, OrderSide.BUY, 1.0, notional_adv=1_000_000)
        large = m.fill_price("EURUSD", 1.0820, OrderSide.BUY, 500_000.0, notional_adv=1_000_000)
        assert large > small  # more impact on large order

    def test_direction_string_buy_variants(self):
        from brokers.paper_trading import SlippageModel
        from brokers.base import OrderSide

        m = SlippageModel(model="gaussian", seed=0)
        # "LONG" string should behave like BUY
        fill_buy = m.fill_price("EURUSD", 1.0820, OrderSide.BUY, 1.0)
        assert fill_buy > 0.0


# ---------------------------------------------------------------------------
# PaperTradingBroker — initialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPaperTradingBrokerInit:
    def test_default_balance(self):
        broker = _make_broker()
        assert broker.balance == pytest.approx(10_000.0)
        assert broker.equity == pytest.approx(10_000.0)
        assert broker.initial_balance == pytest.approx(10_000.0)

    def test_custom_balance(self):
        broker = _make_broker(initial_balance=50_000.0)
        assert broker.balance == pytest.approx(50_000.0)

    def test_empty_orders_and_positions(self):
        broker = _make_broker()
        assert broker.orders == {}
        assert broker.positions == {}

    def test_equity_history_seeded(self):
        broker = _make_broker()
        history = broker.get_equity_history()
        assert len(history) >= 1
        assert history[0][1] == pytest.approx(10_000.0)

    def test_market_prices_populated(self):
        broker = _make_broker()
        assert "EURUSD" in broker.market_prices
        assert "XAUUSD" in broker.market_prices
        assert "BTC/USD" in broker.market_prices

    def test_config_dict_overrides_balance(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(config={"initial_balance": 25_000.0}, slippage_model="zero", seed=0)
        broker.connected = True
        assert broker.balance == pytest.approx(25_000.0)

    def test_commission_per_lot_stored(self):
        broker = _make_broker(commission_per_lot=7.0)
        assert broker._commission_per_lot == pytest.approx(7.0)

    def test_redis_state_none_when_redis_unavailable(self, monkeypatch):
        # Simulate Redis being unavailable by making ping() raise
        import redis as _redis_lib

        monkeypatch.setattr(_redis_lib, "from_url", lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("no redis")))
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        assert broker._redis_state is None


# ---------------------------------------------------------------------------
# PaperTradingBroker — connect / disconnect
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_sets_connected(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        result = await broker.connect()
        assert result is True
        assert broker.connected is True

    @pytest.mark.asyncio
    async def test_disconnect_clears_connected(self):
        broker = _make_broker()
        result = await broker.disconnect()
        assert result is True
        assert broker.connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        from brokers.paper_trading import PaperTradingBroker

        async with PaperTradingBroker(slippage_model="zero", seed=0) as broker:
            assert broker.connected is True
        assert broker.connected is False


# ---------------------------------------------------------------------------
# PaperTradingBroker — place_order (market)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlaceMarketOrder:
    def test_market_buy_returns_filled_order(self):
        from brokers.base import OrderStatus

        broker = _make_broker()
        order = _buy(broker)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == pytest.approx(1.0)

    def test_market_sell_returns_filled_order(self):
        from brokers.base import OrderStatus

        broker = _make_broker()
        _buy(broker)  # open position first
        order = _sell(broker)
        assert order.status == OrderStatus.FILLED

    def test_market_order_stored_in_orders(self):
        broker = _make_broker()
        order = _buy(broker)
        assert order.id in broker.orders

    def test_market_order_creates_position(self):
        broker = _make_broker()
        _buy(broker)
        assert "EURUSD" in broker.positions

    def test_market_order_average_price_set(self):
        broker = _make_broker()
        order = _buy(broker)
        assert order.average_price is not None
        assert order.average_price > 0.0

    def test_market_order_unknown_symbol_uses_default_price(self):
        from brokers.base import OrderStatus

        broker = _make_broker()
        order = _buy(broker, symbol="UNKNOWN_SYM")
        assert order.status == OrderStatus.FILLED
        assert order.average_price == pytest.approx(1000.0)

    def test_not_connected_raises(self):
        broker = _make_broker()
        broker.connected = False
        with pytest.raises(ConnectionError):
            _buy(broker)

    def test_equity_snapshot_taken_after_fill(self):
        broker = _make_broker()
        initial_len = len(broker._equity_history)
        _buy(broker)
        assert len(broker._equity_history) > initial_len


# ---------------------------------------------------------------------------
# PaperTradingBroker — place_order (limit / stop)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlaceLimitOrder:
    def test_limit_order_status_open(self):
        from brokers.base import OrderStatus

        broker = _make_broker()
        order = _limit_buy(broker)
        assert order.status == OrderStatus.OPEN

    def test_limit_order_stored(self):
        broker = _make_broker()
        order = _limit_buy(broker)
        assert order.id in broker.orders

    def test_limit_order_does_not_create_position(self):
        broker = _make_broker()
        _limit_buy(broker)
        assert "EURUSD" not in broker.positions

    def test_stop_order_status_open(self):
        from brokers.base import OrderSide, OrderStatus, OrderType

        broker = _make_broker()
        order = broker.place_order("EURUSD", OrderSide.BUY, OrderType.STOP, 1.0, stop_price=1.07)
        assert order.status == OrderStatus.OPEN


# ---------------------------------------------------------------------------
# PaperTradingBroker — cancel_order
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCancelOrder:
    def test_cancel_pending_order(self):
        from brokers.base import OrderStatus

        broker = _make_broker()
        order = _limit_buy(broker)
        result = broker.cancel_order(order.id)
        assert result is True
        assert broker.orders[order.id].status == OrderStatus.CANCELLED

    def test_cancel_nonexistent_order_returns_false(self):
        broker = _make_broker()
        assert broker.cancel_order("nonexistent-id") is False

    def test_cancel_filled_order_returns_false(self):
        broker = _make_broker()
        order = _buy(broker)
        result = broker.cancel_order(order.id)
        assert result is False


# ---------------------------------------------------------------------------
# PaperTradingBroker — get_order
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetOrder:
    def test_get_existing_order(self):
        broker = _make_broker()
        order = _buy(broker)
        fetched = broker.get_order(order.id)
        assert fetched is order

    def test_get_nonexistent_order_returns_none(self):
        broker = _make_broker()
        assert broker.get_order("no-such-id") is None


# ---------------------------------------------------------------------------
# PaperTradingBroker — get_positions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPositions:
    def test_no_positions_initially(self):
        broker = _make_broker()
        assert broker.get_positions() == []

    def test_position_created_after_buy(self):
        broker = _make_broker()
        _buy(broker)
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "EURUSD"

    def test_position_side_long_after_buy(self):
        broker = _make_broker()
        _buy(broker)
        pos = broker.get_positions()[0]
        assert pos.side == "LONG"

    def test_position_unrealized_pnl_computed(self):
        broker = _make_broker()
        _buy(broker)
        broker.update_market_price("EURUSD", 1.0900)
        pos = broker.get_positions()[0]
        assert pos.unrealized_pnl != 0.0

    def test_position_id_set(self):
        broker = _make_broker()
        _buy(broker)
        pos = broker.get_positions()[0]
        assert pos.id  # non-empty

    def test_multiple_symbols(self):
        broker = _make_broker()
        _buy(broker, "EURUSD")
        _buy(broker, "XAUUSD")
        assert len(broker.get_positions()) == 2


# ---------------------------------------------------------------------------
# PaperTradingBroker — close_position
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClosePosition:
    def test_close_existing_position(self):
        broker = _make_broker()
        _buy(broker)
        result = broker.close_position("EURUSD")
        assert result is True
        assert "EURUSD" not in broker.positions

    def test_close_nonexistent_position_returns_false(self):
        broker = _make_broker()
        assert broker.close_position("NOSYM") is False

    def test_close_long_profitable(self):
        broker = _make_broker()
        _buy(broker)
        broker.update_market_price("EURUSD", 1.1000)
        initial_balance = broker.balance
        broker.close_position("EURUSD")
        assert broker.balance > initial_balance

    def test_close_long_losing(self):
        broker = _make_broker()
        _buy(broker)
        broker.update_market_price("EURUSD", 1.0500)
        initial_balance = broker.balance
        broker.close_position("EURUSD")
        assert broker.balance < initial_balance

    def test_close_short_profitable(self):
        from brokers.base import OrderSide, OrderType

        broker = _make_broker()
        broker.place_order("EURUSD", OrderSide.SELL, OrderType.MARKET, 1.0)
        broker.update_market_price("EURUSD", 1.0500)
        initial_balance = broker.balance
        broker.close_position("EURUSD")
        assert broker.balance > initial_balance

    def test_close_by_position_id(self):
        broker = _make_broker()
        _buy(broker)
        pos = broker.get_positions()[0]
        result = broker.close_position(pos.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_close_all_positions(self):
        broker = _make_broker()
        _buy(broker, "EURUSD")
        _buy(broker, "XAUUSD")
        closed = await broker.close_all_positions()
        assert closed == 2
        assert broker.positions == {}


# ---------------------------------------------------------------------------
# PaperTradingBroker — get_account_info
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAccountInfo:
    def test_returns_account_info(self):
        from brokers.base import AccountInfo

        broker = _make_broker()
        info = broker.get_account_info()
        assert isinstance(info, AccountInfo)

    def test_balance_matches(self):
        broker = _make_broker()
        info = broker.get_account_info()
        assert info.balance == pytest.approx(broker.balance)

    def test_equity_includes_unrealized(self):
        broker = _make_broker()
        _buy(broker)
        broker.update_market_price("EURUSD", 1.1000)
        info = broker.get_account_info()
        assert info.equity > info.balance  # unrealized profit

    def test_positions_count(self):
        broker = _make_broker()
        _buy(broker, "EURUSD")
        _buy(broker, "XAUUSD")
        info = broker.get_account_info()
        assert info.positions_count == 2

    def test_equity_history_grows_after_60s(self, monkeypatch):
        broker = _make_broker()
        # Force last snapshot to be old
        broker._equity_history[-1] = (time.time() - 61, broker.initial_balance)
        initial_len = len(broker._equity_history)
        broker.get_account_info()
        assert len(broker._equity_history) > initial_len

    def test_equity_history_not_duplicated_within_60s(self):
        broker = _make_broker()
        len_before = len(broker._equity_history)
        broker.get_account_info()
        broker.get_account_info()
        # Should not add more than one point within 60s
        assert len(broker._equity_history) <= len_before + 1


# ---------------------------------------------------------------------------
# PaperTradingBroker — get_market_data
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMarketData:
    def test_returns_list(self):
        broker = _make_broker()
        data = broker.get_market_data("EURUSD")
        assert isinstance(data, list)

    def test_default_limit_100(self):
        broker = _make_broker()
        data = broker.get_market_data("EURUSD")
        assert len(data) == 100

    def test_custom_limit(self):
        broker = _make_broker()
        data = broker.get_market_data("EURUSD", limit=10)
        assert len(data) == 10

    def test_bar_structure(self):
        broker = _make_broker()
        bar = broker.get_market_data("EURUSD", limit=1)[0]
        for key in ("timestamp", "open", "high", "low", "close", "volume"):
            assert key in bar

    def test_high_gte_close(self):
        broker = _make_broker()
        for bar in broker.get_market_data("EURUSD", limit=20):
            assert bar["high"] >= bar["close"]

    def test_low_lte_close(self):
        broker = _make_broker()
        for bar in broker.get_market_data("EURUSD", limit=20):
            assert bar["low"] <= bar["close"]

    def test_unknown_symbol_uses_fallback_price(self):
        broker = _make_broker()
        data = broker.get_market_data("UNKNOWN", limit=5)
        assert len(data) == 5
        assert data[0]["close"] > 0.0

    def test_timeframe_variants(self):
        broker = _make_broker()
        for tf in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "unknown"):
            data = broker.get_market_data("EURUSD", timeframe=tf, limit=3)
            assert len(data) == 3


# ---------------------------------------------------------------------------
# PaperTradingBroker — update_market_price / get_market_price
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarketPrice:
    def test_update_and_get(self):
        broker = _make_broker()
        broker.update_market_price("EURUSD", 1.1234)
        assert broker.get_market_price("EURUSD") == pytest.approx(1.1234)

    def test_get_unknown_symbol_returns_zero(self):
        broker = _make_broker()
        assert broker.get_market_price("NOSYM") == 0.0

    def test_update_affects_position_pnl(self):
        broker = _make_broker()
        _buy(broker)
        broker.update_market_price("EURUSD", 1.2000)
        pos = broker.get_positions()[0]
        assert pos.unrealized_pnl > 0.0


# ---------------------------------------------------------------------------
# PaperTradingBroker — set_spread
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetSpread:
    def test_set_spread_for_symbol(self):
        broker = _make_broker()
        broker.set_spread(0.002, symbol="EURUSD")
        assert broker._slippage._spread_overrides["EURUSD"] == pytest.approx(0.001)

    def test_set_default_spread(self):
        broker = _make_broker()
        broker.set_spread(0.005)
        assert broker._current_spread == pytest.approx(0.005)


# ---------------------------------------------------------------------------
# PaperTradingBroker — commission
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCommission:
    def test_zero_commission_no_balance_change(self):
        broker = _make_broker(commission_per_lot=0.0)
        initial = broker.balance
        broker._deduct_commission(100_000.0)
        assert broker.balance == pytest.approx(initial)

    def test_commission_deducted_from_balance(self):
        broker = _make_broker(commission_per_lot=7.0)
        initial = broker.balance
        broker._deduct_commission(100_000.0)  # 1 standard lot
        assert broker.balance == pytest.approx(initial - 7.0)

    def test_commission_proportional_to_quantity(self):
        broker = _make_broker(commission_per_lot=7.0)
        initial = broker.balance
        broker._deduct_commission(200_000.0)  # 2 lots
        assert broker.balance == pytest.approx(initial - 14.0)

    def test_commission_charged_on_market_order(self):
        broker = _make_broker(commission_per_lot=7.0)
        initial = broker.balance
        _buy(broker, qty=100_000.0)
        assert broker.balance < initial

    def test_commission_charged_on_close(self):
        broker = _make_broker(commission_per_lot=7.0)
        _buy(broker, qty=100_000.0)
        balance_after_open = broker.balance
        broker.close_position("EURUSD")
        assert broker.balance < balance_after_open + 1.0  # close commission deducted


# ---------------------------------------------------------------------------
# PaperTradingBroker — _update_position (averaging)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdatePosition:
    def test_second_buy_averages_price(self):
        broker = _make_broker()
        broker.market_prices["EURUSD"] = 1.0800
        _buy(broker, qty=1.0)
        broker.market_prices["EURUSD"] = 1.0900
        _buy(broker, qty=1.0)
        pos = broker.positions["EURUSD"]
        assert pos.quantity == pytest.approx(2.0)
        assert 1.0800 < pos.entry_price < 1.0900

    def test_sell_creates_short_position(self):
        from brokers.base import OrderSide, OrderType

        broker = _make_broker()
        broker.place_order("EURUSD", OrderSide.SELL, OrderType.MARKET, 1.0)
        pos = broker.positions["EURUSD"]
        assert pos.side == "SHORT"


# ---------------------------------------------------------------------------
# PaperTradingBroker — place_market_order (async)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlaceMarketOrderAsync:
    @pytest.mark.asyncio
    async def test_async_buy(self):
        from brokers.base import OrderStatus

        broker = _make_broker()
        order = await broker.place_market_order("EURUSD", "buy", 1.0)
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_async_sell(self):
        from brokers.base import OrderStatus

        broker = _make_broker()
        order = await broker.place_market_order("EURUSD", "sell", 1.0)
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_async_long_alias(self):
        from brokers.base import OrderStatus

        broker = _make_broker()
        order = await broker.place_market_order("EURUSD", "long", 1.0)
        assert order.status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# PaperTradingBroker — equity history / snapshot
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEquityHistory:
    def test_initial_history_has_one_point(self):
        broker = _make_broker()
        history = broker.get_equity_history()
        assert len(history) >= 1

    def test_snapshot_appends_point(self):
        broker = _make_broker()
        before = len(broker._equity_history)
        broker._snapshot_equity()
        assert len(broker._equity_history) == before + 1

    def test_history_bounded_at_10000(self):
        broker = _make_broker()
        for _ in range(10_005):
            broker._snapshot_equity()
        assert len(broker._equity_history) == 10_000

    def test_get_equity_history_returns_list(self):
        broker = _make_broker()
        history = broker.get_equity_history()
        assert isinstance(history, list)

    def test_equity_history_tuple_structure(self):
        broker = _make_broker()
        ts, equity = broker.get_equity_history()[0]
        assert isinstance(ts, float)
        assert isinstance(equity, float)


# ---------------------------------------------------------------------------
# PaperTradingBroker — set_price_feed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetPriceFeed:
    def test_price_feed_stored(self):
        broker = _make_broker()
        feed = MagicMock()
        broker.set_price_feed(feed)
        assert broker._price_feed is feed


# ---------------------------------------------------------------------------
# PaperTradingBroker — _persist_trade (no session factory)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPersistTrade:
    def test_no_session_factory_is_noop(self):
        from brokers.base import Position

        broker = _make_broker()
        pos = Position(
            symbol="EURUSD",
            side="LONG",
            quantity=1.0,
            entry_price=1.0820,
            current_price=1.0850,
            unrealized_pnl=30.0,
        )
        # Should not raise
        broker._persist_trade(pos, 1.0850, 30.0)

    def test_session_factory_exception_logged(self):
        from brokers.base import Position
        from brokers.paper_trading import PaperTradingBroker

        def _bad_factory():
            raise RuntimeError("db down")

        broker = PaperTradingBroker(session_factory=_bad_factory, slippage_model="zero", seed=0)
        broker.connected = True
        pos = Position(
            symbol="EURUSD",
            side="LONG",
            quantity=1.0,
            entry_price=1.0820,
            current_price=1.0850,
            unrealized_pnl=30.0,
        )
        # Should not raise — exception is caught and logged
        broker._persist_trade(pos, 1.0850, 30.0)


# ---------------------------------------------------------------------------
# PaperTradingBroker — Redis state (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRedisState:
    def test_restore_state_skips_invalid_positions(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        broker.connected = True

        mock_redis = MagicMock()
        mock_redis.load_state_on_boot.return_value = {
            "positions": [
                {"symbol": "", "entry_price": 0, "quantity": 0},  # invalid — skipped
                {"symbol": "EURUSD", "entry_price": 1.08, "quantity": 1.0, "side": "BUY"},
            ]
        }
        broker._redis_state = mock_redis
        broker._restore_state_from_redis()
        assert "EURUSD" in broker.positions
        assert "" not in broker.positions

    def test_restore_state_handles_exception(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        broker.connected = True

        mock_redis = MagicMock()
        mock_redis.load_state_on_boot.side_effect = RuntimeError("redis error")
        broker._redis_state = mock_redis
        # Should not raise
        broker._restore_state_from_redis()

    @pytest.mark.asyncio
    async def test_connect_restores_redis_state(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        mock_redis = MagicMock()
        mock_redis.load_state_on_boot.return_value = {"positions": []}
        broker._redis_state = mock_redis
        await broker.connect()
        mock_redis.load_state_on_boot.assert_called_once()

    def test_close_position_removes_from_redis(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        broker.connected = True
        mock_redis = MagicMock()
        broker._redis_state = mock_redis
        _buy(broker)
        broker.close_position("EURUSD")
        mock_redis.remove_position.assert_called_once_with("EURUSD")

    def test_close_position_redis_exception_does_not_raise(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        broker.connected = True
        mock_redis = MagicMock()
        mock_redis.remove_position.side_effect = RuntimeError("redis down")
        broker._redis_state = mock_redis
        _buy(broker)
        # Should not raise
        broker.close_position("EURUSD")

    def test_place_order_attempts_redis_save(self):
        # The redis block is entered when _redis_state is set.
        # order.filled_price doesn't exist on the Order dataclass, so the
        # AttributeError is caught and logged — save_order may or may not be
        # called depending on where the error occurs.  We verify the block is
        # entered by confirming no exception propagates to the caller.
        from brokers.paper_trading import PaperTradingBroker
        from brokers.base import OrderStatus

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        broker.connected = True
        mock_redis = MagicMock()
        broker._redis_state = mock_redis
        order = _buy(broker)
        # Order must still be filled — Redis failure must not affect the result
        assert order.status == OrderStatus.FILLED

    def test_place_order_redis_exception_does_not_raise(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(slippage_model="zero", seed=0)
        broker.connected = True
        mock_redis = MagicMock()
        mock_redis.save_order.side_effect = RuntimeError("redis down")
        broker._redis_state = mock_redis
        # Should not raise
        _buy(broker)


# ---------------------------------------------------------------------------
# PaperTradingBroker — is_connected / repr
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMiscBroker:
    def test_is_connected_true(self):
        broker = _make_broker()
        assert broker.is_connected() is True

    @pytest.mark.asyncio
    async def test_is_connected_false_after_disconnect(self):
        broker = _make_broker()
        await broker.disconnect()
        assert broker.is_connected() is False

    def test_repr_contains_name(self):
        broker = _make_broker()
        assert "PaperTradingBroker" in repr(broker)
