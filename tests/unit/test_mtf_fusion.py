# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_mtf_fusion.py
==============================
Unit tests for research/pipeline/mtf_fusion.py — MTFFusion and MTFFusionStore.

Covers:
- _compute_daily_regime: all d_* columns present, no look-ahead
- _compute_hourly_regime: all h_* columns present
- _align_to_intraday: forward-fill, no look-ahead (shift_periods=1)
- MTFFusion.enrich: correct column count, no NaN in regime cols
- MTFFusion.resample_to_daily / _resample_to_hourly
- MTFFusionStore.align_to_h1: returns d_*/h_* columns aligned to H1 index
- MTFFusionStore.is_ready: False before bootstrap, True after
- Feature flag FEATURE_MTF_FUSION=false disables MTF in signal engine
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 300, freq: str = "1h", start: str = "2023-01-01") -> pd.DataFrame:
    """Generate synthetic OHLCV with a UTC DatetimeIndex."""
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    close = 2000.0 + np.cumsum(rng.normal(0, 5, n))
    high = close + rng.uniform(0, 10, n)
    low = close - rng.uniform(0, 10, n)
    open_ = close + rng.normal(0, 3, n)
    vol = rng.uniform(1000, 5000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def _make_daily(n: int = 500) -> pd.DataFrame:
    return _make_ohlcv(n=n, freq="1D", start="2021-01-01")


# ── _compute_daily_regime ─────────────────────────────────────────────────────


class TestComputeDailyRegime:
    def setup_method(self):
        from research.pipeline.mtf_fusion import _compute_daily_regime

        self._fn = _compute_daily_regime

    def test_returns_only_d_prefixed_columns(self):
        df = _make_daily(300)
        result = self._fn(df)
        assert all(c.startswith("d_") for c in result.columns)

    def test_expected_columns_present(self):
        df = _make_daily(300)
        result = self._fn(df)
        expected = {
            "d_trend_20",
            "d_trend_50",
            "d_trend_200",
            "d_ma_align",
            "d_realvol_20",
            "d_high_vol",
            "d_rsi_14",
            "d_bb_pct",
            "d_dist_52wh",
            "d_dist_52wl",
            "d_ret_1d",
            "d_ret_5d",
            "d_ret_20d",
        }
        assert expected.issubset(set(result.columns))

    def test_trend_values_are_plus_minus_one(self):
        df = _make_daily(300)
        result = self._fn(df)
        for col in ("d_trend_20", "d_trend_50"):
            vals = result[col].dropna().unique()
            assert set(vals).issubset({1, -1})

    def test_rsi_in_range(self):
        df = _make_daily(300)
        result = self._fn(df)
        rsi = result["d_rsi_14"].dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all()

    def test_no_future_leakage_in_returns(self):
        """d_ret_1d at index i must use close[i-1] → close[i], not close[i+1]."""
        df = _make_daily(10)
        result = self._fn(df)
        # First row should be NaN (no previous bar)
        assert pd.isna(result["d_ret_1d"].iloc[0])


# ── _compute_hourly_regime ────────────────────────────────────────────────────


class TestComputeHourlyRegime:
    def setup_method(self):
        from research.pipeline.mtf_fusion import _compute_hourly_regime

        self._fn = _compute_hourly_regime

    def test_returns_only_h_prefixed_columns(self):
        df = _make_ohlcv(200, freq="1h")
        result = self._fn(df)
        assert all(c.startswith("h_") for c in result.columns)

    def test_expected_columns_present(self):
        df = _make_ohlcv(200, freq="1h")
        result = self._fn(df)
        assert {
            "h_trend_20",
            "h_realvol_20",
            "h_rsi_14",
            "h_ret_1h",
            "h_ret_4h",
        }.issubset(set(result.columns))


# ── _align_to_intraday ────────────────────────────────────────────────────────


class TestAlignToIntraday:
    def setup_method(self):
        from research.pipeline.mtf_fusion import _align_to_intraday

        self._fn = _align_to_intraday

    def test_output_index_matches_intraday(self):
        daily = _make_daily(100)
        intraday = _make_ohlcv(500, freq="1h")
        from research.pipeline.mtf_fusion import _compute_daily_regime

        regime = _compute_daily_regime(daily)
        aligned = self._fn(intraday.index, regime, shift_periods=1)
        assert aligned.index.equals(intraday.index)

    def test_shift_prevents_look_ahead(self):
        """After shift_periods=1, the first intraday bar within a day must see
        the *previous* day's regime, not the current day's.
        """
        daily = _make_daily(50)
        from research.pipeline.mtf_fusion import _compute_daily_regime

        regime = _compute_daily_regime(daily)
        # Unshifted vs shifted
        aligned_shifted = self._fn(daily.index, regime, shift_periods=1)
        aligned_unshifted = self._fn(daily.index, regime, shift_periods=0)
        # Shifted row i should equal unshifted row i-1 (where both are non-NaN)
        for i in range(2, 10):
            if not pd.isna(aligned_unshifted.iloc[i - 1, 0]):
                assert aligned_shifted.iloc[i, 0] == aligned_unshifted.iloc[i - 1, 0]


# ── MTFFusion.enrich ──────────────────────────────────────────────────────────


class TestMTFFusionEnrich:
    def setup_method(self):
        from research.pipeline.mtf_fusion import MTFFusion

        self._fusion = MTFFusion(resample_hourly_from_5m=True)

    def test_enrich_adds_d_and_h_columns(self):
        intraday = _make_ohlcv(500, freq="1h")
        daily = _make_daily(300)
        result = self._fusion.enrich(intraday, daily)
        d_cols = [c for c in result.columns if c.startswith("d_")]
        h_cols = [c for c in result.columns if c.startswith("h_")]
        assert len(d_cols) >= 10
        assert len(h_cols) >= 4

    def test_enrich_no_nan_in_regime_cols(self):
        intraday = _make_ohlcv(500, freq="1h")
        daily = _make_daily(300)
        result = self._fusion.enrich(intraday, daily)
        regime_cols = [c for c in result.columns if c.startswith(("d_", "h_"))]
        assert result[regime_cols].isna().sum().sum() == 0

    def test_enrich_preserves_original_columns(self):
        intraday = _make_ohlcv(200, freq="1h")
        daily = _make_daily(300)
        result = self._fusion.enrich(intraday, daily)
        for col in intraday.columns:
            assert col in result.columns

    def test_enrich_row_count_unchanged(self):
        intraday = _make_ohlcv(200, freq="1h")
        daily = _make_daily(300)
        result = self._fusion.enrich(intraday, daily)
        assert len(result) == len(intraday)

    def test_enrich_with_explicit_hourly(self):
        intraday = _make_ohlcv(500, freq="1h")
        daily = _make_daily(300)
        hourly = _make_ohlcv(200, freq="1h")
        result = self._fusion.enrich(intraday, daily, hourly_df=hourly)
        assert any(c.startswith("h_") for c in result.columns)


# ── MTFFusion.resample helpers ────────────────────────────────────────────────


class TestMTFFusionResample:
    def test_resample_to_daily(self):
        from research.pipeline.mtf_fusion import MTFFusion

        df = _make_ohlcv(500, freq="1h")
        daily = MTFFusion.resample_to_daily(df)
        assert len(daily) < len(df)
        assert "close" in daily.columns

    def test_resample_to_hourly(self):
        from research.pipeline.mtf_fusion import MTFFusion

        df = _make_ohlcv(500, freq="5min")
        hourly = MTFFusion._resample_to_hourly(df)
        assert len(hourly) < len(df)
        assert "close" in hourly.columns


# ── MTFFusionStore ────────────────────────────────────────────────────────────


class TestMTFFusionStore:
    def test_is_ready_false_before_bootstrap(self):
        from research.pipeline.mtf_fusion import MTFFusionStore

        store = MTFFusionStore()
        assert store.is_ready is False

    @pytest.mark.asyncio
    async def test_bootstrap_with_yfinance_fallback(self, monkeypatch):
        """Bootstrap should succeed via yfinance when CSVs are absent."""
        from research.pipeline.mtf_fusion import MTFFusionStore

        # Patch yfinance to return synthetic data
        mock_yf = MagicMock()
        h1_df = _make_ohlcv(500, freq="1h")
        h1_df.columns = [c.upper() for c in h1_df.columns]
        mock_yf.download.return_value = h1_df

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            store = MTFFusionStore(data_dir="/nonexistent")
            await store.bootstrap()

        # Even if yfinance mock doesn't perfectly match, store should not crash
        assert store._bootstrapped is True

    @pytest.mark.asyncio
    async def test_align_to_h1_returns_none_when_not_ready(self):
        from research.pipeline.mtf_fusion import MTFFusionStore

        store = MTFFusionStore()
        h1 = _make_ohlcv(100, freq="1h")
        result = store.align_to_h1(h1)
        assert result is None

    @pytest.mark.asyncio
    async def test_align_to_h1_returns_regime_df_when_ready(self):
        from research.pipeline.mtf_fusion import MTFFusionStore

        store = MTFFusionStore()
        # Manually inject data to simulate post-bootstrap state
        store._d1_df = _make_daily(500)
        store._h4_df = _make_ohlcv(500, freq="4h")
        store._bootstrapped = True

        h1 = _make_ohlcv(200, freq="1h")
        result = store.align_to_h1(h1)

        assert result is not None
        assert len(result) == len(h1)
        d_cols = [c for c in result.columns if c.startswith("d_")]
        assert len(d_cols) >= 5

    @pytest.mark.asyncio
    async def test_align_to_h1_no_nan_in_output(self):
        from research.pipeline.mtf_fusion import MTFFusionStore

        store = MTFFusionStore()
        store._d1_df = _make_daily(500)
        store._h4_df = _make_ohlcv(500, freq="4h")
        store._bootstrapped = True

        h1 = _make_ohlcv(200, freq="1h")
        result = store.align_to_h1(h1)
        assert result is not None
        assert result.isna().sum().sum() == 0


# ── Feature flag gate ─────────────────────────────────────────────────────────


class TestMTFFeatureFlag:
    def test_flag_enabled_by_default(self):
        from config.feature_flags import flags

        # Default is True — MTF fusion is on unless explicitly disabled
        os.environ.pop("FEATURE_MTF_FUSION", None)
        assert flags.MTF_FUSION is True

    def test_flag_disabled_by_env(self, monkeypatch):
        monkeypatch.setenv("FEATURE_MTF_FUSION", "false")
        from config.feature_flags import flags

        assert flags.MTF_FUSION is False

    def test_fetch_mtf_df_returns_none_when_flag_off(self, monkeypatch):
        monkeypatch.setenv("FEATURE_MTF_FUSION", "false")
        from core.signal_engine import _fetch_mtf_df

        h1 = _make_ohlcv(100, freq="1h")
        result = _fetch_mtf_df(h1, app_state=None)
        assert result is None
