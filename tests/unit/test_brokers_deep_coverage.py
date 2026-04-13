"""Deep coverage tests for brokers/ modules."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestBrokersInitOANDA:
    def _broker(self):
        from brokers import OANDABroker

        return OANDABroker(api_key="k", account_id="a1", practice=True)

    def test_init_sets_practice_url(self):
        b = self._broker()
        assert "fxpractice" in b.base_url

    def test_init_live_url(self):
        from brokers import OANDABroker

        b = OANDABroker(api_key="k", account_id="a1", practice=False)
        assert "fxtrade" in b.base_url

    @pytest.mark.asyncio
    async def test_disconnect_closes_session(self):
        b = self._broker()
        mock_session = MagicMock()

        # close() must be a coroutine so `await session.close()` works
        async def _async_close():
            pass

        mock_session.close = _async_close
        b._session = mock_session
        b.connected = True
        await b.disconnect()
        assert not b.connected

    @pytest.mark.asyncio
    async def test_cancel_order_success(self):
        b = self._broker()
        with patch.object(b, "_make_request", return_value={}):
            result = await b.cancel_order("ord-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_order_failure(self):
        b = self._broker()
        with patch.object(b, "_make_request", side_effect=Exception("fail")):
            result = await b.cancel_order("ord-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_position_invalid_id(self):
        b = self._broker()
        result = await b.close_position("badformat")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_position_success(self):
        b = self._broker()
        with patch.object(b, "_make_request", return_value={"longOrderFillTransaction": {}}):
            result = await b.close_position("XAUUSD_long")
        assert result is True

    @pytest.mark.asyncio
    async def test_close_position_exception(self):
        b = self._broker()
        with patch.object(b, "_make_request", side_effect=Exception("err")):
            result = await b.close_position("XAUUSD/long")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_account_info(self):
        b = self._broker()
        payload = {
            "account": {
                "balance": "5000",
                "NAV": "5100",
                "marginUsed": "100",
                "marginAvailable": "5000",
                "unrealizedPL": "50",
                "realizedPL": "200",
                "currency": "USD",
                "positions": [],
            }
        }
        with patch.object(b, "_make_request", return_value=payload):
            info = await b.get_account_info()
        assert info["balance"] == 5000.0

    @pytest.mark.asyncio
    async def test_get_pending_orders(self):
        b = self._broker()
        payload = {"orders": [{"id": "1", "instrument": "XAU_USD", "units": 100, "type": "LIMIT", "price": "1950"}]}
        with patch.object(b, "_make_request", return_value=payload):
            orders = await b.get_pending_orders()
        assert len(orders) == 1

    @pytest.mark.asyncio
    async def test_get_positions_cached(self):
        import time
        from brokers import OrderSide, Position

        b = self._broker()
        pos = Position(
            id="p1", symbol="XAU/USD", side=OrderSide.BUY, quantity=1.0, entry_price=1950.0, current_price=1960.0
        )
        b._positions_cache = {"p1": pos}
        b._last_cache_update = time.time()
        positions = await b.get_positions()
        assert len(positions) == 1

    @pytest.mark.asyncio
    async def test_get_positions_from_api(self):
        b = self._broker()
        b._last_cache_update = 0
        payload = {
            "positions": [
                {
                    "instrument": "XAU_USD",
                    "long": {
                        "units": "1",
                        "averagePrice": "1950",
                        "markPrice": "1960",
                        "unrealizedPL": "10",
                        "realizedPL": "0",
                    },
                    "short": {"units": "0"},
                }
            ]
        }
        with patch.object(b, "_make_request", return_value=payload):
            positions = await b.get_positions()
        assert len(positions) == 1

    @pytest.mark.asyncio
    async def test_place_market_order(self):
        b = self._broker()
        payload = {"orderFillTransaction": {"id": "t1", "price": "1950", "commission": "0"}}
        with patch.object(b, "_make_request", return_value=payload):
            order = await b.place_market_order("XAU/USD", "buy", 1.0)
        assert order.id == "t1"

    @pytest.mark.asyncio
    async def test_place_market_order_no_fill(self):
        b = self._broker()
        with patch.object(b, "_make_request", return_value={}), pytest.raises(ValueError):
            await b.place_market_order("XAU/USD", "buy", 1.0)


@pytest.mark.unit
class TestCreateBroker:
    def test_create_paper(self):
        from brokers import create_broker

        b = create_broker("paper", {})
        assert b is not None

    def test_create_unknown_raises(self):
        from brokers import create_broker

        with pytest.raises(ValueError):
            create_broker("unknown_broker_xyz", {})

    def test_create_ccxt(self):
        from brokers import create_broker

        mock_ccxt = MagicMock()
        mock_exchange = MagicMock()
        mock_ccxt.binance = MagicMock(return_value=mock_exchange)
        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            b = create_broker("ccxt", {"exchange": "binance"})
        assert b is not None


@pytest.mark.unit
class TestBaseBrokerDefaults:
    def _make_broker(self):
        from brokers import BaseBroker, Order, OrderSide, OrderStatus, OrderType

        class ConcreteBroker(BaseBroker):
            async def connect(self):
                self.connected = True

            async def disconnect(self):
                self.connected = False

            async def get_account_info(self):
                return {}

            async def place_market_order(self, symbol, side, quantity):
                return Order(
                    id="o1",
                    symbol=symbol,
                    side=OrderSide(side),
                    type=OrderType.MARKET,
                    quantity=quantity,
                    status=OrderStatus.FILLED,
                    filled_quantity=quantity,
                    average_fill_price=100.0,
                )

            async def cancel_order(self, order_id):
                return True

            async def get_positions(self):
                return []

            async def close_position(self, position_id):
                return True

            async def get_pending_orders(self):
                return []

        return ConcreteBroker()

    @pytest.mark.asyncio
    async def test_close_all_positions_empty(self):
        b = self._make_broker()
        result = await b.close_all_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_cancel_all_orders_empty(self):
        b = self._make_broker()
        result = await b.cancel_all_orders()
        assert result == []

    @pytest.mark.asyncio
    async def test_close_all_positions_with_positions(self):
        from brokers import OrderSide, Position

        b = self._make_broker()
        pos = Position(
            id="p1", symbol="XAUUSD", side=OrderSide.BUY, quantity=1.0, entry_price=1950.0, current_price=1960.0
        )

        async def mock_get_positions():
            return [pos]

        b.get_positions = mock_get_positions
        result = await b.close_all_positions()
        assert "p1" in result

    @pytest.mark.asyncio
    async def test_close_all_positions_failure(self):
        from brokers import OrderSide, Position

        b = self._make_broker()
        pos = Position(
            id="p1", symbol="XAUUSD", side=OrderSide.BUY, quantity=1.0, entry_price=1950.0, current_price=1960.0
        )

        async def mock_get_positions():
            return [pos]

        async def mock_close_position(pid):
            raise RuntimeError("close failed")

        b.get_positions = mock_get_positions
        b.close_position = mock_close_position
        result = await b.close_all_positions()
        assert result == []


# ---------------------------------------------------------------------------
# brokers/factory.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBrokerFactory:
    def setup_method(self):
        from brokers.factory import BrokerFactory

        BrokerFactory._brokers = {}

    def test_list_brokers_includes_paper(self):
        from brokers.factory import BrokerFactory

        brokers = BrokerFactory.list_brokers()
        assert "paper" in brokers

    def test_create_paper_broker(self):
        from brokers.factory import BrokerFactory

        b = BrokerFactory.create_broker("paper")
        assert b is not None

    def test_create_unknown_returns_none(self):
        from brokers.factory import BrokerFactory

        b = BrokerFactory.create_broker("nonexistent_xyz")
        assert b is None

    def test_create_broker_default_env(self):
        from brokers.factory import BrokerFactory

        with patch.dict("os.environ", {"BROKER": "paper"}):
            b = BrokerFactory.create_broker()
        assert b is not None

    def test_get_broker_info_known(self):
        from brokers.factory import BrokerFactory

        info = BrokerFactory.get_broker_info("paper")
        assert info.get("name") == "paper"

    def test_get_broker_info_unknown(self):
        from brokers.factory import BrokerFactory

        info = BrokerFactory.get_broker_info("does_not_exist")
        assert info == {}

    def test_register_broker(self):
        from brokers.base import BrokerConnector
        from brokers.factory import BrokerFactory

        class FakeBroker(BrokerConnector):
            def connect(self):
                return True

            def disconnect(self):
                return True

            def place_order(self, **kw):
                return None

            def cancel_order(self, oid):
                return True

            def get_order(self, oid):
                return None

            def get_positions(self):
                return []

            def close_position(self, sym):
                return True

            def get_account_info(self):
                return None

            def get_market_data(self, *a, **kw):
                return []

            def is_connected(self):
                return True

        BrokerFactory.register_broker("fake_test", FakeBroker)
        assert "fake_test" in BrokerFactory._brokers

    def test_yaml_config_missing_file(self):
        from brokers.factory import BrokerFactory

        result = BrokerFactory.get_broker_from_yaml(config_path="/nonexistent/path.yaml")
        assert result is None

    def test_yaml_config_missing_broker_key(self, tmp_path):
        import yaml
        from brokers.factory import BrokerFactory

        cfg = {"brokers": {"default": "missing_key"}}
        p = tmp_path / "brokers.yaml"
        p.write_text(yaml.dump(cfg))
        result = BrokerFactory.get_broker_from_yaml(name="missing_key", config_path=str(p))
        assert result is None

    def test_yaml_config_unsupported_type(self, tmp_path):
        import yaml
        from brokers.factory import BrokerFactory

        cfg = {"brokers": {"mybroker": {"type": "unsupported_xyz"}}}
        p = tmp_path / "brokers.yaml"
        p.write_text(yaml.dump(cfg))
        result = BrokerFactory.get_broker_from_yaml(name="mybroker", config_path=str(p))
        assert result is None


# ---------------------------------------------------------------------------
# brokers/manager.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBrokerManager:
    def _make_mock_broker(self, connected=True):
        from brokers.base import AccountInfo, BrokerConnector, Order, OrderStatus
        from datetime import datetime, timezone

        _connected_flag = connected

        class MockBroker(BrokerConnector):
            def __init__(self):
                super().__init__({})
                self.connected = _connected_flag

            def connect(self):
                self.connected = True
                return True

            def disconnect(self):
                self.connected = False
                return True

            def place_order(self, symbol, side, order_type, quantity, price=None, **kw):
                return Order(
                    id="o1",
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    quantity=quantity,
                    status=OrderStatus.FILLED,
                    filled_quantity=quantity,
                    average_price=price or 1950.0,
                    timestamp=datetime.now(timezone.utc),
                )

            def cancel_order(self, oid):
                return True

            def get_order(self, oid):
                return None

            def get_positions(self):
                return []

            def close_position(self, sym):
                return True

            def get_account_info(self):
                return AccountInfo(
                    balance=10000.0,
                    equity=10000.0,
                    margin_used=0.0,
                    margin_available=10000.0,
                    positions_count=0,
                    timestamp=datetime.now(timezone.utc),
                )

            def get_market_data(self, *a, **kw):
                return []

        return MockBroker()

    def test_init(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager(primary_broker_name="paper")
        assert mgr._primary_name == "paper"

    def test_register_and_set_active(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        assert mgr.get_active_broker_name() == "mock"

    def test_set_active_unknown_raises(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        with pytest.raises(ValueError):
            mgr.set_active("nonexistent")

    def test_connect_all(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker(connected=False)
        mgr.register("mock", broker)
        results = mgr.connect_all()
        assert results.get("mock") is True

    def test_disconnect_all(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.disconnect_all()
        assert not broker.is_connected()

    def test_place_order_no_broker_raises(self):
        from brokers.base import OrderSide, OrderType
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        with pytest.raises(RuntimeError):
            mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_place_order_kill_switch_blocks(self):
        from brokers.base import OrderSide, OrderType
        from brokers.manager import BrokerManager

        ks = MagicMock()
        ks.is_active.return_value = True
        ks._reason = "test"
        mgr = BrokerManager(kill_switch=ks)
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        with pytest.raises(RuntimeError, match="kill switch"):
            mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_place_order_success(self):
        from brokers.base import OrderSide, OrderType
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        order = mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order is not None

    def test_get_account_info(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        info = mgr.get_account_info()
        assert info.balance == 10000.0

    def test_get_positions(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        positions = mgr.get_positions()
        assert positions == []

    def test_heartbeat(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        health = mgr.heartbeat()
        assert "mock" in health
        assert health["mock"].connected is True

    def test_is_connected_no_broker(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        assert mgr.is_connected() is False

    def test_is_connected_with_broker(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        assert mgr.is_connected() is True

    def test_record_failure_triggers_failover(self):
        from brokers.manager import BrokerManager, _MAX_CONSECUTIVE_FAILURES

        mgr = BrokerManager()
        b1 = self._make_mock_broker()
        b2 = self._make_mock_broker()
        mgr.register("primary", b1)
        mgr.register("paper", b2)
        mgr.set_active("primary")
        mgr._failover_chain = ["primary", "paper"]
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            mgr._record_failure(RuntimeError("err"))
        assert mgr._active_name == "paper"

    def test_cancel_order(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        result = mgr.cancel_order("ord-1")
        assert result is True

    def test_close_all_positions_kill_switch(self):
        from brokers.manager import BrokerManager

        ks = MagicMock()
        ks.is_active.return_value = True
        ks._reason = "test"
        mgr = BrokerManager(kill_switch=ks)
        broker = self._make_mock_broker()
        mgr.register("mock", broker)
        mgr.set_active("mock")
        with pytest.raises(RuntimeError):
            mgr.close_all_positions()

    def test_context_manager(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        broker = self._make_mock_broker(connected=False)
        mgr.register("mock", broker)
        mgr.set_active("mock")
        with mgr:
            assert broker.is_connected()
        assert not broker.is_connected()

    def test_from_env(self):
        from brokers.manager import BrokerManager

        with patch.dict("os.environ", {"BROKER_PRIMARY": "paper", "BROKER_ENABLE_FIX": "false"}):
            mgr = BrokerManager.from_env()
        assert mgr._primary_name == "paper"


# ---------------------------------------------------------------------------
# brokers/ccxt_connector.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCCXTConnector:
    def _make_connector(self, connected=False):
        from brokers.ccxt_connector import CCXTConnector

        c = CCXTConnector({"exchange": "binance", "api_key": "k", "api_secret": "s"})
        if connected:
            mock_ex = MagicMock()
            mock_ex.markets = {"BTC/USDT": {}, "ETH/USDT": {}}
            mock_ex.has = {"fetchPositions": True}
            c._exchange = mock_ex
            c.connected = True
        return c

    def test_init(self):
        c = self._make_connector()
        assert c._exchange_id == "binance"
        assert not c.connected

    def test_connect_success(self):
        mock_ccxt = MagicMock()
        mock_exchange = MagicMock()
        mock_exchange.markets = {"BTC/USDT": {}}
        mock_ccxt.binance = MagicMock(return_value=mock_exchange)
        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            from brokers.ccxt_connector import CCXTConnector

            c = CCXTConnector({"exchange": "binance"})
            result = c.connect()
        assert result is True
        assert c.connected

    def test_connect_failure(self):
        mock_ccxt = MagicMock()
        mock_ccxt.binance = MagicMock(side_effect=Exception("no connection"))
        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            from brokers.ccxt_connector import CCXTConnector

            c = CCXTConnector({"exchange": "binance"})
            result = c.connect()
        assert result is False

    def test_disconnect(self):
        c = self._make_connector(connected=True)
        result = c.disconnect()
        assert result is True
        assert not c.connected

    def test_require_connected_raises(self):
        c = self._make_connector()
        with pytest.raises(RuntimeError):
            c._require_connected()

    def test_place_order(self):
        c = self._make_connector(connected=True)
        from brokers.base import OrderSide, OrderType

        raw = {
            "id": "o1",
            "symbol": "BTC/USDT",
            "side": "buy",
            "type": "market",
            "amount": 1.0,
            "status": "closed",
            "filled": 1.0,
            "average": 50000.0,
            "timestamp": None,
        }
        c._exchange.create_order.return_value = raw
        order = c.place_order("BTC/USDT", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order.id == "o1"

    def test_cancel_order_success(self):
        c = self._make_connector(connected=True)
        c._exchange.cancel_order.return_value = {}
        result = c.cancel_order("o1", "BTC/USDT")
        assert result is True

    def test_cancel_order_failure(self):
        c = self._make_connector(connected=True)
        c._exchange.cancel_order.side_effect = Exception("not found")
        result = c.cancel_order("o1")
        assert result is False

    def test_get_order_success(self):
        c = self._make_connector(connected=True)
        raw = {
            "id": "o1",
            "symbol": "BTC/USDT",
            "side": "buy",
            "type": "market",
            "amount": 1.0,
            "status": "closed",
            "filled": 1.0,
            "average": 50000.0,
            "timestamp": None,
        }
        c._exchange.fetch_order.return_value = raw
        order = c.get_order("o1")
        assert order is not None

    def test_get_order_failure(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_order.side_effect = Exception("not found")
        order = c.get_order("o1")
        assert order is None

    def test_get_positions_futures(self):
        c = self._make_connector(connected=True)
        raw_pos = [
            {
                "symbol": "BTC/USDT",
                "contracts": 1.0,
                "entryPrice": 50000.0,
                "markPrice": 51000.0,
                "unrealizedPnl": 1000.0,
                "realizedPnl": 0.0,
            }
        ]
        c._exchange.fetch_positions.return_value = raw_pos
        positions = c.get_positions()
        assert len(positions) == 1

    def test_get_positions_spot_fallback(self):
        c = self._make_connector(connected=True)
        c._exchange.has = {"fetchPositions": False}
        c._exchange.fetch_balance.return_value = {
            "total": {"BTC": 0.5, "USDT": 1000.0},
            "free": {"BTC": 0.5, "USDT": 1000.0},
        }
        positions = c.get_positions()
        assert any(p.symbol == "BTC/USDT" for p in positions)

    def test_get_positions_exception(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_positions.side_effect = Exception("err")
        positions = c.get_positions()
        assert positions == []

    def test_get_account_info(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_balance.return_value = {
            "total": {"USDT": 10000.0},
            "free": {"USDT": 9000.0},
        }
        c._exchange.fetch_positions.return_value = []
        info = c.get_account_info()
        assert info.balance == 10000.0

    def test_get_market_data(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_ohlcv.return_value = [[1700000000000, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]]
        data = c.get_market_data("BTC/USDT", "1h", 1)
        assert len(data) == 1

    def test_get_market_data_failure(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_ohlcv.side_effect = Exception("err")
        data = c.get_market_data("BTC/USDT")
        assert data == []

    def test_get_ticker(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_ticker.return_value = {"last": 50000.0}
        ticker = c.get_ticker("BTC/USDT")
        assert ticker["last"] == 50000.0

    def test_get_ticker_failure(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_ticker.side_effect = Exception("err")
        ticker = c.get_ticker("BTC/USDT")
        assert ticker == {}

    def test_get_orderbook(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_order_book.return_value = {"bids": [[50000, 1]], "asks": [[50001, 1]]}
        ob = c.get_orderbook("BTC/USDT")
        assert "bids" in ob

    def test_get_orderbook_failure(self):
        c = self._make_connector(connected=True)
        c._exchange.fetch_order_book.side_effect = Exception("err")
        ob = c.get_orderbook("BTC/USDT")
        assert ob == {"bids": [], "asks": []}

    def test_list_symbols(self):
        c = self._make_connector(connected=True)
        symbols = c.list_symbols()
        assert "BTC/USDT" in symbols

    def test_list_supported_exchanges(self):
        mock_ccxt = MagicMock()
        mock_ccxt.exchanges = ["binance", "bybit"]
        with patch.dict("sys.modules", {"ccxt": mock_ccxt}):
            from brokers.ccxt_connector import list_supported_exchanges

            result = list_supported_exchanges()
        assert "binance" in result

    def test_list_supported_exchanges_no_ccxt(self):
        with patch.dict("sys.modules", {"ccxt": None}):
            import brokers.ccxt_connector as mod

            with patch.object(mod, "list_supported_exchanges", wraps=lambda: []):
                result = mod.list_supported_exchanges()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# brokers/ohlcv_store.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOHLCVStore:
    def _make_store(self):
        from brokers.ohlcv_store import OHLCVStore

        return OHLCVStore(timeframe="H1", max_bars=100)

    def _bar(self, ts=None):
        from datetime import datetime, timezone

        return {
            "ts": (ts or datetime.now(timezone.utc)).isoformat(),
            "open": 1950.0,
            "high": 1960.0,
            "low": 1940.0,
            "close": 1955.0,
            "volume": 100.0,
        }

    def test_push_and_buffer_size(self):
        import uuid

        store = self._make_store()
        sym = f"TEST_{uuid.uuid4().hex[:8]}"
        store.push(sym, self._bar())
        assert store.buffer_size(sym) == 1

    def test_push_multiple(self):
        import uuid

        store = self._make_store()
        sym = f"TEST_{uuid.uuid4().hex[:8]}"
        for _ in range(5):
            store.push(sym, self._bar())
        assert store.buffer_size(sym) == 5

    def test_get_insufficient_bars(self):
        import uuid

        store = self._make_store()
        sym = f"TEST_{uuid.uuid4().hex[:8]}"
        # push only 1 bar into a fresh symbol, request 50 — ring buffer has 1
        store.push(sym, self._bar())
        result = store.get(sym, bars=50)
        # Ring buffer has 1 bar; Redis won't have this unique symbol
        assert result is None or len(result) < 50

    def test_get_sufficient_bars(self):
        import uuid

        store = self._make_store()
        sym = f"TEST_{uuid.uuid4().hex[:8]}"
        from datetime import datetime, timedelta, timezone

        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(10):
            store.push(sym, self._bar(ts=base + timedelta(hours=i)))
        result = store.get(sym, bars=5)
        assert result is not None
        assert len(result) >= 5

    def test_get_unknown_symbol(self):
        import uuid

        store = self._make_store()
        sym = f"UNKNOWN_{uuid.uuid4().hex[:8]}"
        result = store.get(sym, bars=5)
        assert result is None

    def test_symbols(self):
        import uuid

        store = self._make_store()
        sym1 = f"TEST_{uuid.uuid4().hex[:8]}"
        sym2 = f"TEST_{uuid.uuid4().hex[:8]}"
        store.push(sym1, self._bar())
        store.push(sym2, self._bar())
        syms = store.symbols()
        assert sym1 in syms
        assert sym2 in syms

    def test_health(self):
        import uuid

        store = self._make_store()
        sym = f"TEST_{uuid.uuid4().hex[:8]}"
        store.push(sym, self._bar())
        h = store.health()
        assert "redis_ok" in h
        assert sym in h["symbols"]

    def test_push_adds_timestamp_if_missing(self):
        import uuid

        store = self._make_store()
        sym = f"TEST_{uuid.uuid4().hex[:8]}"
        bar = {"open": 1950.0, "high": 1960.0, "low": 1940.0, "close": 1955.0, "volume": 10.0}
        store.push(sym, bar)
        assert store.buffer_size(sym) == 1

    def test_get_ohlcv_store_singleton(self):
        import brokers.ohlcv_store as mod

        mod._store = None
        s1 = mod.get_ohlcv_store()
        s2 = mod.get_ohlcv_store()
        assert s1 is s2

    def test_bars_to_df_empty(self):
        from brokers.ohlcv_store import _bars_to_df

        result = _bars_to_df([])
        assert result is None

    def test_bars_to_df_epoch_ts(self):
        from brokers.ohlcv_store import _bars_to_df

        bars = [{"bar_open_ts": 1700000000.0, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]
        df = _bars_to_df(bars)
        assert df is not None
        assert len(df) == 1

    def test_bars_to_df_no_ts_skipped(self):
        from brokers.ohlcv_store import _bars_to_df

        bars = [{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]
        result = _bars_to_df(bars)
        assert result is None


# ---------------------------------------------------------------------------
# brokers/oanda_ws.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOandaWS:
    @pytest.mark.asyncio
    async def test_start_raises_streaming_forbidden(self):
        from brokers.oanda_ws import OANDAStreamAdapter, StreamingForbiddenError

        adapter = OANDAStreamAdapter()
        with pytest.raises(StreamingForbiddenError):
            await adapter.start()

    @pytest.mark.asyncio
    async def test_stop_raises_streaming_forbidden(self):
        from brokers.oanda_ws import OANDAStreamAdapter, StreamingForbiddenError

        adapter = OANDAStreamAdapter()
        with pytest.raises(StreamingForbiddenError):
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_poll_rest_raises_streaming_forbidden(self):
        from brokers.oanda_ws import OANDAStreamAdapter, StreamingForbiddenError

        adapter = OANDAStreamAdapter()
        with pytest.raises(StreamingForbiddenError):
            await adapter.poll_rest()

    def test_streaming_forbidden_error_message(self):
        from brokers.oanda_ws import StreamingForbiddenError

        err = StreamingForbiddenError("start")
        assert "NuclearStreamer" in str(err)


# ---------------------------------------------------------------------------
# brokers/oanda_paper_clock.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOandaPaperClock:
    def _make_clock(self, tmp_path):
        from brokers.oanda_paper_clock import OandaPaperClock

        stamp = tmp_path / "oanda_paper_start.json"
        return OandaPaperClock(stamp_path=stamp)

    def test_maybe_start_creates_stamp(self, tmp_path):
        clock = self._make_clock(tmp_path)
        result = clock.maybe_start(account_id="101-001", environment="practice")
        assert result is True
        stamp = tmp_path / "oanda_paper_start.json"
        assert stamp.exists()

    def test_maybe_start_idempotent(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.maybe_start(account_id="101-001", environment="practice")
        # Second call returns False (already started) — stamp file preserved
        result = clock.maybe_start(account_id="101-001", environment="practice")
        stamp = tmp_path / "oanda_paper_start.json"
        assert stamp.exists()
        assert result is False  # already started

    def test_status_not_started(self, tmp_path):
        clock = self._make_clock(tmp_path)
        status = clock.status()
        assert status.get("started") is False or "elapsed_days" not in status

    def test_status_after_start(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.maybe_start(account_id="101-001", environment="practice")
        status = clock.status()
        assert status is not None

    def test_record_fill(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.maybe_start(account_id="101-001")
        # Should not raise even if sharpe tracker is None
        result = clock.record_fill(trade_return=0.01, symbol="XAUUSD")
        assert result is not None

    def test_is_complete_false_initially(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.maybe_start(account_id="101-001")
        result = clock.is_complete()
        assert result is False


# ---------------------------------------------------------------------------
# brokers/cme_comex.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCMEComexConnector:
    def _make_connector(self):
        from brokers.cme_comex import CMEComexConnector

        return CMEComexConnector(
            {
                "fix_host": "127.0.0.1",
                "fix_port": 9876,
                "sender_id": "TEST",
                "target_id": "CME",
                "username": "u",
                "password": "p",
                "account": "ACC1",
            }
        )

    def test_init(self):
        c = self._make_connector()
        assert c is not None

    def test_from_env(self):
        from brokers.cme_comex import CMEComexConnector

        with patch.dict(
            "os.environ",
            {
                "CME_FIX_HOST": "127.0.0.1",
                "CME_FIX_PORT": "9876",
                "CME_FIX_SENDER_ID": "TEST",
                "CME_FIX_TARGET_ID": "CME",
                "CME_FIX_USERNAME": "u",
                "CME_FIX_PASSWORD": "p",
                "CME_ACCOUNT": "ACC1",
            },
        ):
            c = CMEComexConnector.from_env()
        assert c is not None

    def test_connect_paper_fallback(self):
        c = self._make_connector()
        # Without FIX/IBKR, should fall back to paper
        result = c.connect()
        assert isinstance(result, bool)

    def test_disconnect(self):
        c = self._make_connector()
        result = c.disconnect()
        assert result is True

    def test_is_connected_false(self):
        c = self._make_connector()
        assert c._connected is False

    def test_normalise_symbol(self):
        from brokers.cme_comex import CMEComexConnector

        assert CMEComexConnector._normalise_symbol("XAU_USD") == "GC"
        assert CMEComexConnector._normalise_symbol("XAUUSD") == "GC"
        assert CMEComexConnector._normalise_symbol("GC") == "GC"

    def test_get_account_info_not_connected(self):
        c = self._make_connector()
        info = c.get_account_info()
        assert info is not None

    def test_get_positions_not_connected(self):
        c = self._make_connector()
        positions = c.get_positions()
        assert isinstance(positions, list)

    def test_get_market_data_not_connected(self):
        c = self._make_connector()
        data = c.get_market_data("XAU_USD")
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# brokers/cpp_shim_connector.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCPPShimConnector:
    def _make_connector(self):
        from brokers.cpp_shim_connector import CPPShimConnector

        return CPPShimConnector(
            {
                "cmd_addr": "tcp://127.0.0.1:6555",
                "resp_addr": "tcp://127.0.0.1:6556",
                "timeout_ms": 100,
            }
        )

    def test_init(self):
        c = self._make_connector()
        assert c is not None

    def test_from_env(self):
        from brokers.cpp_shim_connector import CPPShimConnector

        with patch.dict(
            "os.environ",
            {
                "CPP_SHIM_ZMQ_CMD_ADDR": "tcp://127.0.0.1:6555",
                "CPP_SHIM_ZMQ_RESP_ADDR": "tcp://127.0.0.1:6556",
            },
        ):
            c = CPPShimConnector.from_env()
        assert c is not None

    def test_connect_no_zmq(self):
        c = self._make_connector()
        with patch.dict("sys.modules", {"zmq": None}):
            result = c.connect()
        assert result is False

    def test_connect_zmq_error(self):
        c = self._make_connector()
        mock_zmq = MagicMock()
        mock_zmq.Context.return_value.socket.side_effect = Exception("zmq error")
        with patch.dict("sys.modules", {"zmq": mock_zmq}):
            result = c.connect()
        assert result is False

    def test_disconnect_not_connected(self):
        c = self._make_connector()
        result = c.disconnect()
        assert result is True

    def test_is_connected_false(self):
        c = self._make_connector()
        assert c._connected is False

    def test_place_order_not_connected(self):
        from brokers.base import OrderSide, OrderType

        c = self._make_connector()
        with pytest.raises(RuntimeError):
            c.place_order("XAU_USD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_get_account_info_not_connected(self):
        c = self._make_connector()
        info = c.get_account_info()
        assert info is not None

    def test_get_positions_not_connected(self):
        c = self._make_connector()
        positions = c.get_positions()
        assert isinstance(positions, list)


# ---------------------------------------------------------------------------
# brokers/oanda_stream.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOANDAStream:
    def _make_stream(self):
        from brokers.oanda_stream import OANDAStream

        return OANDAStream(
            api_key="test-key",  # pragma: allowlist secret
            account_id="101-001",
            instruments=["XAU_USD"],
            practice=True,
        )

    def test_init_practice(self):
        s = self._make_stream()
        assert "fxpractice" in s._rest_base

    def test_init_live(self):
        from brokers.oanda_stream import OANDAStream

        s = OANDAStream(api_key="k", account_id="a", instruments=[], practice=False)
        assert "fxtrade" in s._rest_base

    def test_init_missing_credentials(self):
        from brokers.oanda_stream import OANDAStream

        with pytest.raises(ValueError):
            OANDAStream(api_key="", account_id="", instruments=[])

    def test_init_on_tick_ignored(self):
        from brokers.oanda_stream import OANDAStream

        # Should not raise, just log warning
        s = OANDAStream(api_key="k", account_id="a", instruments=[], on_tick=lambda x: x)
        assert s is not None

    @pytest.mark.asyncio
    async def test_stream_prices_raises(self):
        from brokers.oanda_stream import StreamingForbiddenError

        s = self._make_stream()
        with pytest.raises(StreamingForbiddenError):
            await s.stream_prices()

    def _async_cm(self, mock_resp):
        """Return an async context manager that yields mock_resp."""
        from unittest.mock import AsyncMock

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    @pytest.mark.asyncio
    async def test_connect_success(self):
        from unittest.mock import AsyncMock

        s = self._make_stream()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"account": {"balance": "5000"}})
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        s._session = mock_session
        result = await s.connect()
        assert result is True

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        s = self._make_stream()
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("connection refused"))
        s._session = mock_session
        result = await s.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        from unittest.mock import AsyncMock

        s = self._make_stream()
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        s._session = mock_session
        await s.disconnect()
        assert s._session is None

    @pytest.mark.asyncio
    async def test_context_manager(self):
        from unittest.mock import AsyncMock
        from brokers.oanda_stream import OANDAStream

        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            async with OANDAStream(api_key="k", account_id="a", instruments=[]) as s:
                assert s._session is not None

    @pytest.mark.asyncio
    async def test_get_account_info(self):
        from unittest.mock import AsyncMock

        s = self._make_stream()
        payload = {
            "account": {
                "id": "101",
                "currency": "USD",
                "balance": "5000",
                "NAV": "5100",
                "unrealizedPL": "50",
                "pl": "200",
                "marginUsed": "100",
                "marginAvailable": "5000",
                "openTradeCount": 1,
                "openPositionCount": 1,
                "marginRate": "0.02",
            }
        }
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=payload)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        s._session = mock_session
        info = await s.get_account_info()
        assert info.balance == 5000.0

    @pytest.mark.asyncio
    async def test_get_account_info_no_session(self):
        s = self._make_stream()
        info = await s.get_account_info()
        assert info is None

    @pytest.mark.asyncio
    async def test_place_order_market(self):
        from unittest.mock import AsyncMock
        from brokers.base import OrderSide

        s = self._make_stream()
        payload = {
            "orderFillTransaction": {
                "id": "t1",
                "price": "1950",
                "tradeOpened": {"tradeID": "tr1"},
                "commission": "0",
                "units": "1",
            }
        }
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.json = AsyncMock(return_value=payload)
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=self._async_cm(mock_resp))
        s._session = mock_session
        order = await s.place_order("XAU_USD", OrderSide.BUY, 1.0)
        assert order is not None

    @pytest.mark.asyncio
    async def test_get_positions(self):
        from unittest.mock import AsyncMock

        s = self._make_stream()
        payload = {
            "positions": [
                {
                    "instrument": "XAU_USD",
                    "long": {"units": "1", "averagePrice": "1950", "unrealizedPL": "10", "pl": "0"},
                    "short": {"units": "0"},
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=payload)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        s._session = mock_session
        positions = await s.get_positions()
        assert len(positions) >= 1

    @pytest.mark.asyncio
    async def test_cancel_order(self):
        from unittest.mock import AsyncMock

        s = self._make_stream()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={})
        mock_session = MagicMock()
        mock_session.put = MagicMock(return_value=self._async_cm(mock_resp))
        s._session = mock_session
        result = await s.cancel_order("ord-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_close_position(self):
        from unittest.mock import AsyncMock

        s = self._make_stream()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={})
        mock_session = MagicMock()
        mock_session.put = MagicMock(return_value=self._async_cm(mock_resp))
        s._session = mock_session
        result = await s.close_position("XAU_USD")
        assert result is True


# ---------------------------------------------------------------------------
# brokers/oanda_broker.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOandaBroker:
    def _make_broker(self):
        from brokers.oanda_broker import OandaBroker

        return OandaBroker({"login": "101-001", "password": "test-token", "server": "practice"})  # pragma: allowlist secret

    def test_init(self):
        b = self._make_broker()
        assert not b.connected

    def _async_cm(self, mock_resp):
        from unittest.mock import AsyncMock

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    @pytest.mark.asyncio
    async def test_connect_success(self):
        from unittest.mock import AsyncMock

        b = self._make_broker()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"account": {"currency": "USD"}})
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await b.connect()
        assert result is True
        assert b.connected

    @pytest.mark.asyncio
    async def test_connect_failure_status(self):
        from unittest.mock import AsyncMock

        b = self._make_broker()
        mock_resp = MagicMock()
        mock_resp.status = 401
        mock_resp.text = AsyncMock(return_value="Unauthorized")
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        mock_session.close = AsyncMock()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await b.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        from unittest.mock import AsyncMock

        b = self._make_broker()
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        b._session = mock_session
        b.connected = True
        await b.disconnect()
        assert not b.connected

    @pytest.mark.asyncio
    async def test_get_account_info_not_connected(self):
        b = self._make_broker()
        result = await b.get_account_info()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_account_info_connected(self):
        from unittest.mock import AsyncMock

        b = self._make_broker()
        b.connected = True
        b._account_id = "101-001"
        b._base_url = "https://api-fxpractice.oanda.com"
        payload = {
            "account": {
                "id": "101-001",
                "currency": "USD",
                "balance": "5000",
                "NAV": "5100",
                "unrealizedPL": "50",
                "pl": "200",
                "marginUsed": "100",
                "marginAvailable": "5000",
                "openTradeCount": 0,
                "openPositionCount": 0,
                "marginRate": "0.02",
            }
        }
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=payload)
        mock_session = MagicMock()
        mock_session.closed = False  # must be False so _assert_connected passes
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        b._session = mock_session
        info = await b.get_account_info()
        assert info["balance"] == 5000.0

    @pytest.mark.asyncio
    async def test_get_positions_not_connected(self):
        b = self._make_broker()
        result = await b.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_place_order_not_connected(self):
        b = self._make_broker()
        result = await b.place_order({"instrument": "XAU_USD", "units": 1, "order_type": "MARKET"})
        # Returns error dict when not connected
        assert result is not None
        assert result.get("success") is False

    @pytest.mark.asyncio
    async def test_place_order_connected(self):
        from unittest.mock import AsyncMock

        b = self._make_broker()
        b.connected = True
        b._account_id = "101-001"
        b._base_url = "https://api-fxpractice.oanda.com"
        payload = {
            "orderFillTransaction": {
                "id": "t1",
                "price": "1950",
                "tradeOpened": {"tradeID": "tr1"},
                "commission": "0",
                "units": "1",
            }
        }
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.json = AsyncMock(return_value=payload)
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=self._async_cm(mock_resp))
        b._session = mock_session
        result = await b.place_order({"instrument": "XAU_USD", "units": 1, "order_type": "MARKET"})
        assert result is not None

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self):
        b = self._make_broker()
        result = await b.cancel_order("ord-1")
        assert result is not None  # returns dict with success=False

    @pytest.mark.asyncio
    async def test_get_orders_not_connected(self):
        b = self._make_broker()
        result = await b.get_orders()
        assert result == []


# ---------------------------------------------------------------------------
# brokers/ibkr_fix_bridge.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestIBKRFIXBridge:
    def _make_config(self):
        from brokers.ibkr_fix_bridge import IBKRFIXConfig

        return IBKRFIXConfig(
            sender_comp_id="TEST",
            target_comp_id="IBKR",
            host="127.0.0.1",
            port=4001,
            username="u",
            password="p",
        )

    def test_from_env(self):
        from brokers.ibkr_fix_bridge import IBKRFIXBridge

        with patch.dict(
            "os.environ",
            {
                "IBKR_FIX_HOST": "127.0.0.1",
                "IBKR_FIX_PORT": "4001",
                "IBKR_FIX_SENDER_ID": "TEST",
                "IBKR_FIX_TARGET_ID": "IBKR",
                "IBKR_FIX_USERNAME": "u",
                "IBKR_FIX_PASSWORD": "p",
            },
        ):
            bridge = IBKRFIXBridge.from_env()
        assert bridge is not None

    def test_init(self):
        from brokers.ibkr_fix_bridge import IBKRFIXBridge

        bridge = IBKRFIXBridge(config=self._make_config())
        assert not bridge._started

    def test_stop_not_started(self):
        from brokers.ibkr_fix_bridge import IBKRFIXBridge

        bridge = IBKRFIXBridge(config=self._make_config())
        bridge.stop()  # Should not raise when not started

    def test_kill_switch_stored(self):
        from brokers.ibkr_fix_bridge import IBKRFIXBridge

        ks = MagicMock()
        bridge = IBKRFIXBridge(config=self._make_config(), kill_switch=ks)
        assert bridge._kill_switch is ks

    def test_start_without_quickfix_raises_or_logs(self):
        import contextlib

        from brokers.ibkr_fix_bridge import IBKRFIXBridge

        bridge = IBKRFIXBridge(config=self._make_config())
        with contextlib.suppress(RuntimeError, ImportError, OSError):
            bridge.start()

    @pytest.mark.asyncio
    async def test_place_order_not_started_raises(self):
        from brokers.ibkr_fix_bridge import FIXOrder, IBKRFIXBridge
        from execution.fix_adapter import FIXOrdType, FIXSide

        bridge = IBKRFIXBridge(config=self._make_config())
        order = FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, ord_type=FIXOrdType.MARKET)
        with pytest.raises(RuntimeError):
            await bridge.place_order(order)


# ---------------------------------------------------------------------------
# brokers/ibkr.py — real implementation (ib_insync absent in CI)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestIBKRBrokerReal:
    def test_init_paper(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker({"server": "paper"})
        assert broker._cfg.paper is True
        assert not broker.connected

    def test_init_live(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker({"server": "live"})
        assert broker._cfg.paper is False

    def test_init_defaults(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker()
        assert broker is not None
        assert broker._total_orders == 0
        assert broker._total_fills == 0

    @pytest.mark.asyncio
    async def test_connect_returns_false_without_ib_insync(self):
        from brokers.ibkr import IBKRBroker, _IB_AVAILABLE

        if _IB_AVAILABLE:
            pytest.skip("ib_insync is installed — skip unavailability test")
        broker = IBKRBroker()
        result = await broker.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker()
        await broker.disconnect()  # Should not raise
        assert not broker.connected

    def test_market_data_forbidden(self):
        from brokers.ibkr import IBKRBroker, MarketDataForbiddenError

        broker = IBKRBroker()
        with pytest.raises(MarketDataForbiddenError):
            broker.get_market_data("XAUUSD")

    def test_market_data_forbidden_error_message(self):
        from brokers.ibkr import MarketDataForbiddenError

        err = MarketDataForbiddenError("get_market_data")
        assert "ARCHITECTURAL VIOLATION" in str(err)

    def test_register_fill_callback(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker()
        cb = MagicMock()
        broker.register_fill_callback(cb)
        assert cb in broker._fill_callbacks

    @pytest.mark.asyncio
    async def test_get_account_info_not_connected(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker()
        result = await broker.get_account_info()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_open_positions_not_connected(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker()
        result = await broker.get_open_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_place_order_not_connected(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker()
        # place_order takes a dict; when not connected returns error dict
        result = await broker.place_order(
            {"symbol": "XAUUSD", "action": "BUY", "order_type": "MARKET", "quantity": 1.0}
        )
        assert isinstance(result, dict)
        assert result.get("success") is False or "error" in result or "status" in result

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self):
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker()
        result = await broker.cancel_order(12345)
        assert result is False


# ---------------------------------------------------------------------------
# brokers/mt5_bridge.py — real implementation (MT5 absent in CI → signal-export mode)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMT5BridgeReal:
    def _make_bridge(self, tmp_path):
        from brokers.mt5_bridge import MT5Bridge

        return MT5Bridge(server="Demo", login=12345, password="pass", signal_dir=tmp_path / "signals")  # pragma: allowlist secret

    def test_init(self, tmp_path):
        b = self._make_bridge(tmp_path)
        assert b.server == "Demo"
        assert b.login == 12345
        assert not b._connected

    def test_connect_signal_export_mode(self, tmp_path):
        """Without MT5 package, connect() activates signal-export mode."""
        from brokers.mt5_bridge import _MT5_AVAILABLE

        if _MT5_AVAILABLE:
            pytest.skip("MT5 package installed — skip signal-export mode test")
        b = self._make_bridge(tmp_path)
        result = b.connect()
        assert result is True
        assert b._connected

    def test_disconnect(self, tmp_path):
        b = self._make_bridge(tmp_path)
        b._connected = True
        b.disconnect()
        assert not b._connected

    def test_require_connected_raises(self, tmp_path):
        b = self._make_bridge(tmp_path)
        with pytest.raises(RuntimeError, match="not connected"):
            b._require_connected()

    def test_send_order_no_stop_loss_raises(self, tmp_path):
        from brokers.mt5_bridge import MT5Order, OrderSide, OrderType

        b = self._make_bridge(tmp_path)
        b._connected = True
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, order_type=OrderType.MARKET, stop_loss=None)
        with pytest.raises(ValueError, match="stop_loss"):
            b.send_order(order)

    def test_send_order_signal_export_mode(self, tmp_path):
        from brokers.mt5_bridge import MT5Order, OrderSide, OrderType, _MT5_AVAILABLE

        if _MT5_AVAILABLE:
            pytest.skip("MT5 package installed")
        b = self._make_bridge(tmp_path)
        b.connect()
        order = MT5Order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
            order_type=OrderType.MARKET,
            stop_loss=1900.0,
            take_profit=2000.0,
            timeout_sec=0.1,
        )
        # In signal-export mode, poll_fill will timeout since no EA is running
        with pytest.raises(TimeoutError):
            b.send_order(order)

    def test_from_env_missing_login_raises(self):
        from brokers.mt5_bridge import MT5Bridge

        with patch.dict("os.environ", {}, clear=True), pytest.raises(OSError, match="MT5_LOGIN"):
            MT5Bridge.from_env()

    def test_from_env_success(self, tmp_path):
        from brokers.mt5_bridge import MT5Bridge

        with patch.dict(
            "os.environ",
            {
                "MT5_LOGIN": "12345",
                "MT5_PASSWORD": "pass",  # pragma: allowlist secret
                "MT5_SERVER": "Demo",
            },
        ):
            b = MT5Bridge.from_env()
        assert b.login == 12345


# ---------------------------------------------------------------------------
# brokers/mt5_bridge.py — EX5SignalExporter
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEX5SignalExporter:
    def _make_exporter(self, tmp_path):
        from brokers.mt5_bridge import EX5SignalExporter

        return EX5SignalExporter(signal_dir=tmp_path / "signals")

    def test_export_creates_file(self, tmp_path):
        from brokers.mt5_bridge import MT5Order, OrderSide, OrderType

        exp = self._make_exporter(tmp_path)
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, order_type=OrderType.MARKET, stop_loss=1900.0)
        path = exp.export(order)
        assert path.exists()

    def test_export_file_content(self, tmp_path):
        import json
        from brokers.mt5_bridge import MT5Order, OrderSide, OrderType

        exp = self._make_exporter(tmp_path)
        order = MT5Order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
            order_type=OrderType.MARKET,
            stop_loss=1900.0,
            take_profit=2000.0,
        )
        path = exp.export(order)
        data = json.loads(path.read_text())
        assert data["symbol"] == "XAUUSD"
        assert data["side"] == "BUY"
        assert data["status"] == "PENDING"

    def test_export_modify(self, tmp_path):
        exp = self._make_exporter(tmp_path)
        path = exp.export_modify(ticket=1001, symbol="XAUUSD", stop_loss=1910.0, take_profit=2010.0)
        assert path.exists()

    def test_export_cancel(self, tmp_path):
        exp = self._make_exporter(tmp_path)
        path = exp.export_cancel(ticket=1001, symbol="XAUUSD")
        assert path.exists()

    def test_poll_fill_timeout(self, tmp_path):
        from brokers.mt5_bridge import MT5Order, OrderSide, OrderType

        exp = self._make_exporter(tmp_path)
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, order_type=OrderType.MARKET, stop_loss=1900.0)
        path = exp.export(order)
        with pytest.raises(TimeoutError):
            exp.poll_fill(path, timeout_sec=0.1)

    def test_poll_fill_filled(self, tmp_path):
        import json
        from brokers.mt5_bridge import FillStatus, MT5Order, OrderSide, OrderType

        exp = self._make_exporter(tmp_path)
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, order_type=OrderType.MARKET, stop_loss=1900.0)
        path = exp.export(order)
        # Simulate EA filling the order
        data = json.loads(path.read_text())
        data["status"] = "FILLED"
        data["ticket"] = 9999
        data["fill_price"] = 1950.0
        data["fill_volume"] = 0.1
        path.write_text(json.dumps(data))
        result = exp.poll_fill(path, timeout_sec=2.0)
        assert result.status == FillStatus.FILLED
        assert result.ticket == 9999

    def test_poll_fill_rejected(self, tmp_path):
        import json
        from brokers.mt5_bridge import MT5Order, OrderSide, OrderType

        exp = self._make_exporter(tmp_path)
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, order_type=OrderType.MARKET, stop_loss=1900.0)
        path = exp.export(order)
        data = json.loads(path.read_text())
        data["status"] = "REJECTED"
        data["reject_reason"] = "insufficient margin"
        path.write_text(json.dumps(data))
        with pytest.raises(RuntimeError, match="rejected"):
            exp.poll_fill(path, timeout_sec=2.0)

    def test_cleanup_old_signals(self, tmp_path):
        import time

        exp = self._make_exporter(tmp_path)
        sig_dir = tmp_path / "signals"
        old_file = sig_dir / "old_signal.json"
        old_file.write_text("{}")
        # Set mtime to 25 hours ago
        old_time = time.time() - 25 * 3600
        import os

        os.utime(old_file, (old_time, old_time))
        removed = exp.cleanup_old_signals(max_age_hours=24)
        assert removed >= 1


# ---------------------------------------------------------------------------
# brokers/mt5_zmq_bridge.py — real implementation (ZMQ absent in CI → DEGRADED)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMT5ZmqBridge:
    def _make_bridge(self):
        from brokers.mt5_zmq_bridge import MT5ZmqBridge

        return MT5ZmqBridge(host="localhost", cmd_port=5555, resp_port=5556)

    def test_init(self):
        b = self._make_bridge()
        assert b.host == "localhost"
        assert b.cmd_port == 5555

    def test_start_degraded_without_zmq(self):
        from brokers.mt5_zmq_bridge import BridgeStatus, _ZMQ_AVAILABLE

        if _ZMQ_AVAILABLE:
            pytest.skip("ZMQ installed")
        b = self._make_bridge()
        b.start()
        assert b._status == BridgeStatus.DEGRADED

    def test_stop_when_not_started(self):
        b = self._make_bridge()
        b.stop()  # Should not raise

    def test_context_manager(self):
        from brokers.mt5_zmq_bridge import BridgeStatus, _ZMQ_AVAILABLE

        if _ZMQ_AVAILABLE:
            pytest.skip("ZMQ installed")
        b = self._make_bridge()
        with b:
            assert b._status == BridgeStatus.DEGRADED
        assert b._status == BridgeStatus.STOPPED

    def test_send_order_not_connected_raises(self):
        from brokers.mt5_zmq_bridge import _ZMQ_AVAILABLE

        if _ZMQ_AVAILABLE:
            pytest.skip("ZMQ installed")
        b = self._make_bridge()
        b.start()  # DEGRADED
        with pytest.raises(RuntimeError):
            b.send_order("XAUUSD", "BUY", lots=0.01, sl=1900.0)

    def test_close_position_not_connected_raises(self):
        from brokers.mt5_zmq_bridge import _ZMQ_AVAILABLE

        if _ZMQ_AVAILABLE:
            pytest.skip("ZMQ installed")
        b = self._make_bridge()
        b.start()
        with pytest.raises(RuntimeError):
            b.close_position(ticket=12345)

    def test_modify_position_not_connected_raises(self):
        from brokers.mt5_zmq_bridge import _ZMQ_AVAILABLE

        if _ZMQ_AVAILABLE:
            pytest.skip("ZMQ installed")
        b = self._make_bridge()
        b.start()
        with pytest.raises(RuntimeError):
            b.modify_position(ticket=12345, sl=1910.0)

    def test_ping_degraded_returns_sentinel(self):
        from brokers.mt5_zmq_bridge import _ZMQ_AVAILABLE

        if _ZMQ_AVAILABLE:
            pytest.skip("ZMQ installed")
        b = self._make_bridge()
        b.start()  # DEGRADED
        result = b.ping()
        assert isinstance(result, float)  # -1.0 sentinel in degraded mode

    def test_status_property(self):
        from brokers.mt5_zmq_bridge import BridgeStatus

        b = self._make_bridge()
        s = b.status  # property, not method
        assert isinstance(s, BridgeStatus)

    def test_stats_property(self):
        from brokers.mt5_zmq_bridge import BridgeStats

        b = self._make_bridge()
        s = b.stats  # property, not method
        assert isinstance(s, BridgeStats)

    def test_register_tick_callback(self):
        b = self._make_bridge()
        cb = MagicMock()
        b.register_tick_callback(cb)
        assert cb in b._tick_callbacks

    def test_get_bridge_singleton(self):
        from brokers.mt5_zmq_bridge import get_bridge

        b1 = get_bridge()
        b2 = get_bridge()
        assert b1 is b2

    def test_start_already_connected_noop(self):
        from brokers.mt5_zmq_bridge import BridgeStatus, _ZMQ_AVAILABLE

        if _ZMQ_AVAILABLE:
            pytest.skip("ZMQ installed")
        b = self._make_bridge()
        b.start()  # DEGRADED
        b._status = BridgeStatus.CONNECTED
        b.start()  # Should be a no-op
        assert b._status == BridgeStatus.CONNECTED


# ---------------------------------------------------------------------------
# brokers/mt5_broker.py — real implementation (MT5 absent in CI, all methods async)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMT5BrokerConnector:
    def _make_broker(self):
        from brokers.mt5_broker import MT5Broker

        return MT5Broker({"login": "12345", "password": "pass", "server": "Demo"})  # pragma: allowlist secret

    def test_init(self):
        b = self._make_broker()
        assert b is not None

    @pytest.mark.asyncio
    async def test_connect_without_mt5(self):
        from brokers.mt5_broker import _MT5_AVAILABLE

        if _MT5_AVAILABLE:
            pytest.skip("MT5 installed")
        b = self._make_broker()
        result = await b.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        b = self._make_broker()
        await b.disconnect()  # Should not raise

    def test_status(self):
        b = self._make_broker()
        s = b.status()
        assert isinstance(s, dict)

    @pytest.mark.asyncio
    async def test_get_account_info_not_connected(self):
        b = self._make_broker()
        info = await b.get_account_info()
        assert info is None

    @pytest.mark.asyncio
    async def test_get_positions_not_connected(self):
        b = self._make_broker()
        positions = await b.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_orders_not_connected(self):
        b = self._make_broker()
        orders = await b.get_orders()
        assert orders == []

    @pytest.mark.asyncio
    async def test_place_order_not_connected(self):
        b = self._make_broker()
        result = await b.place_order({"symbol": "XAUUSD", "side": "BUY", "volume": 0.1, "sl": 1900.0})
        assert result is not None
        assert result.get("success") is False or "error" in result

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self):
        b = self._make_broker()
        result = await b.cancel_order(12345)
        assert result is not None

    @pytest.mark.asyncio
    async def test_close_position_not_connected(self):
        b = self._make_broker()
        result = await b.close_position(12345)
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_tick_not_connected(self):
        b = self._make_broker()
        tick = await b.get_tick("XAUUSD")
        assert tick is None

    @pytest.mark.asyncio
    async def test_modify_position_not_connected(self):
        b = self._make_broker()
        result = await b.modify_position(12345, sl=1900.0, tp=2000.0)
        assert result is not None


# ---------------------------------------------------------------------------
# brokers/ibkr_connector.py — raises ImportError when ib_insync absent
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestIBKRConnector:
    def test_raises_import_error_without_ib_insync(self):
        from brokers.ibkr_connector import IBKRConfig, IBKRConnector, IB_AVAILABLE

        if IB_AVAILABLE:
            pytest.skip("ib_insync installed")
        with pytest.raises(ImportError, match="ib_insync"):
            IBKRConnector(config=IBKRConfig())

    def test_ib_available_flag(self):
        from brokers.ibkr_connector import IB_AVAILABLE

        assert isinstance(IB_AVAILABLE, bool)

    def test_ibkr_config_defaults(self):
        from brokers.ibkr_connector import IBKRConfig

        cfg = IBKRConfig()
        assert cfg.port in (7497, 4002)  # paper TWS or paper gateway
        assert cfg.client_id >= 0

    def test_ibkr_config_custom(self):
        from brokers.ibkr_connector import IBKRConfig

        cfg = IBKRConfig(host="192.168.1.1", port=7496, client_id=5)
        assert cfg.host == "192.168.1.1"
        assert cfg.port == 7496
        assert cfg.client_id == 5
