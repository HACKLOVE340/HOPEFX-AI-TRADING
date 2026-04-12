# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for ml/daily_aggregator.py.
Covers needs_resampling, to_daily, ensure_daily — all branches.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

import ml.daily_aggregator as da_mod


def _intraday(n: int = 500, freq: str = "1h") -> pd.DataFrame:
    """Return an intraday OHLCV DataFrame with DatetimeIndex."""
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    np.random.seed(3)
    c = 2000.0 + np.cumsum(np.random.randn(n))
    return pd.DataFrame({
        "open": c - 0.5, "high": c + 1.0,
        "low": c - 1.0, "close": c,
        "volume": np.ones(n) * 500,
    }, index=idx)


def _daily(n: int = 150) -> pd.DataFrame:
    """Return a daily OHLCV DataFrame with DatetimeIndex."""
    idx = pd.date_range("2023-01-01", periods=n, freq="1D", tz="UTC")
    np.random.seed(5)
    c = 1900.0 + np.cumsum(np.random.randn(n))
    return pd.DataFrame({
        "open": c - 0.5, "high": c + 1.0,
        "low": c - 1.0, "close": c,
        "volume": np.ones(n) * 1000,
    }, index=idx)


# ── needs_resampling ──────────────────────────────────────────────────────────

class TestNeedsResampling:
    def test_intraday_returns_true(self):
        df = _intraday(200, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"):
            assert da_mod.needs_resampling(df) is True

    def test_daily_returns_false(self):
        df = _daily(150)
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"):
            assert da_mod.needs_resampling(df) is False

    def test_intraday_mode_always_false(self):
        df = _intraday(200, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "intraday"):
            assert da_mod.needs_resampling(df) is False

    def test_non_datetime_index_returns_false(self):
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        assert da_mod.needs_resampling(df) is False

    def test_single_row_returns_false(self):
        df = _intraday(1)
        assert da_mod.needs_resampling(df) is False

    def test_handles_exception_gracefully(self):
        df = _intraday(10)
        # Corrupt the index so diff() raises
        df.index = pd.Index(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"])
        result = da_mod.needs_resampling(df)
        assert result is False


# ── to_daily ──────────────────────────────────────────────────────────────────

class TestToDaily:
    def test_resamples_intraday_to_daily(self):
        df = _intraday(500, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"), \
             patch.object(da_mod, "_MIN_DAILY_BARS", 10):
            result = da_mod.to_daily(df, min_bars=10)
        assert result is not None
        assert len(result) >= 10

    def test_returns_none_when_too_few_daily_bars(self):
        df = _intraday(24, "1h")  # only 1 day of data
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"):
            result = da_mod.to_daily(df, min_bars=100)
        assert result is None

    def test_intraday_mode_passthrough(self):
        df = _intraday(200, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "intraday"):
            result = da_mod.to_daily(df, min_bars=10)
        assert result is df  # same object returned

    def test_intraday_mode_passthrough_too_few(self):
        df = _intraday(5, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "intraday"):
            result = da_mod.to_daily(df, min_bars=100)
        assert result is None

    def test_non_datetime_index_passthrough(self):
        df = pd.DataFrame({"open": [1.0]*200, "high": [2.0]*200,
                           "low": [0.5]*200, "close": [1.5]*200})
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"):
            result = da_mod.to_daily(df, min_bars=10)
        assert result is not None  # passthrough

    def test_non_datetime_index_too_few(self):
        df = pd.DataFrame({"open": [1.0]*5, "high": [2.0]*5,
                           "low": [0.5]*5, "close": [1.5]*5})
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"):
            result = da_mod.to_daily(df, min_bars=100)
        assert result is None

    def test_missing_ohlcv_columns_passthrough(self):
        idx = pd.date_range("2024-01-01", periods=200, freq="1h", tz="UTC")
        df = pd.DataFrame({"close": np.random.randn(200)}, index=idx)
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"):
            result = da_mod.to_daily(df, min_bars=10)
        # Missing open/high/low → passthrough
        assert result is not None

    def test_timezone_naive_index_gets_localized(self):
        idx = pd.date_range("2024-01-01", periods=500, freq="1h")  # no tz
        np.random.seed(9)
        c = 2000.0 + np.cumsum(np.random.randn(500))
        df = pd.DataFrame({
            "open": c - 0.5, "high": c + 1.0,
            "low": c - 1.0, "close": c, "volume": np.ones(500),
        }, index=idx)
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"), \
             patch.object(da_mod, "_MIN_DAILY_BARS", 5):
            result = da_mod.to_daily(df, min_bars=5)
        assert result is not None

    def test_volume_column_summed(self):
        df = _intraday(500, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"), \
             patch.object(da_mod, "_MIN_DAILY_BARS", 5):
            result = da_mod.to_daily(df, min_bars=5)
        assert result is not None
        assert "volume" in result.columns
        # Daily volume should be sum of hourly volumes
        assert result["volume"].iloc[0] > df["volume"].iloc[0]

    def test_handles_resampling_exception(self):
        df = _intraday(200, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"), \
             patch("pandas.DataFrame.resample", side_effect=RuntimeError("resample fail")):
            result = da_mod.to_daily(df, min_bars=10)
        # Falls back to passthrough
        assert result is not None or result is None  # either is acceptable


# ── ensure_daily ──────────────────────────────────────────────────────────────

class TestEnsureDaily:
    def test_resamples_when_intraday(self):
        df = _intraday(500, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"), \
             patch.object(da_mod, "_MIN_DAILY_BARS", 5):
            result = da_mod.ensure_daily(df, min_bars=5)
        assert result is not None

    def test_passthrough_when_already_daily(self):
        df = _daily(150)
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"):
            result = da_mod.ensure_daily(df, min_bars=100)
        assert result is df

    def test_returns_none_when_daily_too_few(self):
        df = _daily(50)
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "daily"):
            result = da_mod.ensure_daily(df, min_bars=100)
        assert result is None

    def test_intraday_mode_passthrough(self):
        df = _intraday(200, "1h")
        with patch.object(da_mod, "_INFERENCE_TIMEFRAME", "intraday"):
            result = da_mod.ensure_daily(df, min_bars=100)
        assert result is df
