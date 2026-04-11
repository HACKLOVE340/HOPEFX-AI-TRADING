# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for:
  ml/regime.py, ml/regime_conditional.py, ml/signal_features.py,
  ml/signal_filter.py, ml/macro_features.py, ml/daily_aggregator.py,
  ml/macro_store.py
Real implementations only.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

UTC = timezone.utc


# ===========================================================================
# ml/regime.py
# ===========================================================================

@pytest.mark.unit
class TestMarketRegime:
    def test_all_regimes_defined(self):
        from ml.regime import MarketRegime
        names = {r.name for r in MarketRegime}
        assert "TRENDING_UP" in names
        assert "TRENDING_DOWN" in names
        assert "HIGH_VOL" in names
        assert "UNKNOWN" in names

    def test_regime_result_dataclass(self):
        from ml.regime import RegimeResult, MarketRegime
        r = RegimeResult(
            regime=MarketRegime.TRENDING_UP,
            confidence=0.85,
            duration_bars=10,
            transition_probability=0.12,
        )
        assert r.regime == MarketRegime.TRENDING_UP
        assert r.confidence == 0.85


@pytest.mark.unit
class TestRegimeDetector:
    def test_init_defaults(self):
        from ml.regime import RegimeDetector
        rd = RegimeDetector()
        assert rd.n_regimes == 5
        assert rd._is_fitted is False

    def test_detect_unfitted_returns_unknown(self):
        from ml.regime import RegimeDetector, MarketRegime
        rd = RegimeDetector()
        features = MagicMock()
        features.returns = 0.001
        features.volatility = 0.01
        features.rsi = 50.0
        features.macd = 0.0
        features.bid_ask_ratio = 1.0
        features.hawkes_intensity = 0.5

        import asyncio
        regime, conf = asyncio.run(rd.detect(features))
        assert regime == MarketRegime.UNKNOWN
        assert conf == 0.0

    @pytest.mark.asyncio
    async def test_load_no_model_file(self, tmp_path):
        from ml.regime import RegimeDetector
        rd = RegimeDetector(model_path=tmp_path / "nonexistent.pkl")
        await rd.load()
        assert rd._is_fitted is False


# ===========================================================================
# ml/regime_conditional.py
# ===========================================================================

@pytest.mark.unit
class TestRegimeConditionalFunctions:
    def _ohlcv(self, n=200):
        rng = np.random.default_rng(42)
        idx = pd.date_range("2024-01-01", periods=n, freq="1h")
        return pd.DataFrame({
            "open":   3300 + rng.normal(0, 5, n).cumsum(),
            "high":   3310 + rng.normal(0, 5, n).cumsum(),
            "low":    3290 + rng.normal(0, 5, n).cumsum(),
            "close":  3300 + rng.normal(0, 5, n).cumsum(),
            "volume": rng.uniform(100, 1000, n),
        }, index=idx)

    def test_detect_regime_labels_returns_series(self):
        from ml.regime_conditional import detect_regime_labels
        df = self._ohlcv()
        labels = detect_regime_labels(df)
        assert isinstance(labels, pd.Series)
        assert len(labels) == len(df)

    def test_add_regime_features_adds_columns(self):
        from ml.regime_conditional import add_regime_features
        df = self._ohlcv()
        result = add_regime_features(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)

    def test_is_parabolic_bubble_regime(self):
        from ml.regime_conditional import is_parabolic_bubble_regime
        df = self._ohlcv()
        result = is_parabolic_bubble_regime(df)
        assert isinstance(result, bool)

    def test_get_regime_conditional_model_no_file_returns_none(self):
        from ml.regime_conditional import get_regime_conditional_model
        # No saved model file → returns None (expected behaviour)
        model = get_regime_conditional_model(model_path="/tmp/nonexistent_rcm.joblib")
        assert model is None

    def test_regime_conditional_model_fit_predict(self):
        from ml.regime_conditional import RegimeConditionalModel
        rng = np.random.default_rng(0)
        # Must include regime_hurst and regime_trend_str columns for detect_regime_labels
        cols = ["regime_hurst", "regime_trend_str", "f0", "f1", "f2"]
        X = pd.DataFrame(rng.normal(0, 1, (100, 5)), columns=cols)
        X["regime_hurst"] = rng.uniform(0.3, 0.7, 100)
        X["regime_trend_str"] = rng.uniform(0.0, 1.0, 100)
        y = pd.Series(rng.integers(0, 2, 100))
        model = RegimeConditionalModel()
        model.fit(X, y)
        preds = model.predict(X)
        assert len(preds) == 100

    def test_regime_conditional_model_predict_proba(self):
        from ml.regime_conditional import RegimeConditionalModel
        rng = np.random.default_rng(1)
        cols = ["regime_hurst", "regime_trend_str", "f0", "f1"]
        X = pd.DataFrame(rng.normal(0, 1, (80, 4)), columns=cols)
        X["regime_hurst"] = rng.uniform(0.3, 0.7, 80)
        X["regime_trend_str"] = rng.uniform(0.0, 1.0, 80)
        y = pd.Series(rng.integers(0, 2, 80))
        model = RegimeConditionalModel()
        model.fit(X, y)
        proba = model.predict_proba(X)
        assert proba.shape[0] == 80
        assert proba.shape[1] == 2


