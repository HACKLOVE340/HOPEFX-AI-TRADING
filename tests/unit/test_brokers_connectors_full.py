# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for brokers/alpaca.py, brokers/binance.py, brokers/bybit_connector.py.
All network calls are mocked — no live connections required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from brokers.base import OrderSide, OrderStatus, OrderType

UTC = timezone.utc


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(json_data, status_code=200, raise_for_status=False):
    r = MagicMock()
    r.json.return_value = json_data
    r.status_code = status_code
    if raise_for_status:
        r.raise_for_status.side_effect = Exception("HTTP error")
    else:
        r.raise_for_status.return_value = None
    return r


# ═══════════════════════════════════════════════════════════════════════════════
# AlpacaConnector
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlpacaConnector:
    def _make(self, connected=False):
        from brokers.alpaca import AlpacaConnector
        c = AlpacaConnector({"api_key": "key", "api_secret": "secret", "paper": True})
        c.connected = connected
        c.session = MagicMock()
        return c

    def test_init_raises_without_credentials(self):
        from brokers.alpaca import AlpacaConnector
        with pytest.raises(ValueError, match="api_key"):
            AlpacaConnector({})

    def test_init_paper_url(self):
        from brokers.alpaca import AlpacaConnector
        c = AlpacaConnector({"api_key": "k", "api_secret": "s", "paper": True})
        assert "paper" in c.base_url

    def test_init_live_url(self):
        from brokers.alpaca import AlpacaConnector
        c = AlpacaConnector({"api_key": "k", "api_secret": "s", "paper": False})
        assert "paper" not in c.base_url

    def test_connect_success(self):
        from brokers.alpaca import AlpacaConnector
        c = AlpacaConnector({"api_key": "k", "api_secret": "s"})
        mock_session = MagicMock()
        mock_session.get.return_value = _mock_response({"status": "ACTIVE"})
        with patch("requests.Session", return_value=mock_session):
            result = c.connect()
        assert result is True
        assert c.connected is True

    def test_connect_failure(self):
        from brokers.alpaca import AlpacaConnector
        c = AlpacaConnector({"api_key": "k", "api_secret": "s"})
        with patch("requests.Session", side_effect=RuntimeError("network")):
            result = c.connect()
        assert result is False

    def test_disconnect_success(self):
        c = self._make(connected=True)
        assert c.disconnect() is True
        assert c.connected is False

    def test_disconnect_failure(self):
        c = self._make(connected=True)
        c.session.close.side_effect = RuntimeError("fail")
        assert c.disconnect() is False

    def test_place_order_not_connected(self):
        c = self._make(connected=False)
        result = c.place_order("AAPL", OrderSide.BUY, order_type=OrderType.MARKET, quantity=1.0)
        assert result is None

    def test_place_order_success(self):
        c = self._make(connected=True)
        c.session.post.return_value = _mock_response({
            "id": "order-1", "symbol": "AAPL", "side": "buy",
            "type": "market", "qty": "1", "status": "new",
            "filled_qty": "0", "created_at": "2024-01-01T00:00:00Z",
        })
        order = c.place_order("AAPL", OrderSide.BUY, order_type=OrderType.MARKET, quantity=1.0)
        assert order is not None
        assert order.id == "order-1"

    def test_place_order_limit_with_price(self):
        c = self._make(connected=True)
        c.session.post.return_value = _mock_response({
            "id": "order-2", "symbol": "AAPL", "side": "buy",
            "type": "limit", "qty": "1", "status": "new",
            "limit_price": "150.0", "filled_qty": "0",
            "created_at": "2024-01-01T00:00:00Z",
        })
        order = c.place_order("AAPL", OrderSide.BUY, order_type=OrderType.LIMIT,
                              quantity=1.0, price=150.0)
        assert order is not None

    def test_place_order_stop_limit(self):
        c = self._make(connected=True)
        c.session.post.return_value = _mock_response({
            "id": "order-3", "symbol": "AAPL", "side": "sell",
            "type": "stop_limit", "qty": "1", "status": "new",
            "stop_price": "140.0", "limit_price": "139.0",
            "filled_qty": "0", "created_at": "2024-01-01T00:00:00Z",
        })
        order = c.place_order("AAPL", OrderSide.SELL, order_type=OrderType.STOP_LIMIT,
                              quantity=1.0, price=139.0, stop_price=140.0)
        assert order is not None

    def test_place_order_extended_hours(self):
        c = self._make(connected=True)
        c.session.post.return_value = _mock_response({
            "id": "order-4", "symbol": "AAPL", "side": "buy",
            "type": "market", "qty": "1", "status": "new",
            "filled_qty": "0", "created_at": "2024-01-01T00:00:00Z",
        })
        order = c.place_order("AAPL", OrderSide.BUY, order_type=OrderType.MARKET,
                              quantity=1.0, extended_hours=True)
        assert order is not None
        call_kwargs = c.session.post.call_args[1]["json"]
        assert call_kwargs.get("extended_hours") is True

    def test_place_order_exception(self):
        c = self._make(connected=True)
        c.session.post.side_effect = RuntimeError("network error")
        result = c.place_order("AAPL", OrderSide.BUY, order_type=OrderType.MARKET, quantity=1.0)
        assert result is None

    def test_cancel_order_not_connected(self):
        c = self._make(connected=False)
        assert c.cancel_order("order-1") is False

    def test_cancel_order_success(self):
        c = self._make(connected=True)
        c.session.delete.return_value = _mock_response({})
        assert c.cancel_order("order-1") is True

    def test_cancel_order_failure(self):
        c = self._make(connected=True)
        c.session.delete.side_effect = RuntimeError("fail")
        assert c.cancel_order("order-1") is False

    def test_get_order_not_connected(self):
        c = self._make(connected=False)
        assert c.get_order("order-1") is None

    def test_get_order_success(self):
        c = self._make(connected=True)
        c.session.get.return_value = _mock_response({
            "id": "order-1", "symbol": "AAPL", "side": "buy",
            "type": "market", "qty": "1", "status": "filled",
            "filled_qty": "1", "filled_avg_price": "150.0",
            "created_at": "2024-01-01T00:00:00Z",
        })
        order = c.get_order("order-1")
        assert order is not None
        assert order.status == OrderStatus.FILLED

    def test_get_order_exception(self):
        c = self._make(connected=True)
        c.session.get.side_effect = RuntimeError("fail")
        assert c.get_order("order-1") is None

    def test_get_positions_not_connected(self):
        c = self._make(connected=False)
        assert c.get_positions() == []

    def test_get_positions_success(self):
        c = self._make(connected=True)
        c.session.get.return_value = _mock_response([{
            "symbol": "AAPL", "qty": "10",
            "avg_entry_price": "150.0", "current_price": "155.0",
            "unrealized_pl": "50.0",
        }])
        positions = c.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].side == "LONG"

    def test_get_positions_short(self):
        c = self._make(connected=True)
        c.session.get.return_value = _mock_response([{
            "symbol": "TSLA", "qty": "-5",
            "avg_entry_price": "200.0", "current_price": "190.0",
            "unrealized_pl": "50.0",
        }])
        positions = c.get_positions()
        assert positions[0].side == "SHORT"

    def test_get_positions_exception(self):
        c = self._make(connected=True)
        c.session.get.side_effect = RuntimeError("fail")
        assert c.get_positions() == []

    def test_close_position_not_connected(self):
        c = self._make(connected=False)
        assert c.close_position("AAPL") is False

    def test_close_position_full(self):
        c = self._make(connected=True)
        c.session.delete.return_value = _mock_response({})
        assert c.close_position("AAPL") is True

    def test_close_position_partial(self):
        c = self._make(connected=True)
        # get_positions returns a LONG position
        c.session.get.return_value = _mock_response([{
            "symbol": "AAPL", "qty": "10",
            "avg_entry_price": "150.0", "current_price": "155.0",
            "unrealized_pl": "50.0",
        }])
        c.session.post.return_value = _mock_response({
            "id": "order-5", "symbol": "AAPL", "side": "sell",
            "type": "market", "qty": "5", "status": "new",
            "filled_qty": "0", "created_at": "2024-01-01T00:00:00Z",
        })
        result = c.close_position("AAPL", quantity=5.0)
        assert result is True

    def test_close_position_partial_no_position(self):
        c = self._make(connected=True)
        c.session.get.return_value = _mock_response([])
        result = c.close_position("AAPL", quantity=5.0)
        assert result is False

    def test_close_position_exception(self):
        c = self._make(connected=True)
        c.session.delete.side_effect = RuntimeError("fail")
        assert c.close_position("AAPL") is False

    def test_get_account_info_not_connected(self):
        c = self._make(connected=False)
        assert c.get_account_info() is None

    def test_get_account_info_success(self):
        c = self._make(connected=True)
        c.session.get.return_value = _mock_response({
            "cash": "10000", "equity": "10500",
            "initial_margin": "500", "buying_power": "9500",
            "position_count": "2",
        })
        info = c.get_account_info()
        assert info is not None
        assert info.balance == pytest.approx(10000.0)

    def test_get_account_info_exception(self):
        c = self._make(connected=True)
        c.session.get.side_effect = RuntimeError("fail")
        assert c.get_account_info() is None

    def test_get_market_data_not_connected(self):
        c = self._make(connected=False)
        assert c.get_market_data("AAPL") is None

    def test_get_market_data_success(self):
        c = self._make(connected=True)
        c.session.get.return_value = _mock_response({
            "bars": [{"t": "2024-01-01T00:00:00Z", "o": 150.0, "h": 151.0,
                      "l": 149.0, "c": 150.5, "v": 1000}]
        })
        bars = c.get_market_data("AAPL")
        assert len(bars) == 1
        assert bars[0]["close"] == 150.5

    def test_get_market_data_exception(self):
        c = self._make(connected=True)
        c.session.get.side_effect = RuntimeError("fail")
        assert c.get_market_data("AAPL") is None

    def test_get_quote_not_connected(self):
        c = self._make(connected=False)
        assert c.get_quote("AAPL") is None

    def test_get_quote_success(self):
        c = self._make(connected=True)
        c.session.get.return_value = _mock_response({
            "quote": {"bp": 150.0, "ap": 150.1, "bs": 100, "as": 200,
                      "t": "2024-01-01T00:00:00Z"}
        })
        quote = c.get_quote("AAPL")
        assert quote is not None
        assert quote["bid"] == 150.0

    def test_get_quote_no_quote_key(self):
        c = self._make(connected=True)
        c.session.get.return_value = _mock_response({})
        assert c.get_quote("AAPL") is None

    def test_get_quote_exception(self):
        c = self._make(connected=True)
        c.session.get.side_effect = RuntimeError("fail")
        assert c.get_quote("AAPL") is None

    def test_convert_order_type_all(self):
        from brokers.alpaca import AlpacaConnector
        c = AlpacaConnector({"api_key": "k", "api_secret": "s"})
        assert c._convert_order_type(OrderType.MARKET) == "market"
        assert c._convert_order_type(OrderType.LIMIT) == "limit"
        assert c._convert_order_type(OrderType.STOP) == "stop"
        assert c._convert_order_type(OrderType.STOP_LIMIT) == "stop_limit"

    def test_parse_order_type_all(self):
        from brokers.alpaca import AlpacaConnector
        c = AlpacaConnector({"api_key": "k", "api_secret": "s"})
        assert c._parse_order_type("market") == OrderType.MARKET
        assert c._parse_order_type("limit") == OrderType.LIMIT
        assert c._parse_order_type("stop") == OrderType.STOP
        assert c._parse_order_type("stop_limit") == OrderType.STOP_LIMIT
        assert c._parse_order_type("trailing_stop") == OrderType.STOP
        assert c._parse_order_type("unknown") == OrderType.MARKET

    def test_parse_order_status_all(self):
        from brokers.alpaca import AlpacaConnector
        c = AlpacaConnector({"api_key": "k", "api_secret": "s"})
        assert c._parse_order_status("filled") == OrderStatus.FILLED
        assert c._parse_order_status("canceled") == OrderStatus.CANCELLED
        assert c._parse_order_status("rejected") == OrderStatus.REJECTED
        assert c._parse_order_status("new") == OrderStatus.OPEN
        assert c._parse_order_status("unknown_xyz") == OrderStatus.PENDING


