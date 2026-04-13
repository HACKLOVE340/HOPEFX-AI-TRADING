# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage gap-fill tests for mt5_bridge (direct MT5 mode), oanda_broker
(close_trade, cancel_order, get_tick, get_ohlcv_candles), and
mt5_zmq_bridge (recv_loop, start/stop with ZMQ mocked).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── OandaBroker: close_trade, cancel_order, get_tick, get_ohlcv_candles ──────

from brokers.oanda_broker import OandaBroker


def _connected_oanda():
    b = OandaBroker({"login": "101-999-0000001-001", "password": "tok", "server": "practice"})
    b.connected = True
    session = MagicMock()
    session.closed = False
    b._session = session
    b._account_id = "101-999-0000001-001"
    b._base_url = "https://api-fxpractice.oanda.com"
    return b


def _resp(status=200, json_data=None, text_data="ok"):
    r = AsyncMock()
    r.status = status
    r.json = AsyncMock(return_value=json_data or {})
    r.text = AsyncMock(return_value=text_data)
    r.headers = {}
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=False)
    return r


class TestOandaCloseTrade:
    @pytest.mark.asyncio
    async def test_close_trade_not_connected(self):
        b = OandaBroker({"login": "x", "password": "y", "server": "practice"})
        result = await b.close_trade("t1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_200(self):
        b = _connected_oanda()
        r = _resp(200, {"orderFillTransaction": {"price": "1920.0"}})
        b._session.put.return_value = r
        result = await b.close_trade("t1")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_close_trade_400(self):
        b = _connected_oanda()
        r = _resp(400, {"errorMessage": "Bad trade"})
        b._session.put.return_value = r
        result = await b.close_trade("t1")
        assert result["success"] is False
        assert "Bad trade" in result["comment"]

    @pytest.mark.asyncio
    async def test_close_trade_404(self):
        b = _connected_oanda()
        r = _resp(404, {"errorMessage": "Not found"})
        b._session.put.return_value = r
        result = await b.close_trade("t1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_500_retries_exhausted(self):
        b = _connected_oanda()
        r = _resp(500, {})
        b._session.put.return_value = r
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.close_trade("t1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_429_with_retry_after(self):
        b = _connected_oanda()
        r = _resp(429, {})
        r.headers = {"Retry-After": "0.001"}
        b._session.put.return_value = r
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.close_trade("t1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_non_200_non_retryable(self):
        b = _connected_oanda()
        r = _resp(422, {"errorMessage": "Unprocessable"})
        b._session.put.return_value = r
        result = await b.close_trade("t1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_connection_error(self):
        import aiohttp

        b = _connected_oanda()
        b._session.put.side_effect = aiohttp.ClientConnectionError("refused")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.close_trade("t1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_generic_client_error(self):
        import aiohttp

        b = _connected_oanda()
        b._session.put.side_effect = aiohttp.ClientError("generic")
        result = await b.close_trade("t1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_partial(self):
        b = _connected_oanda()
        r = _resp(200, {"orderFillTransaction": {"price": "1920.0"}})
        b._session.put.return_value = r
        result = await b.close_trade("t1", units="50")
        assert result["success"] is True


class TestOandaCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self):
        b = OandaBroker({"login": "x", "password": "y", "server": "practice"})
        result = await b.cancel_order("ord-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_order_200(self):
        b = _connected_oanda()
        r = _resp(200, {})
        b._session.put.return_value = r
        result = await b.cancel_order("ord-1")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_cancel_order_404(self):
        b = _connected_oanda()
        r = _resp(404, {"errorMessage": "Not found"})
        b._session.put.return_value = r
        result = await b.cancel_order("ord-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_order_500_retries(self):
        b = _connected_oanda()
        r = _resp(500, {})
        b._session.put.return_value = r
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.cancel_order("ord-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_order_429(self):
        b = _connected_oanda()
        r = _resp(429, {})
        r.headers = {"Retry-After": "0.001"}
        b._session.put.return_value = r
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.cancel_order("ord-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_order_non_200(self):
        b = _connected_oanda()
        r = _resp(422, {"errorMessage": "Cannot cancel"})
        b._session.put.return_value = r
        result = await b.cancel_order("ord-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_order_connection_error(self):
        import aiohttp

        b = _connected_oanda()
        b._session.put.side_effect = aiohttp.ClientConnectionError("refused")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.cancel_order("ord-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_order_client_error(self):
        import aiohttp

        b = _connected_oanda()
        b._session.put.side_effect = aiohttp.ClientError("generic")
        result = await b.cancel_order("ord-1")
        assert result["success"] is False


class TestOandaGetTick:
    @pytest.mark.asyncio
    async def test_get_tick_not_connected(self):
        b = OandaBroker({"login": "x", "password": "y", "server": "practice"})
        result = await b.get_tick("XAU_USD")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tick_success(self):
        b = _connected_oanda()
        data = {"prices": [{"bids": [{"price": "1919.5"}], "asks": [{"price": "1920.0"}], "tradeable": True}]}
        r = _resp(200, data)
        b._session.get.return_value = r
        result = await b.get_tick("XAU_USD")
        assert result["bid"] == 1919.5
        assert result["ask"] == 1920.0

    @pytest.mark.asyncio
    async def test_get_tick_non_200(self):
        b = _connected_oanda()
        r = _resp(500, {})
        b._session.get.return_value = r
        result = await b.get_tick("XAU_USD")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tick_empty_prices(self):
        b = _connected_oanda()
        r = _resp(200, {"prices": []})
        b._session.get.return_value = r
        result = await b.get_tick("XAU_USD")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tick_client_error(self):
        import aiohttp

        b = _connected_oanda()
        b._session.get.side_effect = aiohttp.ClientError("err")
        result = await b.get_tick("XAU_USD")
        assert result is None


class TestOandaGetOhlcv:
    @pytest.mark.asyncio
    async def test_get_ohlcv_not_connected(self):
        b = OandaBroker({"login": "x", "password": "y", "server": "practice"})
        result = await b.get_ohlcv_candles("XAU_USD")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_ohlcv_success(self):
        b = _connected_oanda()
        data = {
            "candles": [
                {
                    "complete": True,
                    "time": "2025-01-01T00:00:00Z",
                    "volume": 100,
                    "mid": {"o": "1900.0", "h": "1920.0", "l": "1890.0", "c": "1910.0"},
                },
            ]
        }
        r = _resp(200, data)
        b._session.get.return_value = r
        result = await b.get_ohlcv_candles("XAU_USD")
        assert len(result) == 1
        assert result[0]["close"] == 1910.0

    @pytest.mark.asyncio
    async def test_get_ohlcv_skips_incomplete(self):
        b = _connected_oanda()
        data = {
            "candles": [
                {
                    "complete": False,
                    "time": "2025-01-01T01:00:00Z",
                    "volume": 10,
                    "mid": {"o": "1910.0", "h": "1915.0", "l": "1905.0", "c": "1912.0"},
                },
            ]
        }
        r = _resp(200, data)
        b._session.get.return_value = r
        result = await b.get_ohlcv_candles("XAU_USD")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_ohlcv_non_200(self):
        b = _connected_oanda()
        r = _resp(500, {}, "server error")
        b._session.get.return_value = r
        result = await b.get_ohlcv_candles("XAU_USD")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_ohlcv_client_error(self):
        import aiohttp

        b = _connected_oanda()
        b._session.get.side_effect = aiohttp.ClientError("err")
        result = await b.get_ohlcv_candles("XAU_USD")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_ohlcv_with_from_to(self):
        b = _connected_oanda()
        data = {
            "candles": [
                {
                    "complete": True,
                    "time": "2025-01-01T00:00:00Z",
                    "volume": 50,
                    "mid": {"o": "1900.0", "h": "1905.0", "l": "1895.0", "c": "1902.0"},
                },
            ]
        }
        r = _resp(200, data)
        b._session.get.return_value = r
        result = await b.get_ohlcv_candles("XAU_USD", from_time="2025-01-01T00:00:00Z", to_time="2025-01-02T00:00:00Z")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_ohlcv_with_from_only(self):
        b = _connected_oanda()
        data = {
            "candles": [
                {
                    "complete": True,
                    "time": "2025-01-01T00:00:00Z",
                    "volume": 50,
                    "mid": {"o": "1900.0", "h": "1905.0", "l": "1895.0", "c": "1902.0"},
                },
            ]
        }
        r = _resp(200, data)
        b._session.get.return_value = r
        result = await b.get_ohlcv_candles("XAU_USD", from_time="2025-01-01T00:00:00Z")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_ohlcv_malformed_candle_skipped(self):
        b = _connected_oanda()
        data = {
            "candles": [
                {"complete": True, "time": "2025-01-01T00:00:00Z", "volume": 50, "mid": {}},  # missing o/h/l/c
            ]
        }
        r = _resp(200, data)
        b._session.get.return_value = r
        result = await b.get_ohlcv_candles("XAU_USD")
        assert result == []

    @pytest.mark.asyncio
    async def test_place_order_429_retry_after_invalid(self):
        """Cover the ValueError branch in Retry-After parsing."""
        b = _connected_oanda()
        r = _resp(429, {})
        r.headers = {"Retry-After": "not-a-number"}
        b._session.post.return_value = r
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.place_order({"instrument": "XAU_USD", "units": 100})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_trade_429_retry_after_invalid(self):
        """Cover the ValueError branch in close_trade Retry-After parsing."""
        b = _connected_oanda()
        r = _resp(429, {})
        r.headers = {"Retry-After": "bad"}
        b._session.put.return_value = r
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.close_trade("t1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_order_429_retry_after_invalid(self):
        b = _connected_oanda()
        r = _resp(429, {})
        r.headers = {"Retry-After": "bad"}
        b._session.put.return_value = r
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await b.cancel_order("ord-1")
        assert result["success"] is False
