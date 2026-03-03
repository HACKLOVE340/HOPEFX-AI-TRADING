"""
Comprehensive unit tests for all broker connectors.

Covers: AlpacaConnector, BinanceConnector, OANDAConnector, MT5Connector,
InteractiveBrokersConnector, AdvancedOrderManager, BrokerFactory,
and all Prop Firm connectors (FTMO, MyForexFunds, The5ers, TopstepTrader).
"""

import sys
import types
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Inject stub modules for optional heavy dependencies BEFORE any broker import
# ---------------------------------------------------------------------------

# MetaTrader5 stub
_mt5_stub = types.ModuleType("MetaTrader5")
_mt5_stub.initialize = MagicMock(return_value=True)
_mt5_stub.login = MagicMock(return_value=True)
_mt5_stub.shutdown = MagicMock(return_value=True)
_mt5_stub.last_error = MagicMock(return_value=(0, ""))
_mt5_stub.account_info = MagicMock()
_mt5_stub.symbol_info = MagicMock()
_mt5_stub.symbol_select = MagicMock(return_value=True)
_mt5_stub.symbol_info_tick = MagicMock()
_mt5_stub.order_send = MagicMock()
_mt5_stub.orders_get = MagicMock(return_value=[])
_mt5_stub.positions_get = MagicMock(return_value=[])
_mt5_stub.copy_rates_from_pos = MagicMock(return_value=None)
_mt5_stub.symbols_get = MagicMock(return_value=[])
# MT5 constants
_mt5_stub.ORDER_TYPE_BUY = 0
_mt5_stub.ORDER_TYPE_SELL = 1
_mt5_stub.ORDER_TYPE_BUY_LIMIT = 2
_mt5_stub.ORDER_TYPE_SELL_LIMIT = 3
_mt5_stub.ORDER_TYPE_BUY_STOP = 4
_mt5_stub.ORDER_TYPE_SELL_STOP = 5
_mt5_stub.POSITION_TYPE_BUY = 0
_mt5_stub.POSITION_TYPE_SELL = 1
_mt5_stub.TRADE_ACTION_DEAL = 1
_mt5_stub.TRADE_ACTION_PENDING = 5
_mt5_stub.TRADE_ACTION_REMOVE = 8
_mt5_stub.TRADE_RETCODE_DONE = 10009
_mt5_stub.ORDER_TIME_GTC = 1
_mt5_stub.ORDER_FILLING_IOC = 1
_mt5_stub.TIMEFRAME_M1 = 1
_mt5_stub.TIMEFRAME_M5 = 5
_mt5_stub.TIMEFRAME_M15 = 15
_mt5_stub.TIMEFRAME_M30 = 30
_mt5_stub.TIMEFRAME_H1 = 16385
_mt5_stub.TIMEFRAME_H4 = 16388
_mt5_stub.TIMEFRAME_D1 = 16408
_mt5_stub.TIMEFRAME_W1 = 32769
_mt5_stub.TIMEFRAME_MN1 = 49153
sys.modules.setdefault("MetaTrader5", _mt5_stub)

# ib_insync stub
_ib_stub = types.ModuleType("ib_insync")
_ib_stub.IB = MagicMock
_ib_stub.Stock = MagicMock
_ib_stub.Forex = MagicMock
_ib_stub.Future = MagicMock
_ib_stub.Option = MagicMock
_ib_stub.MarketOrder = MagicMock
_ib_stub.LimitOrder = MagicMock
_ib_stub.StopOrder = MagicMock
sys.modules.setdefault("ib_insync", _ib_stub)

# Now import brokers (stubs are already in sys.modules)
from brokers.alpaca import AlpacaConnector
from brokers.binance import BinanceConnector
from brokers.oanda import OANDAConnector
from brokers.mt5 import MT5Connector
from brokers.interactive_brokers import InteractiveBrokersConnector

# ---------------------------------------------------------------------------
# Override module-level availability flags so connectors are constructable
# even though the real packages aren't installed in this environment.
# ---------------------------------------------------------------------------
import brokers.mt5 as _mt5_module
_mt5_module.MT5_AVAILABLE = True
_mt5_module.mt5 = _mt5_stub

import brokers.interactive_brokers as _ib_module
_ib_module.IB_AVAILABLE = True
_ib_module.IB = MagicMock
_ib_module.Stock = MagicMock
_ib_module.Forex = MagicMock
_ib_module.Future = MagicMock
_ib_module.Option = MagicMock
_ib_module.MarketOrder = MagicMock
_ib_module.LimitOrder = MagicMock
_ib_module.StopOrder = MagicMock
from brokers.advanced_orders import (
    AdvancedOrderManager,
    Order as AdvOrder,
    OrderSide as AdvOrderSide,
    OrderType as AdvOrderType,
    OrderStatus as AdvOrderStatus,
    TimeInForce,
)
from brokers.factory import BrokerFactory
from brokers.prop_firms.ftmo import FTMOConnector
from brokers.prop_firms.myforexfunds import MyForexFundsConnector
from brokers.prop_firms.the5ers import The5ersConnector
from brokers.prop_firms.topstep import TopstepTraderConnector
from brokers.base import OrderType, OrderSide, OrderStatus


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ALPACA_CONFIG = {"api_key": "test_key", "api_secret": "test_secret", "paper": True}
BINANCE_CONFIG = {"api_key": "test_key", "api_secret": "test_secret", "testnet": True}
OANDA_CONFIG = {"api_key": "test_token", "account_id": "test_account", "environment": "practice"}
MT5_CONFIG = {"server": "Demo-Server", "login": 12345678, "password": "test_pass"}
IB_CONFIG = {"host": "127.0.0.1", "port": 7497, "client_id": 1, "paper": True}


