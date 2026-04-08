# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for ml/inference_engine.py

Covers: InferenceEngine init, predict (neutral fallback, insufficient bars),
        _check_model_staleness, _check_feature_drift, get_inference_engine
        singleton, and signal thresholding env vars.
"""

import os
import time

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Shared OHLCV fixture (200 bars — above _MIN_BARS=100)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ohlcv_200():
    rng = np.random.default_rng(42)
    n = 200
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


@pytest.fixture(scope="module")
def ohlcv_50():
    """Below _MIN_BARS threshold."""
    rng = np.random.default_rng(99)
    n = 50
    close = 1800.0 + np.cumsum(rng.standard_normal(n) * 2)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.ones(n) * 1000,
        },
        index=pd.date_range("2024-01-01", periods=n, freq="1h"),
    )
    return df


# ---------------------------------------------------------------------------
# InferenceEngine — init
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInferenceEngineInit:
    def test_init_state(self):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        assert engine._predictor is None
        assert engine._predict_count == 0
        assert engine._fallback_count == 0
        assert engine._model_stale is False

    def test_init_drift_buffer_empty(self):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        assert len(engine._drift_buffer) == 0

    def test_init_signal_window_empty(self):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        assert len(engine._signal_window) == 0


# ---------------------------------------------------------------------------
# InferenceEngine — predict (no model loaded → neutral fallback)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInferenceEnginePredict:
    def test_predict_returns_dict(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200)
        assert isinstance(result, dict)

    def test_predict_required_keys(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200)
        for key in (
            "direction",
            "probability",
            "confidence",
            "model_version",
            "bars_used",
            "last_close",
            "latency_ms",
            "fallback",
        ):
            assert key in result, f"Missing key: {key}"

    def test_predict_neutral_when_no_model(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200)
        assert result["direction"] == "neutral"
        assert result["fallback"] is True

    def test_predict_direction_valid_value(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200)
        assert result["direction"] in ("long", "short", "neutral")

    def test_predict_probability_in_range(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200)
        assert 0.0 <= result["probability"] <= 1.0

    def test_predict_latency_ms_positive(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200)
        assert result["latency_ms"] >= 0.0

    def test_predict_increments_count(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        engine.predict(ohlcv_200)
        engine.predict(ohlcv_200)
        assert engine._predict_count == 2

    def test_predict_insufficient_bars_returns_neutral(self, ohlcv_50):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_50)
        assert result["direction"] == "neutral"
        assert result["fallback"] is True

    def test_predict_last_close_matches_data(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200)
        assert result["last_close"] == pytest.approx(float(ohlcv_200["close"].iloc[-1]))

    def test_predict_bars_used(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200)
        # bars_used may differ if resampling occurred, but should be > 0
        assert result["bars_used"] > 0

    def test_predict_with_custom_symbol(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        result = engine.predict(ohlcv_200, symbol="EUR_USD")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _check_model_staleness
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckModelStaleness:
    def test_disabled_when_max_age_zero(self, monkeypatch):
        monkeypatch.setenv("MODEL_MAX_AGE_DAYS", "0")
        # Re-import to pick up env var
        import importlib
        import ml.inference_engine as ie

        importlib.reload(ie)
        engine = ie.InferenceEngine()
        result = engine._check_model_staleness()
        assert result is False
        assert engine._model_stale is False
        assert engine._model_age_days is None

    def test_returns_false_when_no_model_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MODEL_MAX_AGE_DAYS", "30")
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        # Point to a non-existent path
        engine._active_model_path = tmp_path / "nonexistent.pkl"
        result = engine._check_model_staleness()
        assert result is False

    def test_detects_stale_model(self, tmp_path):
        from ml.inference_engine import InferenceEngine
        import ml.inference_engine as ie

        engine = InferenceEngine()
        # Create a file with old mtime (40 days ago)
        old_file = tmp_path / "old_model.pkl"
        old_file.write_bytes(b"fake model")
        old_mtime = time.time() - (40 * 86400)
        os.utime(old_file, (old_mtime, old_mtime))
        engine._active_model_path = old_file
        # Patch the module-level constant directly
        original = ie._MODEL_MAX_AGE_DAYS
        ie._MODEL_MAX_AGE_DAYS = 1.0
        try:
            result = engine._check_model_staleness()
        finally:
            ie._MODEL_MAX_AGE_DAYS = original
        assert result is True
        assert engine._model_stale is True
        assert engine._model_age_days > 1

    def test_fresh_model_not_stale(self, tmp_path):
        from ml.inference_engine import InferenceEngine
        import ml.inference_engine as ie

        engine = InferenceEngine()
        fresh_file = tmp_path / "fresh_model.pkl"
        fresh_file.write_bytes(b"fake model")
        engine._active_model_path = fresh_file
        original = ie._MODEL_MAX_AGE_DAYS
        ie._MODEL_MAX_AGE_DAYS = 30.0
        try:
            result = engine._check_model_staleness()
        finally:
            ie._MODEL_MAX_AGE_DAYS = original
        assert result is False
        assert engine._model_stale is False


# ---------------------------------------------------------------------------
# _check_feature_drift
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckFeatureDrift:
    def test_returns_false_when_no_train_stats(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        # No feature_stats.json → drift guard disabled
        X_row = pd.DataFrame({"f1": [0.5], "f2": [1.0]})
        result = engine._check_feature_drift(X_row)
        assert result is False

    def test_returns_false_when_buffer_not_full(self, ohlcv_200, tmp_path):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        # Inject fake train stats
        stats = {"f1": {"mean": 0.5, "std": 0.1}, "f2": {"mean": 1.0, "std": 0.2}}
        engine._train_stats = stats
        X_row = pd.DataFrame({"f1": [0.5], "f2": [1.0]})
        # Buffer not full yet — should return False
        result = engine._check_feature_drift(X_row)
        assert result is False

    def test_appends_to_drift_buffer(self, ohlcv_200):
        from ml.inference_engine import InferenceEngine

        engine = InferenceEngine()
        engine._train_stats = {"f1": {"mean": 0.5, "std": 0.1}}
        X_row = pd.DataFrame({"f1": [0.5]})
        engine._check_feature_drift(X_row)
        assert len(engine._drift_buffer) == 1


# ---------------------------------------------------------------------------
# get_inference_engine singleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetInferenceEngine:
    def test_returns_inference_engine_instance(self):
        from ml.inference_engine import InferenceEngine, get_inference_engine

        engine = get_inference_engine()
        assert isinstance(engine, InferenceEngine)

    def test_returns_same_instance(self):
        from ml.inference_engine import get_inference_engine

        e1 = get_inference_engine()
        e2 = get_inference_engine()
        assert e1 is e2


# ---------------------------------------------------------------------------
# Signal threshold env vars
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSignalThresholds:
    def test_custom_thresholds_applied(self, monkeypatch, ohlcv_200):
        """Custom SIGNAL_THRESHOLD_LONG/SHORT are read at module load time."""
        monkeypatch.setenv("SIGNAL_THRESHOLD_LONG", "0.70")
        monkeypatch.setenv("SIGNAL_THRESHOLD_SHORT", "0.30")
        import importlib
        import ml.inference_engine as ie

        importlib.reload(ie)
        assert pytest.approx(0.70) == ie._THRESHOLD_LONG
        assert pytest.approx(0.30) == ie._THRESHOLD_SHORT

    def test_default_thresholds(self, monkeypatch):
        monkeypatch.delenv("SIGNAL_THRESHOLD_LONG", raising=False)
        monkeypatch.delenv("SIGNAL_THRESHOLD_SHORT", raising=False)
        import importlib
        import ml.inference_engine as ie

        importlib.reload(ie)
        assert pytest.approx(0.58) == ie._THRESHOLD_LONG
        assert pytest.approx(0.42) == ie._THRESHOLD_SHORT