# ═══════════════════════════════════════════════════════════════════════════════
# BinanceConnector
# ═══════════════════════════════════════════════════════════════════════════════

class TestBinanceConnector:
    def _make(self, connected=False):
        from brokers.binance import BinanceConnector
        c = BinanceConnector({"api_key": "key", "api_secret": "secret", "testnet": True})
        c.connected = connected
        c.session = MagicMock()
        return c

    def test_init_raises_without_credentials(self):
        from brokers.binance import BinanceConnector
        with pytest.raises(ValueError, match="api_key"):
            BinanceConnector({})

    def test_connect_success(self):
        from brokers.binance import BinanceConnector
        c = BinanceConnector({"api_key": "k", "api_secret": "s"})
        mock_session = MagicMock()
        mock_session.get.return_value = _mock_response({})
        with patch("requests.Session", return_value=mock_session):
            result = c.connect()
        assert result is True

    def test_connect_failure(self):
        from brokers.binance import BinanceConnector
        c = BinanceConnector({"api_key": "k", "api_secret": "s"})
        with patch("requests.Session", side_effect=RuntimeError("fail")):
            result = c.connect()
        assert result is False

    def test_disconnect_success(self):
        c = self._make(connected=True)
        assert c.disconnect() is True

    def test_disconnect_failure(self):
        c = self._make(connected=True)
        c.session.close.side_effect = RuntimeError("fail")
        assert c.disconnect() is False

    def test_place_order_not_connected(self):
        c = self._make(connected=False)
        assert c.place_order("BTCUSDT", OrderSide.BUY, quantity=0.001) is None

    def test_place_order_success(self):
        c = self._make(connected=True)
        c.session.post.return_value = _mock_response({
            "orderId": 12345, "symbol": "BTCUSDT", "side": "BUY",
            "type": "MARKET", "origQty": "0.001", "status": "FILLED",
            "executedQty": "0.001", "price": "50000",
            "transactTime": 1704067200000,
        })
        order = c.place_order("BTCUSDT", OrderSide.BUY, quantity=0.001)
        assert order is not None
        assert order.id == "12345"

    def test_place_order_limit(self):
        c = self._make(connected=True)
        c.session.post.return_value = _mock_response({
            "orderId": 12346, "symbol": "BTCUSDT", "side": "BUY",
            "type": "LIMIT", "origQty": "0.001", "status": "NEW",
            "executedQty": "0", "price": "45000",
            "transactTime": 1704067200000,
        })
        order = c.place_order("BTCUSDT", OrderSide.BUY, quantity=0.001,
                              order_type=OrderType.LIMIT, price=45000.0)
        assert order is not None

    def test_place_order_stop_limit(self):
        c = self._make(connected=True)
        c.session.post.return_value = _mock_response({
            "orderId": 12347, "symbol": "BTCUSDT", "side": "SELL",
            "type": "STOP_LOSS_LIMIT", "origQty": "0.001", "status": "NEW",
            "executedQty": "0", "price": "44000",
            "transactTime": 1704067200000,
        })
        order = c.place_order("BTCUSDT", OrderSide.SELL, quantity=0.001,
                              order_type=OrderType.STOP_LIMIT,
                              price=44000.0, stop_price=44500.0)
        assert order is not None

    def test_place_order_exception(self):
        c = self._make(connected=True)
        c.session.post.side_effect = RuntimeError("fail")
        assert c.place_order("BTCUSDT", OrderSide.BUY, quantity=0.001) is None

    def test_cancel_order_not_connected(self):
        c = self._make(connected=False)
        assert c.cancel_order("123") is False

    def test_cancel_order_no_symbol(self):
        c = self._make(connected=True)
        assert c.cancel_order("123") is False

    def test_cancel_order_success(self):
        c = self._make(connected=True)
        c.session.delete.return_value = _mock_response({})
        assert c.cancel_order("123", symbol="BTCUSDT") is True

    def test_cancel_order_exception(self):
        c = self._make(connected=True)
        c.session.delete.side_effect = RuntimeError("fail")
        assert c.cancel_order("123", symbol="BTCUSDT") is False

    def test_get_order_not_connected(self):
        c = self._make(connected=False)
        assert c.get_order("123") is None

    def test_get_order_no_symbol(self):
        c = self._make(connected=True)
        assert c.get_order("123") is None

    def test_generate_signature(self):
        c = self._make()
        params = {"symbol": "BTCUSDT", "timestamp": 1234567890}
        sig = c._generate_signature(params)
        assert isinstance(sig, str)
        assert len(sig) == 64  # HMAC-SHA256 hex