def _mock_response(json_data=None, status_code=200, raise_for_status=None):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if raise_for_status:
        resp.raise_for_status.side_effect = raise_for_status
    else:
        resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# AlpacaConnector Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAlpacaConnector:
    """Tests for AlpacaConnector."""

    def test_initialization_paper(self):
        broker = AlpacaConnector(ALPACA_CONFIG)
        assert broker.api_key == "test_key"
        assert broker.api_secret == "test_secret"
        assert broker.paper is True
        assert broker.base_url == AlpacaConnector.PAPER_URL
        assert not broker.connected

    def test_initialization_live(self):
        cfg = {**ALPACA_CONFIG, "paper": False}
        broker = AlpacaConnector(cfg)
        assert broker.base_url == AlpacaConnector.LIVE_URL

    def test_initialization_missing_credentials_raises(self):
        with pytest.raises(ValueError):
            AlpacaConnector({"api_key": "key"})

    @patch("brokers.alpaca.requests.Session")
    def test_connect_success(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({"status": "ACTIVE"})

        broker = AlpacaConnector(ALPACA_CONFIG)
        assert broker.connect() is True
        assert broker.connected is True

    @patch("brokers.alpaca.requests.Session")
    def test_connect_failure(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.side_effect = Exception("network error")

        broker = AlpacaConnector(ALPACA_CONFIG)
        assert broker.connect() is False
        assert not broker.connected

    @patch("brokers.alpaca.requests.Session")
    def test_disconnect(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response()

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connect()
        assert broker.disconnect() is True
        assert not broker.connected

    @patch("brokers.alpaca.requests.Session")
    def test_place_market_buy_order(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response()
        mock_sess.post.return_value = _mock_response({
            "id": "order-1",
            "symbol": "AAPL",
            "side": "buy",
            "type": "market",
            "qty": "10",
            "status": "new",
            "filled_qty": "0",
            "created_at": "2024-01-01T00:00:00Z",
        })

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connect()
        order = broker.place_order("AAPL", OrderSide.BUY, 10)

        assert order is not None
        assert order.id == "order-1"
        assert order.symbol == "AAPL"
        assert order.side == OrderSide.BUY

    @patch("brokers.alpaca.requests.Session")
    def test_place_limit_sell_order(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response()
        mock_sess.post.return_value = _mock_response({
            "id": "order-2",
            "symbol": "AAPL",
            "side": "sell",
            "type": "limit",
            "qty": "5",
            "limit_price": "200.00",
            "status": "new",
            "filled_qty": "0",
            "created_at": "2024-01-01T00:00:00Z",
        })

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connect()
        order = broker.place_order("AAPL", OrderSide.SELL, 5, OrderType.LIMIT, price=200.0)

        assert order is not None
        assert order.side == OrderSide.SELL

    @patch("brokers.alpaca.requests.Session")
    def test_place_order_not_connected_returns_none(self, _):
        broker = AlpacaConnector(ALPACA_CONFIG)
        order = broker.place_order("AAPL", OrderSide.BUY, 10)
        assert order is None

    @patch("brokers.alpaca.requests.Session")
    def test_cancel_order_success(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response()
        mock_sess.delete.return_value = _mock_response({})

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connect()
        assert broker.cancel_order("order-1") is True

    @patch("brokers.alpaca.requests.Session")
    def test_cancel_order_not_connected(self, _):
        broker = AlpacaConnector(ALPACA_CONFIG)
        assert broker.cancel_order("order-1") is False

    @patch("brokers.alpaca.requests.Session")
    def test_get_positions(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response([
            {
                "symbol": "AAPL",
                "qty": "10",
                "avg_entry_price": "150.00",
                "current_price": "155.00",
                "unrealized_pl": "50.00",
            }
        ])

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        positions = broker.get_positions()

        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 10.0

    @patch("brokers.alpaca.requests.Session")
    def test_get_positions_not_connected(self, _):
        broker = AlpacaConnector(ALPACA_CONFIG)
        assert broker.get_positions() == []

    @patch("brokers.alpaca.requests.Session")
    def test_get_account_info(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "cash": "10000",
            "equity": "11000",
            "initial_margin": "500",
            "buying_power": "20000",
            "position_count": "1",
        })

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        info = broker.get_account_info()

        assert info is not None
        assert info.balance == 10000.0
        assert info.equity == 11000.0

    @patch("brokers.alpaca.requests.Session")
    def test_get_account_info_not_connected(self, _):
        broker = AlpacaConnector(ALPACA_CONFIG)
        assert broker.get_account_info() is None

    @patch("brokers.alpaca.requests.Session")
    def test_close_position_full(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response()
        mock_sess.delete.return_value = _mock_response({})

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connect()
        assert broker.close_position("AAPL") is True

    @patch("brokers.alpaca.requests.Session")
    def test_get_market_data(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "bars": [
                {"t": "2024-01-01T00:00:00Z", "o": 100.0, "h": 110.0, "l": 99.0, "c": 105.0, "v": 1000}
            ]
        })

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        candles = broker.get_market_data("AAPL", "1Min", 1)

        assert candles is not None
        assert len(candles) == 1
        assert candles[0]["open"] == 100.0

    @patch("brokers.alpaca.requests.Session")
    def test_get_quote(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "quote": {"bp": 149.0, "ap": 149.1, "bs": 100, "as": 200, "t": "2024-01-01T00:00:00Z"}
        })

        broker = AlpacaConnector(ALPACA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        quote = broker.get_quote("AAPL")

        assert quote is not None
        assert quote["bid"] == 149.0
        assert quote["ask"] == 149.1

    def test_convert_order_type(self):
        broker = AlpacaConnector(ALPACA_CONFIG)
        assert broker._convert_order_type(OrderType.MARKET) == "market"
        assert broker._convert_order_type(OrderType.LIMIT) == "limit"
        assert broker._convert_order_type(OrderType.STOP) == "stop"
        assert broker._convert_order_type(OrderType.STOP_LIMIT) == "stop_limit"

    def test_parse_order_status(self):
        broker = AlpacaConnector(ALPACA_CONFIG)
        assert broker._parse_order_status("filled") == OrderStatus.FILLED
        assert broker._parse_order_status("canceled") == OrderStatus.CANCELLED
        assert broker._parse_order_status("new") == OrderStatus.OPEN
        assert broker._parse_order_status("rejected") == OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# BinanceConnector Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBinanceConnector:
    """Tests for BinanceConnector."""

    def test_initialization_testnet(self):
        broker = BinanceConnector(BINANCE_CONFIG)
        assert broker.testnet is True
        assert broker.base_url == BinanceConnector.TESTNET_URL
        assert not broker.connected

    def test_initialization_live(self):
        cfg = {**BINANCE_CONFIG, "testnet": False}
        broker = BinanceConnector(cfg)
        assert broker.base_url == BinanceConnector.LIVE_URL

    def test_initialization_missing_credentials_raises(self):
        with pytest.raises(ValueError):
            BinanceConnector({"api_key": "key"})

    @patch("brokers.binance.requests.Session")
    def test_connect_success(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "balances": [{"asset": "USDT", "free": "1000", "locked": "0"}]
        })

        broker = BinanceConnector(BINANCE_CONFIG)
        assert broker.connect() is True
        assert broker.connected is True

    @patch("brokers.binance.requests.Session")
    def test_connect_failure(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.side_effect = Exception("timeout")

        broker = BinanceConnector(BINANCE_CONFIG)
        assert broker.connect() is False

    @patch("brokers.binance.requests.Session")
    def test_disconnect(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({"balances": []})

        broker = BinanceConnector(BINANCE_CONFIG)
        broker.connect()
        assert broker.disconnect() is True

    @patch("brokers.binance.requests.Session")
    def test_place_market_buy(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.post.return_value = _mock_response({
            "orderId": 12345,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "origQty": "0.001",
            "executedQty": "0.001",
            "status": "FILLED",
            "price": "50000",
            "transactTime": 1704067200000,
        })

        broker = BinanceConnector(BINANCE_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        order = broker.place_order("BTCUSDT", OrderSide.BUY, 0.001)

        assert order is not None
        assert order.id == "12345"
        assert order.status == OrderStatus.FILLED

    @patch("brokers.binance.requests.Session")
    def test_place_limit_sell(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.post.return_value = _mock_response({
            "orderId": 67890,
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "LIMIT",
            "origQty": "0.001",
            "executedQty": "0",
            "status": "NEW",
            "price": "55000",
            "transactTime": 1704067200000,
        })

        broker = BinanceConnector(BINANCE_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        order = broker.place_order("BTCUSDT", OrderSide.SELL, 0.001, OrderType.LIMIT, price=55000)

        assert order is not None
        assert order.status == OrderStatus.OPEN

    @patch("brokers.binance.requests.Session")
    def test_place_order_not_connected(self, _):
        broker = BinanceConnector(BINANCE_CONFIG)
        assert broker.place_order("BTCUSDT", OrderSide.BUY, 0.001) is None

    @patch("brokers.binance.requests.Session")
    def test_cancel_order_success(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.delete.return_value = _mock_response({})

        broker = BinanceConnector(BINANCE_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        assert broker.cancel_order("12345", symbol="BTCUSDT") is True

    @patch("brokers.binance.requests.Session")
    def test_cancel_order_no_symbol(self, _):
        broker = BinanceConnector(BINANCE_CONFIG)
        broker.connected = True
        assert broker.cancel_order("12345") is False

    @patch("brokers.binance.requests.Session")
    def test_get_positions(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "balances": [
                {"asset": "BTC", "free": "0.5", "locked": "0"},
                {"asset": "USDT", "free": "1000", "locked": "50"},
                {"asset": "ETH", "free": "0", "locked": "0"},
            ]
        })

        broker = BinanceConnector(BINANCE_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        positions = broker.get_positions()

        # Only non-zero balances
        assert len(positions) == 2

    @patch("brokers.binance.requests.Session")
    def test_get_account_info(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "balances": [
                {"asset": "USDT", "free": "5000", "locked": "0"},
                {"asset": "BTC", "free": "0.1", "locked": "0"},
            ]
        })

        broker = BinanceConnector(BINANCE_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        info = broker.get_account_info()

        assert info is not None
        assert info.balance == 5000.0

    @patch("brokers.binance.requests.Session")
    def test_get_market_data(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response([
            [1704067200000, "50000", "51000", "49000", "50500", "10.5",
             1704067259000, "525000", 100, "5.5", "275000", "0"]
        ])

        broker = BinanceConnector(BINANCE_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        candles = broker.get_market_data("BTCUSDT", "1m", 1)

        assert candles is not None
        assert len(candles) == 1
        assert candles[0]["open"] == 50000.0

    def test_generate_signature(self):
        broker = BinanceConnector(BINANCE_CONFIG)
        sig = broker._generate_signature({"timestamp": 1704067200000})
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA256 hex length

    def test_parse_order_status(self):
        broker = BinanceConnector(BINANCE_CONFIG)
        assert broker._parse_order_status("FILLED") == OrderStatus.FILLED
        assert broker._parse_order_status("CANCELED") == OrderStatus.CANCELLED
        assert broker._parse_order_status("NEW") == OrderStatus.OPEN
        assert broker._parse_order_status("REJECTED") == OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# OANDAConnector Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOANDAConnector:
    """Tests for OANDAConnector."""

    def test_initialization_practice(self):
        broker = OANDAConnector(OANDA_CONFIG)
        assert broker.environment == "practice"
        assert broker.base_url == OANDAConnector.PRACTICE_URL
        assert not broker.connected

    def test_initialization_live(self):
        cfg = {**OANDA_CONFIG, "environment": "live"}
        broker = OANDAConnector(cfg)
        assert broker.base_url == OANDAConnector.LIVE_URL

    def test_initialization_missing_credentials_raises(self):
        with pytest.raises(ValueError):
            OANDAConnector({"api_key": "token"})

    @patch("brokers.oanda.requests.Session")
    def test_connect_success(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({"account": {"id": "test_account"}})

        broker = OANDAConnector(OANDA_CONFIG)
        assert broker.connect() is True
        assert broker.connected is True

    @patch("brokers.oanda.requests.Session")
    def test_connect_failure(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.side_effect = Exception("auth error")

        broker = OANDAConnector(OANDA_CONFIG)
        assert broker.connect() is False

    @patch("brokers.oanda.requests.Session")
    def test_disconnect(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({"account": {}})

        broker = OANDAConnector(OANDA_CONFIG)
        broker.connect()
        assert broker.disconnect() is True

    @patch("brokers.oanda.requests.Session")
    def test_place_market_order_fill_response(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({"account": {}})
        mock_sess.post.return_value = _mock_response({
            "orderFillTransaction": {
                "id": "txn-1",
                "units": "10000",
                "price": "1.1050",
            }
        })

        broker = OANDAConnector(OANDA_CONFIG)
        broker.connect()
        order = broker.place_order("EUR_USD", OrderSide.BUY, 10000)

        assert order is not None
        assert order.status == OrderStatus.FILLED
        assert order.quantity == 10000.0

    @patch("brokers.oanda.requests.Session")
    def test_place_limit_order_create_response(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({"account": {}})
        mock_sess.post.return_value = _mock_response({
            "orderCreateTransaction": {
                "id": "txn-2",
                "units": "5000",
                "price": "1.0950",
            }
        })

        broker = OANDAConnector(OANDA_CONFIG)
        broker.connect()
        order = broker.place_order("EUR_USD", OrderSide.BUY, 5000, OrderType.LIMIT, price=1.0950)

        assert order is not None
        assert order.status == OrderStatus.OPEN

    @patch("brokers.oanda.requests.Session")
    def test_place_order_not_connected(self, _):
        broker = OANDAConnector(OANDA_CONFIG)
        assert broker.place_order("EUR_USD", OrderSide.BUY, 1000) is None

    @patch("brokers.oanda.requests.Session")
    def test_cancel_order(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.put.return_value = _mock_response({})

        broker = OANDAConnector(OANDA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        assert broker.cancel_order("order-1") is True

    @patch("brokers.oanda.requests.Session")
    def test_get_positions(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "positions": [
                {
                    "instrument": "EUR_USD",
                    "long": {"units": "10000", "averagePrice": "1.1050", "unrealizedPL": "50", "realizedPL": "0"},
                    "short": {"units": "0", "averagePrice": "0", "unrealizedPL": "0"},
                }
            ]
        })

        broker = OANDAConnector(OANDA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        positions = broker.get_positions()

        assert len(positions) == 1
        assert positions[0].symbol == "EUR/USD"
        assert positions[0].side == "LONG"

    @patch("brokers.oanda.requests.Session")
    def test_get_account_info(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "account": {
                "balance": "50000",
                "NAV": "51000",
                "marginUsed": "1000",
                "marginAvailable": "49000",
                "openPositionCount": "2",
            }
        })

        broker = OANDAConnector(OANDA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        info = broker.get_account_info()

        assert info is not None
        assert info.balance == 50000.0
        assert info.positions_count == 2

    @patch("brokers.oanda.requests.Session")
    def test_close_position(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.put.return_value = _mock_response({}, status_code=200)

        broker = OANDAConnector(OANDA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        assert broker.close_position("EUR_USD") is True

    @patch("brokers.oanda.requests.Session")
    def test_get_market_data(self, mock_session_cls):
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = _mock_response({
            "candles": [
                {
                    "time": "2024-01-01T00:00:00Z",
                    "mid": {"o": "1.1000", "h": "1.1050", "l": "1.0980", "c": "1.1030"},
                    "volume": 5000,
                    "complete": True,
                }
            ]
        })

        broker = OANDAConnector(OANDA_CONFIG)
        broker.connected = True
        broker.session = mock_sess
        candles = broker.get_market_data("EUR_USD", "M1", 1)

        assert candles is not None
        assert len(candles) == 1
        assert candles[0]["open"] == 1.1000

    def test_parse_order_status(self):
        broker = OANDAConnector(OANDA_CONFIG)
        assert broker._parse_order_status("FILLED") == OrderStatus.FILLED
        assert broker._parse_order_status("CANCELLED") == OrderStatus.CANCELLED
        assert broker._parse_order_status("PENDING") == OrderStatus.PENDING


# ---------------------------------------------------------------------------
# MT5Connector Tests  (MetaTrader5 is stubbed via sys.modules)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMT5Connector:
    """Tests for MT5Connector (uses MetaTrader5 stub)."""

    def setup_method(self):
        """Reset MT5 stub state before each test."""
        _mt5_stub.initialize.return_value = True
        _mt5_stub.login.return_value = True
        _mt5_stub.account_info.return_value = MagicMock(
            server="Demo-Server",
            login=12345678,
            balance=100000.0,
            equity=100500.0,
            margin=1000.0,
            margin_free=99000.0,
            leverage=100,
        )

    def test_initialization(self):
        broker = MT5Connector(MT5_CONFIG)
        assert broker.server == "Demo-Server"
        assert broker.login == 12345678
        assert not broker.connected

    def test_initialization_missing_fields_raises(self):
        with pytest.raises(ValueError):
            MT5Connector({"server": "Demo"})

    def test_connect_success(self):
        broker = MT5Connector(MT5_CONFIG)
        assert broker.connect() is True
        assert broker.connected is True

    def test_connect_initialize_failure(self):
        _mt5_stub.initialize.return_value = False
        broker = MT5Connector(MT5_CONFIG)
        assert broker.connect() is False

    def test_connect_login_failure(self):
        _mt5_stub.login.return_value = False
        broker = MT5Connector(MT5_CONFIG)
        assert broker.connect() is False
        assert not broker.connected

    def test_disconnect(self):
        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        assert broker.disconnect() is True
        assert not broker.connected

    def test_place_market_order(self):
        mock_result = MagicMock()
        mock_result.retcode = _mt5_stub.TRADE_RETCODE_DONE
        mock_result.order = 111
        mock_result.deal = 222
        mock_result.volume = 0.1
        mock_result.price = 1950.5
        _mt5_stub.order_send.return_value = mock_result

        sym_info = MagicMock()
        sym_info.visible = True
        _mt5_stub.symbol_info.return_value = sym_info

        tick = MagicMock()
        tick.ask = 1950.5
        tick.bid = 1950.3
        _mt5_stub.symbol_info_tick.return_value = tick

        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        order = broker.place_order("XAUUSD", OrderSide.BUY, 0.1)

        assert order is not None
        assert order.id == "111"
        assert order.status == OrderStatus.FILLED

    def test_place_order_not_connected(self):
        broker = MT5Connector(MT5_CONFIG)
        assert broker.place_order("XAUUSD", OrderSide.BUY, 0.1) is None

    def test_place_order_symbol_not_found(self):
        _mt5_stub.symbol_info.return_value = None
        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        assert broker.place_order("INVALID", OrderSide.BUY, 0.1) is None

    def test_place_order_failed_retcode(self):
        mock_result = MagicMock()
        mock_result.retcode = 10006  # Not DONE
        mock_result.comment = "Invalid price"
        _mt5_stub.order_send.return_value = mock_result

        sym_info = MagicMock()
        sym_info.visible = True
        _mt5_stub.symbol_info.return_value = sym_info

        tick = MagicMock()
        tick.ask = 1950.0
        _mt5_stub.symbol_info_tick.return_value = tick

        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        assert broker.place_order("XAUUSD", OrderSide.BUY, 0.1) is None

    def test_cancel_order(self):
        mock_result = MagicMock()
        mock_result.retcode = _mt5_stub.TRADE_RETCODE_DONE
        _mt5_stub.order_send.return_value = mock_result

        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        assert broker.cancel_order("111") is True

    def test_cancel_order_not_connected(self):
        broker = MT5Connector(MT5_CONFIG)
        assert broker.cancel_order("111") is False

    def test_get_positions(self):
        pos = MagicMock()
        pos.symbol = "XAUUSD"
        pos.type = _mt5_stub.POSITION_TYPE_BUY
        pos.volume = 0.1
        pos.price_open = 1950.0
        pos.profit = 50.0
        pos.time = 1704067200
        _mt5_stub.positions_get.return_value = [pos]

        tick = MagicMock()
        tick.bid = 1960.0
        tick.ask = 1960.2
        _mt5_stub.symbol_info_tick.return_value = tick

        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        positions = broker.get_positions()

        assert len(positions) == 1
        assert positions[0].symbol == "XAUUSD"
        assert positions[0].side == "LONG"

    def test_get_positions_not_connected(self):
        broker = MT5Connector(MT5_CONFIG)
        assert broker.get_positions() == []

    def test_get_account_info(self):
        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        _mt5_stub.positions_get.return_value = []
        info = broker.get_account_info()

        assert info is not None
        assert info.balance == 100000.0
        assert info.equity == 100500.0

    def test_get_account_info_not_connected(self):
        broker = MT5Connector(MT5_CONFIG)
        assert broker.get_account_info() is None

    def test_close_position(self):
        pos = MagicMock()
        pos.symbol = "XAUUSD"
        pos.type = _mt5_stub.POSITION_TYPE_BUY
        pos.volume = 0.1
        pos.ticket = 999
        _mt5_stub.positions_get.return_value = [pos]

        tick = MagicMock()
        tick.bid = 1960.0
        tick.ask = 1960.2
        _mt5_stub.symbol_info_tick.return_value = tick

        mock_result = MagicMock()
        mock_result.retcode = _mt5_stub.TRADE_RETCODE_DONE
        _mt5_stub.order_send.return_value = mock_result

        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        assert broker.close_position("XAUUSD") is True

    def test_get_market_data(self):
        rates = [
            {"time": 1704067200, "open": 1950.0, "high": 1960.0, "low": 1940.0, "close": 1955.0, "tick_volume": 500}
        ]
        _mt5_stub.copy_rates_from_pos.return_value = rates

        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        candles = broker.get_market_data("XAUUSD", "H1", 1)

        assert candles is not None
        assert len(candles) == 1
        assert candles[0]["open"] == 1950.0

    def test_get_symbols(self):
        sym1 = MagicMock()
        sym1.name = "EURUSD"
        sym1.visible = True
        sym2 = MagicMock()
        sym2.name = "XAUUSD"
        sym2.visible = True
        _mt5_stub.symbols_get.return_value = [sym1, sym2]

        broker = MT5Connector(MT5_CONFIG)
        broker.connected = True
        syms = broker.get_symbols()

        assert "EURUSD" in syms
        assert "XAUUSD" in syms


# ---------------------------------------------------------------------------
# InteractiveBrokersConnector Tests  (ib_insync is stubbed)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInteractiveBrokersConnector:
    """Tests for InteractiveBrokersConnector (uses ib_insync stub)."""

    def _make_broker(self):
        """Create a broker with a fresh IB mock."""
        broker = InteractiveBrokersConnector(IB_CONFIG)
        broker.ib = MagicMock()
        return broker

    def test_initialization(self):
        broker = InteractiveBrokersConnector(IB_CONFIG)
        assert broker.host == "127.0.0.1"
        assert broker.port == 7497
        assert broker.paper is True
        assert not broker.connected

    def test_connect_success(self):
        broker = self._make_broker()
        broker.ib.managedAccounts.return_value = ["DU123456"]
        assert broker.connect() is True
        assert broker.connected is True
        assert broker.account == "DU123456"

    def test_connect_failure(self):
        broker = self._make_broker()
        broker.ib.connect.side_effect = Exception("cannot connect")
        assert broker.connect() is False
        assert not broker.connected

    def test_disconnect(self):
        broker = self._make_broker()
        broker.connected = True
        assert broker.disconnect() is True
        assert not broker.connected

    def test_place_market_order(self):
        broker = self._make_broker()
        broker.connected = True

        mock_trade = MagicMock()
        mock_trade.order.orderId = 42
        broker.ib.placeOrder.return_value = mock_trade

        order = broker.place_order("AAPL", OrderSide.BUY, 10)

        assert order is not None
        assert order.id == "42"
        assert order.symbol == "AAPL"

    def test_place_limit_order(self):
        broker = self._make_broker()
        broker.connected = True

        mock_trade = MagicMock()
        mock_trade.order.orderId = 55
        broker.ib.placeOrder.return_value = mock_trade

        order = broker.place_order("AAPL", OrderSide.SELL, 5, OrderType.LIMIT, price=190.0)

        assert order is not None
        assert order.price == 190.0

    def test_place_order_not_connected(self):
        broker = self._make_broker()
        assert broker.place_order("AAPL", OrderSide.BUY, 10) is None

    def test_cancel_order_found(self):
        broker = self._make_broker()
        broker.connected = True

        mock_trade = MagicMock()
        mock_trade.order.orderId = 42
        broker.ib.trades.return_value = [mock_trade]

        assert broker.cancel_order("42") is True

    def test_cancel_order_not_found(self):
        broker = self._make_broker()
        broker.connected = True
        broker.ib.trades.return_value = []

        assert broker.cancel_order("99") is False

    def test_get_positions(self):
        broker = self._make_broker()
        broker.connected = True

        mock_pos = MagicMock()
        mock_pos.contract.symbol = "AAPL"
        mock_pos.position = 100
        mock_pos.avgCost = 15000.0
        mock_pos.unrealizedPNL = 500.0
        broker.ib.positions.return_value = [mock_pos]

        mock_ticker = MagicMock()
        mock_ticker.marketPrice.return_value = 155.0
        broker.ib.reqTicker.return_value = mock_ticker

        positions = broker.get_positions()

        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].side == "LONG"

    def test_get_positions_not_connected(self):
        broker = self._make_broker()
        assert broker.get_positions() == []

    def test_get_account_info(self):
        broker = self._make_broker()
        broker.connected = True
        broker.ib.positions.return_value = []

        account_vals = [
            MagicMock(tag="TotalCashValue", value="10000"),
            MagicMock(tag="NetLiquidation", value="11000"),
            MagicMock(tag="MaintMarginReq", value="500"),
            MagicMock(tag="AvailableFunds", value="9500"),
        ]
        broker.ib.accountValues.return_value = account_vals

        info = broker.get_account_info()

        assert info is not None
        assert info.balance == 10000.0
        assert info.equity == 11000.0

    def test_get_account_info_not_connected(self):
        broker = self._make_broker()
        assert broker.get_account_info() is None

    def test_close_position(self):
        broker = self._make_broker()
        broker.connected = True

        mock_pos = MagicMock()
        mock_pos.contract.symbol = "AAPL"
        mock_pos.position = 100
        mock_pos.avgCost = 15000.0
        mock_pos.unrealizedPNL = 500.0
        broker.ib.positions.return_value = [mock_pos]

        mock_ticker = MagicMock()
        mock_ticker.marketPrice.return_value = 155.0
        broker.ib.reqTicker.return_value = mock_ticker

        mock_trade = MagicMock()
        mock_trade.order.orderId = 77
        broker.ib.placeOrder.return_value = mock_trade

        assert broker.close_position("AAPL") is True

    def test_get_market_data(self):
        broker = self._make_broker()
        broker.connected = True

        mock_bar = MagicMock()
        mock_bar.date = datetime(2024, 1, 1)
        mock_bar.open = 150.0
        mock_bar.high = 155.0
        mock_bar.low = 149.0
        mock_bar.close = 153.0
        mock_bar.volume = 10000
        broker.ib.reqHistoricalData.return_value = [mock_bar]

        candles = broker.get_market_data("AAPL", "1 hour", 5)

        assert candles is not None
        assert len(candles) == 1
        assert candles[0]["open"] == 150.0


# ---------------------------------------------------------------------------
# AdvancedOrderManager Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAdvancedOrderManager:
    """Tests for AdvancedOrderManager."""

    def test_initialization(self):
        mgr = AdvancedOrderManager()
        assert mgr.orders == {}
        assert mgr.oco_orders == {}
        assert mgr.bracket_orders == {}
        assert mgr.stats["total_orders"] == 0

    def test_create_basic_order(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_order(
            "EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 10000, price=1.1000
        )
        assert order.symbol == "EURUSD"
        assert order.side == AdvOrderSide.BUY
        assert order.price == 1.1000
        assert order.id in mgr.orders
        assert mgr.stats["total_orders"] == 1

    def test_create_trailing_stop(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_trailing_stop(
            "EURUSD", AdvOrderSide.SELL, 10000, trail_amount=50.0
        )
        assert order.trail_amount == 50.0
        assert order.id in mgr.trailing_stops

    def test_create_trailing_stop_percent(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_trailing_stop(
            "XAUUSD", AdvOrderSide.SELL, 1.0, trail_percent=1.5
        )
        assert order.trail_percent == 1.5

    def test_create_oco_order(self):
        mgr = AdvancedOrderManager()
        oco = mgr.create_oco_order(
            "EURUSD", AdvOrderSide.SELL, 10000,
            limit_price=1.1100, stop_price=1.0900
        )
        assert oco.order1.price == 1.1100
        assert oco.order2.stop_price == 1.0900
        assert oco.id in mgr.oco_orders
        # 2 child orders created
        assert mgr.stats["total_orders"] == 2

    def test_oco_order_fill_cancels_other(self):
        mgr = AdvancedOrderManager()
        oco = mgr.create_oco_order(
            "EURUSD", AdvOrderSide.SELL, 10000,
            limit_price=1.1100, stop_price=1.0900
        )
        # Simulate order1 fill
        mgr.handle_order_fill(oco.order1.id, 1.1100, 10000)
        assert oco.order2.status == AdvOrderStatus.CANCELLED
        assert oco.status == AdvOrderStatus.FILLED
        assert mgr.stats["oco_triggered"] == 1

    def test_create_bracket_order(self):
        mgr = AdvancedOrderManager()
        bracket = mgr.create_bracket_order(
            symbol="XAUUSD",
            side=AdvOrderSide.BUY,
            quantity=1.0,
            entry_type=AdvOrderType.MARKET,
            entry_price=None,
            stop_loss_price=1920.0,
            take_profit_price=2000.0,
        )
        assert bracket.entry_order.side == AdvOrderSide.BUY
        assert bracket.stop_loss_order.stop_price == 1920.0
        assert bracket.take_profit_order.price == 2000.0
        assert bracket.id in mgr.bracket_orders
        # 3 orders: entry + sl + tp
        assert mgr.stats["total_orders"] == 3

    def test_bracket_entry_fill_activates_sl_tp(self):
        mgr = AdvancedOrderManager()
        bracket = mgr.create_bracket_order(
            "XAUUSD", AdvOrderSide.BUY, 1.0,
            AdvOrderType.MARKET, None, 1920.0, 2000.0
        )
        mgr.handle_order_fill(bracket.entry_order.id, 1960.0, 1.0)
        assert bracket.position_filled is True
        assert bracket.stop_loss_order.status == AdvOrderStatus.OPEN
        assert bracket.take_profit_order.status == AdvOrderStatus.OPEN

    def test_bracket_tp_fill_cancels_sl(self):
        mgr = AdvancedOrderManager()
        bracket = mgr.create_bracket_order(
            "XAUUSD", AdvOrderSide.BUY, 1.0,
            AdvOrderType.MARKET, None, 1920.0, 2000.0
        )
        mgr.handle_order_fill(bracket.entry_order.id, 1960.0, 1.0)
        mgr.handle_order_fill(bracket.take_profit_order.id, 2000.0, 1.0)
        assert bracket.stop_loss_order.status == AdvOrderStatus.CANCELLED
        assert bracket.status == AdvOrderStatus.FILLED
        assert mgr.stats["brackets_completed"] == 1

    def test_bracket_sl_fill_cancels_tp(self):
        mgr = AdvancedOrderManager()
        bracket = mgr.create_bracket_order(
            "XAUUSD", AdvOrderSide.BUY, 1.0,
            AdvOrderType.MARKET, None, 1920.0, 2000.0
        )
        mgr.handle_order_fill(bracket.entry_order.id, 1960.0, 1.0)
        mgr.handle_order_fill(bracket.stop_loss_order.id, 1920.0, 1.0)
        assert bracket.take_profit_order.status == AdvOrderStatus.CANCELLED
        assert bracket.status == AdvOrderStatus.FILLED

    def test_update_trailing_stop_sell(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_trailing_stop(
            "EURUSD", AdvOrderSide.SELL, 10000, trail_amount=0.0020
        )
        # Price moves up
        new_stop = mgr.update_trailing_stop(order.id, 1.1100)
        assert new_stop == pytest.approx(1.1080, abs=1e-5)

    def test_update_trailing_stop_buy(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_trailing_stop(
            "EURUSD", AdvOrderSide.BUY, 10000, trail_amount=0.0020
        )
        # Price moves down
        new_stop = mgr.update_trailing_stop(order.id, 1.0900)
        assert new_stop == pytest.approx(1.0920, abs=1e-5)

    def test_cancel_order(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000)
        assert mgr.cancel_order(order.id) is True
        assert mgr.orders[order.id].status == AdvOrderStatus.CANCELLED

    def test_cancel_filled_order_fails(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.MARKET, 1000)
        order.status = AdvOrderStatus.FILLED
        assert mgr.cancel_order(order.id) is False

    def test_create_conditional_order(self):
        mgr = AdvancedOrderManager()
        base_order = mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000)
        conditions = [{"type": "price_above", "value": 1.1000}]
        cond_order = mgr.create_conditional_order(base_order, conditions)
        assert cond_order.id in mgr.conditional_orders

    def test_evaluate_conditional_order_price_above_true(self):
        mgr = AdvancedOrderManager()
        base_order = mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000)
        conditions = [{"type": "price_above", "value": 1.1000}]
        cond = mgr.create_conditional_order(base_order, conditions)
        result = mgr.evaluate_conditional_order(cond.id, {"price": 1.1100})
        assert result is True

    def test_evaluate_conditional_order_price_below_false(self):
        mgr = AdvancedOrderManager()
        base_order = mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000)
        conditions = [{"type": "price_below", "value": 1.0900}]
        cond = mgr.create_conditional_order(base_order, conditions)
        result = mgr.evaluate_conditional_order(cond.id, {"price": 1.1000})
        assert result is False

    def test_create_scaled_order(self):
        mgr = AdvancedOrderManager()
        scaled = mgr.create_scaled_order(
            "EURUSD", AdvOrderSide.BUY, 10000, 4, 1.0900, 1.1000
        )
        assert len(scaled.levels) == 4
        assert len(scaled.child_orders) == 4
        assert sum(l["quantity"] for l in scaled.levels) == pytest.approx(10000, rel=1e-5)

    def test_get_open_orders(self):
        mgr = AdvancedOrderManager()
        o1 = mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000)
        o2 = mgr.create_order("XAUUSD", AdvOrderSide.SELL, AdvOrderType.STOP, 500)
        o2.status = AdvOrderStatus.FILLED  # filled, shouldn't appear
        open_orders = mgr.get_open_orders()
        assert any(o.id == o1.id for o in open_orders)
        assert not any(o.id == o2.id for o in open_orders)

    def test_get_open_orders_filtered_by_symbol(self):
        mgr = AdvancedOrderManager()
        mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000)
        mgr.create_order("XAUUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 500)
        open_orders = mgr.get_open_orders(symbol="EURUSD")
        assert all(o.symbol == "EURUSD" for o in open_orders)

    def test_get_statistics(self):
        mgr = AdvancedOrderManager()
        mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000)
        stats = mgr.get_statistics()
        assert stats["total_orders"] == 1
        assert "active_orders" in stats
        assert "active_oco" in stats

    def test_get_order(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000)
        found = mgr.get_order(order.id)
        assert found is not None
        assert found.id == order.id

    def test_order_to_dict(self):
        mgr = AdvancedOrderManager()
        order = mgr.create_order("EURUSD", AdvOrderSide.BUY, AdvOrderType.LIMIT, 1000, price=1.10)
        d = order.to_dict()
        assert d["symbol"] == "EURUSD"
        assert d["price"] == 1.10
        assert d["side"] == "buy"

    def test_oco_to_dict(self):
        mgr = AdvancedOrderManager()
        oco = mgr.create_oco_order("EURUSD", AdvOrderSide.SELL, 10000, 1.11, 1.09)
        d = oco.to_dict()
        assert "order1" in d
        assert "order2" in d

    def test_bracket_to_dict(self):
        mgr = AdvancedOrderManager()
        bracket = mgr.create_bracket_order(
            "EURUSD", AdvOrderSide.BUY, 10000, AdvOrderType.LIMIT, 1.10, 1.08, 1.12
        )
        d = bracket.to_dict()
        assert "entry_order" in d
        assert "stop_loss_order" in d
        assert "take_profit_order" in d


# ---------------------------------------------------------------------------
# BrokerFactory Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBrokerFactory:
    """Tests for BrokerFactory."""

    def test_list_brokers(self):
        brokers = BrokerFactory.list_brokers()
        assert "paper" in brokers
        assert "oanda" in brokers
        assert "binance" in brokers
        assert "alpaca" in brokers
        assert "mt5" in brokers
        assert "ib" in brokers
        assert "ftmo" in brokers
        assert "topstep" in brokers
        assert "the5ers" in brokers
        assert "myforexfunds" in brokers

    def test_create_paper_broker(self):
        broker = BrokerFactory.create_broker("paper", {})
        assert broker is not None

    def test_create_alpaca_broker(self):
        broker = BrokerFactory.create_broker("alpaca", ALPACA_CONFIG)
        assert isinstance(broker, AlpacaConnector)

    def test_create_binance_broker(self):
        broker = BrokerFactory.create_broker("binance", BINANCE_CONFIG)
        assert isinstance(broker, BinanceConnector)

    def test_create_oanda_broker(self):
        broker = BrokerFactory.create_broker("oanda", OANDA_CONFIG)
        assert isinstance(broker, OANDAConnector)

    def test_create_mt5_broker(self):
        broker = BrokerFactory.create_broker("mt5", MT5_CONFIG)
        assert isinstance(broker, MT5Connector)

    def test_create_ib_broker(self):
        broker = BrokerFactory.create_broker("ib", IB_CONFIG)
        assert isinstance(broker, InteractiveBrokersConnector)

    def test_create_interactive_brokers_alias(self):
        broker = BrokerFactory.create_broker("interactive_brokers", IB_CONFIG)
        assert isinstance(broker, InteractiveBrokersConnector)

    def test_create_ftmo_broker(self):
        cfg = {**MT5_CONFIG, "challenge_type": "demo"}
        broker = BrokerFactory.create_broker("ftmo", cfg)
        assert isinstance(broker, FTMOConnector)

    def test_create_topstep_broker(self):
        broker = BrokerFactory.create_broker("topstep", MT5_CONFIG)
        assert isinstance(broker, TopstepTraderConnector)

    def test_create_topsteptrader_alias(self):
        broker = BrokerFactory.create_broker("topsteptrader", MT5_CONFIG)
        assert isinstance(broker, TopstepTraderConnector)

    def test_create_the5ers_broker(self):
        broker = BrokerFactory.create_broker("the5ers", MT5_CONFIG)
        assert isinstance(broker, The5ersConnector)

    def test_create_myforexfunds_broker(self):
        broker = BrokerFactory.create_broker("myforexfunds", MT5_CONFIG)
        assert isinstance(broker, MyForexFundsConnector)

    def test_create_mff_alias(self):
        broker = BrokerFactory.create_broker("mff", MT5_CONFIG)
        assert isinstance(broker, MyForexFundsConnector)

    def test_create_unknown_broker_returns_none(self):
        broker = BrokerFactory.create_broker("unknown_broker", {})
        assert broker is None

    def test_create_broker_case_insensitive(self):
        broker = BrokerFactory.create_broker("ALPACA", ALPACA_CONFIG)
        assert isinstance(broker, AlpacaConnector)

    def test_register_custom_broker(self):
        from brokers.base import BrokerConnector

        class CustomBroker(BrokerConnector):
            def connect(self): return True
            def disconnect(self): return True
            def place_order(self, *a, **kw): return None
            def cancel_order(self, *a, **kw): return False
            def get_order(self, *a, **kw): return None
            def get_positions(self, *a, **kw): return []
            def close_position(self, *a, **kw): return False
            def get_account_info(self, *a, **kw): return None
            def get_market_data(self, *a, **kw): return None

        BrokerFactory.register_broker("custom_test", CustomBroker)
        broker = BrokerFactory.create_broker("custom_test", {})
        assert isinstance(broker, CustomBroker)

    def test_register_non_broker_class_raises(self):
        with pytest.raises(ValueError):
            BrokerFactory.register_broker("bad", object)


# ---------------------------------------------------------------------------
# Prop Firm Connector Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFTMOConnector:
    """Tests for FTMOConnector."""

    def test_initialization_auto_server(self):
        cfg = {"login": 12345, "password": "pass", "challenge_type": "demo"}
        broker = FTMOConnector(cfg)
        assert "FTMO" in broker.server
        assert broker.challenge_type == "demo"

    def test_initialization_live_auto_server(self):
        cfg = {"login": 12345, "password": "pass", "challenge_type": "live"}
        broker = FTMOConnector(cfg)
        assert broker.server in FTMOConnector.FTMO_SERVERS["live"]

    def test_initialization_explicit_server(self):
        cfg = {**MT5_CONFIG, "server": "FTMO-Demo2", "challenge_type": "demo"}
        broker = FTMOConnector(cfg)
        assert broker.server == "FTMO-Demo2"

    def test_get_ftmo_rules(self):
        cfg = {"login": 12345, "password": "pass", "challenge_type": "demo"}
        broker = FTMOConnector(cfg)
        rules = broker.get_ftmo_rules()
        assert "max_daily_loss" in rules
        assert "profit_target" in rules
        assert "profit_split" in rules

    def test_check_ftmo_compliance_not_connected(self):
        cfg = {"login": 12345, "password": "pass", "challenge_type": "demo"}
        broker = FTMOConnector(cfg)
        # Not connected → get_account_info returns None
        compliance = broker.check_ftmo_compliance()
        assert compliance["compliant"] is False

    def test_check_ftmo_compliance_connected(self):
        cfg = {"login": 12345, "password": "pass", "challenge_type": "demo"}
        broker = FTMOConnector(cfg)
        broker.connected = True
        _mt5_stub.account_info.return_value = MagicMock(
            balance=100000.0, equity=99000.0,
            margin=500.0, margin_free=98500.0,
        )
        _mt5_stub.positions_get.return_value = []
        compliance = broker.check_ftmo_compliance()
        assert "compliant" in compliance
        assert "equity" in compliance

    def test_inherits_mt5_connect(self):
        cfg = {"login": 12345, "password": "pass", "challenge_type": "demo"}
        broker = FTMOConnector(cfg)
        _mt5_stub.initialize.return_value = True
        _mt5_stub.login.return_value = True
        assert broker.connect() is True


@pytest.mark.unit
class TestMyForexFundsConnector:
    """Tests for MyForexFundsConnector."""

    def test_initialization_auto_server(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = MyForexFundsConnector(cfg)
        assert broker.server == "MyForexFunds-Demo"
        assert broker.account_size == 100000

    def test_initialization_explicit_server(self):
        cfg = {"login": 12345, "password": "pass", "server": "MyForexFunds-Live", "account_size": 50000}
        broker = MyForexFundsConnector(cfg)
        assert broker.server == "MyForexFunds-Live"
        assert broker.account_size == 50000

    def test_get_myforexfunds_rules(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = MyForexFundsConnector(cfg)
        rules = broker.get_myforexfunds_rules()
        assert "max_daily_loss" in rules
        assert "profit_split" in rules
        assert "scaling" in rules

    def test_inherits_mt5_methods(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = MyForexFundsConnector(cfg)
        assert hasattr(broker, "place_order")
        assert hasattr(broker, "get_account_info")
        assert hasattr(broker, "get_positions")


@pytest.mark.unit
class TestThe5ersConnector:
    """Tests for The5ersConnector."""

    def test_initialization_auto_server(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = The5ersConnector(cfg)
        assert broker.server == "The5ers-Demo"
        assert broker.program == "high_stakes"

    def test_initialization_with_program(self):
        cfg = {"login": 12345, "password": "pass", "program": "instant_funding"}
        broker = The5ersConnector(cfg)
        assert broker.program == "instant_funding"

    def test_get_the5ers_rules(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = The5ersConnector(cfg)
        rules = broker.get_the5ers_rules()
        assert "profit_split" in rules
        assert "programs" in rules
        assert "high_stakes" in rules["programs"]

    def test_inherits_mt5_methods(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = The5ersConnector(cfg)
        assert hasattr(broker, "connect")
        assert hasattr(broker, "cancel_order")


@pytest.mark.unit
class TestTopstepTraderConnector:
    """Tests for TopstepTraderConnector."""

    def test_initialization_auto_server(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = TopstepTraderConnector(cfg)
        assert broker.server == "TopstepTrader-Server01"
        assert broker.account_type == "combine"

    def test_initialization_funded_type(self):
        cfg = {"login": 12345, "password": "pass", "account_type": "funded"}
        broker = TopstepTraderConnector(cfg)
        assert broker.account_type == "funded"

    def test_get_topstep_rules(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = TopstepTraderConnector(cfg)
        rules = broker.get_topstep_rules()
        assert "max_daily_loss" in rules
        assert "profit_target" in rules
        assert "profit_split" in rules

    def test_inherits_mt5_connect(self):
        cfg = {"login": 12345, "password": "pass"}
        broker = TopstepTraderConnector(cfg)
        _mt5_stub.initialize.return_value = True
        _mt5_stub.login.return_value = True
        assert broker.connect() is True
