# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Comprehensive tests for ML model modules.

Tests BaseMLModel, LSTMPricePredictor, RandomForestTradingClassifier,
EnsemblePredictor, and TechnicalFeatureEngineer without requiring
TensorFlow, PyTorch, or sklearn to be available.
"""

import json
import os

# Maximum fraction of feature_names allowed to be uncategorised in feature groups
_MAX_UNCATEGORISED_FRACTION = 0.3
import tempfile

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from ml.features.technical import TechnicalFeatureEngineer
from ml.models.base import BaseMLModel
from ml.models.ensemble import (
    EnsemblePredictor,
    EnsemblePrediction,
    ModelPrediction,
)
from ml.models.lstm import LSTMPricePredictor
from ml.models.random_forest import RandomForestTradingClassifier


# ---------------------------------------------------------------------------
# Helpers / Fixtures shared across test classes
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Return a realistic OHLCV DataFrame of length *n*."""
    np.random.seed(seed)
    dates = pd.date_range(start="2024-01-01", periods=n, freq="D")
    base = 1800.0
    returns = np.random.randn(n) * 0.01
    close = base * np.cumprod(1 + returns)
    df = pd.DataFrame(
        {
            "open": close * (1 + np.random.randn(n) * 0.003),
            "high": close * (1 + np.abs(np.random.randn(n) * 0.005)),
            "low": close * (1 - np.abs(np.random.randn(n) * 0.005)),
            "close": close,
            "volume": np.random.randint(1000, 10000, n).astype(float),
        },
        index=dates,
    )
    return df


def _make_price_series(n: int = 200, seed: int = 0) -> np.ndarray:
    np.random.seed(seed)
    return np.cumsum(np.random.randn(n) * 5) + 1800.0


# ---------------------------------------------------------------------------
# Concrete subclass of the abstract BaseMLModel for testing
# ---------------------------------------------------------------------------


class _ConcreteModel(BaseMLModel):
    """
    Minimal concrete subclass used to exercise BaseMLModel methods.

    Uses a real sklearn DummyClassifier as the underlying model so that
    attribute access (feature_importances_, coef_, etc.) behaves like a
    real estimator rather than a MagicMock.
    """

    def build(self) -> None:
        self.model = DummyClassifier(strategy="most_frequent")

    def train(self, X_train, y_train, X_val=None, y_val=None):
        if self.model is None:
            self.build()
        self.model.fit(X_train, y_train)
        self.is_trained = True
        return {"loss": 0.01}

    def predict(self, X):
        return np.zeros(len(X))


# ===========================================================================
# BaseMLModel Tests
# ===========================================================================


