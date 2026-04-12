# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for backtesting/data_validator.py.
All external I/O (ccxt, yfinance, aiohttp) is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from backtesting.data_validator import (
    BarValidationResult,
    MultiSourceValidator,
    ValidationReport,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 10, base_price: float = 1800.0, ts_start: int = 1_700_000_000_000) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame indexed by Unix-ms timestamps."""
    timestamps = [ts_start + i * 3_600_000 for i in range(n)]
    prices = [base_price + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "volume": [1000.0] * n,
        },
        index=pd.Index(timestamps, name="timestamp"),
    )


# ── BarValidationResult ───────────────────────────────────────────────────────


class TestBarValidationResult:
    def test_accepted_bar(self):
        r = BarValidationResult(
            timestamp=1_700_000_000_000,
            accepted=True,
            sources_agreed=2,
            sources_total=2,
            prices={"binance": 1800.0, "kraken": 1800.5},
        )
        assert r.accepted is True
        assert r.sources_agreed == 2
        assert r.flags == []

    def test_rejected_bar_has_flags(self):
        r = BarValidationResult(
            timestamp=1_700_000_000_000,
            accepted=False,
            sources_agreed=1,
            sources_total=2,
            prices={"binance": 1800.0, "kraken": 2000.0},
            flags=["PRICE_DISAGREEMENT"],
        )
        assert r.accepted is False
        assert "PRICE_DISAGREEMENT" in r.flags


# ── ValidationReport ──────────────────────────────────────────────────────────


class TestValidationReport:
    def test_summary_contains_key_fields(self):
        report = ValidationReport(
            symbol="XAU/USDT",
            timeframe="1h",
            total_bars=100,
            accepted_bars=95,
            rejected_bars=5,
            sources_used=["binance", "kraken"],
            rejection_reasons={"PRICE_DISAGREEMENT": 5},
            coverage_pct=95.0,
        )
        summary = report.summary()
        assert "XAU/USDT" in summary
        assert "95" in summary
        assert "100" in summary

    def test_zero_bars_report(self):
        report = ValidationReport(
            symbol="BTC/USDT",
            timeframe="1d",
            total_bars=0,
            accepted_bars=0,
            rejected_bars=0,
            sources_used=[],
            rejection_reasons={},
            coverage_pct=0.0,
        )
        assert report.coverage_pct == 0.0
        assert report.summary() is not None


# ── MultiSourceValidator._bar_ms ─────────────────────────────────────────────


class TestBarMs:
    @pytest.mark.parametrize(
        "tf,expected",
        [
            ("1m", 60_000),
            ("5m", 300_000),
            ("15m", 900_000),
            ("30m", 1_800_000),
            ("1h", 3_600_000),
            ("4h", 14_400_000),
            ("1d", 86_400_000),
            ("unknown", 3_600_000),  # default
        ],
    )
    def test_known_timeframes(self, tf, expected):
        assert MultiSourceValidator._bar_ms(tf) == expected


# ── MultiSourceValidator._ohlc_sanity_filter ─────────────────────────────────


class TestOHLCSanityFilter:
    def test_valid_bars_pass(self):
        df = _make_ohlcv(5)
        v = MultiSourceValidator()
        result = v._ohlc_sanity_filter(df)
        assert len(result) == 5

    def test_invalid_bar_filtered(self):
        df = _make_ohlcv(3)
        # Make one bar invalid: high < close
        df.iloc[1, df.columns.get_loc("high")] = df.iloc[1]["close"] - 5.0
        v = MultiSourceValidator()
        result = v._ohlc_sanity_filter(df)
        assert len(result) == 2

    def test_zero_close_filtered(self):
        df = _make_ohlcv(3)
        df.iloc[0, df.columns.get_loc("close")] = 0.0
        v = MultiSourceValidator()
        result = v._ohlc_sanity_filter(df)
        assert len(result) == 2


# ── MultiSourceValidator.validate — single source fallback ───────────────────


class TestValidateSingleSource:
    def test_falls_back_to_ohlc_only_when_one_source(self):
        df = _make_ohlcv(10)
        v = MultiSourceValidator(min_sources=2)
        validated, report = v.validate({"binance": df}, "XAU/USDT", "1h")
        assert isinstance(validated, pd.DataFrame)
        assert report.sources_used == ["binance"]
        assert report.total_bars == 10

    def test_returns_empty_when_no_sources(self):
        v = MultiSourceValidator(min_sources=2)
        validated, report = v.validate({}, "XAU/USDT", "1h")
        assert validated.empty
        assert report.total_bars == 0
        assert report.accepted_bars == 0

    def test_single_source_rejects_invalid_ohlc(self):
        df = _make_ohlcv(5)
        # Corrupt one bar
        df.iloc[2, df.columns.get_loc("high")] = df.iloc[2]["low"] - 1.0
        v = MultiSourceValidator(min_sources=2)
        validated, report = v.validate({"binance": df}, "XAU/USDT", "1h")
        assert report.rejected_bars >= 1


# ── MultiSourceValidator.validate — multi-source ─────────────────────────────


class TestValidateMultiSource:
    def test_accepts_bars_when_sources_agree(self):
        df1 = _make_ohlcv(10, base_price=1800.0)
        df2 = _make_ohlcv(10, base_price=1800.1)  # within 0.5% tolerance
        v = MultiSourceValidator(min_sources=2, max_price_dev=0.005)
        validated, report = v.validate({"binance": df1, "kraken": df2}, "XAU/USDT", "1h")
        assert report.accepted_bars > 0
        assert report.sources_used == ["binance", "kraken"]

    def test_rejects_bars_when_prices_diverge(self):
        df1 = _make_ohlcv(5, base_price=1800.0)
        df2 = _make_ohlcv(5, base_price=2000.0)  # >10% deviation
        v = MultiSourceValidator(min_sources=2, max_price_dev=0.005)
        validated, report = v.validate({"binance": df1, "kraken": df2}, "XAU/USDT", "1h")
        assert report.rejected_bars > 0
        assert any("PRICE_DISAGREEMENT" in k for k in report.rejection_reasons)

    def test_rejects_bars_with_invalid_ohlc(self):
        df1 = _make_ohlcv(5, base_price=1800.0)
        df2 = _make_ohlcv(5, base_price=1800.1)
        # Corrupt one bar in primary
        df1.iloc[1, df1.columns.get_loc("high")] = df1.iloc[1]["low"] - 1.0
        v = MultiSourceValidator(min_sources=2)
        validated, report = v.validate({"binance": df1, "kraken": df2}, "XAU/USDT", "1h")
        assert report.rejected_bars >= 1
        assert "OHLC_INVALID" in report.rejection_reasons

    def test_detects_gap(self):
        df1 = _make_ohlcv(5, base_price=1800.0)
        df2 = _make_ohlcv(5, base_price=1800.1)
        # Create a large gap between bar 1 and bar 2
        df1.iloc[2, df1.columns.get_loc("open")] = 1800.0 * 1.20  # 20% gap
        v = MultiSourceValidator(min_sources=2, max_gap_pct=0.05)
        validated, report = v.validate({"binance": df1, "kraken": df2}, "XAU/USDT", "1h")
        gap_flags = [k for k in report.rejection_reasons if k.startswith("GAP_")]
        assert len(gap_flags) >= 1

    def test_detects_spike(self):
        df1 = _make_ohlcv(5, base_price=1800.0)
        df2 = _make_ohlcv(5, base_price=1800.1)
        # Create a spike: high - low >> close
        df1.iloc[1, df1.columns.get_loc("high")] = 1800.0 * 1.50
        df1.iloc[1, df1.columns.get_loc("low")] = 1800.0 * 0.50
        v = MultiSourceValidator(min_sources=2, max_spike_pct=0.10)
        validated, report = v.validate({"binance": df1, "kraken": df2}, "XAU/USDT", "1h")
        spike_flags = [k for k in report.rejection_reasons if k.startswith("SPIKE_")]
        assert len(spike_flags) >= 1

    def test_uses_nearest_timestamp_for_secondary_source(self):
        """Secondary source bars offset by half a bar interval should still match."""
        ts_start = 1_700_000_000_000
        df1 = _make_ohlcv(5, base_price=1800.0, ts_start=ts_start)
        # Offset secondary by 30 min (within 1.5x bar tolerance for 1h bars)
        df2 = _make_ohlcv(5, base_price=1800.1, ts_start=ts_start + 1_800_000)
        v = MultiSourceValidator(min_sources=2, max_price_dev=0.005)
        validated, report = v.validate({"binance": df1, "kraken": df2}, "XAU/USDT", "1h")
        assert isinstance(validated, pd.DataFrame)

    def test_coverage_pct_is_correct(self):
        df1 = _make_ohlcv(10, base_price=1800.0)
        df2 = _make_ohlcv(10, base_price=1800.1)
        v = MultiSourceValidator(min_sources=2, max_price_dev=0.005)
        _, report = v.validate({"binance": df1, "kraken": df2}, "XAU/USDT", "1h")
        expected = report.accepted_bars / report.total_bars * 100
        assert report.coverage_pct == pytest.approx(expected, abs=0.1)


# ── _fetch_ccxt (unit — no real network) ─────────────────────────────────────


class TestFetchCCXT:
    @pytest.mark.asyncio
    async def test_returns_none_when_ccxt_unavailable(self):
        from backtesting.data_validator import _fetch_ccxt

        with patch.dict("sys.modules", {"ccxt": None, "ccxt.async_support": None}):
            result = await _fetch_ccxt("binance", "XAU/USDT", "1h", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_unknown_exchange(self):
        from backtesting.data_validator import _fetch_ccxt

        mock_ccxt = MagicMock()
        mock_ccxt.async_support = MagicMock(spec=[])  # no 'nonexistent' attr
        with patch.dict("sys.modules", {"ccxt.async_support": mock_ccxt}):
            result = await _fetch_ccxt("nonexistent_exchange", "XAU/USDT", "1h", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_dataframe_on_success(self):
        from backtesting.data_validator import _fetch_ccxt

        ts = 1_700_000_000_000
        bars = [[ts + i * 3_600_000, 1800.0, 1801.0, 1799.0, 1800.5, 100.0] for i in range(3)]

        mock_exchange = AsyncMock()
        mock_exchange.fetch_ohlcv = AsyncMock(side_effect=[bars, []])
        mock_exchange.rateLimit = 100
        mock_exchange.close = AsyncMock()

        mock_ccxt_async = MagicMock()
        mock_ccxt_async.binance = MagicMock(return_value=mock_exchange)

        # _fetch_ccxt does a local `import ccxt.async_support` on every call.
        # Override sys.modules so that import resolves to our mock regardless
        # of whether ccxt is installed in the test environment.
        import sys

        orig = sys.modules.get("ccxt.async_support")
        sys.modules["ccxt.async_support"] = mock_ccxt_async
        try:
            result = await _fetch_ccxt("binance", "XAU/USDT", "1h", ts)
        finally:
            if orig is None:
                sys.modules.pop("ccxt.async_support", None)
            else:
                sys.modules["ccxt.async_support"] = orig

        assert result is not None
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from backtesting.data_validator import _fetch_ccxt

        mock_exchange = AsyncMock()
        mock_exchange.fetch_ohlcv = AsyncMock(side_effect=RuntimeError("API error"))
        mock_exchange.close = AsyncMock()

        mock_ccxt_async = MagicMock()
        mock_ccxt_async.binance = MagicMock(return_value=mock_exchange)

        with patch.dict("sys.modules", {"ccxt.async_support": mock_ccxt_async}):
            result = await _fetch_ccxt("binance", "XAU/USDT", "1h", 0)

        assert result is None


# ── _fetch_yfinance (unit — no real network) ──────────────────────────────────


class TestFetchYfinance:
    @pytest.mark.asyncio
    async def test_returns_none_when_yfinance_unavailable(self):
        from backtesting.data_validator import _fetch_yfinance

        with patch.dict("sys.modules", {"yfinance": None}):
            result = await _fetch_yfinance("XAU/USDT", "1h", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_data(self):
        from backtesting.data_validator import _fetch_yfinance

        mock_yf = MagicMock()
        mock_yf.download = MagicMock(return_value=pd.DataFrame())

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = await _fetch_yfinance("XAU/USDT", "1h", 1_700_000_000_000)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from backtesting.data_validator import _fetch_yfinance

        mock_yf = MagicMock()
        mock_yf.download = MagicMock(side_effect=RuntimeError("network"))

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = await _fetch_yfinance("XAU/USDT", "1h", 1_700_000_000_000)
        assert result is None


# ── MultiSourceValidator.fetch_all_sources ────────────────────────────────────


class TestFetchAllSources:
    @pytest.mark.asyncio
    async def test_returns_only_successful_sources(self):
        df = _make_ohlcv(5)
        v = MultiSourceValidator()

        with (
            patch("backtesting.data_validator._fetch_ccxt", new_callable=AsyncMock) as mock_ccxt,
            patch("backtesting.data_validator._fetch_yfinance", new_callable=AsyncMock) as mock_yf,
            patch("backtesting.data_validator._fetch_alpha_vantage", new_callable=AsyncMock) as mock_av,
        ):
            mock_ccxt.side_effect = [df, None]  # binance ok, kraken fails
            mock_yf.return_value = None
            mock_av.return_value = None

            sources = await v.fetch_all_sources("XAU/USDT", "1h", 1_700_000_000_000)

        assert "binance" in sources
        assert "kraken" not in sources

    @pytest.mark.asyncio
    async def test_handles_exception_from_source(self):
        v = MultiSourceValidator()

        with (
            patch("backtesting.data_validator._fetch_ccxt", new_callable=AsyncMock) as mock_ccxt,
            patch("backtesting.data_validator._fetch_yfinance", new_callable=AsyncMock) as mock_yf,
            patch("backtesting.data_validator._fetch_alpha_vantage", new_callable=AsyncMock) as mock_av,
        ):
            mock_ccxt.side_effect = RuntimeError("unexpected")
            mock_yf.return_value = None
            mock_av.return_value = None

            sources = await v.fetch_all_sources("XAU/USDT", "1h", 0)

        assert isinstance(sources, dict)
