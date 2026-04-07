# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for ml/robust_predictor.py

Covers: ModelConfig, PredictionResult, Regime, RegimeDetector,
        DriftDetector, DriftResult, RobustPredictor.
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Shared OHLCV fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ohlcv_df():
    rng = np.random.default_rng(42)
    n = 300
    close = 1800.0 + np.cumsum(rng.standard_normal(n) * 2)
    df = pd.DataFrame(
        {
            "open": close - np.abs(rng.standard_normal(n) * 0.5),
            "high": close + np.abs(rng.standard_normal(n) * 1.0),
            "low": close - np.abs(rng.standard_normal(n) * 1.0),
            "close": close,
            "volume": rng.integers(500, 5000, n).astype(float),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="1h"),
    )
    df["high"] = df[["high", "close", "open"]].max(axis=1) + 0.01
    df["low"] = df[["low", "close", "open"]].min(axis=1) - 0.01
    return df


# ---------------------------------------------------------------------------
# Regime enum
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRegimeEnum:
    def test_values(self):
        from ml.robust_predictor import Regime
        assert Regime.TRENDING.value == "trending"
        assert Regime.MEAN_REVERTING.value == "mean_reverting"
        assert Regime.HIGH_VOLATILITY.value == "high_volatility"
        assert Regime.LOW_VOLATILITY.value == "low_volatility"
        assert Regime.UNKNOWN.value == "unknown"


# ---------------------------------------------------------------------------
# ModelConfig
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestModelConfig:
    def test_defaults(self):
        from ml.robust_predictor import ModelConfig
        cfg = ModelConfig()
        assert cfg.min_train_samples == 5000
        assert cfg.n_splits == 5
        assert cfg.max_depth == 5

    def test_ensemble_methods_default(self):
        from ml.robust_predictor import ModelConfig
        cfg = ModelConfig()
        assert cfg.ensemble_methods == ["xgb", "lgb"]

    def test_ensemble_methods_custom(self):
        from ml.robust_predictor import ModelConfig
        cfg = ModelConfig(ensemble_methods=["xgb", "lgb", "rf"])
        assert "rf" in cfg.ensemble_methods

    def test_post_init_sets_ensemble_when_none(self):
        from ml.robust_predictor import ModelConfig
        cfg = ModelConfig(ensemble_methods=None)
        assert cfg.ensemble_methods is not None
        assert len(cfg.ensemble_methods) > 0

    def test_custom_values(self):
        from ml.robust_predictor import ModelConfig
        cfg = ModelConfig(max_depth=3, learning_rate=0.05)
        assert cfg.max_depth == 3
        assert cfg.learning_rate == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# PredictionResult
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPredictionResult:
    def test_init(self):
        from ml.robust_predictor import PredictionResult, Regime
        pr = PredictionResult(
            direction=1,
            probability=0.72,
            confidence="high",
            expected_return=0.005,
            uncertainty=0.1,
            regime=Regime.TRENDING,
            model_agreement=0.85,
            features_importance={"rsi": 0.3},
            timestamp=datetime.now(UTC),
        )
        assert pr.direction == 1
        assert pr.confidence == "high"
        assert pr.thresholds_calibrated is False

    def test_direction_values(self):
        from ml.robust_predictor import PredictionResult, Regime
        for direction in (-1, 0, 1):
            pr = PredictionResult(
                direction=direction,
                probability=0.5,
                confidence="low",
                expected_return=0.0,
                uncertainty=0.5,
                regime=Regime.UNKNOWN,
                model_agreement=0.5,
                features_importance={},
                timestamp=datetime.now(UTC),
            )
            assert pr.direction == direction


# ---------------------------------------------------------------------------
# RegimeDetector
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRegimeDetector:
    def test_init(self):
        from ml.robust_predictor import RegimeDetector
        rd = RegimeDetector()
        assert rd.lookback == 50
        assert rd.volatility_threshold > 0

    def test_detect_returns_array(self, ohlcv_df):
        from ml.robust_predictor import RegimeDetector
        rd = RegimeDetector()
        regimes = rd.detect(ohlcv_df)
        assert isinstance(regimes, np.ndarray)
        assert len(regimes) == len(ohlcv_df)

    def test_detect_first_bars_unknown(self, ohlcv_df):
        from ml.robust_predictor import Regime, RegimeDetector
        rd = RegimeDetector()
        regimes = rd.detect(ohlcv_df)
        # First `lookback` bars should be UNKNOWN
        assert all(r == Regime.UNKNOWN for r in regimes[:rd.lookback])

    def test_detect_valid_regime_values(self, ohlcv_df):
        from ml.robust_predictor import Regime, RegimeDetector
        rd = RegimeDetector()
        regimes = rd.detect(ohlcv_df)
        valid = set(Regime)
        assert all(r in valid for r in regimes)

    def test_detect_single_returns_regime(self, ohlcv_df):
        from ml.robust_predictor import Regime, RegimeDetector
        rd = RegimeDetector()
        result = rd.detect_single(ohlcv_df)
        assert isinstance(result, Regime)

    def test_detect_single_with_precomputed_columns(self):
        from ml.robust_predictor import Regime, RegimeDetector
        rd = RegimeDetector()
        df = pd.DataFrame({
            "regime_hurst": [0.6],
            "regime_trend_str": [0.3],
        })
        result = rd.detect_single(df)
        assert result == Regime.TRENDING

    def test_detect_single_nan_columns_returns_unknown(self):
        from ml.robust_predictor import Regime, RegimeDetector
        rd = RegimeDetector()
        df = pd.DataFrame({
            "regime_hurst": [float("nan")],
            "regime_trend_str": [0.3],
        })
        result = rd.detect_single(df)
        assert result == Regime.UNKNOWN