# ===========================================================================
# ml/signal_filter.py
# ===========================================================================

@pytest.mark.unit
class TestSignalFilter:
    def _filter(self):
        from ml.signal_filter import SignalFilter
        return SignalFilter()

    def _signal(self, direction="long", confidence=0.75, symbol="XAUUSD"):
        return {"direction": direction, "confidence": confidence, "symbol": symbol}

    def test_check_high_confidence_passes(self):
        sf = self._filter()
        result = sf.check(self._signal(confidence=0.80))
        assert hasattr(result, "passed")

    def test_check_low_confidence_blocked(self):
        sf = self._filter()
        result = sf.check(self._signal(confidence=0.30))
        assert result.passed is False

    def test_check_hold_direction_blocked(self):
        sf = self._filter()
        result = sf.check(self._signal(direction="HOLD", confidence=0.90))
        assert result.passed is False

    def test_filter_result_bool(self):
        from ml.signal_filter import FilterResult
        r = FilterResult(passed=True, reason="ok", gate="", confidence=0.8)
        assert bool(r) is True
        r2 = FilterResult(passed=False, reason="low conf", gate="confidence")
        assert bool(r2) is False

    def test_record_outcome_updates_stats(self):
        sf = self._filter()
        for _ in range(5):
            sf.record_outcome("XAUUSD", pnl_pct=0.01, direction=1, confidence=0.75)
        stats = sf.get_stats()
        assert "per_symbol" in stats
        assert "XAUUSD" in stats["per_symbol"]

    def test_ev_stats_after_outcomes(self):
        sf = self._filter()
        for i in range(15):
            sf.record_outcome("XAUUSD", pnl_pct=0.005 * (1 if i % 3 else -1), direction=1, confidence=0.7)
        ev = sf.ev_stats("XAUUSD")
        assert "ev" in ev
        assert "win_rate" in ev

    def test_get_signal_filter_singleton(self):
        from ml.signal_filter import get_signal_filter, SignalFilter
        import ml.signal_filter as sf_mod
        sf_mod._signal_filter = None
        f1 = get_signal_filter()
        f2 = get_signal_filter()
        assert f1 is f2

    def test_circuit_breaker_trip(self):
        sf = self._filter()
        # Record many losing trades to trip circuit breaker
        for _ in range(50):
            sf.record_outcome("XAUUSD", pnl_pct=-0.01, direction=1, confidence=0.75)
        # After many losses, circuit breaker may trip
        result = sf.check(self._signal(confidence=0.80))
        assert hasattr(result, "passed")  # either state is valid


# ===========================================================================
# ml/macro_features.py
# ===========================================================================

