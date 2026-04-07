# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for ml/training.py

Covers: FeatureEngineer (create_features, static helpers, scale_features),
        XGBoostModel, RandomForestModel, EnsembleModel, HyperparameterTuner.
"""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Shared OHLCV fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ohlcv_df():
    """300-bar OHLCV DataFrame with DatetimeIndex."""
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
# FeatureEngineer
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFeatureEngineer:
    def test_init_defaults(self):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer()
        assert fe.include_indicators is True
        assert fe.include_lags is True
        assert fe.feature_names == []

    def test_create_features_returns_tuple(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        result = fe.create_features(ohlcv_df)
        assert isinstance(result, tuple)
        assert len(result) == 4  # X, y_class, y_reg, data

    def test_create_features_X_is_dataframe(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, y_class, y_reg, data = fe.create_features(ohlcv_df)
        assert isinstance(X, pd.DataFrame)
        assert len(X) > 0

    def test_create_features_no_nan(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, y_class, y_reg, data = fe.create_features(ohlcv_df)
        assert not X.isnull().any().any(), "Feature matrix contains NaN"

    def test_create_features_y_class_binary(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, y_class, y_reg, data = fe.create_features(ohlcv_df)
        assert set(y_class.unique()).issubset({0, 1})

    def test_create_features_aligned_lengths(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, y_class, y_reg, data = fe.create_features(ohlcv_df)
        assert len(X) == len(y_class) == len(y_reg)

    def test_create_features_populates_feature_names(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        fe.create_features(ohlcv_df)
        assert len(fe.feature_names) > 0

    def test_scale_features_returns_tuple(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, _, _, _ = fe.create_features(ohlcv_df)
        X_scaled, X_test_scaled = fe.scale_features(X)
        assert X_scaled.shape == X.shape
        assert X_test_scaled is None

    def test_scale_features_with_test_set(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, _, _, _ = fe.create_features(ohlcv_df)
        split = int(len(X) * 0.8)
        X_train_scaled, X_test_scaled = fe.scale_features(X.iloc[:split], X.iloc[split:])
        assert X_train_scaled.shape[0] == split
        assert X_test_scaled is not None
        assert X_test_scaled.shape[0] == len(X) - split

    def test_calculate_rsi_range(self, ohlcv_df):
        from ml.training import FeatureEngineer
        rsi = FeatureEngineer._calculate_rsi(ohlcv_df["close"], period=14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_calculate_atr_positive(self, ohlcv_df):
        from ml.training import FeatureEngineer
        atr = FeatureEngineer._calculate_atr(ohlcv_df, period=14)
        assert (atr.dropna() > 0).all()

    def test_calculate_obv_returns_series(self, ohlcv_df):
        from ml.training import FeatureEngineer
        obv = FeatureEngineer._calculate_obv(ohlcv_df)
        assert isinstance(obv, pd.Series)
        assert len(obv) == len(ohlcv_df)

    def test_save_and_load_scaler(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, _, _, _ = fe.create_features(ohlcv_df)
        fe.scale_features(X)
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        try:
            fe.save_scaler(path)
            fe2 = FeatureEngineer(include_macro=False, include_regime=False)
            fe2.load_scaler(path)
            X_scaled, _ = fe2.scale_features(X)
            assert X_scaled.shape == X.shape
        finally:
            Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# XGBoostModel
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestXGBoostModel:
    @pytest.fixture
    def xy(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, y_class, _, _ = fe.create_features(ohlcv_df)
        X_scaled, _ = fe.scale_features(X)
        return X_scaled, y_class.values

    def test_init_classifier(self):
        from ml.training import XGBoostModel
        m = XGBoostModel(model_type="classifier")
        assert m.model_type == "classifier"

    def test_build_model(self):
        from ml.training import XGBoostModel
        m = XGBoostModel(model_type="classifier")
        m.build_model()
        assert m.model is not None

    def test_fit_returns_metrics(self, xy):
        from ml.training import XGBoostModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = XGBoostModel(model_type="classifier")
        m.build_model()
        metrics = m.fit(X[:split], y[:split], X[split:], y[split:])
        assert isinstance(metrics, dict)

    def test_predict_shape(self, xy):
        from ml.training import XGBoostModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = XGBoostModel(model_type="classifier")
        m.build_model()
        m.fit(X[:split], y[:split], X[split:], y[split:])
        preds = m.predict(X[split:])
        assert len(preds) == len(X[split:])

    def test_predict_proba_shape(self, xy):
        from ml.training import XGBoostModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = XGBoostModel(model_type="classifier")
        m.build_model()
        m.fit(X[:split], y[:split], X[split:], y[split:])
        proba = m.predict_proba(X[split:])
        assert proba.shape[0] == len(X[split:])

    def test_predict_proba_raises_for_regressor(self):
        from ml.training import XGBoostModel
        m = XGBoostModel(model_type="regressor")
        m.build_model()
        with pytest.raises(ValueError, match="classifier"):
            m.predict_proba(np.zeros((5, 3)))

    def test_evaluate_returns_dict(self, xy):
        from ml.training import XGBoostModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = XGBoostModel(model_type="classifier")
        m.build_model()
        m.fit(X[:split], y[:split], X[split:], y[split:])
        metrics = m.evaluate(X[split:], y[split:])
        assert "accuracy" in metrics

    def test_save_and_load(self, xy, tmp_path):
        from ml.training import XGBoostModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = XGBoostModel(model_type="classifier")
        m.build_model()
        m.fit(X[:split], y[:split], X[split:], y[split:])
        path = str(tmp_path / "xgb_model.pkl")
        m.save(path)
        m2 = XGBoostModel(model_type="classifier")
        m2.load(path)
        preds = m2.predict(X[split:])
        assert len(preds) == len(X[split:])


# ---------------------------------------------------------------------------
# RandomForestModel
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRandomForestModel:
    @pytest.fixture
    def xy(self, ohlcv_df):
        from ml.training import FeatureEngineer
        fe = FeatureEngineer(include_macro=False, include_regime=False)
        X, y_class, _, _ = fe.create_features(ohlcv_df)
        X_scaled, _ = fe.scale_features(X)
        return X_scaled, y_class.values

    def test_init(self):
        from ml.training import RandomForestModel
        m = RandomForestModel(model_type="classifier", n_estimators=10)
        assert m.model_type == "classifier"

    def test_build_model(self):
        from ml.training import RandomForestModel
        m = RandomForestModel(model_type="classifier", n_estimators=10)
        m.build_model()
        assert m.model is not None

    def test_fit_returns_metrics(self, xy):
        from ml.training import RandomForestModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = RandomForestModel(model_type="classifier", n_estimators=10)
        m.build_model()
        metrics = m.fit(X[:split], y[:split])
        assert isinstance(metrics, dict)

    def test_predict_shape(self, xy):
        from ml.training import RandomForestModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = RandomForestModel(model_type="classifier", n_estimators=10)
        m.build_model()
        m.fit(X[:split], y[:split])
        preds = m.predict(X[split:])
        assert len(preds) == len(X[split:])

    def test_evaluate_accuracy_in_range(self, xy):
        from ml.training import RandomForestModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = RandomForestModel(model_type="classifier", n_estimators=10)
        m.build_model()
        m.fit(X[:split], y[:split])
        metrics = m.evaluate(X[split:], y[split:])
        assert 0.0 <= metrics["accuracy"] <= 1.0

    def test_save_and_load(self, xy, tmp_path):
        from ml.training import RandomForestModel
        X, y = xy
        split = int(len(X) * 0.8)
        m = RandomForestModel(model_type="classifier", n_estimators=10)
        m.build_model()
        m.fit(X[:split], y[:split])
        path = str(tmp_path / "rf_model.pkl")
        m.save(path)
        m2 = RandomForestModel(model_type="classifier")
        m2.load(path)
        preds = m2.predict(X[split:])
        assert len(preds) == len(X[split:])


# ---------------------------------------------------------------------------
# EnsembleModel
# ---------------------------------------------------------------------------

def _import_training_module():
    """Load ml/training.py directly (bypasses the package __init__ re-export)."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "_ml_training_direct",
        Path(__file__).parent.parent.parent / "ml" / "training.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
class TestEnsembleModel:
    def test_init(self):
        mod = _import_training_module()
        em = mod.EnsembleModel()
        assert em.models == {}

    def test_add_model(self):
        mod = _import_training_module()
        em = mod.EnsembleModel()
        rf = mod.RandomForestModel(n_estimators=5)
        rf.build_model()
        em.add_model("rf", rf)
        assert "rf" in em.models

    def test_predict_majority_vote(self, ohlcv_df):
        mod = _import_training_module()
        fe = mod.FeatureEngineer(include_macro=False, include_regime=False)
        X, y_class, _, _ = fe.create_features(ohlcv_df)
        X_scaled, _ = fe.scale_features(X)
        split = int(len(X_scaled) * 0.8)

        em = mod.EnsembleModel()
        for name in ("rf1", "rf2"):
            rf = mod.RandomForestModel(n_estimators=5)
            rf.build_model()
            rf.fit(X_scaled[:split], y_class.values[:split])
            em.add_model(name, rf)

        preds = em.predict({"rf1": X_scaled[split:], "rf2": X_scaled[split:]})
        assert len(preds) == len(X_scaled[split:])
        assert set(preds).issubset({0, 1})