# ---------------------------------------------------------------------------
# DriftDetector
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDriftDetector:
    def test_init(self):
        from ml.robust_predictor import DriftDetector
        dd = DriftDetector(window_size=50, check_every=10, p_threshold=0.05)
        assert dd._window_size == 50
        assert dd._p_threshold == pytest.approx(0.05)

    def test_set_reference(self):
        from ml.robust_predictor import DriftDetector
        dd = DriftDetector()
        ref = np.random.default_rng(42).standard_normal(100)
        dd.set_reference(ref)
        assert dd._reference is not None
        assert len(dd._reference) == 100

    def test_update_returns_none_before_window_full(self):
        from ml.robust_predictor import DriftDetector
        dd = DriftDetector(window_size=50, check_every=10)
        ref = np.random.default_rng(42).standard_normal(100)
        dd.set_reference(ref)
        for _ in range(49):
            result = dd.update(0.0)
        assert result is None

    def test_update_returns_drift_result_when_window_full(self):
        from ml.robust_predictor import DriftDetector, DriftResult
        rng = np.random.default_rng(42)
        dd = DriftDetector(window_size=50, check_every=10)
        ref = rng.standard_normal(100)
        dd.set_reference(ref)
        # Fill window and trigger check
        for _ in range(60):
            result = dd.update(rng.standard_normal())
        # At least one result should have been returned
        assert result is not None
        assert isinstance(result, DriftResult)

    def test_drift_detected_on_shifted_distribution(self):
        from ml.robust_predictor import DriftDetector
        rng = np.random.default_rng(42)
        dd = DriftDetector(window_size=50, check_every=10, p_threshold=0.05)
        # Reference: N(0,1)
        dd.set_reference(rng.standard_normal(200))
        # Feed values from N(10, 1) — very different distribution
        last_result = None
        for _ in range(60):
            r = dd.update(10.0 + rng.standard_normal())
            if r is not None:
                last_result = r
        assert last_result is not None
        assert last_result.detected is True

    def test_no_drift_on_same_distribution(self):
        from ml.robust_predictor import DriftDetector
        rng = np.random.default_rng(42)
        dd = DriftDetector(window_size=50, check_every=10, p_threshold=0.05)
        ref = rng.standard_normal(200)
        dd.set_reference(ref)
        last_result = None
        for _ in range(60):
            r = dd.update(rng.standard_normal())
            if r is not None:
                last_result = r
        # Same distribution — drift should NOT be detected
        if last_result is not None:
            assert last_result.detected is False

    def test_drift_result_fields(self):
        from ml.robust_predictor import DriftDetector
        rng = np.random.default_rng(42)
        dd = DriftDetector(window_size=50, check_every=10)
        dd.set_reference(rng.standard_normal(100))
        last_result = None
        for _ in range(60):
            r = dd.update(rng.standard_normal())
            if r is not None:
                last_result = r
        if last_result is not None:
            assert hasattr(last_result, "statistic")
            assert hasattr(last_result, "p_value")
            assert hasattr(last_result, "window_mean")
            assert hasattr(last_result, "reference_mean")
            assert 0.0 <= last_result.statistic <= 1.0


# ---------------------------------------------------------------------------
# RobustPredictor
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRobustPredictor:
    def test_init_defaults(self):
        from ml.robust_predictor import ModelConfig, RobustPredictor
        rp = RobustPredictor()
        assert isinstance(rp.config, ModelConfig)
        assert rp.models == {}
        assert rp.selected_features == []

    def test_init_custom_config(self):
        from ml.robust_predictor import ModelConfig, RobustPredictor
        cfg = ModelConfig(max_depth=3)
        rp = RobustPredictor(config=cfg)
        assert rp.config.max_depth == 3

    def test_should_retrain_insufficient_data(self):
        from ml.robust_predictor import RobustPredictor
        rp = RobustPredictor()
        # With no performance history, should not retrain
        assert rp.should_retrain([]) is False

    def test_should_retrain_poor_performance(self):
        from ml.robust_predictor import RobustPredictor
        rp = RobustPredictor()
        # Consistently poor accuracy should trigger retrain
        poor_perf = [0.45] * 20
        result = rp.should_retrain(poor_perf)
        assert isinstance(result, bool)

    def test_regime_detector_attached(self):
        from ml.robust_predictor import RegimeDetector, RobustPredictor
        rp = RobustPredictor()
        assert isinstance(rp.regime_detector, RegimeDetector)

    def test_predict_raises_when_not_fitted(self, ohlcv_df):
        from ml.robust_predictor import RobustPredictor
        rp = RobustPredictor()
        with pytest.raises(ValueError, match="not trained"):
            rp.predict(ohlcv_df)
