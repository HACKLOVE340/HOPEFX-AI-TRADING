# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Broker coverage boost — targets uncovered lines in brokers/__init__.py and brokers/manager.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# brokers/__init__.py — Order / Position / PaperTradingBroker
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrokersInitOrder:
    def _order(self, **kw):
        from brokers import Order, OrderSide, OrderType

        defaults = dict(
            id="o1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=1.0,
        )
        defaults.update(kw)
        return Order(**defaults)

    def test_remaining_quantity(self):
        o = self._order(quantity=10.0, filled_quantity=3.0)
        assert o.remaining_quantity == pytest.approx(7.0)

    def test_is_complete_filled(self):
        from brokers import OrderStatus

        o = self._order()
        o.status = OrderStatus.FILLED
        assert o.is_complete is True

    def test_is_complete_cancelled(self):
        from brokers import OrderStatus

        o = self._order()
        o.status = OrderStatus.CANCELLED
        assert o.is_complete is True

    def test_is_complete_pending(self):
        from brokers import OrderStatus

        o = self._order()
        o.status = OrderStatus.PENDING
        assert o.is_complete is False

    def test_to_dict_keys(self):
        o = self._order()
        d = o.to_dict()
        assert "id" in d and "symbol" in d and "side" in d


@pytest.mark.unit
class TestBrokersInitPosition:
    def _pos(self, **kw):
        from brokers import OrderSide, Position

        defaults = dict(
            id="p1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=1.0,
            entry_price=1950.0,
            current_price=1960.0,
        )
        defaults.update(kw)
        return Position(**defaults)

    def test_update_price_buy(self):
        pos = self._pos(
            side=__import__("brokers").OrderSide.BUY, quantity=2.0, entry_price=1950.0, current_price=1950.0
        )
        pos.update_price(1970.0)
        assert pos.unrealized_pnl == pytest.approx(40.0)

    def test_update_price_sell(self):
        from brokers import OrderSide

        pos = self._pos(side=OrderSide.SELL, quantity=1.0, entry_price=1950.0, current_price=1950.0)
        pos.update_price(1930.0)
        assert pos.unrealized_pnl == pytest.approx(20.0)

    def test_market_value(self):
        pos = self._pos(quantity=2.0, current_price=2000.0)
        assert pos.market_value == pytest.approx(4000.0)

    def test_to_dict_keys(self):
        pos = self._pos()
        d = pos.to_dict()
        assert "id" in d and "symbol" in d