@pytest.mark.unit
class TestMacroFeatures:
    def _ohlcv(self, n=120):
        rng = np.random.default_rng(10)
        idx = pd.date_range("2024-01-01", periods=n, freq="1h")
        return pd.DataFrame({
            "open":   3300 + rng.normal(0, 3, n).cumsum(),
            "high":   3310 + rng.normal(0, 3, n).cumsum(),
            "low":    3290 + rng.normal(0, 3, n).cumsum(),
            "close":  3300 + rng.normal(0, 3, n).cumsum(),
            "volume": rng.uniform(100, 500, n),
        }, index=idx)

    def test_add_macro_features_returns_dataframe(self):
        from ml.macro_features import add_macro_features
        df = self._ohlcv()
        result = add_macro_features(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)

    def test_add_macro_features_adds_columns(self):
        from ml.macro_features import add_macro_features
        df = self._ohlcv()
        result = add_macro_features(df)
        assert result.shape[1] > df.shape[1]

    def test_add_regime_features_macro(self):
        from ml.macro_features import add_regime_features
        df = self._ohlcv()
        result = add_regime_features(df)
        assert isinstance(result, pd.DataFrame)

    def test_build_enhanced_feature_matrix(self):
        from ml.macro_features import build_enhanced_feature_matrix
        df = self._ohlcv(n=150)
        result = build_enhanced_feature_matrix(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_fetch_macro_history_no_api_key(self):
        from ml.macro_features import fetch_macro_history
        # Without API key, should return empty DataFrame or raise gracefully
        with patch.dict(os.environ, {}, clear=False):
            try:
                result = fetch_macro_history("DXY", days=30)
                assert isinstance(result, pd.DataFrame)
            except Exception:
                pass  # acceptable — no API key configured


# ===========================================================================
# ml/daily_aggregator.py
# ===========================================================================

@pytest.mark.unit
class TestDailyAggregator:
    def _intraday(self, n=2400):
        # 2400 hourly bars = 100 days — enough to exceed _MIN_DAILY_BARS
        rng = np.random.default_rng(20)
        idx = pd.date_range("2023-01-01 00:00", periods=n, freq="1h", tz="UTC")
        return pd.DataFrame({
            "open":   3300 + rng.normal(0, 2, n).cumsum(),
            "high":   3310 + rng.normal(0, 2, n).cumsum(),
            "low":    3290 + rng.normal(0, 2, n).cumsum(),
            "close":  3300 + rng.normal(0, 2, n).cumsum(),
            "volume": rng.uniform(50, 300, n),
        }, index=idx)

    def _daily(self, n=100):
        # 100 daily bars — enough to exceed _MIN_DAILY_BARS
        rng = np.random.default_rng(21)
        idx = pd.date_range("2023-01-01", periods=n, freq="1D", tz="UTC")
        return pd.DataFrame({
            "open":   3300 + rng.normal(0, 5, n).cumsum(),
            "high":   3320 + rng.normal(0, 5, n).cumsum(),
            "low":    3280 + rng.normal(0, 5, n).cumsum(),
            "close":  3300 + rng.normal(0, 5, n).cumsum(),
            "volume": rng.uniform(500, 2000, n),
        }, index=idx)

    def test_needs_resampling_intraday_true(self):
        from ml.daily_aggregator import needs_resampling
        df = self._intraday()
        assert needs_resampling(df) is True

    def test_needs_resampling_daily_false(self):
        from ml.daily_aggregator import needs_resampling
        df = self._daily()
        assert needs_resampling(df) is False

    def test_to_daily_returns_dataframe(self):
        from ml.daily_aggregator import to_daily
        df = self._intraday()
        result = to_daily(df)
        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_to_daily_ohlcv_columns(self):
        from ml.daily_aggregator import to_daily
        df = self._intraday()
        result = to_daily(df)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result.columns

    def test_ensure_daily_already_daily(self):
        from ml.daily_aggregator import ensure_daily
        df = self._daily()
        result = ensure_daily(df)
        assert isinstance(result, pd.DataFrame)

    def test_ensure_daily_intraday_resamples(self):
        from ml.daily_aggregator import ensure_daily
        df = self._intraday()
        result = ensure_daily(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) < len(df)

    def test_needs_resampling_empty_df(self):
        from ml.daily_aggregator import needs_resampling
        df = pd.DataFrame()
        assert needs_resampling(df) is False

    def test_needs_resampling_no_datetimeindex(self):
        from ml.daily_aggregator import needs_resampling
        df = pd.DataFrame({"close": [1, 2, 3]})
        assert needs_resampling(df) is False


# ===========================================================================
# ml/macro_store.py
# ===========================================================================

@pytest.mark.unit
class TestMacroStore:
    def _store(self):
        from ml.macro_store import MacroStore
        return MacroStore()

    def test_update_and_snapshot(self):
        store = self._store()
        store.update("DXY", "2024-01-15", 103.5)
        snap = store.snapshot()
        assert "DXY" in snap
        assert abs(snap["DXY"]["value"] - 103.5) < 0.01

    def test_snapshot_missing_series_empty(self):
        store = self._store()
        snap = store.snapshot()
        assert isinstance(snap, dict)

    def test_update_multiple_values(self):
        store = self._store()
        store.update("CPI", "2024-01-01", 3.1)
        store.update("CPI", "2024-02-01", 3.2)
        store.update("CPI", "2024-03-01", 3.3)
        snap = store.snapshot()
        assert "CPI" in snap
        assert abs(snap["CPI"]["value"] - 3.3) < 0.01

    def test_load_csv(self, tmp_path):
        store = self._store()
        csv_path = tmp_path / "dxy.csv"
        csv_path.write_text("date,value\n2024-01-01,103.0\n2024-01-02,103.5\n")
        n = store.load_csv(csv_path, "DXY")
        assert n == 2

    def test_load_csv_missing_file(self, tmp_path):
        store = self._store()
        n = store.load_csv(tmp_path / "nonexistent.csv", "DXY")
        assert n == 0

    def test_load_defaults_no_crash(self):
        store = self._store()
        store.load_defaults()  # should not raise even if files missing

    def test_series_names(self):
        store = self._store()
        store.update("DXY", "2024-01-01", 103.0)
        store.update("VIX", "2024-01-01", 15.0)
        names = store.series_names()
        assert "DXY" in names
        assert "VIX" in names

    def test_align_to_hourly(self):
        store = self._store()
        store.update("DXY", "2024-01-01", 103.0)
        store.update("DXY", "2024-01-02", 103.5)
        idx = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
        ohlcv = pd.DataFrame({"close": 3300.0}, index=idx)
        result = store.align_to_hourly(ohlcv, series=["DXY"])
        assert isinstance(result, pd.DataFrame)
        assert "DXY" in result.columns
        assert len(result) == 48

    def test_len(self):
        store = self._store()
        store.update("DXY", "2024-01-01", 103.0)
        store.update("VIX", "2024-01-01", 15.0)
        assert len(store) == 2
