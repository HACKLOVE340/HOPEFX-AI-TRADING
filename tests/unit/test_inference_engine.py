# HOPEFX-AI-TRADING
# Tests for ml/inference_engine.py
"""
Branch coverage for InferenceEngine: staleness, drift, nudge, predict, health.
No real model files or network calls — all external dependencies are mocked.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import ml.inference_engine as ie
from ml.inference_engine import InferenceEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 150, freq: str = "D") -> pd.DataFrame:
    """Daily OHLCV so daily_aggregator doesn't resample away bars."""
    idx = pd.date_range("2020-01-01", periods=n, freq=freq)
    rng = np.random.default_rng(42)
    close = 1900.0 + rng.standard_normal(n).cumsum()
    high = close + rng.uniform(0, 5, n)
    low = close - rng.uniform(0, 5, n)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1000.0},
        index=idx,
    )


def _make_feature_df(n_features: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        np.zeros((1, n_features)),
        columns=[f"f{i}" for i in range(n_features)],
    )


@pytest.fixture
def engine() -> InferenceEngine:
    return InferenceEngine()


# ---------------------------------------------------------------------------
# _check_model_staleness
# ---------------------------------------------------------------------------


class TestCheckModelStaleness:
    def test_disabled_when_max_age_zero(self, engine, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 0.0)
        assert engine._check_model_staleness() is False

    def test_missing_file_returns_false(self, engine, tmp_path, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30.0)
        monkeypatch.setattr(ie, "_SAVED", tmp_path)
        # No file created → not stale
        assert engine._check_model_staleness() is False

    def test_fresh_file_returns_false(self, engine, tmp_path, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30.0)
        monkeypatch.setattr(ie, "_SAVED", tmp_path)
        (tmp_path / "advanced_oos.pkl").write_bytes(b"x")
        assert engine._check_model_staleness() is False

    def test_old_file_returns_true(self, engine, tmp_path, monkeypatch):
        import os

        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 0.001)
        monkeypatch.setattr(ie, "_SAVED", tmp_path)
        f = tmp_path / "advanced_oos.pkl"
        f.write_bytes(b"x")
        os.utime(f, (time.time() - 86400, time.time() - 86400))
        assert engine._check_model_staleness() is True
        assert engine._model_age_days is not None and engine._model_age_days > 0


# ---------------------------------------------------------------------------
# _check_feature_drift
# ---------------------------------------------------------------------------


class TestCheckFeatureDrift:
    def test_no_train_stats_returns_false(self, engine, monkeypatch):
        monkeypatch.setattr(engine, "_load_train_stats", lambda: None)
        assert engine._check_feature_drift(_make_feature_df()) is False

    def test_buffer_not_full_returns_false(self, engine, monkeypatch):
        train_stats = {f"f{i}": {"mean": 0.0, "std": 1.0} for i in range(20)}
        monkeypatch.setattr(engine, "_load_train_stats", lambda: train_stats)
        engine._drift_buffer.clear()
        assert engine._check_feature_drift(_make_feature_df()) is False

    def test_drift_detected_when_values_extreme(self, engine, monkeypatch):
        monkeypatch.setattr(ie, "_DRIFT_Z_THRESHOLD", 0.01)
        monkeypatch.setattr(ie, "_DRIFT_BLOCK", False)
        train_stats = {f"f{i}": {"mean": 0.0, "std": 1.0} for i in range(20)}
        monkeypatch.setattr(engine, "_load_train_stats", lambda: train_stats)
        for _ in range(ie._DRIFT_WINDOW):
            engine._drift_buffer.append(np.array([1000.0] * 20))
        assert engine._check_feature_drift(_make_feature_df()) is True

    def test_no_drift_when_values_match_training(self, engine, monkeypatch):
        monkeypatch.setattr(ie, "_DRIFT_Z_THRESHOLD", 4.0)
        train_stats = {f"f{i}": {"mean": 0.0, "std": 1.0} for i in range(20)}
        monkeypatch.setattr(engine, "_load_train_stats", lambda: train_stats)
        for _ in range(ie._DRIFT_WINDOW):
            engine._drift_buffer.append(np.zeros(20))
        X = pd.DataFrame(np.zeros((1, 20)), columns=[f"f{i}" for i in range(20)])
        assert engine._check_feature_drift(X) is False


