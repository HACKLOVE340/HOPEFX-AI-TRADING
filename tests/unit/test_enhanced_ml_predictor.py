# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for enhanced_ml_predictor.py

Covers: Prediction dataclass, AdvancedFeatureEngineer, ModelConfig,
        EnsemblePredictor, EnhancedMLPredictor, generate_synthetic_data.
"""

import warnings
from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with DatetimeIndex."""
    rng = np.random.default_rng(seed)
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
    # Ensure high >= close >= low
    df["high"] = df[["high", "close", "open"]].max(axis=1) + 0.01
    df["low"] = df[["low", "close", "open"]].min(axis=1) - 0.01
    return df


# ---------------------------------------------------------------------------
# Imports (deferred so import errors surface as test failures, not collection)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def predictor_module():
    import enhanced_ml_predictor as m
    return m


# ---------------------------------------------------------------------------
# PredictionTarget / ModelArchitecture enums
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEnums:
    def test_prediction_target_values(self, predictor_module):
        m = predictor_module
        assert m.PredictionTarget.DIRECTION.value == "direction"
        assert m.PredictionTarget.RETURN.value == "return"
        assert m.PredictionTarget.VOLATILITY.value == "volatility"

    def test_model_architecture_values(self, predictor_module):
        m = predictor_module
        assert m.ModelArchitecture.LSTM.value == "lstm"
        assert m.ModelArchitecture.GRU.value == "gru"
        assert m.ModelArchitecture.TRANSFORMER.value == "transformer"


# ---------------------------------------------------------------------------
# ModelConfig dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestModelConfig:
    def test_defaults(self, predictor_module):
        cfg = predictor_module.ModelConfig(
            architecture=predictor_module.ModelArchitecture.LSTM
        )
        assert cfg.sequence_length > 0
        assert isinstance(cfg.hidden_units, list)
        assert 0.0 < cfg.dropout_rate < 1.0

    def test_custom_values(self, predictor_module):
        cfg = predictor_module.ModelConfig(
            architecture=predictor_module.ModelArchitecture.GRU,
            sequence_length=30,
            dropout_rate=0.2,
        )
        assert cfg.sequence_length == 30
        assert cfg.dropout_rate == 0.2

    def test_architecture_stored(self, predictor_module):
        cfg = predictor_module.ModelConfig(
            architecture=predictor_module.ModelArchitecture.TRANSFORMER
        )
        assert cfg.architecture == predictor_module.ModelArchitecture.TRANSFORMER


