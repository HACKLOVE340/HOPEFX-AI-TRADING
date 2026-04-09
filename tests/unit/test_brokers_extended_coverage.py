"""Extended coverage tests for low-coverage broker files."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# brokers/ibkr_broker.py — IBKRBroker (ib_insync absent in CI)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestIBKRBrokerModule:
    def _make(self):
        from brokers.ibkr_broker import IBKRBroker
        return IBKRBroker({"login": "testuser", "password": "pass", "server": "paper"})

    def test_init(self):
        b = self._make()
        assert not b.connected

    @pytest.mark.asyncio
    async def test_connect_no_ib_insync(self):
        from brokers.ibkr_broker import _IB_AVAILABLE
        if _IB_AVAILABLE:
            pytest.skip("ib_insync installed")
        b = self._make()
        assert await b.connect() is False

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self):
        b = self._make()
        await b.disconnect()

    @pytest.mark.asyncio
    async def test_get_account_info_not_connected(self):
        b = self._make()
        assert await b.get_account_info() is None

    @pytest.mark.asyncio
    async def test_get_positions_not_connected(self):
        b = self._make()
        assert await b.get_positions() == []

    @pytest.mark.asyncio
    async def test_get_orders_not_connected(self):
        b = self._make()
        assert await b.get_orders() == []

    @pytest.mark.asyncio
    async def test_place_order_not_connected(self):
        b = self._make()
        result = await b.place_order({"symbol": "XAUUSD", "action": "BUY",
                                      "order_type": "MARKET", "quantity": 1.0})
        assert isinstance(result, dict)
        assert result.get("success") is False or "error" in result

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self):
        b = self._make()
        result = await b.cancel_order("ord-1")
        # Returns dict with success=False when not connected
        assert result is False or (isinstance(result, dict) and not result.get("success", True))

    @pytest.mark.asyncio
    async def test_close_position_not_connected(self):
        b = self._make()
        result = await b.close_position("XAUUSD")
        assert result is False or (isinstance(result, dict) and not result.get("success", True))

    @pytest.mark.asyncio
    async def test_get_tick_not_connected(self):
        b = self._make()
        assert await b.get_tick("XAUUSD") is None

    @pytest.mark.asyncio
    async def test_reconnect_not_connected(self):
        b = self._make()
        assert await b.reconnect() is False

    def test_status(self):
        b = self._make()
        s = b.status()
        assert isinstance(s, dict)
        assert "connected" in s

    def test_resolve_env_placeholder(self):
        from brokers.ibkr_broker import _resolve_env
        with patch.dict("os.environ", {"MY_VAR": "hello"}):
            assert _resolve_env("${MY_VAR:default}") == "hello"
        assert _resolve_env("${MISSING_VAR:fallback}") == "fallback"
        assert _resolve_env("plain_string") == "plain_string"
        assert _resolve_env(42) == "42"
        assert _resolve_env(None) == ""


# ---------------------------------------------------------------------------
# brokers/oanda.py — OANDAConnector (sync requests.Session wrapper)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOANDAConnector:
    def _make(self):
        from brokers.oanda import OANDAConnector
        return OANDAConnector({"api_key": "test-key", "account_id": "101-001",
                               "environment": "practice"})

    def _mock_session(self, status_code=200, json_data=None):
        sess = MagicMock()
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.raise_for_status = MagicMock()
        sess.get.return_value = resp
        sess.post.return_value = resp
        sess.put.return_value = resp
        sess.delete.return_value = resp
        return sess

    def test_init(self):
        c = self._make()
        assert not c.connected

    def test_init_missing_credentials_raises(self):
        from brokers.oanda import OANDAConnector
        with pytest.raises(ValueError):
            OANDAConnector({"api_key": "", "account_id": ""})

    def test_connect_success(self):
        c = self._make()
        mock_sess = self._mock_session(200, {"account": {"currency": "USD"}})
        with patch("requests.Session", return_value=mock_sess):
            result = c.connect()
        assert result is True
        assert c.connected

    def test_connect_failure(self):
        c = self._make()
        with patch("requests.Session", side_effect=Exception("refused")):
            result = c.connect()
        assert result is False

    def test_disconnect(self):
        c = self._make()
        c.connected = True
        c.session = MagicMock()
        result = c.disconnect()
        assert result is True
        assert not c.connected

    def test_get_account_info_not_connected(self):
        c = self._make()
        assert c.get_account_info() is None

    def test_get_positions_not_connected(self):
        c = self._make()
        assert c.get_positions() == []

    def test_place_order_not_connected(self):
        from brokers.base import OrderSide, OrderType
        c = self._make()
        assert c.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0) is None

    def test_cancel_order_not_connected(self):
        c = self._make()
        assert c.cancel_order("ord-1") is False

    def test_close_position_not_connected(self):
        c = self._make()
        assert c.close_position("XAUUSD") is False

    def test_get_market_data_not_connected(self):
        c = self._make()
        result = c.get_market_data("XAUUSD")
        assert result is None or result == []

    def test_get_account_info_connected(self):
        c = self._make()
        c.connected = True
        payload = {"account": {"balance": "5000", "NAV": "5100",
                               "marginUsed": "100", "marginAvailable": "5000",
                               "unrealizedPL": "50", "pl": "200",
                               "currency": "USD", "positions": []}}
        c.session = self._mock_session(200, payload)
        info = c.get_account_info()
        assert info is not None

    def test_get_positions_connected(self):
        c = self._make()
        c.connected = True
        payload = {"positions": [{"instrument": "XAU_USD",
                                   "long": {"units": "1", "averagePrice": "1950",
                                            "unrealizedPL": "10", "pl": "0"},
                                   "short": {"units": "0"}}]}
        c.session = self._mock_session(200, payload)
        positions = c.get_positions()
        assert len(positions) >= 1

    def test_place_order_connected(self):
        from brokers.base import OrderSide, OrderType
        c = self._make()
        c.connected = True
        payload = {"orderFillTransaction": {"id": "t1", "price": "1950",
                                             "commission": "0", "units": "1"}}
        c.session = self._mock_session(201, payload)
        order = c.place_order("XAU_USD", OrderSide.BUY, 1.0)
        assert order is not None

    def test_cancel_order_connected(self):
        c = self._make()
        c.connected = True
        c.session = self._mock_session(200, {})
        result = c.cancel_order("ord-1")
        assert result is True

    def test_close_position_connected(self):
        c = self._make()
        c.connected = True
        c.session = self._mock_session(200, {})
        result = c.close_position("XAU_USD")
        assert result is True

    def test_get_market_data_connected(self):
        c = self._make()
        c.connected = True
        payload = {"candles": [{"time": "2024-01-01T00:00:00Z", "volume": 100,
                                 "mid": {"o": "1950", "h": "1960",
                                         "l": "1940", "c": "1955"}}]}
        c.session = self._mock_session(200, payload)
        data = c.get_market_data("XAU_USD")
        assert data is not None


# ---------------------------------------------------------------------------
# brokers/oanda.py — OANDABroker (async, aliased as OandaAPI)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOANDABroker:
    def _make(self):
        from brokers.oanda import OANDABroker
        return OANDABroker(api_key="test-key", account_id="101-001", server="practice")

    def _async_cm(self, mock_resp):
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    def test_init(self):
        b = self._make()
        assert b is not None

    @pytest.mark.asyncio
    async def test_connect_success(self):
        b = self._make()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"account": {"currency": "USD"}})
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await b.connect()
        assert result is True

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        b = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("401 Unauthorized"))
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        mock_session.close = AsyncMock()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await b.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        b = self._make()
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        b._session = mock_session
        await b.disconnect()
        assert b._session is None

    @pytest.mark.asyncio
    async def test_get_account_info_not_connected(self):
        b = self._make()
        assert await b.get_account_info() is None

    @pytest.mark.asyncio
    async def test_get_open_positions_not_connected(self):
        b = self._make()
        assert await b.get_open_positions() == []

    @pytest.mark.asyncio
    async def test_place_order_not_connected(self):
        b = self._make()
        result = await b.place_order({"symbol": "XAU_USD", "direction": "buy",
                                      "quantity": 1.0, "order_type": "MARKET"})
        assert isinstance(result, dict)
        assert result.get("status") == "rejected" or result.get("success") is False

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self):
        b = self._make()
        result = await b.cancel_order("ord-1")
        assert result is False or (isinstance(result, dict) and not result.get("success", True))

    @pytest.mark.asyncio
    async def test_close_position_not_connected(self):
        b = self._make()
        result = await b.close_position("XAU_USD")
        assert result is not None

    @pytest.mark.asyncio
    async def test_ping_not_connected(self):
        b = self._make()
        result = await b.ping()
        assert isinstance(result, float)

    def test_metrics(self):
        b = self._make()
        m = b.metrics()
        assert isinstance(m, dict)

    def test_market_data_forbidden(self):
        from brokers.oanda import MarketDataForbiddenError
        b = self._make()
        with pytest.raises(MarketDataForbiddenError):
            b.get_market_data("XAU_USD")

    @pytest.mark.asyncio
    async def test_get_candles_forbidden(self):
        from brokers.oanda import MarketDataForbiddenError
        b = self._make()
        with pytest.raises(MarketDataForbiddenError):
            await b.get_candles("XAU_USD")

    @pytest.mark.asyncio
    async def test_stream_prices_forbidden(self):
        from brokers.oanda import MarketDataForbiddenError
        b = self._make()
        with pytest.raises(MarketDataForbiddenError):
            await b.stream_prices(["XAU_USD"])

    @pytest.mark.asyncio
    async def test_get_account_info_connected(self):
        b = self._make()
        b.connected = True
        payload = {"account": {"id": "101-001", "currency": "USD", "balance": "5000",
                               "NAV": "5100", "unrealizedPL": "50", "pl": "200",
                               "marginUsed": "100", "marginAvailable": "5000",
                               "openTradeCount": 0, "openPositionCount": 0,
                               "marginRate": "0.02"}}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=payload)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        b._session = mock_session
        info = await b.get_account_info()
        assert info is not None
        assert info.balance == 5000.0

    @pytest.mark.asyncio
    async def test_get_open_positions_connected(self):
        b = self._make()
        b.connected = True
        payload = {"positions": [{"instrument": "XAU_USD",
                                   "long": {"units": "1", "averagePrice": "1950",
                                            "unrealizedPL": "10", "pl": "0"},
                                   "short": {"units": "0"}}]}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=payload)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=self._async_cm(mock_resp))
        b._session = mock_session
        positions = await b.get_open_positions()
        assert len(positions) >= 1

    @pytest.mark.asyncio
    async def test_place_order_connected(self):
        b = self._make()
        b.connected = True
        payload = {"orderFillTransaction": {"id": "t1", "price": "1950",
                                             "tradeOpened": {"tradeID": "tr1"},
                                             "commission": "0", "units": "1"}}
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=payload)
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=self._async_cm(mock_resp))
        b._session = mock_session
        result = await b.place_order({"symbol": "XAU_USD", "direction": "buy",
                                      "quantity": 1.0, "order_type": "MARKET"})
        assert result is not None