# ---------------------------------------------------------------------------
# _get_data_layer_nudge
# ---------------------------------------------------------------------------


class TestDataLayerNudge:
    def _mock_mod(self, blackout=0.0, confidence=0.9, sentiment=0.5, impact=0.0, ofi=0.3, pressure=0.2):
        mock_tick = MagicMock()
        mock_tick.confidence = confidence
        mock_orch = MagicMock()
        mock_orch.get_latest_tick.return_value = mock_tick
        mock_orch.get_ml_features.return_value = {
            "macro_is_blackout": blackout,
            "news_sentiment_score": sentiment,
            "macro_impact_score_now": impact,
            "micro_ofi": ofi,
            "micro_trade_pressure": pressure,
        }
        mod = MagicMock()
        mod.orchestrator = mock_orch
        return mod

    def test_blackout_suppresses_nudge(self, engine):
        mod = self._mock_mod(blackout=1.0)
        with patch.dict("sys.modules", {"data_layer.orchestrator": mod}):
            assert engine._get_data_layer_nudge() == 0.0

    def test_low_confidence_suppresses_nudge(self, engine):
        mod = self._mock_mod(confidence=0.1)
        with patch.dict("sys.modules", {"data_layer.orchestrator": mod}):
            assert engine._get_data_layer_nudge() == 0.0

    def test_normal_path_returns_bounded_float(self, engine):
        mod = self._mock_mod()
        with patch.dict("sys.modules", {"data_layer.orchestrator": mod}):
            nudge = engine._get_data_layer_nudge()
        assert isinstance(nudge, float)
        assert -0.022 <= nudge <= 0.022

    def test_import_error_returns_zero(self, engine):
        with patch.dict("sys.modules", {"data_layer.orchestrator": None}):
            assert engine._get_data_layer_nudge() == 0.0


# ---------------------------------------------------------------------------
# predict
# ---------------------------------------------------------------------------