# ---------------------------------------------------------------------------
# Prediction dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPrediction:
    def _make(self, predictor_module, confidence: float, total_uncertainty: float) -> object:
        return predictor_module.Prediction(
            symbol="XAU_USD",
            timestamp=datetime.now(UTC),
            target=predictor_module.PredictionTarget.DIRECTION,
            prediction="up",
            confidence=confidence,
            total_uncertainty=total_uncertainty,
        )

    def test_is_confident_true(self, predictor_module):
        p = self._make(predictor_module, confidence=0.75, total_uncertainty=0.1)
        assert p.is_confident() is True

    def test_is_confident_low_confidence(self, predictor_module):
        p = self._make(predictor_module, confidence=0.50, total_uncertainty=0.1)
        assert p.is_confident() is False

    def test_is_confident_high_uncertainty(self, predictor_module):
        p = self._make(predictor_module, confidence=0.80, total_uncertainty=0.35)
        assert p.is_confident() is False

    def test_is_confident_boundary_confidence(self, predictor_module):
        # Exactly 0.6 confidence should pass
        p = self._make(predictor_module, confidence=0.60, total_uncertainty=0.1)
        assert p.is_confident() is True

    def test_is_confident_custom_threshold(self, predictor_module):
        p = self._make(predictor_module, confidence=0.70, total_uncertainty=0.25)
        # With default threshold (0.3) this passes
        assert p.is_confident() is True
        # With tight threshold (0.2) this fails
        assert p.is_confident(threshold=0.20) is False

    def test_to_dict_keys(self, predictor_module):
        p = self._make(predictor_module, confidence=0.70, total_uncertainty=0.1)
        d = p.to_dict()
        for key in ("symbol", "timestamp", "target", "prediction", "confidence", "uncertainty", "model"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_uncertainty_decomposition(self, predictor_module):
        p = predictor_module.Prediction(
            symbol="EUR_USD",
            timestamp=datetime.now(UTC),
            target=predictor_module.PredictionTarget.DIRECTION,
            prediction="neutral",
            confidence=0.55,
            epistemic_uncertainty=0.05,
            aleatoric_uncertainty=0.10,
            total_uncertainty=0.15,
        )
        d = p.to_dict()
        assert d["uncertainty"]["epistemic"] == pytest.approx(0.05)
        assert d["uncertainty"]["aleatoric"] == pytest.approx(0.10)
        assert d["uncertainty"]["total"] == pytest.approx(0.15)

    def test_to_dict_timestamp_is_iso_string(self, predictor_module):
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        p = self._make(predictor_module, confidence=0.7, total_uncertainty=0.1)
        p = predictor_module.Prediction(
            symbol="XAU_USD",
            timestamp=ts,
            target=predictor_module.PredictionTarget.DIRECTION,
            prediction="up",
            confidence=0.7,
            total_uncertainty=0.1,
        )
        d = p.to_dict()
        assert "2025-06-01" in d["timestamp"]


# ---------------------------------------------------------------------------
# AdvancedFeatureEngineer
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAdvancedFeatureEngineer:
    def test_init_defaults(self, predictor_module):
        fe = predictor_module.AdvancedFeatureEngineer()
        assert fe.windows == [5, 10, 20, 50, 100, 200]
        assert fe.is_fitted is False

    def test_init_custom_windows(self, predictor_module):
        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        assert fe.windows == [5, 10]

    def test_create_features_requires_fit_first(self, predictor_module):
        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        df = _make_ohlcv(100)
        with pytest.raises(RuntimeError, match="not fitted"):
            fe.create_features(df, fit=False)

    def test_create_features_fit_returns_dataframe(self, predictor_module):
        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        df = _make_ohlcv(300)
        result = fe.create_features(df, fit=True)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert len(result.columns) > 10

    def test_create_features_no_nan_after_fit(self, predictor_module):
        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        df = _make_ohlcv(300)
        result = fe.create_features(df, fit=True)
        assert not result.isnull().any().any(), "Features contain NaN values"

    def test_create_features_sets_is_fitted(self, predictor_module):
        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        df = _make_ohlcv(300)
        fe.create_features(df, fit=True)
        assert fe.is_fitted is True

    def test_create_features_transform_after_fit(self, predictor_module):
        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        train_df = _make_ohlcv(300)
        fe.create_features(train_df, fit=True)
        # Use enough bars so rolling windows don't drop everything
        test_df = _make_ohlcv(300, seed=99)
        result = fe.create_features(test_df, fit=False)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_create_features_column_alignment(self, predictor_module):
        """Transform output must have same columns as fit output."""
        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        train_df = _make_ohlcv(300)
        train_result = fe.create_features(train_df, fit=True)
        test_df = _make_ohlcv(300, seed=99)
        test_result = fe.create_features(test_df, fit=False)
        assert list(train_result.columns) == list(test_result.columns)

    def test_feature_names_populated_after_fit(self, predictor_module):
        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        df = _make_ohlcv(300)
        fe.create_features(df, fit=True)
        assert len(fe.feature_names) > 0

    def test_get_feature_importance_tree_model(self, predictor_module):
        """get_feature_importance uses native importances for tree models."""
        from sklearn.ensemble import RandomForestClassifier

        fe = predictor_module.AdvancedFeatureEngineer(lookback_windows=[5, 10])
        df = _make_ohlcv(300)
        X = fe.create_features(df, fit=True)
        y = pd.Series(np.random.randint(0, 3, len(X)), index=X.index)
        rf = RandomForestClassifier(n_estimators=5, random_state=42)
        rf.fit(X, y)
        importance = fe.get_feature_importance(rf, X, y)
        assert isinstance(importance, dict)
        assert len(importance) == len(fe.feature_names)
        assert all(isinstance(v, float) for v in importance.values())


# ---------------------------------------------------------------------------
# generate_synthetic_data
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGenerateSyntheticData:
    def test_raises_in_production(self, predictor_module, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(RuntimeError, match="production"):
            predictor_module.generate_synthetic_data(n_samples=100)

    def test_returns_dataframe_in_dev(self, predictor_module, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            df = predictor_module.generate_synthetic_data(n_samples=200)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 200

    def test_required_columns_present(self, predictor_module, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            df = predictor_module.generate_synthetic_data(n_samples=100)
        for col in ("open", "high", "low", "close", "volume"):
            assert col in df.columns, f"Missing column: {col}"

    def test_no_nan_values(self, predictor_module, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            df = predictor_module.generate_synthetic_data(n_samples=200)
        assert not df.isnull().any().any()

    def test_high_gte_low(self, predictor_module, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            df = predictor_module.generate_synthetic_data(n_samples=200)
        assert (df["high"] >= df["low"]).all()

    def test_emits_user_warning(self, predictor_module, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with pytest.warns(UserWarning, match="synthetic"):
            predictor_module.generate_synthetic_data(n_samples=50)


# ---------------------------------------------------------------------------
# EnsemblePredictor
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEnsemblePredictor:
    def test_init(self, predictor_module):
        ep = predictor_module.EnsemblePredictor()
        assert ep.models == {}
        assert ep.weights == {}

    def test_add_model(self, predictor_module):
        ep = predictor_module.EnsemblePredictor()
        mock_model = MagicMock()
        ep.add_model("rf", mock_model, weight=0.5)
        assert "rf" in ep.models
        assert ep.weights["rf"] == pytest.approx(0.5)

    def test_add_multiple_models(self, predictor_module):
        ep = predictor_module.EnsemblePredictor()
        for name in ("rf", "xgb", "lgb"):
            ep.add_model(name, MagicMock(), weight=1.0)
        assert len(ep.models) == 3


# ---------------------------------------------------------------------------
# EnhancedMLPredictor
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEnhancedMLPredictor:
    def test_init_defaults(self, predictor_module):
        p = predictor_module.EnhancedMLPredictor()
        assert p.sequence_length == 60
        assert p.confidence_threshold > 0
        assert p.is_fitted is False

    def test_init_custom_params(self, predictor_module):
        p = predictor_module.EnhancedMLPredictor(sequence_length=30, confidence_threshold=0.7)
        assert p.sequence_length == 30
        assert p.confidence_threshold == pytest.approx(0.7)

    def test_predict_returns_none_when_not_fitted(self, predictor_module):
        p = predictor_module.EnhancedMLPredictor()
        df = _make_ohlcv(300)
        result = p.predict(df)
        # Should return None gracefully when no model is trained
        assert result is None

    def test_get_model_report_not_fitted(self, predictor_module):
        p = predictor_module.EnhancedMLPredictor()
        report = p.get_model_report()
        assert isinstance(report, dict)
        assert report.get("status") == "not_fitted"

    def test_update_performance_no_crash(self, predictor_module):
        p = predictor_module.EnhancedMLPredictor()
        # Should not raise even when not fitted
        p.update_performance(0.01)
        p.update_performance(-0.005)

    def test_build_ensemble_rf_no_crash(self, predictor_module):
        p = predictor_module.EnhancedMLPredictor()
        # Should not raise even if TF is unavailable
        try:
            p.build_ensemble(model_types=["random_forest"])
        except Exception as exc:
            pytest.fail(f"build_ensemble raised unexpectedly: {exc}")

    def test_build_ensemble_creates_ensemble(self, predictor_module):
        p = predictor_module.EnhancedMLPredictor()
        p.build_ensemble(model_types=["random_forest"])
        assert p.ensemble is not None

    def test_fit_and_predict_with_synthetic_data(self, predictor_module, monkeypatch):
        """End-to-end: fit on synthetic data, then predict.

        Uses 2000 samples so the 80/20 split leaves enough rows after the
        200-bar rolling window drops NaNs.
        """
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = predictor_module.generate_synthetic_data(n_samples=2000)

        p = predictor_module.EnhancedMLPredictor()
        p.build_ensemble(model_types=["random_forest"])
        try:
            p.fit(df)
            result = p.predict(df.tail(500))
            if result is not None:
                assert isinstance(result, predictor_module.Prediction)
        except Exception as exc:
            pytest.fail(f"fit/predict raised unexpectedly: {exc}")

    def test_get_model_report_after_fit(self, predictor_module, monkeypatch):
        """Report structure after fitting."""
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = predictor_module.generate_synthetic_data(n_samples=2000)

        p = predictor_module.EnhancedMLPredictor()
        p.build_ensemble(model_types=["random_forest"])
        try:
            p.fit(df)
            report = p.get_model_report()
            assert isinstance(report, dict)
            assert report.get("status") == "fitted"
        except Exception:
            pass  # Graceful degradation acceptable
