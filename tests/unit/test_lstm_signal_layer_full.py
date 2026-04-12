# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for ml/lstm_signal_layer.py.
Targets the 54% → 95%+ branch coverage gap.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n: int = 150) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame."""
    np.random.seed(42)
    close = 1800.0 + np.cumsum(np.random.randn(n))
    return pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.random.randint(100, 1000, n).astype(float),
    })


def _fresh_layer(model_path="nonexistent.pt", seq_len=10, min_bars=20):
    import ml.lstm_signal_layer as lsl
    lsl._lstm_layer = None
    from ml.lstm_signal_layer import LSTMSignalLayer
    return LSTMSignalLayer(model_path=Path(model_path), seq_len=seq_len, min_bars=min_bars)


# ── _load ─────────────────────────────────────────────────────────────────────

class TestLoad:
    def test_returns_false_when_model_file_missing(self):
        layer = _fresh_layer()
        result = layer._load()
        assert result is False
        assert layer._load_attempted is True

    def test_returns_false_on_second_call_after_failure(self):
        layer = _fresh_layer()
        layer._load()
        result = layer._load()  # second call — should short-circuit
        assert result is False

    def test_returns_true_when_already_loaded(self):
        layer = _fresh_layer()
        layer._loaded = True
        assert layer._load() is True

    def test_handles_import_error_gracefully(self, tmp_path):
        p = tmp_path / "model.pt"
        p.write_bytes(b"fake")
        layer = _fresh_layer(model_path=str(p))

        with patch.dict("sys.modules", {"research.pipeline.models_deep": None}):
            result = layer._load()

        assert result is False

    def test_loads_successfully_with_mock_predictor(self, tmp_path):
        p = tmp_path / "model.pt"
        p.write_bytes(b"fake")
        layer = _fresh_layer(model_path=str(p))

        mock_predictor = MagicMock()
        mock_predictor.n_features = 50
        mock_module = MagicMock()
        mock_module.DeepPredictor.load.return_value = mock_predictor

        with patch.dict("sys.modules", {"research.pipeline.models_deep": mock_module}):
            result = layer._load()

        assert result is True
        assert layer._loaded is True
        assert layer._n_features == 50


# ── _neutral ──────────────────────────────────────────────────────────────────

class TestNeutral:
    def test_neutral_returns_correct_structure(self):
        layer = _fresh_layer()
        ohlcv = _make_ohlcv(30)
        result = layer._neutral(ohlcv, reason="test", t0=time.perf_counter())
        assert result["direction"] == "neutral"
        assert result["probability"] == 0.5
        assert result["abstain"] is True
        assert result["reason"] == "test"
        assert "latency_ms" in result

    def test_neutral_with_none_ohlcv(self):
        layer = _fresh_layer()
        result = layer._neutral(None, reason="no_data", t0=time.perf_counter())
        assert result["bars_used"] == 0

    def test_neutral_increments_abstain_count(self):
        layer = _fresh_layer()
        ohlcv = _make_ohlcv(30)
        layer._neutral(ohlcv, reason="test", t0=time.perf_counter())
        assert layer._abstain_count == 1


# ── predict — model unavailable paths ────────────────────────────────────────

class TestPredictModelUnavailable:
    def test_returns_neutral_when_model_missing(self):
        layer = _fresh_layer()
        ohlcv = _make_ohlcv(150)
        result = layer.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_returns_neutral_when_insufficient_bars(self, tmp_path):
        p = tmp_path / "model.pt"
        p.write_bytes(b"fake")
        layer = _fresh_layer(model_path=str(p), seq_len=10, min_bars=50)
        layer._loaded = True
        layer._predictor = MagicMock()

        ohlcv = _make_ohlcv(10)  # too few
        result = layer.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert "insufficient_bars" in result["reason"]

    def test_returns_neutral_when_ohlcv_is_none(self, tmp_path):
        p = tmp_path / "model.pt"
        p.write_bytes(b"fake")
        layer = _fresh_layer(model_path=str(p))
        layer._loaded = True
        layer._predictor = MagicMock()

        result = layer.predict(None)
        assert result["direction"] == "neutral"


# ── predict — sequence build paths ───────────────────────────────────────────

class TestPredictSequenceBuild:
    def _loaded_layer(self, tmp_path):
        p = tmp_path / "model.pt"
        p.write_bytes(b"fake")
        layer = _fresh_layer(model_path=str(p), seq_len=10, min_bars=20)
        layer._loaded = True
        layer._predictor = MagicMock()
        return layer

    def test_returns_neutral_when_sequence_build_fails(self, tmp_path):
        layer = self._loaded_layer(tmp_path)
        ohlcv = _make_ohlcv(150)

        with patch.object(layer, "_build_sequence", return_value=None):
            result = layer.predict(ohlcv)

        assert result["direction"] == "neutral"
        assert result["reason"] == "sequence_build_failed"

    def test_returns_neutral_when_flat_market(self, tmp_path):
        layer = self._loaded_layer(tmp_path)
        ohlcv = _make_ohlcv(150)

        flat_seq = np.zeros((1, 10, 5))  # std == 0
        with patch.object(layer, "_build_sequence", return_value=flat_seq):
            result = layer.predict(ohlcv)

        assert result["direction"] == "neutral"
        assert result["reason"] == "flat_market_low_variance"

    def test_returns_neutral_when_inference_fails(self, tmp_path):
        layer = self._loaded_layer(tmp_path)
        ohlcv = _make_ohlcv(150)

        seq = np.random.randn(1, 10, 5)
        layer._predictor.predict.side_effect = RuntimeError("cuda oom")

        with patch.object(layer, "_build_sequence", return_value=seq):
            result = layer.predict(ohlcv)

        assert result["direction"] == "neutral"
        assert result["reason"] == "inference_failed"


# ── predict — direction branches ──────────────────────────────────────────────

class TestPredictDirections:
    def _layer_with_prob(self, tmp_path, prob: float):
        p = tmp_path / "model.pt"
        p.write_bytes(b"fake")
        layer = _fresh_layer(model_path=str(p), seq_len=10, min_bars=20)
        layer._loaded = True
        mock_pred = MagicMock()
        mock_pred.predict.return_value = np.array([prob])
        layer._predictor = mock_pred
        seq = np.random.randn(1, 10, 5)
        return layer, seq

    def test_long_direction_when_prob_high(self, tmp_path):
        import ml.lstm_signal_layer as lsl
        layer, seq = self._layer_with_prob(tmp_path, 0.80)
        ohlcv = _make_ohlcv(150)
        with patch.object(layer, "_build_sequence", return_value=seq), \
             patch.object(lsl, "_THRESHOLD_LONG", 0.54), \
             patch.object(lsl, "LSTM_ABSTAIN_LOW", 0.46), \
             patch.object(lsl, "LSTM_ABSTAIN_HIGH", 0.54):
            result = layer.predict(ohlcv)
        assert result["direction"] == "long"
        assert result["abstain"] is False

    def test_short_direction_when_prob_low(self, tmp_path):
        import ml.lstm_signal_layer as lsl
        layer, seq = self._layer_with_prob(tmp_path, 0.20)
        ohlcv = _make_ohlcv(150)
        with patch.object(layer, "_build_sequence", return_value=seq), \
             patch.object(lsl, "_THRESHOLD_SHORT", 0.46), \
             patch.object(lsl, "LSTM_ABSTAIN_LOW", 0.46), \
             patch.object(lsl, "LSTM_ABSTAIN_HIGH", 0.54):
            result = layer.predict(ohlcv)
        assert result["direction"] == "short"

    def test_neutral_when_prob_in_dead_band(self, tmp_path):
        import ml.lstm_signal_layer as lsl
        layer, seq = self._layer_with_prob(tmp_path, 0.50)
        ohlcv = _make_ohlcv(150)
        with patch.object(layer, "_build_sequence", return_value=seq), \
             patch.object(lsl, "LSTM_ABSTAIN_LOW", 0.46), \
             patch.object(lsl, "LSTM_ABSTAIN_HIGH", 0.54):
            result = layer.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_high_confidence_flag(self, tmp_path):
        import ml.lstm_signal_layer as lsl
        layer, seq = self._layer_with_prob(tmp_path, 0.90)
        ohlcv = _make_ohlcv(150)
        with patch.object(layer, "_build_sequence", return_value=seq), \
             patch.object(lsl, "LSTM_HIGH_CONF", 0.60), \
             patch.object(lsl, "LSTM_ABSTAIN_LOW", 0.46), \
             patch.object(lsl, "LSTM_ABSTAIN_HIGH", 0.54), \
             patch.object(lsl, "_THRESHOLD_LONG", 0.54):
            result = layer.predict(ohlcv)
        assert result["high_confidence"] is True

    def test_predict_increments_predict_count(self, tmp_path):
        layer, seq = self._layer_with_prob(tmp_path, 0.80)
        ohlcv = _make_ohlcv(150)
        with patch.object(layer, "_build_sequence", return_value=seq):
            layer.predict(ohlcv)
        assert layer._predict_count == 1


# ── _build_sequence ───────────────────────────────────────────────────────────

class TestBuildSequence:
    def test_returns_none_when_advanced_features_fails(self):
        layer = _fresh_layer(seq_len=10)
        ohlcv = _make_ohlcv(50)
        with patch.dict("sys.modules", {"ml.advanced_features": None}):
            result = layer._build_sequence(ohlcv)
        assert result is None

    def test_returns_none_when_X_too_short(self):
        layer = _fresh_layer(seq_len=100)
        ohlcv = _make_ohlcv(50)

        mock_X = pd.DataFrame(np.random.randn(5, 10))  # only 5 rows
        mock_module = MagicMock()
        mock_module.build_advanced_features.return_value = (mock_X, None)

        with patch.dict("sys.modules", {"ml.advanced_features": mock_module}):
            result = layer._build_sequence(ohlcv)
        assert result is None

    def test_returns_array_with_correct_shape(self):
        layer = _fresh_layer(seq_len=5)
        ohlcv = _make_ohlcv(50)

        mock_X = pd.DataFrame(np.random.randn(20, 8))
        mock_module = MagicMock()
        mock_module.build_advanced_features.return_value = (mock_X, None)

        with patch.dict("sys.modules", {"ml.advanced_features": mock_module}):
            result = layer._build_sequence(ohlcv)

        assert result is not None
        assert result.shape == (1, 5, 8)

    def test_replaces_nan_with_zero(self):
        layer = _fresh_layer(seq_len=3)
        ohlcv = _make_ohlcv(20)

        data = np.full((10, 4), np.nan)
        mock_X = pd.DataFrame(data)
        mock_module = MagicMock()
        mock_module.build_advanced_features.return_value = (mock_X, None)

        with patch.dict("sys.modules", {"ml.advanced_features": mock_module}):
            result = layer._build_sequence(ohlcv)

        assert result is not None
        assert np.all(result == 0.0)


# ── stats / is_available ──────────────────────────────────────────────────────

class TestStats:
    def test_stats_returns_expected_keys(self):
        layer = _fresh_layer()
        s = layer.stats
        assert "loaded" in s
        assert "model_path" in s
        assert "seq_len" in s
        assert "min_bars" in s
        assert "n_features" in s
        assert "predict_count" in s
        assert "abstain_count" in s
        assert "abstain_rate" in s
        assert "signal_weight" in s

    def test_abstain_rate_zero_when_no_predictions(self):
        layer = _fresh_layer()
        assert layer.stats["abstain_rate"] == 0.0

    def test_is_available_false_when_not_loaded(self):
        layer = _fresh_layer()
        assert layer.is_available() is False

    def test_is_available_true_when_loaded(self):
        layer = _fresh_layer()
        layer._loaded = True
        assert layer.is_available() is True


# ── Singleton ─────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_lstm_signal_layer_returns_same_instance(self):
        import ml.lstm_signal_layer as lsl
        lsl._lstm_layer = None
        from ml.lstm_signal_layer import get_lstm_signal_layer, LSTMSignalLayer
        a = get_lstm_signal_layer()
        b = get_lstm_signal_layer()
        assert a is b
        assert isinstance(a, LSTMSignalLayer)
