# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_yfinance_source.py
====================================
Unit tests for data_feed/sources/yfinance_source.py — YFinanceSource.

Uses real YFinanceSource code paths.  The synchronous yfinance.download()
call is patched at the pandas-DataFrame level so no network I/O occurs, but
all parsing, validation, and error-handling logic runs against real code.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_feed.sources.yfinance_source import YFinanceSource

_YF_MOD = "data_feed.sources.yfinance_source"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_df(close: float) -> pd.DataFrame:
    """Return a minimal single-row DataFrame matching yfinance output."""
    return pd.DataFrame({"Close": [close]})


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


@contextmanager
def _patch_yf(return_value=None, side_effect=None):
    """Patch both _YF_AVAILABLE=True and _yf.download in one context manager.

    Necessary because yfinance may not be installed in CI — when _YF_AVAILABLE
    is False, fetch() returns None before ever reaching the mocked download().
    """
    mock_yf = MagicMock()
    if side_effect is not None:
        mock_yf.download.side_effect = side_effect
    else:
        mock_yf.download.return_value = return_value
    with patch(f"{_YF_MOD}._YF_AVAILABLE", True), patch(f"{_YF_MOD}._yf", mock_yf):
        yield mock_yf


# ── YFinanceSource construction ───────────────────────────────────────────────


class TestYFinanceSourceInit:
    def test_default_params(self):
        src = YFinanceSource()
        assert src._period == "1d"
        assert src._interval == "1m"
        assert src.name == "yfinance"

    def test_custom_params(self):
        src = YFinanceSource(period="5d", interval="5m")
        assert src._period == "5d"
        assert src._interval == "5m"

    def test_status_available(self):
        src = YFinanceSource()
        s = src.status()
        assert s["source"] == "yfinance"
        assert "available" in s
        assert s["period"] == "1d"
        assert s["interval"] == "1m"


# ── fetch — happy path ────────────────────────────────────────────────────────


class TestYFinanceSourceFetch:
    @pytest.mark.asyncio
    async def test_fetch_returns_close_price(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        with _patch_yf(return_value=_make_df(1950.25)):
            price = await src.fetch("XAUUSD", cfg)
        assert price == pytest.approx(1950.25)

    @pytest.mark.asyncio
    async def test_fetch_uses_configured_ticker(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "SI=F"}
        captured = {}
        def fake_download(ticker, **kwargs):
            captured["ticker"] = ticker
            return _make_df(25.50)
        with _patch_yf(side_effect=fake_download):
            await src.fetch("XAGUSD", cfg)
        assert captured["ticker"] == "SI=F"

    @pytest.mark.asyncio
    async def test_fetch_passes_period_and_interval(self):
        src = YFinanceSource(period="5d", interval="5m")
        cfg = {"yfinance_ticker": "GC=F"}
        captured = {}
        def fake_download(ticker, **kwargs):
            captured.update(kwargs)
            return _make_df(1950.0)
        with _patch_yf(side_effect=fake_download):
            await src.fetch("XAUUSD", cfg)
        assert captured["period"] == "5d"
        assert captured["interval"] == "5m"

    @pytest.mark.asyncio
    async def test_fetch_multi_row_returns_last(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        df = pd.DataFrame({"Close": [1900.0, 1920.0, 1950.0]})
        with _patch_yf(return_value=df):
            price = await src.fetch("XAUUSD", cfg)
        assert price == pytest.approx(1950.0)

    @pytest.mark.asyncio
    async def test_fetch_btcusd_ticker(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "BTC-USD"}
        with _patch_yf(return_value=_make_df(65000.0)):
            price = await src.fetch("BTCUSD", cfg)
        assert price == pytest.approx(65000.0)

    @pytest.mark.asyncio
    async def test_fetch_nas100_ticker(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "NQ=F"}
        with _patch_yf(return_value=_make_df(19500.0)):
            price = await src.fetch("NAS100", cfg)
        assert price == pytest.approx(19500.0)


# ── fetch — missing / invalid config ─────────────────────────────────────────


class TestYFinanceSourceMissingConfig:
    @pytest.mark.asyncio
    async def test_no_ticker_returns_none(self):
        src = YFinanceSource()
        price = await src.fetch("XAUUSD", {})
        assert price is None

    @pytest.mark.asyncio
    async def test_empty_ticker_returns_none(self):
        src = YFinanceSource()
        price = await src.fetch("XAUUSD", {"yfinance_ticker": ""})
        assert price is None


# ── fetch — data quality guards ───────────────────────────────────────────────


class TestYFinanceSourceDataQuality:
    @pytest.mark.asyncio
    async def test_empty_dataframe_returns_none(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        with _patch_yf(return_value=_empty_df()):
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_zero_price_returns_none(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        with _patch_yf(return_value=_make_df(0.0)):
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_negative_price_returns_none(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        with _patch_yf(return_value=_make_df(-100.0)):
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_all_nan_close_returns_none(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        df = pd.DataFrame({"Close": [float("nan"), float("nan")]})
        with _patch_yf(return_value=df):
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_fallback_to_first_numeric_column(self):
        """When 'Close' column is absent, fall back to first numeric column."""
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        df = pd.DataFrame({"Adj Close": [1955.0]})
        with _patch_yf(return_value=df):
            price = await src.fetch("XAUUSD", cfg)
        assert price == pytest.approx(1955.0)


# ── fetch — error handling ────────────────────────────────────────────────────


class TestYFinanceSourceErrors:
    @pytest.mark.asyncio
    async def test_download_exception_returns_none(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        with _patch_yf(side_effect=RuntimeError("network error")):
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_download_returns_none_returns_none(self):
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        with _patch_yf(return_value=None):
            price = await src.fetch("XAUUSD", cfg)
        assert price is None

    @pytest.mark.asyncio
    async def test_unavailable_yfinance_returns_none(self):
        """When _YF_AVAILABLE is False, fetch returns None without calling download."""
        src = YFinanceSource()
        cfg = {"yfinance_ticker": "GC=F"}
        with patch("data_feed.sources.yfinance_source._YF_AVAILABLE", False):
            price = await src.fetch("XAUUSD", cfg)
        assert price is None


# ── close ─────────────────────────────────────────────────────────────────────


class TestYFinanceSourceClose:
    @pytest.mark.asyncio
    async def test_close_is_noop(self):
        src = YFinanceSource()
        await src.close()  # must not raise
