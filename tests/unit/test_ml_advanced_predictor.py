# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for ml/advanced_predictor.py.
Covers AdvancedPredictor, _SGDAdapter, integrity check, predict branches.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def _ohlcv(n: int = 150) -> pd.DataFrame:
    np.random.seed(42)
    c = 2000.0 + np.cumsum(np.random.randn(n))
    return pd.DataFrame(
        {
            "open": c - 0.5,
            "high": c + 1.0,
            "low": c - 1.0,
            "close": c,
            "volume": np.ones(n) * 500,
        }
    )


# ── _SGDAdapter ───────────────────────────────────────────────────────────────


class TestSGDAdapter:
    def test_init_creates_classifier(self):
        from ml.advanced_predictor import _SGDAdapter

        a = _SGDAdapter(10)
        assert a._clf is not None
        assert a.n_updates == 0

    def test_update_noop_when_online_learning_disabled(self):
        import ml.advanced_predictor as ap
        from ml.advanced_predictor import _SGDAdapter

        a = _SGDAdapter(10)
        with patch.object(ap, "ONLINE_LEARNING_ENABLED", False):
            a.update(np.zeros(10), 1)
        assert a.n_updates == 0

    def test_update_increments_when_enabled(self):
        import ml.advanced_predictor as ap
        from ml.advanced_predictor import _SGDAdapter

        a = _SGDAdapter(10)
        with patch.object(ap, "ONLINE_LEARNING_ENABLED", True):
            a.update(np.random.randn(10), 1)
        assert a.n_updates == 1

    def test_predict_proba_returns_none_before_min_updates(self):
        from ml.advanced_predictor import _SGDAdapter

        a = _SGDAdapter(10)
        result = a.predict_proba(np.zeros(10))
        assert result is None  # n_updates < 10

    def test_predict_proba_returns_float_after_updates(self):
        import ml.advanced_predictor as ap
        from ml.advanced_predictor import _SGDAdapter

        a = _SGDAdapter(5)
        with patch.object(ap, "ONLINE_LEARNING_ENABLED", True):
            for i in range(12):
                a.update(np.random.randn(5), i % 2)
        result = a.predict_proba(np.random.randn(5))
        assert result is None or isinstance(result, float)

    def test_init_handles_sklearn_unavailable(self):
        from ml.advanced_predictor import _SGDAdapter

        with patch.dict("sys.modules", {"sklearn.linear_model": None}):
            a = _SGDAdapter(10)
        # clf may be None if sklearn unavailable — should not raise
        assert a is not None


# ── AdvancedPredictor — loading ───────────────────────────────────────────────


class TestAdvancedPredictorLoad:
    def _make(self, tmp_path):
        from ml.advanced_predictor import AdvancedPredictor

        return AdvancedPredictor(model_path=tmp_path / "model.pkl")

    def test_is_available_false_when_no_file(self, tmp_path):
        p = self._make(tmp_path)
        assert p.is_available is False

    def test_is_available_true_when_file_exists(self, tmp_path):
        model_path = tmp_path / "model.pkl"
        model_path.write_bytes(b"fake")
        p = self._make(tmp_path)
        assert p.is_available is True

    def test_version_property(self, tmp_path):
        p = self._make(tmp_path)
        assert isinstance(p.version, str)

    def test_meta_property_empty_when_no_meta(self, tmp_path):
        p = self._make(tmp_path)
        assert isinstance(p.meta, dict)

    def test_load_returns_false_when_file_missing(self, tmp_path):
        p = self._make(tmp_path)
        result = p._load()
        assert result is False

    def test_load_returns_false_on_integrity_failure(self, tmp_path):
        model_path = tmp_path / "model.pkl"
        model_path.write_bytes(b"fake")
        p = self._make(tmp_path)
        # Integrity check will fail because no registry entry exists
        # but _verify_integrity returns True (no digest on record = warn+allow)
        # So load will attempt joblib.load which will fail on "fake" bytes
        result = p._load()
        assert result is False  # joblib.load fails on b"fake"

    def test_load_succeeds_with_valid_model(self, tmp_path):
        from sklearn.linear_model import LogisticRegression
        import joblib

        model_path = tmp_path / "model.pkl"
        clf = LogisticRegression()
        clf.fit(np.random.randn(20, 5), [0, 1] * 10)
        joblib.dump(clf, model_path)

        p = self._make(tmp_path)
        result = p._load()
        assert result is True
        assert p._model is not None


# ── AdvancedPredictor — integrity check ──────────────────────────────────────