class TestPredict:
    def _patch_all(self, monkeypatch, engine, prob: float = 0.80):
        pred = MagicMock()
        pred.is_available = True
        pred.version = "test-v1"
        pred.predict_proba.return_value = prob

        engine._get_predictor = lambda: pred
        engine._calibrator = None
        engine._load_train_stats = lambda: None

        mock_features = MagicMock()
        mock_features.build_extended_features_with_data_layer.return_value = (_make_feature_df(), pd.Series([1]))
        monkeypatch.setitem(
            __import__("sys").modules,
            "ml.features_extended",
            mock_features,
        )
        return pred

    def test_insufficient_bars_returns_neutral(self, engine):
        result = engine.predict(_make_ohlcv(50), symbol="XAU_USD")
        assert result["direction"] == "neutral"
        assert result.get("fallback") is True

    def test_long_signal(self, engine, monkeypatch):
        self._patch_all(monkeypatch, engine, prob=0.80)
        result = engine.predict(
            _make_ohlcv(150),
            symbol="XAU_USD",
            threshold_long=0.58,
            threshold_short=0.42,
        )
        assert result["direction"] == "long"
        assert result["confidence"] > 0

    def test_short_signal(self, engine, monkeypatch):
        self._patch_all(monkeypatch, engine, prob=0.20)
        result = engine.predict(
            _make_ohlcv(150),
            symbol="XAU_USD",
            threshold_long=0.58,
            threshold_short=0.42,
        )
        assert result["direction"] == "short"

    def test_neutral_signal(self, engine, monkeypatch):
        self._patch_all(monkeypatch, engine, prob=0.50)
        result = engine.predict(
            _make_ohlcv(150),
            symbol="XAU_USD",
            threshold_long=0.58,
            threshold_short=0.42,
        )
        assert result["direction"] == "neutral"

    def test_stale_model_block_raises(self, engine, monkeypatch):
        monkeypatch.setattr(ie, "_STALE_MODEL_BLOCK", True)
        self._patch_all(monkeypatch, engine, prob=0.80)
        engine._check_model_staleness = lambda: True
        engine._model_age_days = 45.0
        with pytest.raises(RuntimeError, match="[Ss]tale|STALE"):
            engine.predict(_make_ohlcv(150), symbol="XAU_USD")

    def test_stale_model_warn_only_returns_neutral(self, engine, monkeypatch):
        monkeypatch.setattr(ie, "_STALE_MODEL_BLOCK", False)
        self._patch_all(monkeypatch, engine, prob=0.80)
        engine._check_model_staleness = lambda: True
        engine._model_age_days = 45.0
        result = engine.predict(_make_ohlcv(150), symbol="XAU_USD")
        assert result["direction"] == "neutral"

    def test_no_predictor_returns_neutral(self, engine, monkeypatch):
        no_pred = MagicMock()
        no_pred.is_available = False
        engine._get_predictor = lambda: no_pred
        engine._load_train_stats = lambda: None
        mock_features = MagicMock()
        mock_features.build_extended_features_with_data_layer.return_value = (_make_feature_df(), pd.Series([1]))
        monkeypatch.setitem(__import__("sys").modules, "ml.features_extended", mock_features)
        result = engine.predict(
            _make_ohlcv(150),
            symbol="XAU_USD",
            threshold_long=0.58,
            threshold_short=0.42,
        )
        assert result["direction"] == "neutral"

    def test_online_learner_blend(self, engine, monkeypatch):
        monkeypatch.setattr(ie, "_ONLINE_LEARNING_ENABLED", True)
        self._patch_all(monkeypatch, engine, prob=0.80)
        mock_learner = MagicMock()
        mock_learner.predict_proba.return_value = 0.9
        engine._online_learner = mock_learner
        result = engine.predict(_make_ohlcv(150), symbol="XAU_USD")
        assert result["direction"] in ("long", "short", "neutral")

    def test_result_keys_present(self, engine, monkeypatch):
        self._patch_all(monkeypatch, engine, prob=0.80)
        result = engine.predict(_make_ohlcv(150), symbol="XAU_USD")
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
            assert key in result


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_ok_with_available_predictor(self, engine):
        pred = MagicMock()
        pred.is_available = True
        pred.version = "v1"
        engine._get_predictor = lambda: pred
        engine._first_predict_at = time.time() - 10
        result = engine.health()
        assert result["status"] == "ok"
        assert result["model_available"] is True

    def test_unavailable_with_no_predictor(self, engine):
        no_pred = MagicMock()
        no_pred.is_available = False
        engine._get_predictor = lambda: no_pred
        engine._first_predict_at = None
        engine._predict_count = 0
        result = engine.health()
        assert result["status"] == "unavailable"

    def test_degraded_when_stale(self, engine):
        pred = MagicMock()
        pred.is_available = True
        pred.version = "v1"
        engine._get_predictor = lambda: pred
        engine._first_predict_at = time.time() - 10
        engine._model_stale = True
        # Force staleness check to return True without touching the filesystem
        engine._check_model_staleness = lambda: True
        result = engine.health()
        assert result["status"] in ("degraded", "unavailable")

    def test_health_keys_present(self, engine):
        no_pred = MagicMock()
        no_pred.is_available = False
        engine._get_predictor = lambda: no_pred
        result = engine.health()
        for key in ("status", "model_available", "predict_count", "fallback_rate", "threshold_long", "threshold_short"):
            assert key in result