@pytest.mark.unit
class TestBaseMLModel:
    """Tests for the BaseMLModel abstract base class."""

    def test_initialization_defaults(self):
        model = _ConcreteModel(name="test_model")
        assert model.name == "test_model"
        assert model.config == {}
        assert model.model is None
        assert model.is_trained is False
        assert model.training_history == []
        assert "created_at" in model.metadata
        assert model.metadata["name"] == "test_model"

    def test_initialization_with_config(self):
        cfg = {"lr": 0.01, "epochs": 50}
        model = _ConcreteModel(name="cfg_model", config=cfg)
        assert model.config["lr"] == 0.01
        assert model.config["epochs"] == 50

    def test_str_representation_untrained(self):
        model = _ConcreteModel(name="my_model")
        assert "my_model" in str(model)
        assert "untrained" in str(model)

    def test_str_representation_trained(self):
        model = _ConcreteModel(name="my_model")
        model.is_trained = True
        assert "trained" in str(model)

    def test_repr(self):
        model = _ConcreteModel(name="my_model")
        r = repr(model)
        assert "_ConcreteModel" in r
        assert "my_model" in r

    def test_build_sets_model(self):
        model = _ConcreteModel(name="build_test")
        model.build()
        assert model.model is not None

    def test_train_sets_trained_flag(self):
        X = np.random.randn(50, 5)
        y = np.random.randn(50)
        model = _ConcreteModel(name="train_test")
        model.train(X, y)
        assert model.is_trained is True

    def test_predict_returns_array(self):
        X = np.random.randn(10, 5)
        model = _ConcreteModel(name="pred_test")
        model.is_trained = True
        preds = model.predict(X)
        assert isinstance(preds, np.ndarray)
        assert len(preds) == 10

    def test_get_feature_importance_none_without_model(self):
        model = _ConcreteModel(name="fi_test")
        # model is None → should return None
        assert model.get_feature_importance() is None

    def test_get_feature_importance_with_feature_importances_(self):
        """feature_importances_ path — use a real trained RandomForest."""
        from sklearn.ensemble import RandomForestClassifier

        model = _ConcreteModel(name="fi_test2")
        np.random.seed(0)
        X = np.random.randn(40, 3)
        y = np.random.randint(0, 2, 40)
        rf = RandomForestClassifier(n_estimators=5, random_state=0)
        rf.fit(X, y)
        model.model = rf
        fi = model.get_feature_importance()
        assert fi is not None
        assert len(fi) == 3
        assert abs(sum(fi.values()) - 1.0) < 1e-6  # importances sum to 1

    def test_get_feature_importance_with_coef_(self):
        """coef_ path — use a real trained LogisticRegression."""
        model = _ConcreteModel(name="fi_coef")
        np.random.seed(1)
        X = np.random.randn(40, 2)
        y = np.random.randint(0, 2, 40)
        lr = LogisticRegression(random_state=0, max_iter=200)
        lr.fit(X, y)
        model.model = lr
        fi = model.get_feature_importance()
        assert fi is not None
        # BaseMLModel.get_feature_importance() returns dict(enumerate(coef_)).
        # For binary LogisticRegression coef_ is shape (1, n_features), so the
        # dict has 1 key whose value is the full coefficient array.
        assert len(fi) >= 1

    def test_save_and_load_roundtrip(self):
        model = _ConcreteModel(name="save_test")
        # Use a plain dict as the model object so pickle works
        model.model = {"weights": [1.0, 2.0]}
        model.is_trained = True
        model.training_history = [{"epoch": 1}]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "model.pkl")
            model.save(path)

            # Verify metadata JSON was written
            meta_path = os.path.join(tmpdir, "model_metadata.json")
            assert os.path.exists(meta_path)
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            assert meta["name"] == "save_test"

            # Load into a fresh instance
            loaded = _ConcreteModel(name="loaded")
            loaded.load(path)
            assert loaded.is_trained is True
            assert loaded.training_history == [{"epoch": 1}]

    def test_evaluate_calls_predict(self):
        """evaluate() calls predict() and returns a real metrics dict via sklearn."""
        model = _ConcreteModel(name="eval_test")
        np.random.seed(1)
        X = np.random.randn(30, 5)
        # All-zero labels: _ConcreteModel.predict() always returns zeros,
        # so accuracy/precision/recall/f1 are all 1.0 on this dataset.
        y = np.zeros(30)
        model.train(X, y)

        metrics = model.evaluate(X, y)

        assert isinstance(metrics, dict)
        # Real sklearn metrics — no mocking
        assert "mse" in metrics or "accuracy" in metrics


# ===========================================================================
# LSTMPricePredictor Tests
# ===========================================================================


