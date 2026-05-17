# HOPEFX-AI-TRADING
# Tests for ml/advanced_predictor.py
"""
Full branch coverage for _SGDAdapter, AdvancedPredictor, HybridEnsemblePredictor,
get_predictor(), and get_hybrid_predictor().
joblib.load and build_advanced_features are mocked — no real model file needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import ml.advanced_predictor as ap_mod
from ml.advanced_predictor import (
    AdvancedPredictor,
    _SGDAdapter,
    get_predictor,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n=200, seed=42):
    rng = np.random.default_rng(seed)
    close = 2000.0 + np.cumsum(rng.normal(0, 5, n))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 1, n),
            "high": close + rng.uniform(1, 10, n),
            "low": close - rng.uniform(1, 10, n),
            "close": close,
            "volume": rng.uniform(1000, 5000, n),
        }
    )


def _make_mock_sklearn_model(prob=0.75, n_features=10):
    """Return a mock sklearn Pipeline with predict_proba."""
    model = MagicMock()
    model.predict_proba.return_value = np.array([[1 - prob, prob]])
    model.feature_names_in_ = [f"f{i}" for i in range(n_features)]
    return model


def _make_features(n_rows=1, n_cols=10):
    # Use at least 5 rows so std(axis=0) is non-zero and the variance check
    # in AdvancedPredictor.predict() does not fire before predict_proba.
    actual_rows = max(n_rows, 5)
    rng = np.random.default_rng(0)
    X = pd.DataFrame(
        rng.standard_normal((actual_rows, n_cols)),
        columns=[f"f{i}" for i in range(n_cols)],
    )
    y = pd.Series(rng.integers(0, 2, actual_rows))
    return X, y


def _make_predictor(model_path=None, min_bars=50):
    path = model_path or Path("ml/saved_models/advanced_oos.pkl")
    return AdvancedPredictor(model_path=path, min_bars=min_bars)


# ── _SGDAdapter ───────────────────────────────────────────────────────────────


class TestSGDAdapter:
    def test_init_creates_clf(self):
        adapter = _SGDAdapter(n_features=10)
        assert adapter._clf is not None

    def test_predict_proba_before_fit_returns_none(self):
        adapter = _SGDAdapter(n_features=10)
        x = np.random.randn(10)
        result = adapter.predict_proba(x)
        assert result is None

    def test_update_increments_n_updates(self, monkeypatch):
        monkeypatch.setattr(ap_mod, "ONLINE_LEARNING_ENABLED", True)
        adapter = _SGDAdapter(n_features=10)
        x = np.random.randn(10)
        adapter.update(x, 1)
        adapter.update(x, 0)
        assert adapter.n_updates == 2

    def test_predict_proba_after_update_returns_float(self, monkeypatch):
        monkeypatch.setattr(ap_mod, "ONLINE_LEARNING_ENABLED", True)
        adapter = _SGDAdapter(n_features=10)
        x = np.random.randn(10)
        adapter.update(x, 1)
        adapter.update(x, 0)
        result = adapter.predict_proba(x)
        assert result is None or isinstance(result, float)

    def test_predict_proba_after_both_classes_seen(self, monkeypatch):
        monkeypatch.setattr(ap_mod, "ONLINE_LEARNING_ENABLED", True)
        adapter = _SGDAdapter(n_features=10)
        rng = np.random.default_rng(42)
        for _ in range(10):
            adapter.update(rng.standard_normal(10), 1)
            adapter.update(rng.standard_normal(10), 0)
        x = rng.standard_normal(10)
        result = adapter.predict_proba(x)
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_update_exception_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(ap_mod, "ONLINE_LEARNING_ENABLED", True)
        adapter = _SGDAdapter(n_features=10)
        adapter._clf = MagicMock()
        adapter._clf.partial_fit.side_effect = RuntimeError("fit error")
        adapter.update(np.random.randn(10), 1)  # must not raise

    def test_sklearn_unavailable_clf_is_none(self, monkeypatch):
        """When SGDClassifier import fails, _clf stays None."""
        import sklearn.linear_model as slm

        monkeypatch.setattr(slm, "SGDClassifier", MagicMock(side_effect=ImportError("no sklearn")))
        adapter = _SGDAdapter.__new__(_SGDAdapter)
        adapter.n_features = 10
        adapter._n_updates = 0
        adapter._classes_seen = set()
        adapter._clf = None
        import threading

        adapter._lock = threading.Lock()
        adapter._init_clf()
        assert adapter._clf is None


# ── AdvancedPredictor._load ───────────────────────────────────────────────────


class TestAdvancedPredictorLoad:
    def test_load_returns_false_when_file_missing(self, tmp_path):
        pred = _make_predictor(model_path=tmp_path / "nonexistent.pkl")
        result = pred._load()
        assert result is False
        assert pred._model is None

    def test_load_returns_true_when_already_loaded(self):
        pred = _make_predictor()
        pred._model = MagicMock()
        assert pred._load() is True

    def test_load_success_with_mock_joblib(self, tmp_path):
        model_file = tmp_path / "advanced_oos.pkl"
        model_file.write_bytes(b"fake")
        mock_model = _make_mock_sklearn_model()

        with patch("joblib.load", return_value=mock_model):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file)
                result = pred._load()

        assert result is True
        assert pred._model is mock_model

    def test_load_joblib_raises_returns_false(self, tmp_path):
        model_file = tmp_path / "advanced_oos.pkl"
        model_file.write_bytes(b"fake")

        with patch("joblib.load", side_effect=RuntimeError("corrupt")):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file)
                result = pred._load()

        assert result is False
        assert pred._model is None

    def test_load_integrity_failure_returns_false(self, tmp_path):
        model_file = tmp_path / "advanced_oos.pkl"
        model_file.write_bytes(b"fake")

        with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=False):
            pred = _make_predictor(model_path=model_file)
            result = pred._load()

        assert result is False


# ── AdvancedPredictor.predict — early exits ───────────────────────────────────


class TestAdvancedPredictorEarlyExits:
    def test_predict_model_unavailable(self, tmp_path):
        pred = _make_predictor(model_path=tmp_path / "nonexistent.pkl")
        ohlcv = _make_ohlcv(200)
        result = pred.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["abstain_reason"] == "model_unavailable"

    def test_predict_insufficient_bars(self, tmp_path):
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"fake")
        mock_model = _make_mock_sklearn_model()

        with patch("joblib.load", return_value=mock_model):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file, min_bars=100)
                pred._load()

        ohlcv = _make_ohlcv(50)  # fewer than min_bars
        result = pred.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert "insufficient_bars" in result["abstain_reason"]

    def test_predict_feature_build_failed(self, tmp_path):
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"fake")
        mock_model = _make_mock_sklearn_model()

        with patch("joblib.load", return_value=mock_model):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file, min_bars=50)
                pred._load()

        ohlcv = _make_ohlcv(200)
        with patch.object(pred, "_build_features", return_value=None):
            result = pred.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["abstain_reason"] == "feature_build_failed"

    def test_predict_flat_market_abstains(self, tmp_path):
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"fake")
        mock_model = _make_mock_sklearn_model()

        with patch("joblib.load", return_value=mock_model):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file, min_bars=50)
                pred._load()

        ohlcv = _make_ohlcv(200)
        flat_X = pd.DataFrame(np.zeros((1, 10)), columns=[f"f{i}" for i in range(10)])
        with patch.object(pred, "_build_features", return_value=flat_X):
            result = pred.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["abstain_reason"] == "flat_market_low_variance"

    def test_predict_model_predict_proba_fails(self, tmp_path):
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"fake")
        mock_model = _make_mock_sklearn_model()
        mock_model.predict_proba.side_effect = RuntimeError("predict error")

        with patch("joblib.load", return_value=mock_model):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file, min_bars=50)
                pred._load()

        ohlcv = _make_ohlcv(200)
        # Use 10 rows so the per-feature variance check passes (std(axis=0) on
        # a single row is always 0, triggering flat_market_low_variance instead).
        X, _ = _make_features(10, 10)
        with patch.object(pred, "_build_features", return_value=X):
            result = pred.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["abstain_reason"] == "predict_failed"


# ── AdvancedPredictor.predict — direction thresholding ───────────────────────


class TestAdvancedPredictorDirections:
    def _setup_pred(self, tmp_path, prob):
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"fake")
        mock_model = _make_mock_sklearn_model(prob=prob)

        with patch("joblib.load", return_value=mock_model):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file, min_bars=50)
                pred._load()
        return pred

    def test_long_direction(self, tmp_path):
        pred = self._setup_pred(tmp_path, prob=0.80)
        ohlcv = _make_ohlcv(200)
        X, _ = _make_features(10, 10)
        with patch.object(pred, "_build_features", return_value=X):
            result = pred.predict(ohlcv)
        assert result["direction"] == "long"
        assert result["abstain"] is False

    def test_short_direction(self, tmp_path):
        pred = self._setup_pred(tmp_path, prob=0.20)
        ohlcv = _make_ohlcv(200)
        X, _ = _make_features(10, 10)
        with patch.object(pred, "_build_features", return_value=X):
            result = pred.predict(ohlcv)
        assert result["direction"] == "short"
        assert result["abstain"] is False

    def test_neutral_dead_band(self, tmp_path):
        pred = self._setup_pred(tmp_path, prob=0.50)
        ohlcv = _make_ohlcv(200)
        X, _ = _make_features(1, 10)
        with patch.object(pred, "_build_features", return_value=X):
            result = pred.predict(ohlcv)
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_high_confidence_flag(self, tmp_path):
        pred = self._setup_pred(tmp_path, prob=0.90)
        ohlcv = _make_ohlcv(200)
        X, _ = _make_features(10, 10)
        with patch.object(pred, "_build_features", return_value=X):
            result = pred.predict(ohlcv)
        assert result["high_confidence"] is True

    def test_predict_count_increments(self, tmp_path):
        pred = self._setup_pred(tmp_path, prob=0.80)
        ohlcv = _make_ohlcv(200)
        X, _ = _make_features(1, 10)
        with patch.object(pred, "_build_features", return_value=X):
            pred.predict(ohlcv)
            pred.predict(ohlcv)
        assert pred._predict_count == 2

    def test_result_contains_required_keys(self, tmp_path):
        pred = self._setup_pred(tmp_path, prob=0.75)
        ohlcv = _make_ohlcv(200)
        X, _ = _make_features(1, 10)
        with patch.object(pred, "_build_features", return_value=X):
            result = pred.predict(ohlcv)
        for key in (
            "direction",
            "probability",
            "confidence",
            "high_confidence",
            "abstain",
            "model_version",
            "bars_used",
            "last_close",
            "feature_count",
            "latency_ms",
        ):
            assert key in result


# ── AdvancedPredictor.predict — probability field ─────────────────────────────


class TestAdvancedPredictorProbabilityField:
    def test_predict_returns_probability_float(self, tmp_path):
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"fake")
        mock_model = _make_mock_sklearn_model(prob=0.75)

        with patch("joblib.load", return_value=mock_model):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file, min_bars=50)
                pred._load()

        ohlcv = _make_ohlcv(200)
        X, _ = _make_features(1, 10)
        with patch.object(pred, "_build_features", return_value=X):
            result = pred.predict(ohlcv)
        assert isinstance(result["probability"], float)
        assert 0.0 <= result["probability"] <= 1.0

    def test_predict_returns_05_probability_when_unavailable(self, tmp_path):
        pred = _make_predictor(model_path=tmp_path / "nonexistent.pkl")
        ohlcv = _make_ohlcv(200)
        result = pred.predict(ohlcv)
        assert result["probability"] == pytest.approx(0.5)


# ── AdvancedPredictor.update ──────────────────────────────────────────────────


class TestAdvancedPredictorUpdate:
    def test_update_returns_false_when_model_unavailable(self, tmp_path):
        pred = _make_predictor(model_path=tmp_path / "nonexistent.pkl")
        ohlcv = _make_ohlcv(200)
        result = pred.update(ohlcv, label=1)
        assert result is False

    def test_update_returns_true_when_model_loaded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ap_mod, "ONLINE_LEARNING_ENABLED", True)
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"fake")
        mock_model = _make_mock_sklearn_model()

        with patch("joblib.load", return_value=mock_model):
            with patch("ml.advanced_predictor.AdvancedPredictor._verify_integrity", return_value=True):
                pred = _make_predictor(model_path=model_file, min_bars=50)
                pred._load()

        ohlcv = _make_ohlcv(200)
        X, _ = _make_features(1, 10)
        with patch.object(pred, "_build_features", return_value=X):
            result = pred.update(ohlcv, label=1)
        assert result is True


# ── AdvancedPredictor.is_available / version ──────────────────────────────────


class TestAdvancedPredictorProperties:
    def test_is_available_false_when_file_missing(self, tmp_path):
        pred = _make_predictor(model_path=tmp_path / "nonexistent.pkl")
        assert pred.is_available is False

    def test_is_available_true_when_file_exists(self, tmp_path):
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"fake")
        pred = _make_predictor(model_path=model_file)
        assert pred.is_available is True

    def test_version_is_string(self):
        pred = _make_predictor()
        assert isinstance(pred.version, str)

    def test_stats_initial_state(self):
        pred = _make_predictor()
        s = pred.stats
        assert s["predict_count"] == 0
        assert s["abstain_count"] == 0
        assert s["model_loaded"] is False


# ── get_predictor singleton ───────────────────────────────────────────────────


class TestGetPredictor:
    def test_singleton_returns_same_instance(self):
        ap_mod._predictor = None
        p1 = get_predictor()
        p2 = get_predictor()
        assert p1 is p2
        ap_mod._predictor = None

    def test_singleton_is_advanced_predictor(self):
        ap_mod._predictor = None
        p = get_predictor()
        assert isinstance(p, AdvancedPredictor)
        ap_mod._predictor = None


# ── HybridEnsemblePredictor ───────────────────────────────────────────────────


class TestHybridEnsemblePredictor:
    def test_hybrid_instantiates(self):
        from ml.advanced_predictor import HybridEnsemblePredictor

        hybrid = HybridEnsemblePredictor()
        assert hybrid is not None

    def test_hybrid_predict_proba_returns_float(self):
        from ml.advanced_predictor import HybridEnsemblePredictor

        hybrid = HybridEnsemblePredictor()
        X = np.random.randn(1, 10)
        # _xgb_predict falls back to 0.5 when model not loaded
        result = hybrid.predict_proba(X)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_hybrid_effective_weights_no_lstm_no_rl(self):
        from ml.advanced_predictor import HybridEnsemblePredictor

        hybrid = HybridEnsemblePredictor()
        hybrid._has_lstm = False
        hybrid._has_rl = False
        w_xgb, w_lstm, w_rl = hybrid._effective_weights()
        assert w_xgb == pytest.approx(1.0)
        assert w_lstm == pytest.approx(0.0)
        assert w_rl == pytest.approx(0.0)

    def test_hybrid_effective_weights_all_unavailable(self):
        from ml.advanced_predictor import HybridEnsemblePredictor

        hybrid = HybridEnsemblePredictor()
        hybrid._has_xgb = False
        hybrid._has_lstm = False
        hybrid._has_rl = False
        w_xgb, w_lstm, w_rl = hybrid._effective_weights()
        # Falls back to (1.0, 0.0, 0.0)
        assert w_xgb == pytest.approx(1.0)

    def test_hybrid_xgb_predict_returns_05_when_no_model(self):
        from ml.advanced_predictor import HybridEnsemblePredictor

        hybrid = HybridEnsemblePredictor()
        X = np.random.randn(1, 10)
        result = hybrid._xgb_predict(X)
        assert result == pytest.approx(0.5)

    def test_hybrid_lstm_predict_returns_05_when_unavailable(self):
        from ml.advanced_predictor import HybridEnsemblePredictor

        hybrid = HybridEnsemblePredictor()
        hybrid._has_lstm = False
        X_seq = np.random.randn(1, 60, 10)
        result = hybrid._lstm_predict(X_seq)
        assert result == pytest.approx(0.5)

    def test_get_hybrid_predictor_singleton(self):
        from ml.advanced_predictor import get_hybrid_predictor

        ap_mod._hybrid_predictor = None
        h1 = get_hybrid_predictor()
        h2 = get_hybrid_predictor()
        assert h1 is h2
        ap_mod._hybrid_predictor = None
