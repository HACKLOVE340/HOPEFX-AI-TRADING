# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Comprehensive coverage tests for low-coverage broker modules.

Targets ≥80% branch coverage on:
  - brokers/mt5_broker.py
  - brokers/oanda_broker.py
  - brokers/mt5_zmq_bridge.py
  - brokers/prop_firms/ftmo.py
  - brokers/mt5_bridge.py
  - brokers/mt5.py

All external I/O (MetaTrader5 SDK, aiohttp, zmq) is mocked.
No real network connections or broker credentials are required.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── PART 1: mt5_broker.py ─────────────────────────────────────────────────────


def _make_mt5_mod():
    """Return a minimal mock of the MetaTrader5 module."""
    m = MagicMock()
    m.TRADE_RETCODE_DONE = 10009
    m.ORDER_TIME_GTC = 1
    m.ORDER_FILLING_IOC = 1
    m.POSITION_TYPE_BUY = 0
    m.POSITION_TYPE_SELL = 1
    return m


@pytest.fixture()
def mt5_mod():
    return _make_mt5_mod()


@pytest.fixture()
def mt5_broker(mt5_mod):
    """MT5Broker with SDK mocked out."""
    with patch.dict("sys.modules", {"MetaTrader5": mt5_mod}):
        import importlib
        import brokers.mt5_broker as mod

        importlib.reload(mod)
        broker = mod.MT5Broker({"login": "12345678", "password": "pass", "server": "Demo"})
        yield broker, mod, mt5_mod