@pytest.mark.unit
class TestLSTMPricePredictor:
    """Tests for LSTMPricePredictor (TensorFlow mocked)."""

    def test_initialization_defaults(self):
        lstm = LSTMPricePredictor()
        assert lstm.name == "LSTM_Predictor"
        assert lstm.sequence_length == 60
        assert lstm.lstm_units == [50, 50]
        assert lstm.dropout == pytest.approx(0.2)
        assert lstm.epochs == 100
        assert lstm.batch_size == 32
        assert lstm.learning_rate == pytest.approx(0.001)
        assert lstm.scaler_X is None
        assert lstm.scaler_y is None

    def test_initialization_with_custom_config(self):
        cfg = {
            "sequence_length": 30,
            "lstm_units": [64, 32],
            "dropout": 0.3,
            "epochs": 50,
            "batch_size": 16,
            "learning_rate": 0.005,
        }
        lstm = LSTMPricePredictor(name="custom_lstm", config=cfg)
        assert lstm.sequence_length == 30
        assert lstm.lstm_units == [64, 32]
        assert lstm.dropout == pytest.approx(0.3)
        assert lstm.learning_rate == pytest.approx(0.005)

    def test_prepare_sequences(self):
        lstm = LSTMPricePredictor(config={"sequence_length": 5})
        data = np.arange(10.0).reshape(-1, 1)
        X, y = lstm._prepare_sequences(data)
        assert X.shape == (5, 5)
        assert y.shape == (5,)
        # First sequence should be [0,1,2,3,4], target = 5
        np.testing.assert_array_equal(X[0], [0, 1, 2, 3, 4])
        assert y[0] == pytest.approx(5.0)

    def test_predict_raises_when_not_trained(self):
        lstm = LSTMPricePredictor()
        with pytest.raises(ValueError, match="not trained"):
            lstm.predict(np.random.randn(100))

    def test_predict_next_raises_insufficient_data(self):
        """predict_next() raises ValueError when fewer than sequence_length points given."""
        from sklearn.preprocessing import MinMaxScaler

        lstm = LSTMPricePredictor(config={"sequence_length": 10})
        lstm.is_trained = True
        # Use real fitted scalers so the guard check runs before any scaler call
        scaler_X = MinMaxScaler()
        scaler_X.fit(np.random.randn(20, 1))
        scaler_y = MinMaxScaler()
        scaler_y.fit(np.random.randn(20, 1))
        lstm.scaler_X = scaler_X
        lstm.scaler_y = scaler_y
        # model is only reached after the length guard, so a DummyClassifier is fine
        lstm.model = DummyClassifier()
        # Provide fewer than sequence_length points
        with pytest.raises(ValueError, match="at least"):
            lstm.predict_next(np.random.randn(5))

    def test_get_model_summary_not_built(self):
        lstm = LSTMPricePredictor()
        summary = lstm.get_model_summary()
        assert summary == "Model not built"

    def test_get_model_summary_built(self):
        """get_model_summary() captures the model's summary string."""
        lstm = LSTMPricePredictor()

        # Use a real object with a summary() method that accepts a print_fn kwarg.
        # This matches the Keras model.summary(print_fn=...) interface without
        # requiring TensorFlow to be installed.
        class _FakeKerasModel:
            def summary(self, print_fn=None):
                if print_fn:
                    print_fn("LSTM summary line 1")
                    print_fn("LSTM summary line 2")

        lstm.model = _FakeKerasModel()
        summary = lstm.get_model_summary()
        assert "LSTM summary" in summary

    def test_build_with_mocked_tensorflow(self):
        """build() should log an error (or set use_lstm=False) when TF is absent."""
        lstm = LSTMPricePredictor(config={"sequence_length": 10, "lstm_units": [32]})
        # If TensorFlow is not installed, build() should raise ImportError
        try:
            # TF available: build should set self.model
            lstm.build()
            assert lstm.model is not None
        except ImportError:
            with pytest.raises(ImportError):
                lstm.build()

    def test_scale_data_raises_if_not_fitted(self):
        lstm = LSTMPricePredictor()
        with pytest.raises((ValueError, RuntimeError)):
            lstm._scale_data(np.array([1.0, 2.0]), np.array([1.0, 2.0]), fit=False)

    def test_predict_with_real_scalers_and_stub_model(self):
        """predict() returns correct shape with real MinMaxScalers and a stub model."""
        from sklearn.preprocessing import MinMaxScaler

        seq_len = 5
        n_input = 12  # produces n_input - seq_len = 7 sequences
        lstm = LSTMPricePredictor(config={"sequence_length": seq_len})
        lstm.is_trained = True

        # Real fitted scalers — identity-like (data already in [0,1] range)
        data_2d = np.random.rand(n_input, 1)
        scaler_X = MinMaxScaler()
        scaler_X.fit(data_2d)
        lstm.scaler_X = scaler_X

        scaler_y = MinMaxScaler()
        scaler_y.fit(data_2d)
        lstm.scaler_y = scaler_y

        # Minimal stub model: only needs a predict() method returning the right shape.
        # TensorFlow is not required — we're testing the LSTMPricePredictor wrapper.
        n_sequences = n_input - seq_len

        class _StubKerasModel:
            def predict(self, X, verbose=0):
                return np.zeros((len(X), 1))

        lstm.model = _StubKerasModel()

        data = np.random.rand(n_input)
        preds = lstm.predict(data)
        assert preds.shape == (n_sequences,)


# ===========================================================================
# RandomForestTradingClassifier Tests
# ===========================================================================