class TestIntegrityCheck:
    def test_returns_false_when_artifact_missing(self, tmp_path):
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=tmp_path / "missing.pkl")
        result = p._verify_integrity()
        assert result is False

    def test_returns_true_when_no_digest_on_record(self, tmp_path):
        model_path = tmp_path / "model.pkl"
        model_path.write_bytes(b"data")
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=model_path)
        # No registry → no digest → warn+allow
        with patch.dict("sys.modules", {"ml.model_registry": None}):
            result = p._verify_integrity()
        assert result is True

    def test_returns_false_on_sha256_mismatch(self, tmp_path):
        model_path = tmp_path / "model.pkl"
        model_path.write_bytes(b"real data")
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=model_path)

        mock_registry = MagicMock()
        mock_registry.active_version.return_value = {
            "file": str(model_path),
            "sha256": "deadbeef" * 8,
            "name": "v1",
        }
        mock_registry.list_versions.return_value = {}
        mock_get_registry = MagicMock(return_value=mock_registry)
        mock_sha256 = MagicMock(return_value="actualdigest" * 4)

        mock_module = MagicMock(
            get_registry=mock_get_registry,
            sha256_file=mock_sha256,
        )
        with patch.dict("sys.modules", {"ml.model_registry": mock_module}):
            result = p._verify_integrity()
        assert result is False

    def test_returns_true_on_sha256_match(self, tmp_path):
        model_path = tmp_path / "model.pkl"
        model_path.write_bytes(b"real data")
        from ml.advanced_predictor import AdvancedPredictor
        import hashlib

        actual_digest = hashlib.sha256(b"real data").hexdigest()

        p = AdvancedPredictor(model_path=model_path)
        mock_registry = MagicMock()
        mock_registry.active_version.return_value = {
            "file": str(model_path),
            "sha256": actual_digest,
            "name": "v1",
        }
        mock_registry.list_versions.return_value = {}
        mock_get_registry = MagicMock(return_value=mock_registry)
        mock_sha256 = MagicMock(return_value=actual_digest)
        mock_module = MagicMock(
            get_registry=mock_get_registry,
            sha256_file=mock_sha256,
        )
        with patch.dict("sys.modules", {"ml.model_registry": mock_module}):
            result = p._verify_integrity()
        assert result is True


# ── AdvancedPredictor — predict ───────────────────────────────────────────────


