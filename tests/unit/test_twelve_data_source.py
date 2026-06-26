# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_twelve_data_source.py
========================================
Unit tests for data_feed/sources/twelve_data.py — TwelveDataSource.

Uses aioresponses to intercept real aiohttp requests so the full HTTP
client code path (params, JSON parsing, error handling) runs against
real TwelveDataSource code.  No mocks of internal methods.
"""

from __future__ import annotations

import re

import aiohttp
import pytest
from tests.support.aioresponses_shim import aioresponses

from data_feed.sources.twelve_data import (
    TwelveDataSource,
    _TD_BASE_URL,
    _TD_PRICE_EP,
    _TD_QUOTE_EP,
)

_PRICE_URL = f"{_TD_BASE_URL}{_TD_PRICE_EP}"
_QUOTE_URL = f"{_TD_BASE_URL}{_TD_QUOTE_EP}"

# Regex patterns so aioresponses matches regardless of query-param ordering.
_PRICE_URL_RE = re.compile(r"https://api\.twelvedata\.com/price.*")
_QUOTE_URL_RE = re.compile(r"https://api\.twelvedata\.com/quote.*")

_PRICE_RESPONSE = {"price": "1950.5000"}
_QUOTE_RESPONSE = {"bid": "1950.0000", "ask": "1951.0000", "close": "1950.5000"}
_EURUSD_PRICE = {"price": "1.08750"}
_BTCUSD_PRICE = {"price": "65000.00"}
_NDX_PRICE = {"price": "19500.00"}

_ERROR_CREDITS = {
    "status": "error",
    "code": 429,
    "message": "You have run out of API credits for the current minute.",
}
_ERROR_SYMBOL = {
    "status": "error",
    "code": 400,
    "message": "**symbol** is not valid",
}
_ERROR_GENERIC = {
    "status": "error",
    "code": 500,
    "message": "Internal server error",
}


# ── Construction ──────────────────────────────────────────────────────────────


class TestTwelveDataSourceInit:
    def test_name(self):
        src = TwelveDataSource(api_key="testkey")
        assert src.name == "twelve_data"

    def test_default_uses_price_endpoint(self):
        src = TwelveDataSource(api_key="testkey")
        assert src._use_quote is False

    def test_quote_mode(self):
        src = TwelveDataSource(api_key="testkey", use_quote=True)
        assert src._use_quote is True

    def test_status_no_key(self):
        src = TwelveDataSource()
        s = src.status()
        assert s["source"] == "twelve_data"
        assert s["api_key_set"] is False
        assert s["credits_exhausted"] is False

    def test_status_with_key(self):
        src = TwelveDataSource(api_key="abc123")
        s = src.status()
        assert s["api_key_set"] is True


# ── fetch — no API key ────────────────────────────────────────────────────────


class TestTwelveDataNoKey:
    @pytest.mark.asyncio
    async def test_no_key_returns_none(self):
        src = TwelveDataSource(api_key="")
        price = await src.fetch("XAUUSD", {"twelve_data_symbol": "XAU/USD"})
        assert price is None

    @pytest.mark.asyncio
    async def test_missing_symbol_config_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        price = await src.fetch("XAUUSD", {})
        assert price is None

    @pytest.mark.asyncio
    async def test_empty_symbol_config_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        price = await src.fetch("NAS100", {"twelve_data_symbol": ""})
        assert price is None


# ── fetch — /price endpoint ───────────────────────────────────────────────────


class TestTwelveDataPriceEndpoint:
    @pytest.mark.asyncio
    async def test_xauusd_price_parsed(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload=_PRICE_RESPONSE)
            price = await src.fetch("XAUUSD", cfg)
        assert price == pytest.approx(1950.5)

    @pytest.mark.asyncio
    async def test_eurusd_price_parsed(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "EUR/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload=_EURUSD_PRICE)
            price = await src.fetch("EURUSD", cfg)
        assert price == pytest.approx(1.0875)

    @pytest.mark.asyncio
    async def test_btcusd_price_parsed(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "BTC/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload=_BTCUSD_PRICE)
            price = await src.fetch("BTCUSD", cfg)
        assert price == pytest.approx(65000.0)

    @pytest.mark.asyncio
    async def test_ndx_price_parsed(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "NDX"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload=_NDX_PRICE)
            price = await src.fetch("NAS100", cfg)
        assert price == pytest.approx(19500.0)

    @pytest.mark.asyncio
    async def test_zero_price_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload={"price": "0.0"})
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_empty_price_field_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload={"price": ""})
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_credits_cleared_on_success(self):
        src = TwelveDataSource(api_key="testkey")
        src._credits_exhausted = True
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload=_PRICE_RESPONSE)
            price = await src.fetch("XAUUSD", cfg)
        assert price is not None
        assert src._credits_exhausted is False


# ── fetch — /quote endpoint ───────────────────────────────────────────────────


class TestTwelveDataQuoteEndpoint:
    @pytest.mark.asyncio
    async def test_quote_mid_price(self):
        src = TwelveDataSource(api_key="testkey", use_quote=True)
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_QUOTE_URL_RE, payload=_QUOTE_RESPONSE)
            price = await src.fetch("XAUUSD", cfg)
        # mid = (1950.0 + 1951.0) / 2 = 1950.5
        assert price == pytest.approx(1950.5)

    @pytest.mark.asyncio
    async def test_quote_fallback_to_close(self):
        """When bid/ask absent, fall back to close price."""
        src = TwelveDataSource(api_key="testkey", use_quote=True)
        cfg = {"twelve_data_symbol": "XAU/USD"}
        payload = {"close": "1950.5000"}
        with aioresponses() as m:
            m.get(_QUOTE_URL_RE, payload=payload)
            price = await src.fetch("XAUUSD", cfg)
        assert price == pytest.approx(1950.5)

    @pytest.mark.asyncio
    async def test_quote_inverted_spread_returns_none(self):
        """bid > ask is invalid — must return None."""
        src = TwelveDataSource(api_key="testkey", use_quote=True)
        cfg = {"twelve_data_symbol": "XAU/USD"}
        payload = {"bid": "1952.0", "ask": "1948.0"}
        with aioresponses() as m:
            m.get(_QUOTE_URL_RE, payload=payload)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_quote_zero_bid_returns_none(self):
        src = TwelveDataSource(api_key="testkey", use_quote=True)
        cfg = {"twelve_data_symbol": "XAU/USD"}
        payload = {"bid": "0.0", "ask": "1951.0"}
        with aioresponses() as m:
            m.get(_QUOTE_URL_RE, payload=payload)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None


# ── fetch — API errors ────────────────────────────────────────────────────────


class TestTwelveDataAPIErrors:
    @pytest.mark.asyncio
    async def test_credits_exhausted_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload=_ERROR_CREDITS)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None
        assert src._credits_exhausted is True

    @pytest.mark.asyncio
    async def test_invalid_symbol_error_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "INVALID"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload=_ERROR_SYMBOL)
            price = await src.fetch("INVALID", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_generic_api_error_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, payload=_ERROR_GENERIC)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None


# ── fetch — HTTP errors ───────────────────────────────────────────────────────


class TestTwelveDataHTTPErrors:
    @pytest.mark.asyncio
    async def test_http_500_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, status=500)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, exception=aiohttp.ClientConnectionError("refused"))
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_http_403_returns_none(self):
        src = TwelveDataSource(api_key="testkey")
        cfg = {"twelve_data_symbol": "XAU/USD"}
        with aioresponses() as m:
            m.get(_PRICE_URL_RE, status=403)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None


# ── Shared session ────────────────────────────────────────────────────────────


class TestTwelveDataSharedSession:
    @pytest.mark.asyncio
    async def test_shared_session_not_closed_after_fetch(self):
        async with aiohttp.ClientSession() as session:
            src = TwelveDataSource(api_key="testkey", session=session)
            assert src._owns_session is False
            cfg = {"twelve_data_symbol": "XAU/USD"}
            with aioresponses() as m:
                m.get(_PRICE_URL_RE, payload=_PRICE_RESPONSE)
                price = await src.fetch("XAUUSD", cfg)
            assert price is not None
            assert not session.closed

    @pytest.mark.asyncio
    async def test_close_owned_session(self):
        src = TwelveDataSource(api_key="testkey")
        src._session = aiohttp.ClientSession()
        src._owns_session = True
        await src.close()
        assert src._session is None
