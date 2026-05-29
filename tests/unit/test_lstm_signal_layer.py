# HOPEFX-AI-TRADING
# Tests for ml/lstm_signal_layer.py
"""
Full branch coverage for LSTMSignalLayer and get_lstm_signal_layer().
DeepPredictor and build_advanced_features are mocked — no torch required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import ml.lstm_signal_layer as lstm_mod
from ml.lstm_signal_layer import (
    LSTMSignalLayer,
    get_lstm_signal_layer,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n=200):
    """Return a minimal OHLCV DataFrame with n rows."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame(
        {
            "open": np.random.uniform(1900, 2100, n),
            "high": np.random.uniform(2000, 2200, n),
            "low": np.random.uniform(1800, 2000, n),
            "close": np.random.uniform(1900, 2100, n),
            "volume": np.random.uniform(1000, 5000, n),
        },
        index=idx,
    )


def _make_layer(model_path=None, seq_len=10, min_bars=20):
    return LSTMSignalLayer(
        model_path=model_path or Path("ml/saved_models/lstm_signal.pt"),
        seq_len=seq_len,
        min_bars=min_bars,
    )


def _make_mock_predictor(prob=0.7, n_features=10):
    pred = MagicMock()
    pred.n_features = n_features
    pred.predict.return_value = np.array([prob])
    return pred


def _mock_features(n_rows=50, n_cols=10):
    X = pd.DataFrame(np.random.randn(n_rows, n_cols), columns=[f"f{i}" for i in range(n_cols)])
    y = pd.Series(np.random.randint(0, 2, n_rows))
    return X, y


# ── _load ─────────────────────────────────────────────────────────────────────


class TestLoad:
    def test_load_returns_false_when_file_missing(self, tmp_path):
        layer = _make_layer(model_path=tmp_path / "nonexistent.pt")
        result = layer._load()
        assert result is False
        assert layer._loaded is False

    def test_load_not_retried_after_failure(self, tmp_path):
        layer = _make_layer(model_path=tmp_path / "nonexistent.pt")
        layer._load()
        layer._load()  # second call should not attempt again
        assert layer._load_attempted is True

    def test_load_success(self, tmp_path):
        model_file = tmp_path / "lstm_signal.pt"
        model_file.write_bytes(b"fake model")

        mock_predictor = _make_mock_predictor()
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = mock_predictor

        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file)
            result = layer._load()

        assert result is True
        assert layer._loaded is True
        assert layer._n_features == 10

    def test_load_raises_sets_loaded_false(self, tmp_path):
        model_file = tmp_path / "lstm_signal.pt"
        model_file.write_bytes(b"fake model")

        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.side_effect = RuntimeError("corrupt model")

        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file)
            result = layer._load()

        assert result is False
        assert layer._loaded is False

    def test_load_already_loaded_returns_true(self, tmp_path):
        layer = _make_layer()
        layer._loaded = True
        assert layer._load() is True


# ── _neutral ──────────────────────────────────────────────────────────────────


class TestNeutral:
    def test_neutral_returns_correct_structure(self):
        layer = _make_layer()
        import time

        t0 = time.perf_counter()
        ohlcv = _make_ohlcv(50)
        result = layer._neutral(ohlcv, reason="test", t0=t0)
        assert result["direction"] == "neutral"
        assert result["probability"] == pytest.approx(0.5)
        assert result["abstain"] is True
        assert result["confidence"] == pytest.approx(0.0)
        assert "latency_ms" in result
        assert result["reason"] == "test"

    def test_neutral_with_none_ohlcv(self):
        layer = _make_layer()
        import time

        t0 = time.perf_counter()
        result = layer._neutral(None, reason="no_data", t0=t0)
        assert result["bars_used"] == 0
        assert result["last_close"] == 0.0


# ── predict — early exits ─────────────────────────────────────────────────────


class TestPredictEarlyExits:
    def test_predict_model_unavailable(self):
        layer = _make_layer(model_path=Path("nonexistent.pt"))
        ohlcv = _make_ohlcv(200)
        result = layer.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["reason"] == "model_unavailable"

    def test_predict_insufficient_bars(self, tmp_path):
        model_file = tmp_path / "lstm.pt"
        model_file.write_bytes(b"fake")
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = _make_mock_predictor()
        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file, seq_len=10, min_bars=50)
            layer._load()
        ohlcv = _make_ohlcv(10)  # fewer than min_bars
        result = layer.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert "insufficient_bars" in result["reason"]

    def test_predict_none_ohlcv(self, tmp_path):
        model_file = tmp_path / "lstm.pt"
        model_file.write_bytes(b"fake")
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = _make_mock_predictor()
        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file, seq_len=10, min_bars=20)
            layer._load()
        result = layer.predict(None)
        assert result["direction"] == "neutral"

    def test_predict_sequence_build_failed(self, tmp_path):
        model_file = tmp_path / "lstm.pt"
        model_file.write_bytes(b"fake")
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = _make_mock_predictor()
        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file, seq_len=10, min_bars=20)
            layer._load()

        ohlcv = _make_ohlcv(100)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=None):
            result = layer.predict(ohlcv)
        assert result["reason"] == "sequence_build_failed"

    def test_predict_flat_market_abstains(self, tmp_path):
        model_file = tmp_path / "lstm.pt"
        model_file.write_bytes(b"fake")
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = _make_mock_predictor()
        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file, seq_len=10, min_bars=20)
            layer._load()

        ohlcv = _make_ohlcv(100)
        # Return a flat (zero-variance) sequence
        flat_seq = np.zeros((1, 10, 10), dtype=np.float32)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=flat_seq):
            result = layer.predict(ohlcv)
        assert result["reason"] == "flat_market_low_variance"

    def test_predict_inference_exception(self, tmp_path):
        model_file = tmp_path / "lstm.pt"
        model_file.write_bytes(b"fake")
        mock_predictor = _make_mock_predictor()
        mock_predictor.predict.side_effect = RuntimeError("inference error")
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = mock_predictor
        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file, seq_len=10, min_bars=20)
            layer._load()

        ohlcv = _make_ohlcv(100)
        X_seq = np.random.randn(1, 10, 10).astype(np.float32)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=X_seq):
            result = layer.predict(ohlcv)
        assert result["reason"] == "inference_failed"


