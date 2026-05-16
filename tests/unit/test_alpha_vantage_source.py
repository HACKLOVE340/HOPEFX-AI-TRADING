# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_alpha_vantage_source.py
=========================================
Unit tests for data_feed/sources/alpha_vantage.py — AlphaVantageSource.

Uses aioresponses to intercept real aiohttp requests so the full HTTP
client code path (headers, params, JSON parsing, error handling) runs
against real AlphaVantageSource code.  No mocks of internal methods.
"""

from __future__ import annotations

import re

import aiohttp
import pytest
from aioresponses import aioresponses

from data_feed.sources.alpha_vantage import (
    AlphaVantageSource,
    _AV_BASE_URL,
    _AV_FUNCTION,
)

# aioresponses matches the full URL including query params when they are
# appended by aiohttp.  Use a compiled regex so param ordering doesn't matter.
_AV_URL_RE = re.compile(r"https://www\.alphavantage\.co/query.*")

_VALID_RESPONSE = {
    "Realtime Currency Exchange Rate": {
        "1. From_Currency Code": "XAU",
        "2. From_Currency Name": "Gold",
        "3. To_Currency Code": "USD",
        "4. To_Currency Name": "US Dollar",
        "5. Exchange Rate": "1950.5000",
        "6. Last Refreshed": "2025-01-01 12:00:00",
        "7. Time Zone": "UTC",
        "8. Bid Price": "1950.0000",
        "9. Ask Price": "1951.0000",
    }
}

_RATE_LIMITED_RESPONSE = {
    "Note": (
        "Thank you for using Alpha Vantage! Our standard API rate limit is "
        "25 requests per day. Please subscribe to any of the premium plans "
        "at https://www.alphavantage.co/premium/ to instantly remove all "
        "daily rate limits."
    )
}

_INFORMATION_RESPONSE = {"Information": "The **demo** API key is for demo purposes only."}

_EURUSD_RESPONSE = {
    "Realtime Currency Exchange Rate": {
        "1. From_Currency Code": "EUR",
        "3. To_Currency Code": "USD",
        "5. Exchange Rate": "1.08750",
    }
}


def _av_url_with_params(from_sym: str, to_sym: str, api_key: str) -> str:
    return f"{_AV_BASE_URL}?function={_AV_FUNCTION}&from_currency={from_sym}&to_currency={to_sym}&apikey={api_key}"


# ── Construction ──────────────────────────────────────────────────────────────


class TestAlphaVantageSourceInit:
    def test_name(self):
        src = AlphaVantageSource(api_key="testkey")
        assert src.name == "alpha_vantage"

    def test_no_key_not_rate_limited(self):
        src = AlphaVantageSource()
        assert src._rate_limited is False

    def test_status_no_key(self):
        src = AlphaVantageSource()
        s = src.status()
        assert s["source"] == "alpha_vantage"
        assert s["api_key_set"] is False
        assert s["rate_limited"] is False

    def test_status_with_key(self):
        src = AlphaVantageSource(api_key="abc123")
        s = src.status()
        assert s["api_key_set"] is True


# ── fetch — no API key ────────────────────────────────────────────────────────


class TestAlphaVantageNoKey:
    @pytest.mark.asyncio
    async def test_no_key_returns_none(self):
        src = AlphaVantageSource(api_key="")
        price = await src.fetch("XAUUSD", {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"})
        assert price is None

    @pytest.mark.asyncio
    async def test_missing_symbol_config_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        price = await src.fetch("XAUUSD", {})
        assert price is None

    @pytest.mark.asyncio
    async def test_empty_symbol_config_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        price = await src.fetch("USOIL", {"alpha_vantage_symbol": "", "alpha_vantage_market": "USD"})
        assert price is None


# ── fetch — happy path ────────────────────────────────────────────────────────


class TestAlphaVantageHappyPath:
    @pytest.mark.asyncio
    async def test_xauusd_price_parsed(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload=_VALID_RESPONSE)
            price = await src.fetch("XAUUSD", cfg)
        assert price == pytest.approx(1950.5)

    @pytest.mark.asyncio
    async def test_eurusd_price_parsed(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "EUR", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload=_EURUSD_RESPONSE)
            price = await src.fetch("EURUSD", cfg)
        assert price == pytest.approx(1.0875)

    @pytest.mark.asyncio
    async def test_rate_limited_flag_cleared_on_success(self):
        src = AlphaVantageSource(api_key="testkey")
        src._rate_limited = True
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload=_VALID_RESPONSE)
            price = await src.fetch("XAUUSD", cfg)
        assert price is not None
        assert src._rate_limited is False

    @pytest.mark.asyncio
    async def test_positive_price_returned(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload=_VALID_RESPONSE)
            price = await src.fetch("XAUUSD", cfg)
        assert price is not None
        assert price > 0


# ── fetch — rate limiting ─────────────────────────────────────────────────────


class TestAlphaVantageRateLimiting:
    @pytest.mark.asyncio
    async def test_note_response_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload=_RATE_LIMITED_RESPONSE)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None
        assert src._rate_limited is True

    @pytest.mark.asyncio
    async def test_information_response_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload=_INFORMATION_RESPONSE)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload={})
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_missing_exchange_rate_key_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        payload = {"Realtime Currency Exchange Rate": {}}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload=payload)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None


# ── fetch — HTTP errors ───────────────────────────────────────────────────────


class TestAlphaVantageHTTPErrors:
    @pytest.mark.asyncio
    async def test_http_429_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, status=429)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_http_500_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, status=500)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        with aioresponses() as m:
            m.get(_AV_URL_RE, exception=aiohttp.ClientConnectionError("refused"))
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_zero_rate_returns_none(self):
        src = AlphaVantageSource(api_key="testkey")
        cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
        payload = {"Realtime Currency Exchange Rate": {"5. Exchange Rate": "0.0"}}
        with aioresponses() as m:
            m.get(_AV_URL_RE, payload=payload)
            price = await src.fetch("XAUUSD", cfg)
        assert price is None


# ── Shared session ────────────────────────────────────────────────────────────


class TestAlphaVantageSharedSession:
    @pytest.mark.asyncio
    async def test_shared_session_used(self):
        """When a session is injected, the source uses it and does not close it."""
        async with aiohttp.ClientSession() as session:
            src = AlphaVantageSource(api_key="testkey", session=session)
            assert src._owns_session is False
            cfg = {"alpha_vantage_symbol": "XAU", "alpha_vantage_market": "USD"}
            with aioresponses() as m:
                m.get(_AV_URL_RE, payload=_VALID_RESPONSE)
                price = await src.fetch("XAUUSD", cfg)
            assert price is not None
            # Session must still be open after fetch.
            assert not session.closed

    @pytest.mark.asyncio
    async def test_close_owned_session(self):
        src = AlphaVantageSource(api_key="testkey")
        # Inject a real session so close() has something to close.
        src._session = aiohttp.ClientSession()
        src._owns_session = True
        await src.close()
        assert src._session is None
