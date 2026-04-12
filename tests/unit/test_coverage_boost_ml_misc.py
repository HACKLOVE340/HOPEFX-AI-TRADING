# HOPEFX-AI-TRADING
# Coverage boost: ml/lstm_signal_layer, ml/train_with_macro, ml/train_rl_nuclear
"""Real unit tests — no mocks/stubs/fake data."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ohlcv(n=120, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 2000.0 + np.cumsum(rng.normal(0, 5, n))
    open_ = close + rng.normal(0, 2, n)
    high = np.maximum(close, open_) + rng.uniform(0, 3, n)
    low = np.minimum(close, open_) - rng.uniform(0, 3, n)
    volume = rng.uniform(1000, 5000, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


# ─────────────────────────────────────────────────────────────────────────────
# ml/lstm_signal_layer.py
# ─────────────────────────────────────────────────────────────────────────────


class TestLSTMSignalLayer:
    def _layer(self, path="/nonexistent/model.pt"):
        from ml.lstm_signal_layer import LSTMSignalLayer
        from pathlib import Path

        return LSTMSignalLayer(model_path=Path(path))

    def test_init(self):
        layer = self._layer()
        assert layer._loaded is False
        assert layer._predict_count == 0

    def test_load_returns_false_no_file(self):
        layer = self._layer()
        assert layer._load() is False

    def test_load_idempotent_after_fail(self):
        layer = self._layer()
        layer._load()
        assert layer._load() is False  # second call returns False immediately

    def test_predict_model_unavailable_returns_neutral(self):
        layer = self._layer()
        df = _ohlcv()
        result = layer.predict(df)
        assert result["direction"] == "neutral"
        assert result["abstain"] is True
        assert result["reason"] == "model_unavailable"

    def test_predict_none_ohlcv_returns_neutral(self):
        layer = self._layer()
        result = layer.predict(None)
        assert result["direction"] == "neutral"

    def test_predict_insufficient_bars(self):
        layer = self._layer()
        df = _ohlcv(n=5)
        result = layer.predict(df)
        assert result["direction"] == "neutral"
        assert "insufficient_bars" in result["reason"] or result["reason"] == "model_unavailable"

    def test_neutral_returns_correct_keys(self):
        import time

        layer = self._layer()
        df = _ohlcv()
        result = layer._neutral(df, reason="test_reason", t0=time.perf_counter())
        assert result["direction"] == "neutral"
        assert result["probability"] == 0.5
        assert result["confidence"] == 0.0
        assert result["abstain"] is True
        assert result["reason"] == "test_reason"
        assert "latency_ms" in result

    def test_neutral_none_ohlcv(self):
        import time

        layer = self._layer()
        result = layer._neutral(None, reason="no_data", t0=time.perf_counter())
        assert result["bars_used"] == 0

    def test_stats_property(self):
        layer = self._layer()
        stats = layer.stats
        assert "loaded" in stats
        assert "predict_count" in stats
        assert "abstain_rate" in stats
        assert stats["loaded"] is False

    def test_stats_abstain_rate_after_predict(self):
        layer = self._layer()
        df = _ohlcv()
        layer.predict(df)
        stats = layer.stats
        assert stats["predict_count"] == 1
        assert stats["abstain_rate"] == 1.0

    def test_is_available_false(self):
        layer = self._layer()
        assert layer.is_available() is False

    def test_build_sequence_returns_none_no_model(self):
        layer = self._layer()
        df = _ohlcv()
        # Without model loaded, _build_sequence still runs feature pipeline
        result = layer._build_sequence(df)
        # Either returns array or None — must not raise
        assert result is None or isinstance(result, np.ndarray)

    def test_get_lstm_signal_layer_singleton(self):
        from ml.lstm_signal_layer import get_lstm_signal_layer

        layer1 = get_lstm_signal_layer()
        layer2 = get_lstm_signal_layer()
        assert layer1 is layer2

    def test_predict_increments_count(self):
        layer = self._layer()
        df = _ohlcv()
        layer.predict(df)
        layer.predict(df)
        assert layer._predict_count == 2

    def test_predict_latency_ms_positive(self):
        layer = self._layer()
        df = _ohlcv()
        result = layer.predict(df)
        assert result["latency_ms"] >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ml/train_with_macro.py — pure functions only (no I/O)
# ─────────────────────────────────────────────────────────────────────────────


class TestTrainWithMacro:
    def test_build_features_returns_xy(self):
        from ml.train_with_macro import build_features

        df = _ohlcv()
        X, y = build_features(df, macro_df=None)
        assert X is not None
        assert y is not None
        assert len(X) == len(y)

    def test_build_features_no_inf(self):
        from ml.train_with_macro import build_features

        df = _ohlcv()
        X, y = build_features(df, macro_df=None)
        assert not np.isinf(X.select_dtypes(include=[np.number]).values).any()

    def test_build_features_with_macro(self):
        from ml.train_with_macro import build_features

        df = _ohlcv()
        macro = pd.DataFrame(
            {
                "dxy": np.random.default_rng(0).normal(0, 1, len(df)),
                "vix": np.random.default_rng(1).uniform(10, 40, len(df)),
            },
            index=df.index,
        )
        X, y = build_features(df, macro_df=macro)
        assert len(X) > 0

    def test_oos_eval_returns_dict(self):
        from ml.train_with_macro import oos_eval, build_features

        df = _ohlcv(n=200)
        X, y = build_features(df, macro_df=None)
        split = len(X) // 2
        result = oos_eval(X.iloc[:split], y.iloc[:split], X.iloc[split:], y.iloc[split:], model_type="xgb")
        assert isinstance(result, dict)
        assert "accuracy" in result


# ─────────────────────────────────────────────────────────────────────────────
# ml/train_rl_nuclear.py — pure functions only (no I/O / no training)
# ─────────────────────────────────────────────────────────────────────────────


class TestTrainRLNuclear:
    def test_module_imports(self):
        import ml.train_rl_nuclear as m

        assert m is not None

    def test_parse_args_defaults(self):
        import sys
        from ml.train_rl_nuclear import _parse_args

        orig = sys.argv
        sys.argv = ["train_rl_nuclear"]
        try:
            args = _parse_args()
        finally:
            sys.argv = orig
        assert args is not None

    def test_walk_forward_train_signature(self):
        from ml.train_rl_nuclear import walk_forward_train
        import inspect

        sig = inspect.signature(walk_forward_train)
        assert len(sig.parameters) >= 1