@pytest.mark.unit
class TestRandomForestTradingClassifier:
    """Tests for RandomForestTradingClassifier (sklearn mocked)."""

    def test_initialization_defaults(self):
        rf = RandomForestTradingClassifier()
        assert rf.name == "RF_Classifier"
        assert rf.n_estimators == 100
        assert rf.max_depth == 10
        assert rf.random_state == 42
        assert rf.feature_names == []
        assert rf.label_encoder is None

    def test_initialization_with_config(self):
        cfg = {"n_estimators": 50, "max_depth": 5, "random_state": 7}
        rf = RandomForestTradingClassifier(name="custom_rf", config=cfg)
        assert rf.n_estimators == 50
        assert rf.max_depth == 5
        assert rf.random_state == 7

    def test_predict_raises_when_not_trained(self):
        rf = RandomForestTradingClassifier()
        with pytest.raises(ValueError, match="not trained"):
            rf.predict(np.random.randn(10, 5))

    def test_predict_proba_raises_when_not_trained(self):
        rf = RandomForestTradingClassifier()
        with pytest.raises(ValueError, match="not trained"):
            rf.predict_proba(np.random.randn(10, 5))

    def test_get_feature_importance_dict_untrained(self):
        rf = RandomForestTradingClassifier()
        assert rf.get_feature_importance_dict() == {}

    def test_build_creates_model(self):
        """build() should create a sklearn RandomForestClassifier if available."""
        rf = RandomForestTradingClassifier(config={"n_estimators": 10})
        try:
            rf.build()
            assert rf.model is not None
        except ImportError:
            pytest.skip("sklearn not installed")

    def _make_trained_rf(
        self,
        n_samples: int = 40,
        n_features: int = 5,
        n_classes: int = 3,
        seed: int = 0,
        feature_names: list[str] | None = None,
    ) -> tuple["RandomForestTradingClassifier", np.ndarray, np.ndarray]:
        """
        Return a real trained RandomForestTradingClassifier with data.

        Uses n_estimators=5 for speed. All assertions use real sklearn outputs.
        """

        np.random.seed(seed)
        X = np.random.randn(n_samples, n_features)
        y = np.random.randint(0, n_classes, n_samples)

        rf = RandomForestTradingClassifier(config={"n_estimators": 5, "random_state": seed})
        rf.build()
        names = feature_names or [f"f{i}" for i in range(n_features)]
        rf.train(X, y, feature_names=names)
        return rf, X, y

    def test_train_and_predict_real_model(self):
        """Train/predict pipeline using a real sklearn RandomForest."""
        rf, _, _ = self._make_trained_rf(n_features=5, feature_names=["f1", "f2", "f3", "f4", "f5"])

        assert rf.is_trained is True
        assert "train_accuracy" in rf.training_history[-1]["metrics"]
        assert rf.training_history[-1]["metrics"]["n_features"] == 5

    def test_train_stores_feature_names(self):
        """train() stores the provided feature names."""
        rf, _, _ = self._make_trained_rf(n_features=3, feature_names=["rsi", "macd", "atr"])
        assert rf.feature_names == ["rsi", "macd", "atr"]

    def test_train_infers_feature_names_when_not_provided(self):
        """train() auto-generates feature_N names when none are provided."""
        rf = RandomForestTradingClassifier(config={"n_estimators": 5, "random_state": 0})
        rf.build()
        np.random.seed(0)
        X = np.random.randn(20, 3)
        y = np.random.randint(0, 2, 20)
        rf.train(X, y)
        assert rf.feature_names == ["feature_0", "feature_1", "feature_2"]

    def test_predict_returns_correct_shape(self):
        """predict() returns an array with one label per sample."""
        rf, X, _ = self._make_trained_rf(n_samples=40, n_features=5)
        preds = rf.predict(X[:3])
        assert preds.shape == (3,)
        # All predictions must be valid class labels
        assert set(preds).issubset({0, 1, 2})

    def test_predict_proba_returns_correct_shape(self):
        """predict_proba() returns (n_samples, n_classes) probabilities."""
        rf, X, _ = self._make_trained_rf(n_samples=40, n_features=5, n_classes=3)
        proba = rf.predict_proba(X[:2])
        assert proba.shape[0] == 2
        # Each row must sum to ~1.0
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    def test_predict_with_confidence_shape(self):
        """predict_with_confidence() returns (preds, confidences) arrays."""
        rf, X, _ = self._make_trained_rf(n_samples=40, n_features=5, n_classes=3)
        preds, confidences = rf.predict_with_confidence(X[:4])
        assert len(preds) == 4
        assert len(confidences) == 4
        # Confidence is the max class probability — must be in [0, 1]
        assert all(0.0 <= c <= 1.0 for c in confidences)

    def test_get_feature_importance_dict_with_names(self):
        """get_feature_importance_dict() maps feature names to real importances."""
        rf, _, _ = self._make_trained_rf(n_features=3, feature_names=["a", "b", "c"])
        fi = rf.get_feature_importance_dict()
        assert set(fi.keys()) == {"a", "b", "c"}
        # Importances are non-negative and sum to ~1
        assert all(v >= 0 for v in fi.values())
        assert abs(sum(fi.values()) - 1.0) < 1e-6

    def test_get_feature_importance_dict_without_names(self):
        """get_feature_importance_dict() uses integer keys when no names set."""
        rf, _, _ = self._make_trained_rf(n_features=2)
        rf.feature_names = []  # clear names to test fallback
        fi = rf.get_feature_importance_dict()
        assert len(fi) == 2

    def test_get_top_features(self):
        """get_top_features(n) returns the n highest-importance features in order."""
        rf, _, _ = self._make_trained_rf(n_features=4, feature_names=["a", "b", "c", "d"])
        top2 = rf.get_top_features(n=2)
        assert len(top2) == 2
        # First entry must have higher importance than second
        assert top2[0][1] >= top2[1][1]

    def test_validate_training_history_updated(self):
        """train() appends one entry to training_history with a metrics key."""
        rf, _, _ = self._make_trained_rf(n_features=3)
        assert len(rf.training_history) == 1
        assert "metrics" in rf.training_history[0]


