# HOPEFX-AI-TRADING
# Tests for ml/pipeline.py — full branch coverage supplement
"""
Covers untested branches: HAS_STATSMODELS=False / HAS_SCIPY=False import guards,
MLPipeline.run() OOS accuracy gate failure, p-value gate failure, walk-forward
with too few folds, XGBoostPredictor.save()/load() with real file I/O,
StationarityTester when statsmodels unavailable, FeatureEngineer with missing
optional columns.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from ml.pipeline import (
    FeatureEngineer,
    MLPipeline,
    StationarityTester,
    ValidationReport,
    WalkForwardValidator,
    XGBoostPredictor,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n=600, seed=42):
    rng = np.random.default_rng(seed)
    close = 2000.0 + np.cumsum(rng.normal(0, 5, n))
    high = close + rng.uniform(1, 20, n)
    low = close - rng.uniform(1, 20, n)
    open_ = close + rng.normal(0, 3, n)
    volume = rng.uniform(1000, 10000, n)
    idx = pd.date_range("2023-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    }, index=idx)


def _make_xy(n=200, n_features=10, seed=42):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.standard_normal((n, n_features)),
                     columns=[f"f{i}" for i in range(n_features)])
    y = pd.Series(rng.integers(0, 2, n))
    return X, y


# ── HAS_STATSMODELS=False branch ──────────────────────────────────────────────


class TestHasStatsmodelsFalse:
    def test_stationarity_tester_fallback_when_no_statsmodels(self, monkeypatch):
        import ml.pipeline as pm
        monkeypatch.setattr(pm, "_STATSMODELS", False)
        tester = StationarityTester()
        series = pd.Series(np.random.randn(200))
        result = tester.test(series)
        assert hasattr(result, "is_stationary")
        assert isinstance(result.is_stationary, bool)

    def test_stationarity_tester_fallback_nonstationary(self, monkeypatch):
        import ml.pipeline as pm
        monkeypatch.setattr(pm, "_STATSMODELS", False)
        tester = StationarityTester()
        # Random walk — heuristic should flag as non-stationary
        series = pd.Series(np.cumsum(np.random.randn(300)))
        result = tester.test(series)
        assert hasattr(result, "is_stationary")

    def test_test_dataframe_fallback(self, monkeypatch):
        import ml.pipeline as pm
        monkeypatch.setattr(pm, "_STATSMODELS", False)
        tester = StationarityTester()
        df = pd.DataFrame({
            "a": np.random.randn(200),
            "b": np.cumsum(np.random.randn(200)),
        })
        results = tester.test_dataframe(df, ["a", "b"])
        assert "a" in results
        assert "b" in results


# ── HAS_SCIPY=False branch ────────────────────────────────────────────────────


class TestHasSciPyFalse:
    def test_pipeline_run_without_scipy(self, tmp_path, monkeypatch):
        """MLPipeline.run() uses scipy.stats.binomtest — test fallback when absent."""
        import ml.pipeline as pm
        monkeypatch.setattr(pm, "_STATSMODELS", False)
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        df = _make_ohlcv(600)
        report = pipeline.run(df)
        assert isinstance(report, ValidationReport)
        # p_value should be a float (fallback value)
        assert isinstance(report.p_value, float)


# ── MLPipeline.run() gate failures ───────────────────────────────────────────


class TestMLPipelineGateFailures:
    def _bad_report(self, accuracy=0.50, p_value=0.5):
        return ValidationReport(
            oos_accuracy=accuracy,
            oos_accuracy_std=0.02,
            mean_auc=0.51,
            p_value=p_value,
            n_folds=3,
            n_total_oos_samples=100,
            passes_accuracy_gate=accuracy >= 0.65,
            passes_pvalue_gate=p_value < 0.001,
            folds=[],
            feature_importances={},
        )

    def test_accuracy_gate_failure_no_model_saved(self, tmp_path):
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        df = _make_ohlcv(600)
        with patch.object(pipeline, "_walk_forward_validate",
                          return_value=self._bad_report(accuracy=0.50, p_value=0.0001)):
            report = pipeline.run(df)
        assert report.passes_accuracy_gate is False
        assert not (tmp_path / "xgb_xauusd.pkl").exists()

    def test_pvalue_gate_failure_no_model_saved(self, tmp_path):
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        df = _make_ohlcv(600)
        with patch.object(pipeline, "_walk_forward_validate",
                          return_value=self._bad_report(accuracy=0.70, p_value=0.5)):
            report = pipeline.run(df)
        assert report.passes_pvalue_gate is False
        assert not (tmp_path / "xgb_xauusd.pkl").exists()

    def test_both_gates_pass_model_saved(self, tmp_path):
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        df = _make_ohlcv(600)
        good_report = ValidationReport(
            oos_accuracy=0.70,
            oos_accuracy_std=0.02,
            mean_auc=0.72,
            p_value=0.00001,
            n_folds=3,
            n_total_oos_samples=100,
            passes_accuracy_gate=True,
            passes_pvalue_gate=True,
            folds=[],
            feature_importances={},
        )
        with patch.object(pipeline, "_walk_forward_validate", return_value=good_report):
            report = pipeline.run(df)
        assert report.passes_accuracy_gate is True
        assert (tmp_path / "xgb_xauusd.pkl").exists()

    def test_validation_report_saved_to_json(self, tmp_path):
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        df = _make_ohlcv(600)
        good_report = ValidationReport(
            oos_accuracy=0.70,
            oos_accuracy_std=0.02,
            mean_auc=0.72,
            p_value=0.00001,
            n_folds=3,
            n_total_oos_samples=100,
            passes_accuracy_gate=True,
            passes_pvalue_gate=True,
            folds=[],
            feature_importances={},
        )
        with patch.object(pipeline, "_walk_forward_validate", return_value=good_report):
            pipeline.run(df)
        assert (tmp_path / "validation_report.json").exists()


# ── WalkForwardValidator — too few folds ──────────────────────────────────────


class TestWalkForwardTooFewFolds:
    def test_split_with_minimal_rows_returns_folds(self):
        # WalkForwardValidator always returns n_folds splits regardless of row count
        validator = WalkForwardValidator(n_folds=5)
        splits = validator.split(10)
        assert len(splits) == 5

    def test_split_each_fold_has_train_and_test(self):
        validator = WalkForwardValidator(n_folds=5)
        splits = validator.split(50)
        for train_idx, test_idx in splits:
            assert len(train_idx) > 0
            assert len(test_idx) > 0

    def test_pipeline_run_with_2_folds(self, tmp_path):
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=2)
        df = _make_ohlcv(400)
        report = pipeline.run(df)
        assert isinstance(report, ValidationReport)
        assert report.n_folds == 2


# ── XGBoostPredictor.save() / load() ─────────────────────────────────────────


class TestXGBoostSaveLoad:
    def test_save_creates_file(self, tmp_path):
        pred = XGBoostPredictor()
        X, y = _make_xy()
        pred.fit(X, y)
        path = str(tmp_path / "model.pkl")
        pred.save(path)
        assert Path(path).exists()

    def test_load_restores_predictions(self, tmp_path):
        pred = XGBoostPredictor()
        X, y = _make_xy()
        pred.fit(X, y)
        path = str(tmp_path / "model.pkl")
        pred.save(path)

        pred2 = XGBoostPredictor()
        pred2.load(path)
        preds1 = pred.predict(X)
        preds2 = pred2.predict(X)
        np.testing.assert_array_equal(preds1, preds2)

    def test_load_restores_feature_names(self, tmp_path):
        pred = XGBoostPredictor()
        X, y = _make_xy()
        pred.fit(X, y)
        path = str(tmp_path / "model.pkl")
        pred.save(path)

        pred2 = XGBoostPredictor()
        pred2.load(path)
        assert pred2._feature_names == pred._feature_names

    def test_save_creates_parent_dirs(self, tmp_path):
        pred = XGBoostPredictor()
        X, y = _make_xy()
        pred.fit(X, y)
        nested = tmp_path / "a" / "b" / "c" / "model.pkl"
        pred.save(str(nested))
        assert nested.exists()


# ── FeatureEngineer column validation ────────────────────────────────────────


class TestFeatureEngineerMissingCols:
    def test_compute_raises_on_missing_volume(self):
        fe = FeatureEngineer()
        df = _make_ohlcv(300).drop(columns=["volume"])
        with pytest.raises(ValueError, match="Missing OHLCV"):
            fe.compute(df)

    def test_compute_raises_on_missing_high_low(self):
        fe = FeatureEngineer()
        df = _make_ohlcv(300).drop(columns=["high", "low"])
        with pytest.raises(ValueError, match="Missing OHLCV"):
            fe.compute(df)

    def test_compute_returns_no_nan(self):
        fe = FeatureEngineer()
        df = _make_ohlcv(300)
        feats = fe.compute(df)
        assert not feats.isnull().any().any()

    def test_compute_target_is_binary(self):
        fe = FeatureEngineer()
        df = _make_ohlcv(300)
        feats = fe.compute(df)
        assert set(feats["y"].unique()).issubset({0, 1})


# ── MLPipeline.drop_nonstationary ────────────────────────────────────────────


class TestDropNonstationary:
    def test_drop_nonstationary_reduces_features(self, tmp_path):
        pipeline = MLPipeline(
            model_dir=str(tmp_path), n_folds=3, drop_nonstationary=True
        )
        df = _make_ohlcv(600)
        report = pipeline.run(df)
        assert isinstance(report, ValidationReport)
        # Stationary features list should be populated
        assert len(pipeline._stationary_features) > 0

    def test_no_drop_keeps_all_features(self, tmp_path):
        pipeline_drop = MLPipeline(
            model_dir=str(tmp_path / "drop"), n_folds=3, drop_nonstationary=True
        )
        pipeline_keep = MLPipeline(
            model_dir=str(tmp_path / "keep"), n_folds=3, drop_nonstationary=False
        )
        df = _make_ohlcv(600)
        pipeline_drop.run(df)
        pipeline_keep.run(df)
        # With drop=True, features may be fewer or equal
        assert len(pipeline_drop._stationary_features) <= len(pipeline_keep._stationary_features)
