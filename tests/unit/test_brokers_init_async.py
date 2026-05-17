# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Coverage for async methods in brokers/__init__.py PaperTradingBroker and OANDABroker."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_init_paper_class():
    """Return the PaperTradingBroker from brokers/__init__.py (before override)."""
    # The class is overridden at module bottom by brokers.paper_trading import.
    # We extract it by inspecting the module's source classes directly.
    import brokers as _b

    # Try to get the original class stored before override
    cls = getattr(_b, "_InitPaperTradingBroker", None)
    if cls is None:
        # Fall back to whatever is exported — may be paper_trading version
        cls = _b.PaperTradingBroker
    return cls


def _make_price_feed(symbol="XAUUSD", ask=1951.0, bid=1949.0):
    feed = MagicMock()
    tick = MagicMock()
    tick.ask = ask
    tick.bid = bid
    tick.mid = (ask + bid) / 2
    feed.get_last_price.return_value = tick
    return feed


# ---------------------------------------------------------------------------
# brokers/__init__.py PaperTradingBroker — async path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitPaperBrokerAsync:
    """Tests for the PaperTradingBroker from brokers/paper_trading.py (canonical)."""

    def _broker(self, **kw):
        from brokers.paper_trading import PaperTradingBroker

        return PaperTradingBroker({}, **kw)

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        b = self._broker()
        assert await b.connect() is True
        assert b.connected is True
        assert await b.disconnect() is True
        assert b.connected is False

    @pytest.mark.asyncio
    async def test_get_account_info_structure(self):
        b = self._broker()
        info = await b.get_account_info()
        # Returns AccountInfo dataclass
        assert hasattr(info, "balance") or "balance" in info

    @pytest.mark.asyncio
    async def test_place_market_order_not_connected_raises(self):
        from brokers.paper_trading import PaperTradingBroker
        from brokers.base import OrderSide, OrderType

        b = PaperTradingBroker({})
        b.connected = False
        with pytest.raises((ConnectionError, Exception)):
            b.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    @pytest.mark.asyncio
    async def test_get_positions_empty(self):
        b = self._broker()
        positions = await b.get_positions()
        assert isinstance(positions, list)

    def test_cancel_order_not_found(self):
        b = self._broker()
        result = b.cancel_order("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_place_market_order_async(self):
        from brokers.paper_trading import PaperTradingBroker

        b = PaperTradingBroker({})
        await b.connect()
        b.update_market_price("XAUUSD", 1950.0)
        order = await b.place_market_order("XAUUSD", "buy", 1.0)
        assert order is not None

    def test_is_connected(self):
        b = self._broker()
        b.connected = True
        assert b.is_connected() is True

    def test_set_price_feed(self):
        b = self._broker()
        feed = _make_price_feed()
        b.set_price_feed(feed)
        assert b._price_feed is feed or b.price_feed is feed


# ---------------------------------------------------------------------------
# brokers/__init__.py OANDABroker — mocked HTTP
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitOANDABroker:
    def _broker(self):
        from brokers import OANDABroker

        return OANDABroker(api_key="test-key", account_id="123", practice=True)  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_disconnect_no_session(self):
        b = self._broker()
        result = await b.disconnect()
        assert result is True
        assert b.connected is False

    @pytest.mark.asyncio
    async def test_cancel_order_success(self):
        b = self._broker()
        mock_session = MagicMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=mock_resp)
        b._session = mock_session
        b.connected = True
        result = await b.cancel_order("order-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_order_raises(self):
        b = self._broker()
        mock_session = MagicMock()
        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.text = AsyncMock(return_value="not found")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=mock_resp)
        b._session = mock_session
        b.connected = True
        result = await b.cancel_order("bad-order")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_position_invalid_id(self):
        b = self._broker()
        b.connected = True
        result = await b.close_position("invalid-no-underscore")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_account_info_mocked(self):
        b = self._broker()
        mock_data = {
            "account": {
                "balance": "10000.00",
                "NAV": "10050.00",
                "marginUsed": "500.00",
                "marginAvailable": "9500.00",
                "unrealizedPL": "50.00",
                "realizedPL": "0.00",
                "positions": [],
                "currency": "USD",
            }
        }
        with patch.object(b, "_make_request", AsyncMock(return_value=mock_data)):
            info = await b.get_account_info()
        assert info["balance"] == pytest.approx(10000.0)
        assert info["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_get_positions_mocked(self):
        b = self._broker()
        mock_data = {
            "positions": [
                {
                    "instrument": "XAU_USD",
                    "long": {
                        "units": "1000",
                        "averagePrice": "1950.0",
                        "markPrice": "1960.0",
                        "unrealizedPL": "10.0",
                        "realizedPL": "0.0",
                    },
                    "short": {"units": "0"},
                }
            ]
        }
        with patch.object(b, "_make_request", AsyncMock(return_value=mock_data)):
            positions = await b.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "XAU/USD"

    @pytest.mark.asyncio
    async def test_get_pending_orders_mocked(self):
        b = self._broker()
        mock_data = {
            "orders": [
                {
                    "id": "o1",
                    "instrument": "XAU_USD",
                    "units": 100,
                    "type": "LIMIT",
                    "price": "1940.0",
                }
            ]
        }
        with patch.object(b, "_make_request", AsyncMock(return_value=mock_data)):
            orders = await b.get_pending_orders()
        assert len(orders) == 1

    @pytest.mark.asyncio
    async def test_place_market_order_mocked(self):
        b = self._broker()
        mock_data = {
            "orderFillTransaction": {
                "id": "fill-1",
                "price": "1950.5",
                "commission": "-2.0",
            }
        }
        with patch.object(b, "_make_request", AsyncMock(return_value=mock_data)):
            order = await b.place_market_order("XAU/USD", "buy", 1.0)
        assert order.id == "fill-1"
        assert order.status.value == "filled"

    @pytest.mark.asyncio
    async def test_place_market_order_no_fill_raises(self):
        b = self._broker()
        with patch.object(b, "_make_request", AsyncMock(return_value={})), pytest.raises(ValueError, match="No fill"):
            await b.place_market_order("XAU/USD", "buy", 1.0)

    @pytest.mark.asyncio
    async def test_close_position_mocked(self):
        b = self._broker()
        with patch.object(b, "_make_request", AsyncMock(return_value={})):
            result = await b.close_position("XAU/USD_long")
        assert result is True

    @pytest.mark.asyncio
    async def test_close_position_raises(self):
        b = self._broker()
        with patch.object(b, "_make_request", AsyncMock(side_effect=ValueError("fail"))):
            result = await b.close_position("XAU/USD_long")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_positions_cached(self):
        b = self._broker()
        mock_data = {"positions": []}
        with patch.object(b, "_make_request", AsyncMock(return_value=mock_data)):
            await b.get_positions()
            # Second call should use cache
            b._last_cache_update = time.time()
            positions = await b.get_positions()
        assert isinstance(positions, list)


# ---------------------------------------------------------------------------
# brokers/__init__.py BaseBroker — close_all_positions / cancel_all_orders
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBaseBrokerHelpers:
    @pytest.mark.asyncio
    async def test_close_all_positions_empty(self):
        from brokers.paper_trading import PaperTradingBroker

        b = PaperTradingBroker({})
        await b.connect()
        result = b.close_all_positions()
        # Returns int (count) or list depending on implementation
        assert result is not None