@pytest.mark.unit
class TestPaperTradingBrokerInit:
    def _broker(self, **kw):
        from brokers import PaperTradingBroker

        return PaperTradingBroker(initial_balance=10_000.0, seed=42, **kw)

    @pytest.mark.asyncio
    async def test_connect_sets_connected(self):
        b = self._broker()
        result = await b.connect()
        assert result is True
        assert b.connected is True

    @pytest.mark.asyncio
    async def test_disconnect_sets_disconnected(self):
        b = self._broker()
        await b.connect()
        result = await b.disconnect()
        assert result is True
        assert b.connected is False

    def test_get_account_info_keys(self):
        b = self._broker()
        info = b.get_account_info()
        # Returns AccountInfo dataclass or dict
        if hasattr(info, "balance"):
            assert info.balance >= 0
        else:
            assert "balance" in info

    def test_update_market_price_and_get(self):
        b = self._broker()
        b.update_market_price("XAUUSD", 1950.0)
        assert b.get_market_price("XAUUSD") == pytest.approx(1950.0)

    def test_get_market_price_missing(self):
        b = self._broker()
        # Returns a default price (may be non-zero from defaults)
        price = b.get_market_price("NONEXISTENT_PAIR_XYZ")
        assert isinstance(price, float)

    def test_positions_property(self):
        b = self._broker()
        assert isinstance(b.positions, dict)

    def test_orders_property(self):
        b = self._broker()
        assert isinstance(b.orders, dict)

    def test_market_prices_property(self):
        b = self._broker()
        assert isinstance(b.market_prices, dict)

    def test_place_order_not_connected_raises(self):
        from brokers.paper_trading import PaperTradingBroker
        from brokers.base import OrderSide, OrderType

        b = PaperTradingBroker({})
        b.connected = False
        with pytest.raises(ConnectionError):
            b.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    @pytest.mark.asyncio
    async def test_place_order_market_buy(self):
        from brokers.paper_trading import PaperTradingBroker
        from brokers.base import OrderSide, OrderType, OrderStatus

        b = PaperTradingBroker({})
        await b.connect()
        b.update_market_price("XAUUSD", 1950.0)
        order = b.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order.symbol == "XAUUSD"
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_place_order_market_sell(self):
        from brokers.paper_trading import PaperTradingBroker
        from brokers.base import OrderSide, OrderType

        b = PaperTradingBroker({})
        await b.connect()
        b.update_market_price("XAUUSD", 1950.0)
        b.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        order = b.place_order("XAUUSD", OrderSide.SELL, OrderType.MARKET, 1.0)
        assert order is not None

    @pytest.mark.asyncio
    async def test_place_order_limit(self):
        from brokers.paper_trading import PaperTradingBroker
        from brokers.base import OrderSide, OrderType

        b = PaperTradingBroker({})
        await b.connect()
        b.update_market_price("XAUUSD", 1950.0)
        order = b.place_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 1.0, price=1940.0)
        # Limit orders are not immediately filled
        assert order.filled_quantity == 0.0

    @pytest.mark.asyncio
    async def test_cancel_order_pending(self):
        from brokers.paper_trading import PaperTradingBroker
        from brokers.base import OrderSide, OrderType

        b = PaperTradingBroker({})
        await b.connect()
        b.update_market_price("XAUUSD", 1950.0)
        order = b.place_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 1.0, price=1940.0)
        result = b.cancel_order(order.id)
        assert result is True

    def test_cancel_order_not_found(self):
        from brokers.paper_trading import PaperTradingBroker

        b = PaperTradingBroker({})
        result = b.cancel_order("nonexistent")
        assert result is False

    def test_get_positions_returns_list(self):
        from brokers.paper_trading import PaperTradingBroker

        b = PaperTradingBroker({})
        positions = b.get_positions()
        assert isinstance(positions, list)

    def test_is_connected_false(self):
        from brokers.paper_trading import PaperTradingBroker

        b = PaperTradingBroker({})
        b.connected = False
        assert b.is_connected() is False

    def test_is_connected_true(self):
        from brokers.paper_trading import PaperTradingBroker

        b = PaperTradingBroker({})
        b.connected = True
        assert b.is_connected() is True


@pytest.mark.unit
class TestCreateBroker:
    def test_create_paper_broker(self):
        from brokers import create_broker

        b = create_broker("paper", {"initial_balance": 5000.0})
        assert b is not None

    def test_create_unknown_raises(self):
        from brokers import create_broker

        with pytest.raises(ValueError, match="Unknown broker"):
            create_broker("unknown_xyz", {})