# ── predict — direction thresholding ─────────────────────────────────────────


class TestPredictDirections:
    def _setup_layer(self, tmp_path, prob):
        model_file = tmp_path / "lstm.pt"
        model_file.write_bytes(b"fake")
        mock_predictor = _make_mock_predictor(prob=prob)
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = mock_predictor
        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file, seq_len=10, min_bars=20)
            layer._load()
        return layer

    def test_predict_long_direction(self, tmp_path):
        layer = self._setup_layer(tmp_path, prob=0.80)
        ohlcv = _make_ohlcv(100)
        X_seq = np.random.randn(1, 10, 10).astype(np.float32)
        X, y = _mock_features()
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=X_seq):
            result = layer.predict(ohlcv)
        assert result["direction"] == "long"
        assert result["abstain"] is False
        assert result["probability"] == pytest.approx(0.80, abs=0.01)

    def test_predict_short_direction(self, tmp_path):
        layer = self._setup_layer(tmp_path, prob=0.20)
        ohlcv = _make_ohlcv(100)
        X_seq = np.random.randn(1, 10, 10).astype(np.float32)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=X_seq):
            result = layer.predict(ohlcv)
        assert result["direction"] == "short"
        assert result["abstain"] is False

    def test_predict_neutral_dead_band(self, tmp_path):
        # prob=0.50 is in the dead-band [0.46, 0.54]
        layer = self._setup_layer(tmp_path, prob=0.50)
        ohlcv = _make_ohlcv(100)
        X_seq = np.random.randn(1, 10, 10).astype(np.float32)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=X_seq):
            result = layer.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_predict_high_confidence(self, tmp_path):
        layer = self._setup_layer(tmp_path, prob=0.90)
        ohlcv = _make_ohlcv(100)
        X_seq = np.random.randn(1, 10, 10).astype(np.float32)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=X_seq):
            result = layer.predict(ohlcv)
        assert result["high_confidence"] is True

    def test_predict_low_confidence(self, tmp_path):
        layer = self._setup_layer(tmp_path, prob=0.56)
        ohlcv = _make_ohlcv(100)
        X_seq = np.random.randn(1, 10, 10).astype(np.float32)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=X_seq):
            result = layer.predict(ohlcv)
        assert result["high_confidence"] is False

    def test_predict_increments_predict_count(self, tmp_path):
        layer = self._setup_layer(tmp_path, prob=0.80)
        ohlcv = _make_ohlcv(100)
        X_seq = np.random.randn(1, 10, 10).astype(np.float32)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=X_seq):
            layer.predict(ohlcv)
            layer.predict(ohlcv)
        assert layer._predict_count == 2


# ── stats property ────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_initial_state(self):
        layer = _make_layer()
        s = layer.stats
        assert s["loaded"] is False
        assert s["predict_count"] == 0
        assert s["abstain_count"] == 0
        assert s["abstain_rate"] == 0.0

    def test_stats_after_predictions(self, tmp_path):
        model_file = tmp_path / "lstm.pt"
        model_file.write_bytes(b"fake")
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = _make_mock_predictor(prob=0.80)
        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file, seq_len=10, min_bars=20)
            layer._load()

        ohlcv = _make_ohlcv(100)
        X_seq = np.random.randn(1, 10, 10).astype(np.float32)
        with patch("ml.lstm_signal_layer.LSTMSignalLayer._build_sequence", return_value=X_seq):
            layer.predict(ohlcv)

        s = layer.stats
        assert s["predict_count"] == 1
        assert s["loaded"] is True


# ── is_available ──────────────────────────────────────────────────────────────


class TestIsAvailable:
    def test_not_available_before_load(self):
        layer = _make_layer()
        assert layer.is_available() is False

    def test_available_after_successful_load(self, tmp_path):
        model_file = tmp_path / "lstm.pt"
        model_file.write_bytes(b"fake")
        mock_deep = MagicMock()
        mock_deep.DeepPredictor.load.return_value = _make_mock_predictor()
        with patch.dict(sys.modules, {"research.pipeline.models_deep": mock_deep}):
            layer = _make_layer(model_path=model_file)
            layer._load()
        assert layer.is_available() is True


# ── get_lstm_signal_layer singleton ──────────────────────────────────────────


class TestGetLstmSignalLayer:
    def test_singleton_returns_same_instance(self):
        lstm_mod._lstm_layer = None
        l1 = get_lstm_signal_layer()
        l2 = get_lstm_signal_layer()
        assert l1 is l2
        lstm_mod._lstm_layer = None

    def test_singleton_is_layer_instance(self):
        lstm_mod._lstm_layer = None
        layer = get_lstm_signal_layer()
        assert isinstance(layer, LSTMSignalLayer)
        lstm_mod._lstm_layer = None