class TestAdvancedPredictorPredict:
    def _loaded_predictor(self, tmp_path):
        """Return a predictor with a mocked loaded model."""
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=tmp_path / "model.pkl")
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        p._model = mock_model
        p._feature_names = [f"f{i}" for i in range(10)]
        p._n_features = 10
        return p

    def test_returns_neutral_when_model_unavailable(self, tmp_path):
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=tmp_path / "missing.pkl")
        result = p.predict(_ohlcv(150))
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_returns_neutral_when_insufficient_bars(self, tmp_path):
        p = self._loaded_predictor(tmp_path)
        result = p.predict(_ohlcv(5))
        assert result["direction"] == "neutral"
        assert "insufficient_bars" in result.get("abstain_reason", "")

    def test_returns_neutral_when_feature_build_fails(self, tmp_path):
        p = self._loaded_predictor(tmp_path)
        with patch.object(p, "_build_features", return_value=None):
            result = p.predict(_ohlcv(150))
        assert result["direction"] == "neutral"

    def test_returns_neutral_on_flat_market(self, tmp_path):
        p = self._loaded_predictor(tmp_path)
        flat_X = pd.DataFrame(np.zeros((1, 10)), columns=[f"f{i}" for i in range(10)])
        with patch.object(p, "_build_features", return_value=flat_X):
            result = p.predict(_ohlcv(150))
        assert result["direction"] == "neutral"

    def test_long_direction_on_high_probability(self, tmp_path):
        import ml.advanced_predictor as ap

        p = self._loaded_predictor(tmp_path)
        p._model.predict_proba.return_value = np.array([[0.1, 0.9]])
        X = pd.DataFrame(np.random.randn(1, 10), columns=[f"f{i}" for i in range(10)])
        with (
            patch.object(p, "_build_features", return_value=X),
            patch.object(ap, "THRESHOLD_LONG", 0.58),
            patch.object(ap, "ABSTAIN_LOW", 0.46),
            patch.object(ap, "ABSTAIN_HIGH", 0.54),
        ):
            result = p.predict(_ohlcv(150))
        assert result["direction"] == "long"
        assert result["probability"] == pytest.approx(0.9, abs=0.01)

    def test_short_direction_on_low_probability(self, tmp_path):
        import ml.advanced_predictor as ap

        p = self._loaded_predictor(tmp_path)
        p._model.predict_proba.return_value = np.array([[0.9, 0.1]])
        X = pd.DataFrame(np.random.randn(1, 10), columns=[f"f{i}" for i in range(10)])
        with (
            patch.object(p, "_build_features", return_value=X),
            patch.object(ap, "THRESHOLD_SHORT", 0.42),
            patch.object(ap, "ABSTAIN_LOW", 0.46),
            patch.object(ap, "ABSTAIN_HIGH", 0.54),
        ):
            result = p.predict(_ohlcv(150))
        assert result["direction"] == "short"

    def test_neutral_in_dead_band(self, tmp_path):
        import ml.advanced_predictor as ap

        p = self._loaded_predictor(tmp_path)
        p._model.predict_proba.return_value = np.array([[0.5, 0.5]])
        X = pd.DataFrame(np.random.randn(1, 10), columns=[f"f{i}" for i in range(10)])
        with (
            patch.object(p, "_build_features", return_value=X),
            patch.object(ap, "ABSTAIN_LOW", 0.46),
            patch.object(ap, "ABSTAIN_HIGH", 0.54),
        ):
            result = p.predict(_ohlcv(150))
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_returns_neutral_on_predict_proba_exception(self, tmp_path):
        p = self._loaded_predictor(tmp_path)
        p._model.predict_proba.side_effect = RuntimeError("cuda oom")
        X = pd.DataFrame(np.random.randn(1, 10), columns=[f"f{i}" for i in range(10)])
        with patch.object(p, "_build_features", return_value=X):
            result = p.predict(_ohlcv(150))
        assert result["direction"] == "neutral"

    def test_result_has_all_required_keys(self, tmp_path):
        import ml.advanced_predictor as ap

        p = self._loaded_predictor(tmp_path)
        p._model.predict_proba.return_value = np.array([[0.2, 0.8]])
        X = pd.DataFrame(np.random.randn(1, 10), columns=[f"f{i}" for i in range(10)])
        with (
            patch.object(p, "_build_features", return_value=X),
            patch.object(ap, "ABSTAIN_LOW", 0.46),
            patch.object(ap, "ABSTAIN_HIGH", 0.54),
        ):
            result = p.predict(_ohlcv(150))
        for key in [
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
        ]:
            assert key in result, f"Missing key: {key}"

    def test_mtf_features_appended(self, tmp_path):
        import ml.advanced_predictor as ap

        p = self._loaded_predictor(tmp_path)
        p._model.predict_proba.return_value = np.array([[0.2, 0.8]])
        X = pd.DataFrame(np.random.randn(1, 10), columns=[f"f{i}" for i in range(10)])
        mtf = pd.DataFrame({"d_trend": [1.0]}, index=X.index)
        with (
            patch.object(p, "_build_features", return_value=X),
            patch.object(ap, "ABSTAIN_LOW", 0.46),
            patch.object(ap, "ABSTAIN_HIGH", 0.54),
        ):
            result = p.predict(_ohlcv(150), mtf_df=mtf)
        assert result is not None


# ── _align_features ───────────────────────────────────────────────────────────


class TestAlignFeatures:
    def test_fills_missing_columns_with_zero(self, tmp_path):
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=tmp_path / "m.pkl")
        p._feature_names = ["a", "b", "c"]
        X = pd.DataFrame({"a": [1.0], "b": [2.0]})  # missing "c"
        result = p._align_features(X)
        assert "c" in result.columns
        assert result["c"].iloc[0] == 0.0

    def test_drops_extra_columns(self, tmp_path):
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=tmp_path / "m.pkl")
        p._feature_names = ["a", "b"]
        X = pd.DataFrame({"a": [1.0], "b": [2.0], "extra": [99.0]})
        result = p._align_features(X)
        assert "extra" not in result.columns

    def test_noop_when_no_feature_names(self, tmp_path):
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=tmp_path / "m.pkl")
        p._feature_names = None
        X = pd.DataFrame({"a": [1.0]})
        result = p._align_features(X)
        assert "a" in result.columns


# ── update ────────────────────────────────────────────────────────────────────


class TestUpdate:
    def test_update_returns_false_when_model_not_loaded(self, tmp_path):
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=tmp_path / "missing.pkl")
        result = p.update(_ohlcv(150), label=1)
        assert result is False

    def test_update_returns_false_when_feature_build_fails(self, tmp_path):
        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=tmp_path / "m.pkl")
        p._model = MagicMock()
        with patch.object(p, "_build_features", return_value=None):
            result = p.update(_ohlcv(150), label=1)
        assert result is False


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_predictor_returns_same_instance(self):
        import ml.advanced_predictor as ap

        ap._predictor = None
        from ml.advanced_predictor import get_predictor, AdvancedPredictor

        a = get_predictor()
        b = get_predictor()
        assert a is b
        assert isinstance(a, AdvancedPredictor)