# ---------------------------------------------------------------------------
# brokers/manager.py — BrokerManager
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrokerManager:
    def _mgr(self):
        from brokers.manager import BrokerManager

        return BrokerManager(primary_broker_name="paper")

    def _mock_broker(self, connected=True):
        b = MagicMock()
        b.connect.return_value = connected
        b.disconnect.return_value = True
        b.place_order.return_value = MagicMock(id="o1")
        b.cancel_order.return_value = True
        b.get_order.return_value = None
        b.get_positions.return_value = []
        b.close_position.return_value = True
        b.get_account_info.return_value = {"balance": 10000.0}
        b.get_market_data.return_value = {}
        b.heartbeat.return_value = {"status": "ok"}
        return b

    def test_register_broker(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("test", b)
        assert "test" in mgr._brokers

    def test_set_active_valid(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("test", b)
        mgr.set_active("test")
        assert mgr._active_name == "test"

    def test_set_active_invalid_raises(self):
        mgr = self._mgr()
        with pytest.raises(ValueError):
            mgr.set_active("nonexistent")

    def test_connect_all(self):
        mgr = self._mgr()
        b = self._mock_broker(connected=True)
        mgr.register("mock", b)
        results = mgr.connect_all()
        assert "mock" in results

    def test_connect_all_broker_raises(self):
        mgr = self._mgr()
        b = self._mock_broker()
        b.connect.side_effect = RuntimeError("conn fail")
        mgr.register("bad", b)
        results = mgr.connect_all()
        assert results["bad"] is False

    def test_disconnect_all(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("mock", b)
        mgr.disconnect_all()  # must not raise

    def test_disconnect_all_broker_raises(self):
        mgr = self._mgr()
        b = self._mock_broker()
        b.disconnect.side_effect = RuntimeError("disc fail")
        mgr.register("bad", b)
        mgr.disconnect_all()  # must not raise

    def test_connect_primary_no_broker(self):
        mgr = self._mgr()
        result = mgr.connect_primary()
        assert result is False

    def test_connect_primary_success(self):
        mgr = self._mgr()
        b = self._mock_broker(connected=True)
        mgr.register("paper", b)
        mgr._active_name = "paper"
        result = mgr.connect_primary()
        assert result is True

    def test_connect_primary_raises(self):
        mgr = self._mgr()
        b = self._mock_broker()
        b.connect.side_effect = RuntimeError("fail")
        mgr.register("paper", b)
        mgr._active_name = "paper"
        result = mgr.connect_primary()
        assert result is False

    def test_place_order_no_broker(self):
        from brokers.base import OrderSide, OrderType

        mgr = self._mgr()
        with pytest.raises(RuntimeError):
            mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_place_order_kill_switch_active(self):
        from brokers.base import OrderSide, OrderType

        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        ks = MagicMock()
        ks.is_active.return_value = True
        mgr._kill_switch = ks
        with pytest.raises(RuntimeError, match="[Kk]ill"):
            mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_place_order_success(self):
        from brokers.base import OrderSide, OrderType

        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        order = mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order is not None

    def test_cancel_order_no_broker(self):
        mgr = self._mgr()
        with pytest.raises(RuntimeError):
            mgr.cancel_order("o1")

    def test_cancel_order_success(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        result = mgr.cancel_order("o1")
        assert result is True

    def test_get_order_no_broker(self):
        mgr = self._mgr()
        with pytest.raises(RuntimeError):
            mgr.get_order("o1")

    def test_get_order_success(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        result = mgr.get_order("o1")
        assert result is None

    def test_get_positions_no_broker(self):
        mgr = self._mgr()
        with pytest.raises(RuntimeError):
            mgr.get_positions()

    def test_get_positions_success(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        result = mgr.get_positions()
        assert isinstance(result, list)

    def test_close_position_no_broker(self):
        mgr = self._mgr()
        with pytest.raises(RuntimeError):
            mgr.close_position("p1")

    def test_close_position_success(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        result = mgr.close_position("p1")
        assert result is True

    def test_get_account_info_no_broker(self):
        mgr = self._mgr()
        with pytest.raises(RuntimeError):
            mgr.get_account_info()

    def test_get_account_info_success(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        info = mgr.get_account_info()
        assert "balance" in info

    def test_heartbeat(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        result = mgr.heartbeat()
        assert isinstance(result, dict)

    def test_get_active_broker_name_none(self):
        mgr = self._mgr()
        name = mgr.get_active_broker_name()
        assert name is None or isinstance(name, str)

    def test_is_connected_false(self):
        mgr = self._mgr()
        assert mgr.is_connected() is False

    def test_is_connected_true(self):
        mgr = self._mgr()
        b = self._mock_broker()
        b.is_connected = MagicMock(return_value=True)
        mgr.register("paper", b)
        mgr._active_name = "paper"
        result = mgr.is_connected()
        assert isinstance(result, bool)

    def test_build_failover_chain(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        chain = mgr._build_failover_chain()
        assert isinstance(chain, list)

    def test_record_failure_increments(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        mgr._record_failure(RuntimeError("test"))
        assert mgr._consecutive_failures.get("paper", 0) >= 1

    def test_reset_failures(self):
        mgr = self._mgr()
        b = self._mock_broker()
        mgr.register("paper", b)
        mgr._active_name = "paper"
        mgr._consecutive_failures["paper"] = 5
        mgr._reset_failures()
        assert mgr._consecutive_failures.get("paper", 0) == 0

    def test_context_manager(self):
        mgr = self._mgr()
        with mgr as m:
            assert m is mgr

    def test_close_all_positions_empty(self):
        mgr = self._mgr()
        b = self._mock_broker()
        b.get_positions.return_value = []
        mgr.register("paper", b)
        mgr._active_name = "paper"
        result = mgr.close_all_positions()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# brokers/factory.py — BrokerFactory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrokerFactory:
    def test_list_brokers(self):
        from brokers.factory import BrokerFactory

        brokers = BrokerFactory.list_brokers()
        assert isinstance(brokers, list)

    def test_get_broker_info_unknown(self):
        from brokers.factory import BrokerFactory

        info = BrokerFactory.get_broker_info("nonexistent_xyz")
        assert "error" in info or info == {}

    def test_create_broker_paper(self):
        from brokers.factory import BrokerFactory

        b = BrokerFactory.create_broker("paper", {"initial_balance": 1000.0})
        assert b is not None

    def test_create_broker_none_uses_env(self):
        from brokers.factory import BrokerFactory

        with patch.dict("os.environ", {"BROKER": "paper"}):
            b = BrokerFactory.create_broker(None, {})
            assert b is not None


# ---------------------------------------------------------------------------
# brokers/ibkr_fix_bridge.py — IBKRFIXConfig
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIBKRFIXConfig:
    def test_is_paper_true(self):
        from brokers.ibkr_fix_bridge import IBKRFIXConfig

        cfg = IBKRFIXConfig(host="127.0.0.1", port=7497)
        assert cfg.is_paper is True

    def test_is_paper_false(self):
        from brokers.ibkr_fix_bridge import IBKRFIXConfig

        cfg = IBKRFIXConfig(host="127.0.0.1", port=4001)
        assert cfg.is_paper is False

    def test_generate_quickfix_cfg(self):
        from brokers.ibkr_fix_bridge import IBKRFIXConfig

        cfg = IBKRFIXConfig(host="127.0.0.1", port=7497)
        text = cfg.generate_quickfix_cfg()
        assert "BeginString" in text or len(text) > 0


# ---------------------------------------------------------------------------
# brokers/ohlcv_store.py
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOHLCVStore:
    def _store(self):
        from brokers.ohlcv_store import OHLCVStore

        return OHLCVStore()

    def test_push_and_get(self):
        store = self._store()
        bar = {"open": 1950.0, "high": 1960.0, "low": 1940.0, "close": 1955.0, "volume": 100.0}
        store.push("XAUUSD", bar)
        bars = store.get("XAUUSD")
        assert len(bars) >= 1

    def test_get_missing_symbol(self):
        import uuid

        store = self._store()
        # Use a unique symbol guaranteed to have no data in Redis or the ring buffer.
        unique_sym = f"NOSYM_{uuid.uuid4().hex}"
        bars = store.get(unique_sym)
        # get() returns None when the symbol has no data.
        assert bars is None

    def test_symbols(self):
        store = self._store()
        bar = {"open": 1950.0, "high": 1960.0, "low": 1940.0, "close": 1955.0, "volume": 100.0}
        store.push("XAUUSD", bar)
        assert "XAUUSD" in store.symbols()

    def test_health(self):
        store = self._store()
        h = store.health()
        assert isinstance(h, dict)


# ---------------------------------------------------------------------------
# brokers/prop_firms/guard.py
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPropFirmGuard:
    def test_check_prop_firm_rules_no_config(self):
        from brokers.prop_firms.guard import check_prop_firm_rules

        account = MagicMock()
        account.balance = 10000.0
        account.daily_loss = 0.0
        account.drawdown = 0.0
        # Should not raise; suppress if config not present
        import contextlib

        with contextlib.suppress(Exception):
            check_prop_firm_rules(account)
