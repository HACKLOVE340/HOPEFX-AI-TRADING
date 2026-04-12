# HOPEFX-AI-TRADING
# Tests for brokers/bybit_connector.py
"""
Full branch coverage for ByBitConnector / BybitConnector.
All exchange communication is delegated to CCXTConnector — mocked here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from brokers.base import AccountInfo, Order, OrderSide, OrderStatus, OrderType, Position
from brokers.bybit_connector import ByBitConnector, BybitConnector, _DEFAULT_SYMBOL_MAP


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_connector(connected=True, **config_overrides):
    """Return a ByBitConnector with a mocked CCXTConnector."""
    config = {
        "api_key": "test_key",  # pragma: allowlist secret
        "api_secret": "test_secret",  # pragma: allowlist secret
        "sandbox": True,
        **config_overrides,
    }
    with MagicMock():
        pass

    mock_ccxt = MagicMock()
    mock_ccxt.connected = connected

    connector = ByBitConnector.__new__(ByBitConnector)
    # Manually initialise without calling __init__ to avoid CCXTConnector import
    connector.config = config
    connector.connected = connected
    connector.name = "ByBit"
    connector._symbol_map = dict(_DEFAULT_SYMBOL_MAP)
    connector._symbol_map_rev = {v: k for k, v in connector._symbol_map.items()}
    connector._ccxt = mock_ccxt
    connector.rate_limiter = MagicMock()
    return connector, mock_ccxt


def _make_order(symbol="XAUUSDT", side=OrderSide.BUY):
    return Order(
        id="ord1",
        symbol=symbol,
        side=side,
        type=OrderType.MARKET,
        quantity=0.01,
        status=OrderStatus.FILLED,
        filled_quantity=0.01,
        average_price=2000.0,
    )


def _make_position(symbol="XAUUSDT"):
    return Position(
        symbol=symbol,
        side="LONG",
        quantity=0.01,
        entry_price=2000.0,
        current_price=2010.0,
        unrealized_pnl=0.1,
    )


# ── Symbol translation ────────────────────────────────────────────────────────


class TestSymbolTranslation:
    def test_to_bybit_xauusd(self):
        c, _ = _make_connector()
        assert c._to_bybit("XAUUSD") == "XAUUSDT"

    def test_to_bybit_xau_slash_usd(self):
        c, _ = _make_connector()
        assert c._to_bybit("XAU/USD") == "XAUUSDT"

    def test_to_bybit_btcusd(self):
        c, _ = _make_connector()
        assert c._to_bybit("BTCUSD") == "BTCUSDT"

    def test_to_bybit_ethusd(self):
        c, _ = _make_connector()
        assert c._to_bybit("ETHUSD") == "ETHUSDT"

    def test_to_bybit_solusd(self):
        c, _ = _make_connector()
        assert c._to_bybit("SOLUSD") == "SOLUSDT"

    def test_to_bybit_unknown_passthrough(self):
        c, _ = _make_connector()
        assert c._to_bybit("UNKNOWN") == "UNKNOWN"

    def test_from_bybit_xauusdt(self):
        c, _ = _make_connector()
        # XAUUSDT → XAUUSD (last entry in map wins)
        result = c._from_bybit("XAUUSDT")
        assert result == "XAUUSD"

    def test_from_bybit_btcusdt(self):
        c, _ = _make_connector()
        assert c._from_bybit("BTCUSDT") == "BTCUSD"

    def test_from_bybit_unknown_passthrough(self):
        c, _ = _make_connector()
        assert c._from_bybit("UNKNOWN") == "UNKNOWN"

    def test_custom_symbol_map_override(self):
        """Custom symbol_map in config is merged with defaults via __init__."""
        mock_ccxt = MagicMock()
        mock_ccxt.connected = False
        with MagicMock() as _:
            pass
        config = {
            "api_key": "k",
            "api_secret": "s",
            "sandbox": True,
            "symbol_map": {"CUSTOM": "CUSTOMUSDT"},
        }
        with pytest.MonkeyPatch().context() as mp:
            import brokers.bybit_connector as bbc

            mp.setattr(
                bbc,
                "CCXTConnector" if hasattr(bbc, "CCXTConnector") else "_ccxt_cls",
                MagicMock(return_value=mock_ccxt),
                raising=False,
            )
            # Patch the import inside __init__
            import sys

            fake_ccxt_mod = MagicMock()
            fake_ccxt_mod.CCXTConnector = MagicMock(return_value=mock_ccxt)
            with pytest.MonkeyPatch().context() as mp2:
                mp2.setitem(sys.modules, "brokers.ccxt_connector", fake_ccxt_mod)
                c = ByBitConnector(config)
        assert c._to_bybit("CUSTOM") == "CUSTOMUSDT"
        # Defaults still present
        assert c._to_bybit("XAUUSD") == "XAUUSDT"


# ── connect / disconnect ──────────────────────────────────────────────────────


class TestConnectDisconnect:
    def test_connect_success(self):
        c, mock_ccxt = _make_connector(connected=False)
        mock_ccxt.connect.return_value = True
        mock_ccxt.connected = True
        result = c.connect()
        assert result is True
        assert c.connected is True

    def test_connect_failure(self):
        c, mock_ccxt = _make_connector(connected=False)
        mock_ccxt.connect.return_value = False
        mock_ccxt.connected = False
        result = c.connect()
        assert result is False
        assert c.connected is False

    def test_disconnect(self):
        c, mock_ccxt = _make_connector(connected=True)
        mock_ccxt.disconnect.return_value = True
        result = c.disconnect()
        assert result is True
        assert c.connected is False


# ── get_account_info ──────────────────────────────────────────────────────────


class TestGetAccountInfo:
    def test_returns_ccxt_account_info(self):
        c, mock_ccxt = _make_connector()
        expected = AccountInfo(
            balance=5000.0,
            equity=5100.0,
            margin_used=100.0,
            margin_available=4900.0,
            positions_count=1,
        )
        mock_ccxt.get_account_info.return_value = expected
        result = c.get_account_info()
        assert result is expected

    def test_returns_zero_account_info_when_ccxt_returns_none(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.get_account_info.return_value = None
        result = c.get_account_info()
        assert isinstance(result, AccountInfo)
        assert result.balance == 0.0
        assert result.equity == 0.0
        assert result.positions_count == 0


# ── get_market_data ───────────────────────────────────────────────────────────


class TestGetMarketData:
    def test_translates_symbol_to_bybit(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.get_market_data.return_value = [{"open": 2000.0}]
        result = c.get_market_data("XAUUSD", "1h", 100)
        mock_ccxt.get_market_data.assert_called_once_with("XAUUSDT", "1h", 100)
        assert result == [{"open": 2000.0}]

    def test_get_current_price_translates_symbol(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.get_current_price.return_value = 2350.0
        price = c.get_current_price("XAUUSD")
        mock_ccxt.get_current_price.assert_called_once_with("XAUUSDT")
        assert price == pytest.approx(2350.0)


# ── place_order ───────────────────────────────────────────────────────────────


class TestPlaceOrder:
    def test_translates_symbol_and_back(self):
        c, mock_ccxt = _make_connector()
        returned_order = _make_order(symbol="XAUUSDT")
        mock_ccxt.place_order.return_value = returned_order
        order = c.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.01)
        # CCXT called with ByBit symbol
        mock_ccxt.place_order.assert_called_once_with(
            symbol="XAUUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
            price=None,
            stop_price=None,
        )
        # Symbol translated back in returned order
        assert order.symbol == "XAUUSD"

    def test_limit_order_passes_price(self):
        c, mock_ccxt = _make_connector()
        returned_order = _make_order(symbol="XAUUSDT")
        mock_ccxt.place_order.return_value = returned_order
        c.place_order("XAUUSD", OrderSide.BUY, OrderType.LIMIT, 0.01, price=2350.0)
        call_kwargs = mock_ccxt.place_order.call_args[1]
        assert call_kwargs["price"] == 2350.0

    def test_stop_order_passes_stop_price(self):
        c, mock_ccxt = _make_connector()
        returned_order = _make_order(symbol="XAUUSDT")
        mock_ccxt.place_order.return_value = returned_order
        c.place_order("XAUUSD", OrderSide.SELL, OrderType.STOP, 0.01, stop_price=2300.0)
        call_kwargs = mock_ccxt.place_order.call_args[1]
        assert call_kwargs["stop_price"] == 2300.0


# ── cancel_order / get_order ──────────────────────────────────────────────────


class TestCancelAndGetOrder:
    def test_cancel_order_delegates_to_ccxt(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.cancel_order.return_value = True
        assert c.cancel_order("ord1") is True
        mock_ccxt.cancel_order.assert_called_once_with("ord1")

    def test_cancel_all_orders_delegates(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.cancel_all_orders.return_value = True
        assert c.cancel_all_orders() is True

    def test_get_order_delegates(self):
        c, mock_ccxt = _make_connector()
        expected = _make_order()
        mock_ccxt.get_order.return_value = expected
        result = c.get_order("ord1")
        assert result is expected


# ── get_positions ─────────────────────────────────────────────────────────────


class TestGetPositions:
    def test_translates_position_symbols_back(self):
        c, mock_ccxt = _make_connector()
        pos = _make_position(symbol="XAUUSDT")
        mock_ccxt.get_positions.return_value = [pos]
        positions = c.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "XAUUSD"

    def test_empty_positions(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.get_positions.return_value = []
        assert c.get_positions() == []


# ── close_position ────────────────────────────────────────────────────────────


class TestClosePosition:
    def test_close_position_translates_symbol(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.close_position.return_value = True
        result = c.close_position("XAUUSD")
        mock_ccxt.close_position.assert_called_once_with("XAUUSDT")
        assert result is True

    def test_close_position_exception_returns_false(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.close_position.side_effect = RuntimeError("exchange error")
        result = c.close_position("XAUUSD")
        assert result is False

    def test_close_position_value_error_returns_false(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.close_position.side_effect = ValueError("bad symbol")
        result = c.close_position("XAUUSD")
        assert result is False


# ── get_exchange_info ─────────────────────────────────────────────────────────


class TestGetExchangeInfo:
    def test_delegates_to_ccxt(self):
        c, mock_ccxt = _make_connector()
        mock_ccxt.get_exchange_info.return_value = {"symbol": "XAUUSDT"}
        result = c.get_exchange_info()
        assert result == {"symbol": "XAUUSDT"}


# ── repr ──────────────────────────────────────────────────────────────────────


class TestRepr:
    def test_repr_sandbox(self):
        c, _ = _make_connector()
        r = repr(c)
        assert "SANDBOX" in r
        assert "connected=" in r

    def test_repr_live(self):
        c, _ = _make_connector(sandbox=False)
        c.config["sandbox"] = False
        r = repr(c)
        assert "LIVE" in r


# ── BybitConnector alias ──────────────────────────────────────────────────────


class TestBybitConnectorAlias:
    def test_alias_is_same_class(self):
        assert BybitConnector is ByBitConnector