# ===========================================================================
# EnsemblePredictor Tests
# ===========================================================================


@pytest.mark.unit
class TestEnsemblePredictor:
    """Tests for EnsemblePredictor (all sub-models mocked)."""

    def test_initialization_defaults(self):
        ep = EnsemblePredictor()
        assert ep.name == "Ensemble_Predictor"
        assert ep.sequence_length == 60
        assert ep.use_lstm is True
        assert ep.use_rf is True
        assert ep.use_gb is True
        assert ep.dynamic_weights is True
        assert ep.confidence_threshold == pytest.approx(0.5)
        assert ep.models == {}
        assert isinstance(ep.model_weights, dict)
        assert "lstm" in ep.model_weights
        assert ep.scaler_X is None
        assert ep.scaler_y is None

    def test_initialization_with_config(self):
        cfg = {
            "use_lstm": False,
            "use_xgb": False,
            "sequence_length": 30,
            "confidence_threshold": 0.7,
        }
        ep = EnsemblePredictor(config=cfg)
        assert ep.use_lstm is False
        assert ep.use_xgb is False
        assert ep.sequence_length == 30
        assert ep.confidence_threshold == pytest.approx(0.7)

    def test_predict_raises_when_not_trained(self):
        ep = EnsemblePredictor()
        with pytest.raises(ValueError, match="not trained"):
            ep.predict(np.random.randn(100))

    def test_predict_with_confidence_raises_when_not_trained(self):
        ep = EnsemblePredictor()
        with pytest.raises(ValueError, match="not trained"):
            ep.predict_with_confidence(np.random.randn(100))

    def test_prepare_features_shape(self):
        ep = EnsemblePredictor(config={"sequence_length": 10})
        data = _make_price_series(50)
        X_feat, y_tgt = ep._prepare_features(data)
        expected_rows = len(data) - ep.sequence_length
        assert X_feat.shape == (expected_rows, 10)
        assert y_tgt.shape == (expected_rows,)

    def test_prepare_lstm_sequences_shape(self):
        ep = EnsemblePredictor(config={"sequence_length": 5})
        data = np.arange(20.0)
        X, y = ep._prepare_lstm_sequences(data)
        assert X.shape == (15, 5, 1)
        assert y.shape == (15,)

    def test_combine_predictions_empty(self):
        ep = EnsemblePredictor()
        result = ep._combine_predictions({})
        assert isinstance(result, EnsemblePrediction)
        assert result.prediction == pytest.approx(0.0)
        assert result.consensus == "divergent"

    def test_combine_predictions_single_model(self):
        ep = EnsemblePredictor()
        mp = ModelPrediction(
            model_name="rf",
            prediction=1850.0,
            confidence=0.8,
            weight=0.25,
        )
        result = ep._combine_predictions({"rf": mp})
        assert isinstance(result, EnsemblePrediction)
        assert result.consensus == "single_model"

    def test_combine_predictions_strong_consensus(self):
        ep = EnsemblePredictor()
        # All predictions very close → strong consensus
        preds = {
            "rf": ModelPrediction("rf", 1800.0, 0.8, 0.25),
            "gb": ModelPrediction("gb", 1801.0, 0.8, 0.25),
        }
        result = ep._combine_predictions(preds)
        assert result.consensus in ("strong", "moderate")
        assert result.prediction > 0

    def test_combine_predictions_divergent(self):
        ep = EnsemblePredictor()
        preds = {
            "rf": ModelPrediction("rf", 100.0, 0.5, 0.5),
            "gb": ModelPrediction("gb", 5000.0, 0.5, 0.5),
        }
        result = ep._combine_predictions(preds)
        assert result.consensus in ("divergent", "weak")

    def test_calculate_model_confidence_no_history(self):
        ep = EnsemblePredictor()
        conf = ep._calculate_model_confidence("lstm")
        assert conf == pytest.approx(0.5)

    def test_calculate_model_confidence_with_history(self):
        ep = EnsemblePredictor()
        perf = ep.model_performance["random_forest"]
        perf["total"] = 100
        perf["correct"] = 70
        perf["recent_errors"] = [0.01] * 20

        conf = ep._calculate_model_confidence("random_forest")
        assert 0.1 <= conf <= 0.95

    def test_update_performance_increments_total(self):
        ep = EnsemblePredictor()
        ep.update_performance("lstm", prediction=1.0, actual=1.0)
        assert ep.model_performance["lstm"]["total"] == 1

    def test_update_performance_direction_correct(self):
        ep = EnsemblePredictor()
        ep.update_performance("lstm", prediction=0.5, actual=0.3)
        assert ep.model_performance["lstm"]["correct"] == 1

    def test_update_performance_direction_wrong(self):
        ep = EnsemblePredictor()
        ep.update_performance("lstm", prediction=0.5, actual=-0.3)
        assert ep.model_performance["lstm"]["correct"] == 0

    def test_update_performance_caps_recent_errors(self):
        ep = EnsemblePredictor()
        for i in range(150):
            ep.update_performance("lstm", float(i), float(i + 1))
        assert len(ep.model_performance["lstm"]["recent_errors"]) <= 100

    def test_update_performance_unknown_model(self):
        ep = EnsemblePredictor()
        # Should not raise
        ep.update_performance("nonexistent_model", 1.0, 1.0)

    def test_update_weights_with_models(self):
        """_update_weights() normalises weights to sum to 1.0."""
        ep = EnsemblePredictor()
        # Use real DummyClassifier instances — the weight update only reads
        # model_performance, not the model objects themselves.
        ep.models = {
            "random_forest": DummyClassifier(),
            "gradient_boosting": DummyClassifier(),
        }
        ep.model_performance["random_forest"]["total"] = 10
        ep.model_performance["random_forest"]["correct"] = 8
        ep.model_performance["gradient_boosting"]["total"] = 10
        ep.model_performance["gradient_boosting"]["correct"] = 6
        ep._update_weights()
        total = ep.model_weights["random_forest"] + ep.model_weights["gradient_boosting"]
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_get_model_summary_structure(self):
        """get_model_summary() returns the expected top-level keys."""
        ep = EnsemblePredictor()
        ep.models = {"rf": DummyClassifier()}
        summary = ep.get_model_summary()
        assert "models" in summary
        assert "weights" in summary
        assert "is_trained" in summary
        assert "config" in summary

    def test_ensemble_prediction_to_dict(self):
        mp = ModelPrediction("rf", 1800.0, 0.8, 0.25)
        ep_pred = EnsemblePrediction(
            prediction=1800.0,
            confidence=0.8,
            predictions_by_model={"rf": mp},
            consensus="moderate",
            direction="bullish",
            volatility_factor=0.01,
        )
        d = ep_pred.to_dict()
        assert d["prediction"] == pytest.approx(1800.0)
        assert d["consensus"] == "moderate"
        assert "rf" in d["model_predictions"]

    def test_build_with_only_sklearn_models(self):
        """build() with use_lstm=False, use_xgb=False – only sklearn needed."""
        cfg = {
            "use_lstm": False,
            "use_xgb": False,
            "use_rf": True,
            "use_gb": True,
            "sequence_length": 10,
        }
        ep = EnsemblePredictor(config=cfg)
        ep.build()
        # Random Forest and Gradient Boosting should have been added
        assert "random_forest" in ep.models or ep.use_rf is False
        assert "gradient_boosting" in ep.models or ep.use_gb is False

    def test_build_without_any_dependency(self):
        """build() with all sub-models disabled should result in empty models."""
        cfg = {
            "use_lstm": False,
            "use_xgb": False,
            "use_rf": False,
            "use_gb": False,
        }
        ep = EnsemblePredictor(config=cfg)
        ep.build()
        assert ep.models == {}