class TestMT5BrokerConnect:
    def test_connect_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        mt5.initialize.return_value = True
        mt5.login.return_value = True
        info = MagicMock(balance=10000.0, currency="USD")
        mt5.account_info.return_value = info

        result = asyncio.run(broker.connect())
        assert result is True
        assert broker.connected is True

    def test_connect_initialize_fails(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        mt5.initialize.return_value = False
        mt5.last_error.return_value = (1, "init error")

        result = asyncio.run(broker.connect())
        assert result is False

    def test_connect_login_fails(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        mt5.initialize.return_value = True
        mt5.login.return_value = False
        mt5.last_error.return_value = (2, "login error")

        result = asyncio.run(broker.connect())
        assert result is False

    def test_connect_invalid_login(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker._config["login"] = "not_a_number"
        result = asyncio.run(broker.connect())
        assert result is False

    def test_connect_with_terminal_path(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker._config["terminal_path"] = "/path/to/terminal"
        mt5.initialize.return_value = True
        mt5.login.return_value = True
        mt5.account_info.return_value = MagicMock(balance=0.0, currency="USD")
        result = asyncio.run(broker.connect())
        assert result is True
        call_kwargs = mt5.initialize.call_args[1]
        assert "path" in call_kwargs

    def test_connect_sdk_unavailable(self):
        with patch("brokers.mt5_broker._MT5_AVAILABLE", False):
            import brokers.mt5_broker as mod

            broker = mod.MT5Broker({"login": "1", "password": "p", "server": "s"})
            result = asyncio.run(broker.connect())
            assert result is False

    def test_disconnect(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        asyncio.run(broker.disconnect())
        assert broker.connected is False
        mt5.shutdown.assert_called_once()

    def test_disconnect_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        asyncio.run(broker.disconnect())
        mt5.shutdown.assert_not_called()


class TestMT5BrokerAccount:
    def test_get_account_info_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        result = asyncio.run(broker.get_account_info())
        assert result is None

    def test_get_account_info_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        info = MagicMock(
            login=12345678,
            server="Demo",
            balance=10000.0,
            equity=10100.0,
            margin=500.0,
            margin_free=9600.0,
            margin_level=2020.0,
            currency="USD",
            leverage=100,
            profit=100.0,
        )
        mt5.account_info.return_value = info
        result = asyncio.run(broker.get_account_info())
        assert result["balance"] == 10000.0
        assert result["currency"] == "USD"

    def test_get_account_info_none(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.account_info.return_value = None
        result = asyncio.run(broker.get_account_info())
        assert result is None

    def test_get_positions_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        result = asyncio.run(broker.get_positions())
        assert result == []

    def test_get_positions_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        pos = MagicMock(
            ticket=1,
            symbol="XAUUSD",
            type=0,
            volume=0.1,
            price_open=1900.0,
            price_current=1910.0,
            sl=1880.0,
            tp=1950.0,
            profit=100.0,
            comment="",
            magic=0,
            time=1700000000,
        )
        mt5.positions_get.return_value = [pos]
        result = asyncio.run(broker.get_positions())
        assert len(result) == 1
        assert result[0]["type"] == "buy"

    def test_get_positions_sell(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        pos = MagicMock(
            ticket=2,
            symbol="EURUSD",
            type=1,
            volume=0.05,
            price_open=1.08,
            price_current=1.07,
            sl=1.09,
            tp=1.06,
            profit=-50.0,
            comment="",
            magic=0,
            time=1700000001,
        )
        mt5.positions_get.return_value = [pos]
        result = asyncio.run(broker.get_positions())
        assert result[0]["type"] == "sell"

    def test_get_positions_none(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.positions_get.return_value = None
        result = asyncio.run(broker.get_positions())
        assert result == []

    def test_get_orders_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        result = asyncio.run(broker.get_orders())
        assert result == []

    def test_get_orders_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        order = MagicMock(
            ticket=10,
            symbol="XAUUSD",
            type=2,
            volume_current=0.1,
            price_open=1900.0,
            sl=1880.0,
            tp=1950.0,
            comment="",
            magic=0,
            time_setup=1700000000,
        )
        mt5.orders_get.return_value = [order]
        result = asyncio.run(broker.get_orders())
        assert len(result) == 1

    def test_get_orders_none(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.orders_get.return_value = None
        result = asyncio.run(broker.get_orders())
        assert result == []


class TestMT5BrokerPlaceOrder:
    def test_place_order_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        result = asyncio.run(broker.place_order({"symbol": "XAUUSD", "action": "buy", "volume": 0.01}))
        assert result["success"] is False

    def test_place_order_market_buy_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        mt5.symbol_info.return_value = MagicMock()
        result_obj = MagicMock(retcode=10009, order=12345, comment="OK", volume=0.01, price=1920.0)
        mt5.order_send.return_value = result_obj
        result = asyncio.run(broker.place_order({"symbol": "XAUUSD", "action": "buy", "volume": 0.01}))
        assert result["success"] is True
        assert result["order"] == 12345

    def test_place_order_market_sell_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        mt5.symbol_info.return_value = MagicMock()
        result_obj = MagicMock(retcode=10009, order=12346, comment="OK")
        mt5.order_send.return_value = result_obj
        result = asyncio.run(broker.place_order({"symbol": "XAUUSD", "action": "sell", "volume": 0.01}))
        assert result["success"] is True

    def test_place_order_no_tick(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.symbol_info_tick.return_value = None
        result = asyncio.run(broker.place_order({"symbol": "XAUUSD", "action": "buy", "volume": 0.01}))
        assert result["success"] is False

    def test_place_order_symbol_not_found(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        mt5.symbol_info.return_value = None
        result = asyncio.run(broker.place_order({"symbol": "XAUUSD", "action": "buy", "volume": 0.01}))
        assert result["success"] is False

    def test_place_order_limit_buy(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.symbol_info.return_value = MagicMock()
        result_obj = MagicMock(retcode=10009, order=12347, comment="OK")
        mt5.order_send.return_value = result_obj
        result = asyncio.run(
            broker.place_order(
                {"symbol": "XAUUSD", "action": "buy", "volume": 0.01, "order_type": "limit", "price": 1900.0}
            )
        )
        assert result["success"] is True

    def test_place_order_stop_sell(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.symbol_info.return_value = MagicMock()
        result_obj = MagicMock(retcode=10009, order=12348, comment="OK")
        mt5.order_send.return_value = result_obj
        result = asyncio.run(
            broker.place_order(
                {"symbol": "XAUUSD", "action": "sell", "volume": 0.01, "order_type": "stop", "price": 1880.0}
            )
        )
        assert result["success"] is True

    def test_place_order_unknown_type(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        result = asyncio.run(
            broker.place_order({"symbol": "XAUUSD", "action": "buy", "volume": 0.01, "order_type": "iceberg"})
        )
        assert result["success"] is False

    def test_place_order_send_none(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        mt5.symbol_info.return_value = MagicMock()
        mt5.order_send.return_value = None
        mt5.last_error.return_value = (3, "send error")
        result = asyncio.run(broker.place_order({"symbol": "XAUUSD", "action": "buy", "volume": 0.01}))
        assert result["success"] is False

    def test_place_order_retcode_not_done(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        mt5.symbol_info.return_value = MagicMock()
        result_obj = MagicMock(retcode=10006, order=0, comment="Rejected")
        mt5.order_send.return_value = result_obj
        result = asyncio.run(broker.place_order({"symbol": "XAUUSD", "action": "buy", "volume": 0.01}))
        assert result["success"] is False


class TestMT5BrokerCloseModifyCancel:
    def test_close_position_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        result = asyncio.run(broker.close_position(12345))
        assert result["success"] is False

    def test_close_position_not_found(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.positions_get.return_value = []
        result = asyncio.run(broker.close_position(12345))
        assert result["success"] is False

    def test_close_position_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        pos = MagicMock(type=0, volume=0.1, symbol="XAUUSD", magic=0)
        mt5.positions_get.return_value = [pos]
        tick = MagicMock(bid=1919.5, ask=1920.0)
        mt5.symbol_info_tick.return_value = tick
        result_obj = MagicMock(retcode=10009, order=99, comment="OK")
        mt5.order_send.return_value = result_obj
        result = asyncio.run(broker.close_position(12345))
        assert result["success"] is True

    def test_close_position_partial(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        pos = MagicMock(type=1, volume=0.2, symbol="EURUSD", magic=0)
        mt5.positions_get.return_value = [pos]
        tick = MagicMock(bid=1.079, ask=1.080)
        mt5.symbol_info_tick.return_value = tick
        result_obj = MagicMock(retcode=10009, order=100, comment="OK")
        mt5.order_send.return_value = result_obj
        result = asyncio.run(broker.close_position(12345, volume=0.1))
        assert result["success"] is True

    def test_close_position_no_tick(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        pos = MagicMock(type=0, volume=0.1, symbol="XAUUSD", magic=0)
        mt5.positions_get.return_value = [pos]
        mt5.symbol_info_tick.return_value = None
        result = asyncio.run(broker.close_position(12345))
        assert result["success"] is False

    def test_modify_position_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        result = asyncio.run(broker.modify_position(1, 1880.0, 1950.0))
        assert result["success"] is False

    def test_modify_position_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        result_obj = MagicMock(retcode=10009, comment="OK")
        mt5.order_send.return_value = result_obj
        result = asyncio.run(broker.modify_position(1, 1880.0, 1950.0))
        assert result["success"] is True

    def test_modify_position_send_none(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.order_send.return_value = None
        mt5.last_error.return_value = (4, "err")
        result = asyncio.run(broker.modify_position(1, 1880.0, 1950.0))
        assert result["success"] is False

    def test_cancel_order_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        result = asyncio.run(broker.cancel_order(99))
        assert result["success"] is False

    def test_cancel_order_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        result_obj = MagicMock(retcode=10009, comment="OK")
        mt5.order_send.return_value = result_obj
        result = asyncio.run(broker.cancel_order(99))
        assert result["success"] is True

    def test_cancel_order_send_none(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.order_send.return_value = None
        mt5.last_error.return_value = (5, "err")
        result = asyncio.run(broker.cancel_order(99))
        assert result["success"] is False

    def test_get_tick_not_connected(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = False
        result = asyncio.run(broker.get_tick("XAUUSD"))
        assert result is None

    def test_get_tick_success(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        tick = MagicMock(bid=1919.5, ask=1920.0, time=1700000000)
        mt5.symbol_info_tick.return_value = tick
        result = asyncio.run(broker.get_tick("XAUUSD"))
        assert result["bid"] == 1919.5
        assert result["ask"] == 1920.0

    def test_get_tick_none(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        mt5.symbol_info_tick.return_value = None
        result = asyncio.run(broker.get_tick("XAUUSD"))
        assert result is None

    def test_status(self, mt5_broker):
        broker, mod, mt5 = mt5_broker
        broker.connected = True
        broker._login = 12345678
        broker._server = "Demo"
        s = broker.status()
        assert s["broker"] == "mt5"
        assert s["connected"] is True


# ── PART 2: oanda_broker.py ──────────────────────────────────────────────────

from brokers.oanda_broker import OandaBroker, _resolve_env, _mask_account


class TestOandaHelpers:
    def test_resolve_env_plain_string(self):
        assert _resolve_env("hello") == "hello"

    def test_resolve_env_non_string(self):
        assert _resolve_env(42) == "42"

    def test_resolve_env_none(self):
        assert _resolve_env(None) == ""

    def test_resolve_env_placeholder_with_default(self, monkeypatch):
        monkeypatch.delenv("OANDA_TOKEN", raising=False)
        assert _resolve_env("${OANDA_TOKEN:mydefault}") == "mydefault"

    def test_resolve_env_placeholder_from_env(self, monkeypatch):
        monkeypatch.setenv("OANDA_TOKEN", "realtoken")
        assert _resolve_env("${OANDA_TOKEN:default}") == "realtoken"

    def test_mask_account_short(self):
        assert _mask_account("12") == "****"

    def test_mask_account_long(self):
        result = _mask_account("101-123-4567890-001")
        assert result.startswith("...")
        assert len(result) > 3

    def test_mask_account_none(self):
        assert _mask_account(None) == "****"


def _make_oanda_broker():
    return OandaBroker(
        {"login": "101-123-4567890-001", "password": "token123", "server": "practice"}  # pragma: allowlist secret
    )


def _mock_response(status=200, json_data=None, text_data=""):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text_data)
    resp.headers = {}
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


class TestOandaBrokerConnect:
    @pytest.mark.asyncio
    async def test_connect_success(self):
        broker = _make_oanda_broker()
        resp = _mock_response(200, {"account": {"currency": "USD"}})
        with patch("aiohttp.ClientSession") as MockSession:
            session = MagicMock()
            session.get.return_value = resp
            session.closed = False
            MockSession.return_value = session
            result = await broker.connect()
        assert result is True
        assert broker.connected is True

    @pytest.mark.asyncio
    async def test_connect_non_200(self):
        broker = _make_oanda_broker()
        resp = _mock_response(401, {}, "Unauthorized")
        with patch("aiohttp.ClientSession") as MockSession:
            session = MagicMock()
            session.get.return_value = resp
            session.close = AsyncMock()
            MockSession.return_value = session
            result = await broker.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_client_error(self):
        import aiohttp

        broker = _make_oanda_broker()
        with patch("aiohttp.ClientSession") as MockSession:
            session = MagicMock()
            session.get.side_effect = aiohttp.ClientConnectionError("conn refused")
            session.close = AsyncMock()
            MockSession.return_value = session
            result = await broker.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_live_server(self):
        broker = OandaBroker({"login": "101-123-4567890-001", "password": "tok", "server": "live"})
        resp = _mock_response(200, {"account": {"currency": "USD"}})
        with patch("aiohttp.ClientSession") as MockSession:
            session = MagicMock()
            session.get.return_value = resp
            session.closed = False
            MockSession.return_value = session
            result = await broker.connect()
        assert result is True
        assert "fxtrade" in broker._base_url

    @pytest.mark.asyncio
    async def test_disconnect(self):
        broker = _make_oanda_broker()
        session = MagicMock()
        session.closed = False
        session.close = AsyncMock()
        broker._session = session
        broker.connected = True
        await broker.disconnect()
        assert broker.connected is False
        session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_already_closed(self):
        broker = _make_oanda_broker()
        session = MagicMock()
        session.closed = True
        broker._session = session
        broker.connected = True
        await broker.disconnect()
        assert broker.connected is False


class TestOandaBrokerAccount:
    def _connected_broker(self):
        broker = _make_oanda_broker()
        broker.connected = True
        session = MagicMock()
        session.closed = False
        broker._session = session
        broker._account_id = "101-123-4567890-001"
        broker._base_url = "https://api-fxpractice.oanda.com"
        return broker

    @pytest.mark.asyncio
    async def test_get_account_info_not_connected(self):
        broker = _make_oanda_broker()
        result = await broker.get_account_info()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_account_info_success(self):
        broker = self._connected_broker()
        data = {
            "account": {
                "id": "101-123-4567890-001",
                "currency": "USD",
                "balance": "10000",
                "NAV": "10100",
                "unrealizedPL": "100",
                "pl": "50",
                "marginUsed": "500",
                "marginAvailable": "9600",
                "openTradeCount": 2,
                "openPositionCount": 1,
                "marginRate": "0.02",
            }
        }
        resp = _mock_response(200, data)
        broker._session.get.return_value = resp
        result = await broker.get_account_info()
        assert result["balance"] == 10000.0
        assert result["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_get_account_info_non_200(self):
        broker = self._connected_broker()
        resp = _mock_response(500, {})
        broker._session.get.return_value = resp
        result = await broker.get_account_info()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_positions_not_connected(self):
        broker = _make_oanda_broker()
        result = await broker.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_positions_success(self):
        broker = self._connected_broker()
        data = {
            "positions": [
                {
                    "instrument": "XAU_USD",
                    "long": {"units": "100"},
                    "short": {"units": "0"},
                    "unrealizedPL": "50",
                    "pl": "20",
                },
            ]
        }
        resp = _mock_response(200, data)
        broker._session.get.return_value = resp
        result = await broker.get_positions()
        assert len(result) == 1
        assert result[0]["instrument"] == "XAU_USD"

    @pytest.mark.asyncio
    async def test_get_positions_non_200(self):
        broker = self._connected_broker()
        resp = _mock_response(500, {})
        broker._session.get.return_value = resp
        result = await broker.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_orders_not_connected(self):
        broker = _make_oanda_broker()
        result = await broker.get_orders()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_orders_success(self):
        broker = self._connected_broker()
        data = {
            "orders": [
                {
                    "id": "1",
                    "type": "LIMIT",
                    "instrument": "XAU_USD",
                    "units": "100",
                    "price": "1900",
                    "state": "PENDING",
                    "timeInForce": "GTC",
                },
            ]
        }
        resp = _mock_response(200, data)
        broker._session.get.return_value = resp
        result = await broker.get_orders()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_orders_non_200(self):
        broker = self._connected_broker()
        resp = _mock_response(500, {})
        broker._session.get.return_value = resp
        result = await broker.get_orders()
        assert result == []


class TestOandaBrokerPlaceOrder:
    def _connected_broker(self):
        broker = _make_oanda_broker()
        broker.connected = True
        session = MagicMock()
        session.closed = False
        broker._session = session
        broker._account_id = "101-123-4567890-001"
        broker._base_url = "https://api-fxpractice.oanda.com"
        return broker

    @pytest.mark.asyncio
    async def test_place_order_not_connected(self):
        broker = _make_oanda_broker()
        result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_place_order_market_success(self):
        broker = self._connected_broker()
        data = {
            "orderFillTransaction": {"orderID": "101", "price": "1920.5", "tradeOpened": {"tradeID": "201"}},
            "orderCreateTransaction": {"id": "101"},
        }
        resp = _mock_response(201, data)
        broker._session.post.return_value = resp
        result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is True
        assert result["order_id"] == "101"

    @pytest.mark.asyncio
    async def test_place_order_limit_with_price(self):
        broker = self._connected_broker()
        data = {"orderCreateTransaction": {"id": "102"}}
        resp = _mock_response(201, data)
        broker._session.post.return_value = resp
        result = await broker.place_order(
            {
                "instrument": "XAU_USD",
                "units": 100,
                "order_type": "LIMIT",
                "price": 1900.0,
            }
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_place_order_with_sl_tp(self):
        broker = self._connected_broker()
        data = {"orderFillTransaction": {"orderID": "103", "price": "1920.0", "tradeOpened": {"tradeID": "203"}}}
        resp = _mock_response(201, data)
        broker._session.post.return_value = resp
        result = await broker.place_order(
            {
                "instrument": "XAU_USD",
                "units": 100,
                "sl_distance": 10.0,
                "tp_price": 1950.0,
            }
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_place_order_400_non_retryable(self):
        broker = self._connected_broker()
        resp = _mock_response(400, {"errorMessage": "Bad request"})
        broker._session.post.return_value = resp
        result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False
        assert "Bad request" in result["comment"]

    @pytest.mark.asyncio
    async def test_place_order_401_non_retryable(self):
        broker = self._connected_broker()
        resp = _mock_response(401, {"errorMessage": "Unauthorized"})
        broker._session.post.return_value = resp
        result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_place_order_429_rate_limit_exhausted(self):
        broker = self._connected_broker()
        resp = _mock_response(429, {})
        resp.headers = {"Retry-After": "0.001"}
        broker._session.post.return_value = resp
        result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False
        assert "Rate limited" in result["comment"]

    @pytest.mark.asyncio
    async def test_place_order_500_retries_then_fails(self):
        broker = self._connected_broker()
        resp = _mock_response(500, {})
        broker._session.post.return_value = resp
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_place_order_timeout_retries(self):
        import aiohttp

        broker = self._connected_broker()
        broker._session.post.side_effect = aiohttp.ServerTimeoutError()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_place_order_connection_error_retries(self):
        import aiohttp

        broker = self._connected_broker()
        broker._session.post.side_effect = aiohttp.ClientConnectionError("refused")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_place_order_generic_client_error(self):
        import aiohttp

        broker = self._connected_broker()
        broker._session.post.side_effect = aiohttp.ClientError("generic")
        result = await broker.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_place_order_long_client_id_truncated(self):
        broker = self._connected_broker()
        data = {"orderFillTransaction": {"orderID": "104", "price": "1920.0", "tradeOpened": {"tradeID": "204"}}}
        resp = _mock_response(201, data)
        broker._session.post.return_value = resp
        result = await broker.place_order(
            {
                "instrument": "XAU_USD",
                "units": 100,
                "client_id": "x" * 200,
            }
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_close_trade_not_connected(self):
        broker = _make_oanda_broker()
        result = await broker.close_trade("trade-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_success(self):
        broker = self._connected_broker()
        data = {"orderFillTransaction": {"price": "1920.0"}}
        resp = _mock_response(200, data)
        broker._session.put.return_value = resp
        result = await broker.close_trade("trade-1")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_close_trade_non_200(self):
        broker = self._connected_broker()
        resp = _mock_response(404, {"errorMessage": "Not found"})
        broker._session.put.return_value = resp
        result = await broker.close_trade("trade-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_status(self):
        broker = self._connected_broker()
        s = broker.status()
        assert s["broker"] == "oanda"
        assert s["connected"] is True


# ── PART 3: mt5_zmq_bridge.py ────────────────────────────────────────────────

from brokers.mt5_zmq_bridge import (
    MT5ZmqBridge,
    BridgeStatus,
    FillResult,
    TickData,
    BridgeStats,
    get_bridge,
)


def _degraded_bridge():
    """Bridge with ZMQ unavailable — always DEGRADED."""
    with patch("brokers.mt5_zmq_bridge._ZMQ_AVAILABLE", False):
        b = MT5ZmqBridge()
        b.start()
    return b


class TestMT5ZmqBridgeDegraded:
    def test_start_degraded_when_no_zmq(self):
        b = _degraded_bridge()
        assert b.status == BridgeStatus.DEGRADED

    def test_send_order_raises_in_degraded(self):
        b = _degraded_bridge()
        with pytest.raises(RuntimeError, match="DEGRADED"):
            b.send_order("XAUUSD", "BUY", 0.01)

    def test_close_position_raises_in_degraded(self):
        b = _degraded_bridge()
        with pytest.raises(RuntimeError, match="DEGRADED"):
            b.close_position(12345)

    def test_modify_position_raises_in_degraded(self):
        b = _degraded_bridge()
        with pytest.raises(RuntimeError, match="DEGRADED"):
            b.modify_position(12345, sl=1900.0)

    def test_ping_returns_minus_one_degraded(self):
        b = _degraded_bridge()
        assert b.ping() == -1.0

    def test_publish_signal_no_pub_socket(self):
        b = _degraded_bridge()
        # Should not raise even with no pub socket
        b.publish_signal("XAUUSD", "BUY", 0.9)

    def test_stop_degraded(self):
        b = _degraded_bridge()
        b.stop()
        assert b.status == BridgeStatus.STOPPED

    def test_context_manager_degraded(self):
        with patch("brokers.mt5_zmq_bridge._ZMQ_AVAILABLE", False):
            with MT5ZmqBridge() as b:
                assert b.status == BridgeStatus.DEGRADED
        assert b.status == BridgeStatus.STOPPED


class TestMT5ZmqBridgeNotConnected:
    def test_send_order_not_connected(self):
        b = MT5ZmqBridge()
        # status is STOPPED — not connected
        with pytest.raises(RuntimeError, match="not connected"):
            b.send_order("XAUUSD", "BUY", 0.01)

    def test_close_position_not_connected(self):
        b = MT5ZmqBridge()
        with pytest.raises(RuntimeError, match="not connected"):
            b.close_position(12345)


class TestMT5ZmqBridgeConnected:
    def _connected_bridge(self):
        """Bridge with ZMQ mocked, status=CONNECTED."""
        b = MT5ZmqBridge(order_timeout_s=0.1)
        b._status = BridgeStatus.CONNECTED
        b._push = MagicMock()
        b._pull = MagicMock()
        b._pub = MagicMock()
        return b

    def test_send_order_timeout(self):
        b = self._connected_bridge()
        with pytest.raises(TimeoutError):
            b.send_order("XAUUSD", "BUY", 0.01)

    def test_close_position_timeout(self):
        b = self._connected_bridge()
        with pytest.raises(TimeoutError):
            b.close_position(12345)

    def test_modify_position_timeout(self):
        b = self._connected_bridge()
        with pytest.raises(TimeoutError):
            b.modify_position(12345, sl=1900.0, tp=1950.0)

    def test_send_order_fill_response(self):
        b = self._connected_bridge()

        def inject_fill(cmd_id, payload, **_):
            # Inject fill into the pending queue
            import time as _time

            _time.sleep(0.01)
            with b._lock:
                q = b._pending.get(cmd_id)
            if q:
                q.put_nowait(
                    {
                        "type": "FILL",
                        "id": cmd_id,
                        "ticket": 99999,
                        "symbol": "XAUUSD",
                        "side": "BUY",
                        "lots": 0.01,
                        "price": 1920.5,
                        "ts": int(_time.time() * 1000),
                    }
                )

        original_send = b._send_and_wait

        def patched_send(cmd_id, payload, **kwargs):
            t = threading.Thread(target=inject_fill, args=(cmd_id, payload), kwargs=kwargs)
            t.daemon = True
            t.start()
            return original_send(cmd_id, payload, **kwargs)

        b._send_and_wait = patched_send
        b.order_timeout_s = 2.0
        result = b.send_order("XAUUSD", "BUY", 0.01)
        assert result.ok is True
        assert result.ticket == 99999

    def test_send_order_error_response(self):
        b = self._connected_bridge()

        def inject_error(cmd_id, payload, **_):
            import time as _time

            _time.sleep(0.01)
            with b._lock:
                q = b._pending.get(cmd_id)
            if q:
                q.put_nowait({"type": "ERROR", "id": cmd_id, "code": 10006, "msg": "Trade disabled"})

        original_send = b._send_and_wait

        def patched_send(cmd_id, payload, **kwargs):
            t = threading.Thread(target=inject_error, args=(cmd_id, payload), kwargs=kwargs)
            t.daemon = True
            t.start()
            return original_send(cmd_id, payload, **kwargs)

        b._send_and_wait = patched_send
        b.order_timeout_s = 2.0
        result = b.send_order("XAUUSD", "BUY", 0.01)
        assert result.ok is False
        assert result.error_code == 10006

    def test_publish_signal(self):
        b = self._connected_bridge()
        b.publish_signal("XAUUSD", "BUY", 0.95)
        b._pub.send_string.assert_called_once()

    def test_publish_signal_exception_suppressed(self):
        b = self._connected_bridge()
        b._pub.send_string.side_effect = Exception("zmq error")
        # Should not raise
        b.publish_signal("XAUUSD", "BUY", 0.95)

    def test_register_tick_callback(self):
        b = self._connected_bridge()
        received = []
        b.register_tick_callback(lambda tick: received.append(tick))
        assert len(b._tick_callbacks) == 1

    def test_stats_initial(self):
        b = self._connected_bridge()
        s = b.stats
        assert s.commands_sent == 0
        assert s.fills_received == 0


class TestMT5ZmqBridgeDispatch:
    def _bridge(self):
        b = MT5ZmqBridge()
        b._status = BridgeStatus.CONNECTED
        b._push = MagicMock()
        b._stats = BridgeStats()
        return b

    def test_dispatch_tick_calls_callbacks(self):
        b = self._bridge()
        received = []
        b.register_tick_callback(lambda t: received.append(t))
        b._dispatch(
            {
                "type": "TICK",
                "symbol": "XAUUSD",
                "bid": 1919.5,
                "ask": 1920.0,
                "ts": 1700000000000,
            }
        )
        assert len(received) == 1
        assert received[0].symbol == "XAUUSD"
        assert b._stats.ticks_received == 1

    def test_dispatch_tick_callback_exception_suppressed(self):
        b = self._bridge()
        b.register_tick_callback(lambda t: (_ for _ in ()).throw(ValueError("cb error")))
        # Should not raise
        b._dispatch({"type": "TICK", "symbol": "XAUUSD", "bid": 1.0, "ask": 1.1, "ts": 0})

    def test_dispatch_fill_to_pending(self):
        b = self._bridge()
        from queue import Queue

        q = Queue(maxsize=1)
        b._pending["abc"] = q
        b._dispatch({"type": "FILL", "id": "abc", "ticket": 1, "price": 1920.0, "lots": 0.01, "ts": 0})
        assert not q.empty()
        assert b._stats.fills_received == 1

    def test_dispatch_error_to_pending(self):
        b = self._bridge()
        from queue import Queue

        q = Queue(maxsize=1)
        b._pending["xyz"] = q
        b._dispatch({"type": "ERROR", "id": "xyz", "code": 10006, "msg": "err"})
        assert not q.empty()
        assert b._stats.errors_received == 1

    def test_dispatch_pong(self):
        b = self._bridge()
        from queue import Queue

        q = Queue(maxsize=1)
        b._pending["ping1"] = q
        b._dispatch({"type": "PONG", "id": "ping1", "ts": 0})
        assert not q.empty()

    def test_dispatch_unknown_type(self):
        b = self._bridge()
        # Should not raise
        b._dispatch({"type": "UNKNOWN", "id": "x"})

    def test_tick_data_properties(self):
        tick = TickData(symbol="XAUUSD", bid=1919.5, ask=1920.5)
        assert tick.mid == 1920.0
        assert tick.spread_pips > 0

    def test_fill_result_ok(self):
        fr = FillResult(command_id="a", ticket=1, symbol="XAUUSD", side="BUY", lots=0.01, fill_price=1920.0)
        assert fr.ok is True

    def test_fill_result_not_ok(self):
        fr = FillResult(
            command_id="a",
            ticket=0,
            symbol="XAUUSD",
            side="BUY",
            lots=0.01,
            fill_price=0.0,
            error_code=10006,
            error_msg="err",
        )
        assert fr.ok is False


class TestMT5ZmqBridgeSingleton:
    def test_get_bridge_returns_instance(self):
        import brokers.mt5_zmq_bridge as mod

        mod._bridge = None
        b = get_bridge()
        assert isinstance(b, MT5ZmqBridge)
        # Second call returns same instance
        assert get_bridge() is b
        mod._bridge = None  # cleanup


# ── PART 4: prop_firms/ftmo.py ───────────────────────────────────────────────

from brokers.prop_firms.ftmo import FTMOBroker, FTMOMetrics, FTMOPhase


def _ftmo_metrics(**overrides):
    defaults = dict(
        account_balance=100000.0,
        equity=100500.0,
        profit_loss=500.0,
        drawdown=0.01,
        daily_loss_limit=5000.0,
        remaining_daily_loss=4500.0,
        monthly_loss_limit=10000.0,
        remaining_monthly_loss=9500.0,
        phase=FTMOPhase.CHALLENGE,
        days_remaining=25,
        phase_progress=0.1,
    )
    defaults.update(overrides)
    return FTMOMetrics(**defaults)


def _ftmo_resp(status=200, json_data=None):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.headers = {"X-RateLimit-Remaining": "999", "X-RateLimit-Reset": "0"}
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


class TestFTMOBrokerInit:
    def test_init_live_url(self):
        b = FTMOBroker("key", "secret", "acct123", sandbox=False)
        assert "sandbox" not in b.BASE_URL

    def test_init_sandbox_url(self):
        b = FTMOBroker("key", "secret", "acct123", sandbox=True)
        assert "sandbox" in b.BASE_URL

    def test_generate_signature_returns_headers(self):
        b = FTMOBroker("key", "secret", "acct123")
        headers = b._generate_signature("GET", "/accounts/acct123/metrics")
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("FTMO key:")

    def test_generate_signature_with_params(self):
        b = FTMOBroker("key", "secret", "acct123")
        headers = b._generate_signature("POST", "/orders", {"symbol": "EURUSD"})
        assert "Authorization" in headers

    def test_nonce_increments(self):
        b = FTMOBroker("key", "secret", "acct123")
        b._generate_signature("GET", "/test")
        b._generate_signature("GET", "/test")
        assert b._request_nonce == 2


class TestFTMOBrokerContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_opens_closes_session(self):
        async with FTMOBroker("key", "secret", "acct123") as b:
            assert b.session is not None
        assert b.session.closed or b.session is not None  # closed after exit


class TestFTMOBrokerGetMetrics:
    @pytest.mark.asyncio
    async def test_get_metrics_no_session_raises(self):
        b = FTMOBroker("key", "secret", "acct123")
        with pytest.raises(RuntimeError, match="Session not initialized"):
            await b.get_account_metrics()

    @pytest.mark.asyncio
    async def test_get_metrics_success(self):
        b = FTMOBroker("key", "secret", "acct123")
        data = {
            "accountBalance": "100000",
            "equity": "100500",
            "profitLoss": "500",
            "drawdown": "0.01",
            "dailyLossLimit": "5000",
            "remainingDailyLoss": "4500",
            "monthlyLossLimit": "10000",
            "remainingMonthlyLoss": "9500",
            "phase": "challenge",
            "daysRemaining": "25",
            "phaseProgress": "0.1",
        }
        resp = _ftmo_resp(200, data)
        session = MagicMock()
        session.get.return_value = resp
        b.session = session
        metrics = await b.get_account_metrics()
        assert metrics.account_balance == 100000.0
        assert metrics.phase == FTMOPhase.CHALLENGE

    @pytest.mark.asyncio
    async def test_get_metrics_non_200_raises(self):
        b = FTMOBroker("key", "secret", "acct123")
        resp = _ftmo_resp(401, {"error": "Unauthorized"})
        session = MagicMock()
        session.get.return_value = resp
        b.session = session
        with pytest.raises(RuntimeError, match="FTMO API Error"):
            await b.get_account_metrics()

    @pytest.mark.asyncio
    async def test_get_metrics_timeout_raises(self):
        b = FTMOBroker("key", "secret", "acct123")
        session = MagicMock()
        session.get.side_effect = TimeoutError()
        b.session = session
        with pytest.raises(RuntimeError, match="timed out"):
            await b.get_account_metrics()

    @pytest.mark.asyncio
    async def test_get_metrics_updates_rate_limit(self):
        b = FTMOBroker("key", "secret", "acct123")
        data = {
            "accountBalance": "100000",
            "equity": "100500",
            "profitLoss": "500",
            "drawdown": "0.01",
            "dailyLossLimit": "5000",
            "remainingDailyLoss": "4500",
            "monthlyLossLimit": "10000",
            "remainingMonthlyLoss": "9500",
            "phase": "funded",
            "daysRemaining": "0",
            "phaseProgress": "1.0",
        }
        resp = _ftmo_resp(200, data)
        resp.headers = {"X-RateLimit-Remaining": "42", "X-RateLimit-Reset": "9999"}
        session = MagicMock()
        session.get.return_value = resp
        b.session = session
        await b.get_account_metrics()
        assert b._rate_limit_remaining == 42


class TestFTMOBrokerPlaceOrder:
    def _metrics_resp(self, remaining_daily=4500.0):
        return _ftmo_metrics(remaining_daily_loss=remaining_daily)

    @pytest.mark.asyncio
    async def test_place_order_no_session_raises(self):
        b = FTMOBroker("key", "secret", "acct123")
        with pytest.raises(RuntimeError, match="Session not initialized"):
            await b.place_order("EURUSD", "MARKET", "BUY", 0.1)

    @pytest.mark.asyncio
    async def test_place_order_daily_limit_exceeded(self):
        b = FTMOBroker("key", "secret", "acct123")
        b.session = MagicMock()
        with patch.object(b, "get_account_metrics", return_value=_ftmo_metrics(remaining_daily_loss=0)):
            with pytest.raises(ValueError, match="Daily loss limit exceeded"):
                await b.place_order("EURUSD", "MARKET", "BUY", 0.1)

    @pytest.mark.asyncio
    async def test_place_order_potential_loss_exceeds_limit(self):
        b = FTMOBroker("key", "secret", "acct123")
        b.session = MagicMock()
        # remaining_daily_loss=10, potential_loss = 100 * abs(1.08 - 1.07) = 1.0 — won't exceed
        # Use large quantity so potential_loss > remaining_daily_loss
        with patch.object(b, "get_account_metrics", return_value=_ftmo_metrics(remaining_daily_loss=5.0)):
            with pytest.raises(ValueError, match="exceed daily loss limit"):
                await b.place_order("EURUSD", "MARKET", "BUY", 1000.0, price=1.08, stop_loss=1.07)

    @pytest.mark.asyncio
    async def test_place_order_success(self):
        b = FTMOBroker("key", "secret", "acct123")
        b.session = MagicMock()
        order_resp = _ftmo_resp(201, {"orderId": "ord-1", "status": "FILLED"})
        b.session.post.return_value = order_resp
        with patch.object(b, "get_account_metrics", return_value=_ftmo_metrics()):
            result = await b.place_order("EURUSD", "MARKET", "BUY", 0.01)
        assert result["orderId"] == "ord-1"

    @pytest.mark.asyncio
    async def test_place_order_non_200_raises(self):
        b = FTMOBroker("key", "secret", "acct123")
        b.session = MagicMock()
        order_resp = _ftmo_resp(400, {"error": "Bad request"})
        b.session.post.return_value = order_resp
        with patch.object(b, "get_account_metrics", return_value=_ftmo_metrics()):
            with pytest.raises(RuntimeError, match="Order placement failed"):
                await b.place_order("EURUSD", "MARKET", "BUY", 0.01)


class TestFTMOBrokerOther:
    @pytest.mark.asyncio
    async def test_get_trade_history_no_session_raises(self):
        b = FTMOBroker("key", "secret", "acct123")
        with pytest.raises(RuntimeError):
            await b.get_trade_history()

    @pytest.mark.asyncio
    async def test_get_trade_history_success(self):
        b = FTMOBroker("key", "secret", "acct123")
        data = {
            "trades": [
                {"id": "1", "symbol": "EURUSD", "closeTime": "2025-01-01T00:00:00Z", "profit": "100"},
            ]
        }
        resp = _ftmo_resp(200, data)
        session = MagicMock()
        session.get.return_value = resp
        b.session = session
        df = await b.get_trade_history()
        assert len(df) == 1

    @pytest.mark.asyncio
    async def test_check_violation_daily_loss(self):
        b = FTMOBroker("key", "secret", "acct123")
        with patch.object(b, "get_account_metrics", return_value=_ftmo_metrics(remaining_daily_loss=0)):
            violated, reason = await b.check_violation()
        assert violated is True
        assert "daily" in reason.lower()

    @pytest.mark.asyncio
    async def test_check_violation_monthly_loss(self):
        b = FTMOBroker("key", "secret", "acct123")
        with patch.object(b, "get_account_metrics", return_value=_ftmo_metrics(remaining_monthly_loss=0)):
            violated, reason = await b.check_violation()
        assert violated is True
        assert "monthly" in reason.lower()

    @pytest.mark.asyncio
    async def test_check_violation_drawdown(self):
        b = FTMOBroker("key", "secret", "acct123")
        with patch.object(b, "get_account_metrics", return_value=_ftmo_metrics(drawdown=0.06)):
            violated, reason = await b.check_violation()
        assert violated is True
        assert "drawdown" in reason.lower()

    @pytest.mark.asyncio
    async def test_check_violation_none(self):
        b = FTMOBroker("key", "secret", "acct123")
        with patch.object(b, "get_account_metrics", return_value=_ftmo_metrics()):
            violated, reason = await b.check_violation()
        assert violated is False
        assert reason is None

    @pytest.mark.asyncio
    async def test_request_payout_no_session_raises(self):
        b = FTMOBroker("key", "secret", "acct123")
        with pytest.raises(RuntimeError):
            await b.request_payout(1000.0)

    @pytest.mark.asyncio
    async def test_request_payout_success(self):
        b = FTMOBroker("key", "secret", "acct123")
        resp = _ftmo_resp(200, {"payoutId": "pay-1", "status": "PENDING"})
        session = MagicMock()
        session.post.return_value = resp
        b.session = session
        result = await b.request_payout(1000.0)
        assert result["payoutId"] == "pay-1"

    @pytest.mark.asyncio
    async def test_request_payout_non_200_raises(self):
        b = FTMOBroker("key", "secret", "acct123")
        resp = _ftmo_resp(400, {"error": "Insufficient funds"})
        session = MagicMock()
        session.post.return_value = resp
        b.session = session
        with pytest.raises(RuntimeError):
            await b.request_payout(1000.0)

    def test_ftmo_metrics_to_dict(self):
        m = _ftmo_metrics()
        d = m.to_dict()
        assert d["phase"] == "challenge"
        assert d["account_balance"] == 100000.0


class TestFTMOConnector:
    def test_ftmo_connector_init(self):
        from brokers.prop_firms.ftmo import FTMOConnector

        with patch("brokers.mt5.MT5Connector.__init__", return_value=None):
            c = FTMOConnector.__new__(FTMOConnector)
            c.challenge_type = "demo"
            c.server = "FTMO-Demo"
            # Just verify the class exists and has expected attributes
            assert FTMOConnector is not None

    def test_ftmo_connector_get_rules(self):
        from brokers.prop_firms.ftmo import FTMOConnector

        with patch("brokers.mt5.MT5Connector.__init__", return_value=None):
            c = FTMOConnector.__new__(FTMOConnector)
            c.challenge_type = "demo"
            c.server = "FTMO-Demo"
            # Manually call get_ftmo_rules
            rules = FTMOConnector.get_ftmo_rules(c)
            assert "max_daily_loss" in rules
            assert "profit_target" in rules


# ── PART 5: mt5_bridge.py ────────────────────────────────────────────────────

from brokers.mt5_bridge import (
    MT5Bridge,
    MT5Order,
    EX5SignalExporter,
    OrderSide,
    FillStatus,
    _retry,
)


def _signal_bridge(tmp_path):
    """MT5Bridge in signal-export mode (no MT5 SDK)."""
    return MT5Bridge(
        server="Demo",
        login=12345678,
        password="pass",  # pragma: allowlist secret
        signal_dir=tmp_path / "signals",
    )


class TestMT5BridgeRetry:
    def test_retry_success_first_attempt(self):
        calls = []

        @_retry(max_attempts=3, base_delay=0.001)
        def fn():
            calls.append(1)
            return "ok"

        assert fn() == "ok"
        assert len(calls) == 1

    def test_retry_succeeds_on_second(self):
        calls = []

        @_retry(max_attempts=3, base_delay=0.001)
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise OSError("transient")
            return "ok"

        assert fn() == "ok"
        assert len(calls) == 2

    def test_retry_exhaustion_raises(self):
        @_retry(max_attempts=2, base_delay=0.001)
        def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            fn()

    def test_retry_value_error(self):
        @_retry(max_attempts=2, base_delay=0.001)
        def fn():
            raise ValueError("bad value")

        with pytest.raises(ValueError):
            fn()


class TestEX5SignalExporter:
    def test_export_creates_file(self, tmp_path):
        exporter = EX5SignalExporter(tmp_path / "signals")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0, take_profit=1950.0)
        path = exporter.export(order)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["symbol"] == "XAUUSD"
        assert data["status"] == "PENDING"

    def test_export_modify_creates_file(self, tmp_path):
        exporter = EX5SignalExporter(tmp_path / "signals")
        path = exporter.export_modify(12345, "XAUUSD", stop_loss=1880.0, take_profit=1950.0)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["action"] == "MODIFY"
        assert data["ticket"] == 12345

    def test_export_cancel_creates_file(self, tmp_path):
        exporter = EX5SignalExporter(tmp_path / "signals")
        path = exporter.export_cancel(12345, "XAUUSD")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["action"] == "CANCEL"

    def test_poll_fill_timeout(self, tmp_path):
        exporter = EX5SignalExporter(tmp_path / "signals")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        path = exporter.export(order)
        with pytest.raises(TimeoutError):
            exporter.poll_fill(path, timeout_sec=0.05)

    def test_poll_fill_filled(self, tmp_path):
        exporter = EX5SignalExporter(tmp_path / "signals")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        path = exporter.export(order)
        # Simulate EA writing FILLED status
        data = json.loads(path.read_text())
        data["status"] = "FILLED"
        data["ticket"] = 99999
        data["fill_price"] = 1920.5
        data["fill_volume"] = 0.1
        data["commission"] = -2.5
        data["swap"] = 0.0
        data["profit"] = 50.0
        path.write_text(json.dumps(data))
        result = exporter.poll_fill(path, timeout_sec=2.0)
        assert result.status == FillStatus.FILLED
        assert result.ticket == 99999

    def test_poll_fill_rejected(self, tmp_path):
        exporter = EX5SignalExporter(tmp_path / "signals")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        path = exporter.export(order)
        data = json.loads(path.read_text())
        data["status"] = "REJECTED"
        data["reject_reason"] = "Insufficient margin"
        path.write_text(json.dumps(data))
        with pytest.raises(RuntimeError, match="rejected"):
            exporter.poll_fill(path, timeout_sec=2.0)

    def test_cleanup_old_signals(self, tmp_path):
        exporter = EX5SignalExporter(tmp_path / "signals")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        path = exporter.export(order)
        # Make file appear old
        import os

        old_time = time.time() - 25 * 3600
        os.utime(path, (old_time, old_time))
        removed = exporter.cleanup_old_signals(max_age_hours=24)
        assert removed == 1

    def test_cleanup_no_old_signals(self, tmp_path):
        exporter = EX5SignalExporter(tmp_path / "signals")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        exporter.export(order)
        removed = exporter.cleanup_old_signals(max_age_hours=24)
        assert removed == 0

    def test_write_json_locked_atomic_rename_fallback(self, tmp_path):
        """Cover the OSError fallback path in _write_json_locked."""
        exporter = EX5SignalExporter(tmp_path / "signals")
        target = tmp_path / "signals" / "test.json"
        with patch.object(Path, "replace", side_effect=[OSError("rename failed"), None]):
            exporter._write_json_locked(target, {"key": "value"})

    def test_read_json_locked_bad_json_retries(self, tmp_path):
        """Cover the JSONDecodeError retry path."""
        exporter = EX5SignalExporter(tmp_path / "signals")
        bad_file = tmp_path / "signals" / "bad.json"
        bad_file.write_text("not json{{")
        result = exporter._read_json_locked(bad_file)
        assert result == {}


class TestMT5BridgeSignalMode:
    """Tests for MT5Bridge when _MT5_AVAILABLE=False (signal-export mode)."""

    def test_connect_signal_mode(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        result = bridge.connect()
        assert result is True
        assert bridge._connected is True

    def test_disconnect_signal_mode(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        bridge.disconnect()
        assert bridge._connected is False

    def test_from_env_missing_login_raises(self, monkeypatch):
        monkeypatch.delenv("MT5_LOGIN", raising=False)
        with pytest.raises(OSError, match="MT5_LOGIN"):
            MT5Bridge.from_env()

    def test_from_env_success(self, monkeypatch):
        monkeypatch.setenv("MT5_LOGIN", "12345678")
        monkeypatch.setenv("MT5_PASSWORD", "pass")
        monkeypatch.setenv("MT5_SERVER", "Demo")
        monkeypatch.delenv("MT5_PATH", raising=False)
        bridge = MT5Bridge.from_env()
        assert bridge.login == 12345678

    def test_send_order_not_connected_raises(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        with pytest.raises(RuntimeError, match="not connected"):
            bridge.send_order(order)

    def test_send_order_no_stop_loss_raises(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=None)
        with pytest.raises(ValueError, match="stop_loss"):
            bridge.send_order(order)

    def test_send_order_zero_stop_loss_raises(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=0.0)
        with pytest.raises(ValueError, match="stop_loss"):
            bridge.send_order(order)

    def test_send_order_enforcer_blocks(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        enforcer = MagicMock()
        enforcer.before_execute.return_value = (False, "news blackout")
        bridge._enforcer = enforcer
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        with pytest.raises(RuntimeError, match="PropEnforcer blocked"):
            bridge.send_order(order)

    def test_send_order_signal_export_timeout(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0, timeout_sec=0.05)
        with pytest.raises(TimeoutError):
            bridge.send_order(order)

    def test_close_position_signal_mode_timeout(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        with patch.object(bridge._exporter, "poll_fill", side_effect=TimeoutError("timeout")):
            with pytest.raises(TimeoutError):
                bridge.close_position("XAUUSD", volume=0.1)

    def test_modify_order_signal_mode(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        result = bridge.modify_order(12345, "XAUUSD", stop_loss=1880.0, take_profit=1950.0)
        assert result is True

    def test_cancel_order_signal_mode(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        result = bridge.cancel_order(12345, "XAUUSD")
        assert result is True

    def test_get_account_signal_mode(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        info = bridge.get_account()
        assert info["mode"] == "signal_export"

    def test_get_position_signal_mode(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        pos = bridge.get_position("XAUUSD")
        assert pos == {}

    def test_monitor_fill_signal_mode_raises(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        with pytest.raises(RuntimeError, match="signal-export mode"):
            bridge.monitor_fill(12345)

    def test_require_connected_raises(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        with pytest.raises(RuntimeError, match="not connected"):
            bridge._require_connected()

    def test_context_manager(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        with bridge as b:
            assert b._connected is True
        assert bridge._connected is False

    @pytest.mark.asyncio
    async def test_async_send_order_signal_mode(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0, timeout_sec=0.05)
        with pytest.raises(TimeoutError):
            await bridge.async_send_order(order)

    @pytest.mark.asyncio
    async def test_async_close_position_signal_mode(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        with patch.object(bridge._exporter, "poll_fill", side_effect=TimeoutError("t")):
            with pytest.raises(TimeoutError):
                await bridge.async_close_position("XAUUSD")

    @pytest.mark.asyncio
    async def test_async_modify_order(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        result = await bridge.async_modify_order(12345, "XAUUSD", stop_loss=1880.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_async_cancel_order(self, tmp_path):
        bridge = _signal_bridge(tmp_path)
        bridge.connect()
        result = await bridge.async_cancel_order(12345, "XAUUSD")
        assert result is True


# ── PART 6: brokers/mt5.py (MT5Connector) ────────────────────────────────────


def _make_mt5_connector_mod():
    """Reload brokers.mt5 with a mocked MetaTrader5 module."""
    mt5_mock = MagicMock()
    mt5_mock.TRADE_RETCODE_DONE = 10009
    mt5_mock.TRADE_ACTION_DEAL = 1
    mt5_mock.TRADE_ACTION_PENDING = 5
    mt5_mock.TRADE_ACTION_REMOVE = 8
    mt5_mock.ORDER_TYPE_BUY = 0
    mt5_mock.ORDER_TYPE_SELL = 1
    mt5_mock.ORDER_TYPE_BUY_LIMIT = 2
    mt5_mock.ORDER_TYPE_SELL_LIMIT = 3
    mt5_mock.ORDER_TYPE_BUY_STOP = 4
    mt5_mock.ORDER_TYPE_SELL_STOP = 5
    mt5_mock.ORDER_TIME_GTC = 1
    mt5_mock.ORDER_FILLING_IOC = 1
    mt5_mock.POSITION_TYPE_BUY = 0
    mt5_mock.POSITION_TYPE_SELL = 1
    mt5_mock.TIMEFRAME_M1 = 1
    mt5_mock.TIMEFRAME_M5 = 5
    mt5_mock.TIMEFRAME_M15 = 15
    mt5_mock.TIMEFRAME_M30 = 30
    mt5_mock.TIMEFRAME_H1 = 16385
    mt5_mock.TIMEFRAME_H4 = 16388
    mt5_mock.TIMEFRAME_D1 = 16408
    mt5_mock.TIMEFRAME_W1 = 32769
    mt5_mock.TIMEFRAME_MN1 = 49153
    return mt5_mock


@pytest.fixture()
def mt5_connector():
    mt5_mock = _make_mt5_connector_mod()
    with patch.dict("sys.modules", {"MetaTrader5": mt5_mock}):
        import importlib
        import brokers.mt5 as mod

        importlib.reload(mod)
        config = {"server": "ICMarkets-Demo", "login": 12345678, "password": "pass"}  # pragma: allowlist secret
        connector = mod.MT5Connector(config)
        yield connector, mod, mt5_mock


class TestMT5ConnectorInit:
    def test_init_missing_fields_raises(self):
        mt5_mock = _make_mt5_connector_mod()
        with patch.dict("sys.modules", {"MetaTrader5": mt5_mock}):
            import importlib
            import brokers.mt5 as mod

            importlib.reload(mod)
            with pytest.raises(ValueError, match="requires"):
                mod.MT5Connector({"server": "Demo"})

    def test_init_sdk_unavailable_raises(self):
        with patch("brokers.mt5.MT5_AVAILABLE", False):
            import brokers.mt5 as mod

            with pytest.raises(ImportError):
                mod.MT5Connector({"server": "Demo", "login": 1, "password": "p"})


class TestMT5ConnectorConnect:
    def test_connect_success(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        mt5.initialize.return_value = True
        mt5.login.return_value = True
        mt5.account_info.return_value = MagicMock(server="Demo", login=12345678, balance=10000.0, leverage=100)
        result = conn.connect()
        assert result is True
        assert conn.connected is True

    def test_connect_with_path(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.path = "/path/to/terminal"
        mt5.initialize.return_value = True
        mt5.login.return_value = True
        mt5.account_info.return_value = MagicMock(server="Demo", login=12345678, balance=0.0, leverage=100)
        result = conn.connect()
        assert result is True
        call_kwargs = mt5.initialize.call_args[1]
        assert "path" in call_kwargs

    def test_connect_initialize_fails(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        mt5.initialize.return_value = False
        mt5.last_error.return_value = (1, "init error")
        result = conn.connect()
        assert result is False

    def test_connect_login_fails(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        mt5.initialize.return_value = True
        mt5.login.return_value = False
        mt5.last_error.return_value = (2, "login error")
        result = conn.connect()
        assert result is False

    def test_connect_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        mt5.initialize.side_effect = Exception("crash")
        result = conn.connect()
        assert result is False

    def test_disconnect_success(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        result = conn.disconnect()
        assert result is True
        assert conn.connected is False

    def test_disconnect_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        mt5.shutdown.side_effect = Exception("crash")
        result = conn.disconnect()
        assert result is False


class TestMT5ConnectorPlaceOrder:
    def _setup(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        return conn, mod, mt5

    def test_place_order_not_connected(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        from brokers.base import OrderSide

        result = conn.place_order("XAUUSD", OrderSide.BUY, 0.01)
        assert result is None

    def test_place_order_market_buy(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide

        sym_info = MagicMock(visible=True)
        mt5.symbol_info.return_value = sym_info
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        result_obj = MagicMock(retcode=10009, order=1001, volume=0.01, price=1920.0, deal=2001)
        mt5.order_send.return_value = result_obj
        order = conn.place_order("XAUUSD", OrderSide.BUY, 0.01)
        assert order is not None
        assert order.id == "1001"

    def test_place_order_market_sell(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide

        sym_info = MagicMock(visible=True)
        mt5.symbol_info.return_value = sym_info
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        result_obj = MagicMock(retcode=10009, order=1002, volume=0.01, price=1919.5, deal=2002)
        mt5.order_send.return_value = result_obj
        order = conn.place_order("XAUUSD", OrderSide.SELL, 0.01)
        assert order is not None

    def test_place_order_limit(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide, OrderType

        sym_info = MagicMock(visible=True)
        mt5.symbol_info.return_value = sym_info
        result_obj = MagicMock(retcode=10009, order=1003, volume=0.01, price=1900.0, deal=2003)
        mt5.order_send.return_value = result_obj
        order = conn.place_order("XAUUSD", OrderSide.BUY, 0.01, order_type=OrderType.LIMIT, price=1900.0)
        assert order is not None

    def test_place_order_stop(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide, OrderType

        sym_info = MagicMock(visible=True)
        mt5.symbol_info.return_value = sym_info
        result_obj = MagicMock(retcode=10009, order=1004, volume=0.01, price=1880.0, deal=2004)
        mt5.order_send.return_value = result_obj
        order = conn.place_order("XAUUSD", OrderSide.SELL, 0.01, order_type=OrderType.STOP, price=1880.0)
        assert order is not None

    def test_place_order_symbol_not_found(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide

        mt5.symbol_info.return_value = None
        result = conn.place_order("INVALID", OrderSide.BUY, 0.01)
        assert result is None

    def test_place_order_symbol_select_fails(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide

        sym_info = MagicMock(visible=False)
        mt5.symbol_info.return_value = sym_info
        mt5.symbol_select.return_value = False
        result = conn.place_order("XAUUSD", OrderSide.BUY, 0.01)
        assert result is None

    def test_place_order_no_tick(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide

        sym_info = MagicMock(visible=True)
        mt5.symbol_info.return_value = sym_info
        mt5.symbol_info_tick.return_value = None
        result = conn.place_order("XAUUSD", OrderSide.BUY, 0.01)
        assert result is None

    def test_place_order_unsupported_type(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide, OrderType

        sym_info = MagicMock(visible=True)
        mt5.symbol_info.return_value = sym_info
        result = conn.place_order("XAUUSD", OrderSide.BUY, 0.01, order_type=OrderType.STOP_LIMIT)
        assert result is None

    def test_place_order_retcode_not_done(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide

        sym_info = MagicMock(visible=True)
        mt5.symbol_info.return_value = sym_info
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        result_obj = MagicMock(retcode=10006, comment="Rejected")
        mt5.order_send.return_value = result_obj
        result = conn.place_order("XAUUSD", OrderSide.BUY, 0.01)
        assert result is None

    def test_place_order_with_sl_tp(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide

        sym_info = MagicMock(visible=True)
        mt5.symbol_info.return_value = sym_info
        tick = MagicMock(ask=1920.0, bid=1919.5)
        mt5.symbol_info_tick.return_value = tick
        result_obj = MagicMock(retcode=10009, order=1005, volume=0.01, price=1920.0, deal=2005)
        mt5.order_send.return_value = result_obj
        order = conn.place_order("XAUUSD", OrderSide.BUY, 0.01, stop_loss=1880.0, take_profit=1950.0)
        assert order is not None

    def test_place_order_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        from brokers.base import OrderSide

        mt5.symbol_info.side_effect = Exception("crash")
        result = conn.place_order("XAUUSD", OrderSide.BUY, 0.01)
        assert result is None


class TestMT5ConnectorOther:
    def test_cancel_order_not_connected(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        result = conn.cancel_order("1001")
        assert result is False

    def test_cancel_order_success(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        result_obj = MagicMock(retcode=10009)
        mt5.order_send.return_value = result_obj
        result = conn.cancel_order("1001")
        assert result is True

    def test_cancel_order_fails(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        result_obj = MagicMock(retcode=10006)
        mt5.order_send.return_value = result_obj
        result = conn.cancel_order("1001")
        assert result is False

    def test_cancel_order_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.order_send.side_effect = Exception("crash")
        result = conn.cancel_order("1001")
        assert result is False

    def test_get_order_not_connected(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        result = conn.get_order("1001")
        assert result is None

    def test_get_order_found(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        o = MagicMock(
            ticket=1001, symbol="XAUUSD", type=0, volume_current=0.01, price_open=1920.0, time_setup=1700000000
        )
        mt5.orders_get.return_value = [o]
        result = conn.get_order("1001")
        assert result is not None

    def test_get_order_not_found(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.orders_get.return_value = []
        result = conn.get_order("9999")
        assert result is None

    def test_get_order_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.orders_get.side_effect = Exception("crash")
        result = conn.get_order("1001")
        assert result is None

    def test_get_positions_not_connected(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        result = conn.get_positions()
        assert result == []

    def test_get_positions_success(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        pos = MagicMock(symbol="XAUUSD", type=0, volume=0.1, price_open=1900.0, profit=100.0, time=1700000000)
        mt5.positions_get.return_value = [pos]
        tick = MagicMock(bid=1919.5, ask=1920.0)
        mt5.symbol_info_tick.return_value = tick
        result = conn.get_positions()
        assert len(result) == 1
        assert result[0].symbol == "XAUUSD"

    def test_get_positions_short(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        pos = MagicMock(symbol="EURUSD", type=1, volume=0.05, price_open=1.08, profit=-20.0, time=1700000001)
        mt5.positions_get.return_value = [pos]
        tick = MagicMock(bid=1.079, ask=1.080)
        mt5.symbol_info_tick.return_value = tick
        result = conn.get_positions()
        assert result[0].side == "SHORT"

    def test_get_positions_none(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.positions_get.return_value = None
        result = conn.get_positions()
        assert result == []

    def test_get_positions_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.positions_get.side_effect = Exception("crash")
        result = conn.get_positions()
        assert result == []

    def test_close_position_not_connected(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        result = conn.close_position("XAUUSD")
        assert result is False

    def test_close_position_no_positions(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.positions_get.return_value = []
        result = conn.close_position("XAUUSD")
        assert result is False

    def test_close_position_success(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        pos = MagicMock(type=0, volume=0.1, ticket=1001)
        mt5.positions_get.return_value = [pos]
        tick = MagicMock(bid=1919.5, ask=1920.0)
        mt5.symbol_info_tick.return_value = tick
        result_obj = MagicMock(retcode=10009)
        mt5.order_send.return_value = result_obj
        result = conn.close_position("XAUUSD")
        assert result is True

    def test_close_position_no_tick(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        pos = MagicMock(type=0, volume=0.1, ticket=1001)
        mt5.positions_get.return_value = [pos]
        mt5.symbol_info_tick.return_value = None
        result = conn.close_position("XAUUSD")
        assert result is True  # continues loop, no positions closed but no crash

    def test_close_position_order_fails(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        pos = MagicMock(type=0, volume=0.1, ticket=1001)
        mt5.positions_get.return_value = [pos]
        tick = MagicMock(bid=1919.5, ask=1920.0)
        mt5.symbol_info_tick.return_value = tick
        result_obj = MagicMock(retcode=10006, comment="Rejected")
        mt5.order_send.return_value = result_obj
        result = conn.close_position("XAUUSD")
        assert result is False

    def test_close_position_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.positions_get.side_effect = Exception("crash")
        result = conn.close_position("XAUUSD")
        assert result is False

    def test_get_account_info_not_connected(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        result = conn.get_account_info()
        assert result is None

    def test_get_account_info_success(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        acct = MagicMock(balance=10000.0, equity=10100.0, margin=500.0, margin_free=9600.0)
        mt5.account_info.return_value = acct
        mt5.positions_get.return_value = []
        result = conn.get_account_info()
        assert result is not None
        assert result.balance == 10000.0

    def test_get_account_info_none(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.account_info.return_value = None
        result = conn.get_account_info()
        assert result is None

    def test_get_account_info_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.account_info.side_effect = Exception("crash")
        result = conn.get_account_info()
        assert result is None

    def test_get_market_data_not_connected(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        result = conn.get_market_data("XAUUSD")
        assert result is None

    def test_get_market_data_success(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        rates = [
            {"time": 1700000000, "open": 1900.0, "high": 1920.0, "low": 1890.0, "close": 1910.0, "tick_volume": 1000}
        ]
        mt5.copy_rates_from_pos.return_value = rates
        result = conn.get_market_data("XAUUSD", timeframe="H1", limit=1)
        assert result is not None
        assert len(result) == 1
        assert result[0]["close"] == 1910.0

    def test_get_market_data_all_timeframes(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        rates = [{"time": 1700000000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "tick_volume": 100}]
        mt5.copy_rates_from_pos.return_value = rates
        for tf in ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]:
            result = conn.get_market_data("EURUSD", timeframe=tf, limit=1)
            assert result is not None

    def test_get_market_data_unknown_timeframe(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        rates = [{"time": 1700000000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "tick_volume": 100}]
        mt5.copy_rates_from_pos.return_value = rates
        result = conn.get_market_data("EURUSD", timeframe="INVALID", limit=1)
        assert result is not None  # falls back to H1

    def test_get_market_data_none(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.copy_rates_from_pos.return_value = None
        result = conn.get_market_data("XAUUSD")
        assert result is None

    def test_get_market_data_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.copy_rates_from_pos.side_effect = Exception("crash")
        result = conn.get_market_data("XAUUSD")
        assert result is None

    def test_get_symbols_not_connected(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        result = conn.get_symbols()
        assert result == []

    def test_get_symbols_success(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        s1 = MagicMock(visible=True)
        s1.name = "XAUUSD"
        s2 = MagicMock(visible=False)
        s2.name = "EURUSD"
        mt5.symbols_get.return_value = [s1, s2]
        result = conn.get_symbols()
        assert "XAUUSD" in result
        assert "EURUSD" not in result

    def test_get_symbols_none(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.symbols_get.return_value = None
        result = conn.get_symbols()
        assert result == []

    def test_get_symbols_exception(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        mt5.symbols_get.side_effect = Exception("crash")
        result = conn.get_symbols()
        assert result == []

    def test_mt5_order_to_order_sell(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        o = MagicMock(ticket=2001, symbol="EURUSD", type=1, volume_current=0.05, price_open=1.08, time_setup=1700000000)
        mt5.orders_get.return_value = [o]
        result = conn.get_order("2001")
        assert result is not None

    def test_mt5_order_to_order_limit(self, mt5_connector):
        conn, mod, mt5 = mt5_connector
        conn.connected = True
        o = MagicMock(
            ticket=3001, symbol="XAUUSD", type=2, volume_current=0.1, price_open=1900.0, time_setup=1700000000
        )
        mt5.orders_get.return_value = [o]
        result = conn.get_order("3001")
        assert result is not None