# ═══════════════════════════════════════════════════════════════════════════════
# ByBitConnector
# ═══════════════════════════════════════════════════════════════════════════════

class TestByBitConnector:
    def _make(self):
        mock_ccxt = MagicMock()
        mock_ccxt.connected = True
        with patch("brokers.ccxt_connector.CCXTConnector", return_value=mock_ccxt):
            from brokers.bybit_connector import ByBitConnector
            c = ByBitConnector({"api_key": "k", "api_secret": "s", "sandbox": True})
        c._ccxt = mock_ccxt
        return c

    def test_symbol_translation_to_bybit(self):
        c = self._make()
        assert c._to_bybit("XAUUSD") == "XAUUSDT"
        assert c._to_bybit("BTCUSD") == "BTCUSDT"
        assert c._to_bybit("UNKNOWN") == "UNKNOWN"

    def test_symbol_translation_from_bybit(self):
        c = self._make()
        assert c._from_bybit("XAUUSDT") == "XAUUSD"
        assert c._from_bybit("UNKNOWN") == "UNKNOWN"

    def test_connect_delegates_to_ccxt(self):
        c = self._make()
        c._ccxt.connected = True
        result = c.connect()
        c._ccxt.connect.assert_called_once()
        assert result is True

    def test_connect_failure(self):
        c = self._make()
        c._ccxt.connected = False
        result = c.connect()
        assert result is False

    def test_disconnect_delegates(self):
        c = self._make()
        c._ccxt.disconnect.return_value = True
        assert c.disconnect() is True
        assert c.connected is False

    def test_get_account_info_delegates(self):
        c = self._make()
        from brokers.base import AccountInfo
        mock_info = AccountInfo(balance=1000.0, equity=1000.0,
                                margin_used=0.0, margin_available=1000.0,
                                positions_count=0)
        c._ccxt.get_account_info.return_value = mock_info
        result = c.get_account_info()
        assert result.balance == 1000.0

    def test_get_account_info_returns_empty_on_none(self):
        c = self._make()
        c._ccxt.get_account_info.return_value = None
        result = c.get_account_info()
        assert result.balance == 0.0

    def test_get_market_data_translates_symbol(self):
        c = self._make()
        c._ccxt.get_market_data.return_value = []
        c.get_market_data("XAUUSD", "1h", 100)
        c._ccxt.get_market_data.assert_called_once_with("XAUUSDT", "1h", 100)

    def test_place_order_translates_symbol(self):
        c = self._make()
        from brokers.base import Order, OrderStatus
        mock_order = MagicMock(spec=Order)
        mock_order.symbol = "XAUUSDT"
        c._ccxt.place_order.return_value = mock_order
        c.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.01)
        c._ccxt.place_order.assert_called_once()
        call_kwargs = c._ccxt.place_order.call_args[1]
        assert call_kwargs["symbol"] == "XAUUSDT"

    def test_cancel_order_delegates(self):
        c = self._make()
        c._ccxt.cancel_order.return_value = True
        assert c.cancel_order("order-1") is True

    def test_get_order_delegates(self):
        c = self._make()
        c._ccxt.get_order.return_value = None
        assert c.get_order("order-1") is None

    def test_get_positions_translates_symbols(self):
        c = self._make()
        from brokers.base import Position
        pos = MagicMock(spec=Position)
        pos.symbol = "XAUUSDT"
        c._ccxt.get_positions.return_value = [pos]
        positions = c.get_positions()
        assert len(positions) == 1

    def test_close_position_translates_symbol(self):
        c = self._make()
        c._ccxt.close_position.return_value = True
        result = c.close_position("XAUUSD")
        c._ccxt.close_position.assert_called_once_with("XAUUSDT")
        assert result is True

    def test_close_position_handles_exception(self):
        c = self._make()
        c._ccxt.close_position.side_effect = RuntimeError("fail")
        result = c.close_position("XAUUSD")
        assert result is False

    def test_repr_sandbox(self):
        c = self._make()
        assert "SANDBOX" in repr(c)

    def test_custom_symbol_map(self):
        mock_ccxt = MagicMock()
        with patch("brokers.ccxt_connector.CCXTConnector", return_value=mock_ccxt):
            from brokers.bybit_connector import ByBitConnector
            c = ByBitConnector({
                "api_key": "k", "api_secret": "s",
                "symbol_map": {"CUSTOM": "CUSTOMUSDT"},
            })
        assert c._to_bybit("CUSTOM") == "CUSTOMUSDT"

    def test_get_current_price_delegates(self):
        c = self._make()
        c._ccxt.get_current_price.return_value = 2350.0
        result = c.get_current_price("XAUUSD")
        c._ccxt.get_current_price.assert_called_once_with("XAUUSDT")
        assert result == 2350.0

    def test_get_exchange_info_delegates(self):
        c = self._make()
        c._ccxt.get_exchange_info.return_value = {"symbol": "XAUUSDT"}
        result = c.get_exchange_info()
        assert result["symbol"] == "XAUUSDT"