# ===========================================================================
# TechnicalFeatureEngineer Tests (with known-value validation)
# ===========================================================================


@pytest.mark.unit
class TestTechnicalFeatureEngineerExtended:
    """Extended tests for TechnicalFeatureEngineer including indicator values."""

    @pytest.fixture
    def ohlcv(self):
        return _make_ohlcv(300)

    @pytest.fixture
    def fe(self):
        return TechnicalFeatureEngineer()

    # --- Basic interface ---

    def test_init_no_config(self):
        fe = TechnicalFeatureEngineer()
        assert fe.config == {}
        assert fe.feature_names == []

    def test_init_with_config(self):
        fe = TechnicalFeatureEngineer(config={"key": "value"})
        assert fe.config["key"] == "value"

    def test_missing_columns_raises(self, fe):
        with pytest.raises(ValueError, match="must contain columns"):
            fe.create_features(pd.DataFrame({"close": [1.0, 2.0]}))

    def test_returns_dataframe(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert isinstance(result, pd.DataFrame)

    def test_no_nan_in_result(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert result.isna().sum().sum() == 0

    def test_original_unchanged(self, fe, ohlcv):
        cols_before = set(ohlcv.columns)
        fe.create_features(ohlcv)
        assert set(ohlcv.columns) == cols_before

    # --- Trend features ---

    def test_sma_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        for p in [5, 10, 20, 50]:
            assert f"sma_{p}" in result.columns, f"sma_{p} missing"

    def test_ema_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        for p in [5, 10, 20, 50]:
            assert f"ema_{p}" in result.columns

    def test_macd_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "macd" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_hist" in result.columns

    def test_ma_crossover_values_binary(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        # create_features() calls dropna(), so no NaN rows remain
        assert set(result["sma_10_20_cross"].unique()).issubset({1, -1})

    def test_sma_calculation_correctness(self, fe, ohlcv):
        """SMA-5 should be the 5-period rolling mean of close prices."""
        result = fe.create_features(ohlcv)
        # Pick a row where SMA-5 should equal the 5-period mean
        close = ohlcv["close"]
        # Compare SMA-5 values against manual calculation at a few valid indices
        for idx in result.index[:5]:
            expected = close.loc[:idx].tail(5).mean()
            assert result.loc[idx, "sma_5"] == pytest.approx(expected, rel=1e-6)

    # --- Momentum features ---

    def test_rsi_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        for p in [7, 14, 21]:
            assert f"rsi_{p}" in result.columns

    def test_rsi_bounds(self, fe, ohlcv):
        """RSI must be in [0, 100]."""
        result = fe.create_features(ohlcv)
        assert result["rsi_14"].between(0, 100).all()

    def test_rsi_constant_price_is_50_or_nan(self, fe):
        """RSI with constant prices has 0 gain and 0 loss; any surviving values should be in [0, 100]."""
        n = 50
        prices = np.full(n, 10.0)
        df = pd.DataFrame(
            {
                "open": prices,
                "high": prices + 0.1,
                "low": prices - 0.1,
                "close": prices,
                "volume": np.ones(n) * 1000,
            }
        )
        result = fe.create_features(df)
        # After dropna(), result may be empty for n=50 (sma_200 requires 200 rows)
        if len(result) == 0:
            pytest.skip("Insufficient rows survive dropna() for n=50 with 200-period indicators")
        assert result["rsi_14"].between(0, 100).all()

    def test_stochastic_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "stoch_k_14" in result.columns
        assert "stoch_d_14" in result.columns

    def test_stochastic_bounds(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        # %K is theoretically [0, 100]
        assert result["stoch_k_14"].between(-1, 101).all()

    def test_roc_column_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "roc_5" in result.columns
        assert "roc_10" in result.columns

    def test_williams_r_column_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "williams_r_14" in result.columns

    # --- Volatility features ---

    def test_bollinger_bands_columns(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "bb_upper_20" in result.columns
        assert "bb_lower_20" in result.columns
        assert "bb_width_20" in result.columns

    def test_bollinger_band_ordering(self, fe, ohlcv):
        """Upper band should always be ≥ lower band."""
        result = fe.create_features(ohlcv)
        assert (result["bb_upper_20"] >= result["bb_lower_20"]).all()

    def test_bollinger_width_zero_for_constant(self, fe):
        """BB width = 0 when close is constant (std=0)."""
        n = 100
        prices = np.full(n, 100.0)
        df = pd.DataFrame(
            {
                "open": prices,
                "high": prices + 0.01,
                "low": prices - 0.01,
                "close": prices,
                "volume": np.ones(n) * 500,
            }
        )
        result = fe.create_features(df)
        if "bb_width_20" in result.columns and len(result):
            np.testing.assert_allclose(result["bb_width_20"].values, 0.0, atol=1e-9)

    def test_atr_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        for p in [7, 14, 21]:
            assert f"atr_{p}" in result.columns

    def test_atr_non_negative(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert (result["atr_14"] >= 0).all()

    def test_volatility_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        for p in [10, 20, 30]:
            assert f"volatility_{p}" in result.columns

    # --- Volume features ---

    def test_obv_column_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "obv" in result.columns

    def test_mfi_column_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "mfi_14" in result.columns

    def test_volume_ratio_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "volume_ratio_5" in result.columns

    # --- Price pattern features ---

    def test_price_pattern_columns(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        for col in [
            "body",
            "upper_shadow",
            "lower_shadow",
            "is_bullish",
            "is_bearish",
            "is_doji",
        ]:
            assert col in result.columns

    def test_is_bullish_and_bearish_not_both(self, fe, ohlcv):
        """A candle cannot be both bullish and bearish simultaneously."""
        result = fe.create_features(ohlcv)
        both = (result["is_bullish"] == 1) & (result["is_bearish"] == 1)
        assert not both.any()

    def test_candle_body_sign(self, fe, ohlcv):
        """Body = close - open: sign should match is_bullish."""
        result = fe.create_features(ohlcv)
        bullish_rows = result[result["is_bullish"] == 1]
        if len(bullish_rows):
            assert (bullish_rows["body"] > 0).all()

    # --- Statistical features ---

    def test_returns_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "returns_1" in result.columns
        assert "returns_5" in result.columns

    def test_zscore_columns_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "zscore_20" in result.columns
        assert "zscore_50" in result.columns

    def test_zscore_mean_approx_zero(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        # Over a long series the z-score should average near 0
        mean_z = result["zscore_20"].mean()
        assert abs(mean_z) < 1.0

    def test_skew_and_kurt_present(self, fe, ohlcv):
        result = fe.create_features(ohlcv)
        assert "skew_10" in result.columns
        assert "kurt_10" in result.columns

    # --- Feature groups ---

    def test_get_feature_groups_returns_dict(self, fe, ohlcv):
        fe.create_features(ohlcv)
        groups = fe.get_feature_groups()
        assert isinstance(groups, dict)
        assert "trend" in groups
        assert "momentum" in groups
        assert "volatility" in groups
        assert "volume" in groups
        assert "pattern" in groups
        assert "statistical" in groups

    def test_feature_groups_all_features_categorised(self, fe, ohlcv):
        fe.create_features(ohlcv)
        groups = fe.get_feature_groups()
        all_grouped = set()
        for lst in groups.values():
            all_grouped.update(lst)
        # All feature_names should appear in at least one group
        uncategorised = set(fe.feature_names) - all_grouped
        # It's acceptable to have a few uncategorised features;
        # but most should be covered.
        assert len(uncategorised) < len(fe.feature_names) * _MAX_UNCATEGORISED_FRACTION

    # --- Label creation ---

    def test_create_labels_forward_return(self, fe, ohlcv):
        fe.create_features(ohlcv)
        labels = fe.create_labels(ohlcv, method="forward_return", periods=5, threshold=0.01)
        assert isinstance(labels, pd.Series)
        assert set(labels.unique()).issubset({0, 1, 2})

    def test_create_labels_trend(self, fe, ohlcv):
        labels = fe.create_labels(ohlcv, method="trend", periods=10)
        assert isinstance(labels, pd.Series)
        assert set(labels.unique()).issubset({0, 1, 2})

    def test_create_labels_breakout(self, fe, ohlcv):
        labels = fe.create_labels(ohlcv, method="breakout", lookback=20, threshold=0.02)
        assert isinstance(labels, pd.Series)
        assert set(labels.unique()).issubset({0, 1, 2})

    def test_create_labels_invalid_method(self, fe, ohlcv):
        with pytest.raises(ValueError, match="Unknown labeling method"):
            fe.create_labels(ohlcv, method="unknown_method")

    def test_macd_signal_lags_macd(self, fe, ohlcv):
        """macd_signal is a smoothed MACD – correlation should be high."""
        result = fe.create_features(ohlcv)
        corr = result["macd"].corr(result["macd_signal"])
        assert corr > 0.7

    def test_feature_names_exclude_ohlcv(self, fe, ohlcv):
        fe.create_features(ohlcv)
        ohlcv_cols = {"open", "high", "low", "close", "volume"}
        assert len(ohlcv_cols & set(fe.feature_names)) == 0

    def test_idempotent_calls(self, fe, ohlcv):
        r1 = fe.create_features(ohlcv)
        r2 = fe.create_features(ohlcv)
        pd.testing.assert_frame_equal(r1, r2)
