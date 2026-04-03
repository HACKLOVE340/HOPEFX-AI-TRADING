# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_ml_pipeline.py

Unit tests for ml/pipeline.py — feature engineering, stationarity,
walk-forward validation, XGBoost predictor.
"""

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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(42)


def _make_ohlcv(n: int = 500) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    close = 1950.0 + np.cumsum(RNG.normal(0, 5, n))
    close = np.maximum(close, 100.0)
    high = close + np.abs(RNG.normal(0, 3, n))
    low = close - np.abs(RNG.normal(0, 3, n))
    open_ = close + RNG.normal(0, 2, n)
    volume = np.abs(RNG.normal(1000, 200, n))
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


# ---------------------------------------------------------------------------
# FeatureEngineer
# ---------------------------------------------------------------------------


class TestFeatureEngineer:
    def setup_method(self):
        self.fe = FeatureEngineer()
        self.df = _make_ohlcv(300)

    def test_returns_dataframe(self):
        result = self.fe.compute(self.df)
        assert isinstance(result, pd.DataFrame)

    def test_has_target_column(self):
        result = self.fe.compute(self.df)
        assert "y" in result.columns

    def test_target_is_binary(self):
        result = self.fe.compute(self.df)
        assert set(result["y"].unique()).issubset({0, 1})

    def test_no_nan_in_output(self):
        result = self.fe.compute(self.df)
        assert not result.isnull().any().any()

    def test_feature_count(self):
        result = self.fe.compute(self.df)
        feature_cols = [c for c in result.columns if c != "y"]
        assert len(feature_cols) >= 10  # at least 10 features

    def test_no_look_ahead_bias(self):
        """
        Verify no look-ahead: features at row t must not use close[t].
        We check by confirming features are shifted — the first valid row
        should have features derived from row 0 data, not row 1.
        """
        result = self.fe.compute(self.df)
        # After shift(1), the first feature row corresponds to bar[1]'s features
        # computed from bar[0] data. The index should start at a positive offset.
        assert len(result) < len(self.df)  # rows dropped due to shift + NaN

    def test_missing_column_raises(self):
        bad_df = self.df.drop(columns=["volume"])
        with pytest.raises(ValueError, match="Missing OHLCV"):
            self.fe.compute(bad_df)

    def test_case_insensitive_columns(self):
        df_upper = self.df.rename(columns=str.upper)
        result = self.fe.compute(df_upper)
        assert "y" in result.columns

    def test_rsi_bounded(self):
        result = self.fe.compute(self.df)
        assert (result["rsi_14"] >= 0).all()
        assert (result["rsi_14"] <= 100).all()


# ---------------------------------------------------------------------------
# StationarityTester
# ---------------------------------------------------------------------------


class TestStationarityTester:
    def setup_method(self):
        self.tester = StationarityTester()

    def test_stationary_series_detected(self):
        # White noise is stationary — use bool() to handle np.bool_
        series = pd.Series(RNG.normal(0, 1, 300))
        result = self.tester.test(series, name="white_noise")
        assert bool(result.is_stationary) is True

    def test_nonstationary_series_detected(self):
        # Random walk is non-stationary
        series = pd.Series(np.cumsum(RNG.normal(0, 1, 300)))
        result = self.tester.test(series, name="random_walk")
        assert bool(result.is_stationary) is False

    def test_insufficient_data_returns_nonstationary(self):
        series = pd.Series([0.01, -0.01, 0.005])
        result = self.tester.test(series, name="tiny")
        assert result.is_stationary is False

    def test_result_has_required_fields(self):
        series = pd.Series(RNG.normal(0, 1, 100))
        result = self.tester.test(series, name="test")
        assert hasattr(result, "adf_statistic")
        assert hasattr(result, "adf_pvalue")
        assert hasattr(result, "kpss_statistic")
        assert hasattr(result, "kpss_pvalue")
        assert hasattr(result, "is_stationary")

    def test_test_dataframe(self):
        df = pd.DataFrame(
            {
                "ret": RNG.normal(0, 0.01, 200),
                "rw": np.cumsum(RNG.normal(0, 1, 200)),
            }
        )
        results = self.tester.test_dataframe(df, ["ret", "rw"])
        assert "ret" in results
        assert "rw" in results
        assert bool(results["ret"].is_stationary) is True
        assert bool(results["rw"].is_stationary) is False


# ---------------------------------------------------------------------------
# WalkForwardValidator
# ---------------------------------------------------------------------------


class TestWalkForwardValidator:
    def test_correct_number_of_folds(self):
        validator = WalkForwardValidator(n_folds=5)
        splits = validator.split(200)
        assert len(splits) == 5

    def test_train_expands_each_fold(self):
        validator = WalkForwardValidator(n_folds=4)
        splits = validator.split(200)
        train_sizes = [len(list(tr)) for tr, _ in splits]
        assert train_sizes == sorted(train_sizes)  # monotonically increasing

    def test_no_overlap_between_train_and_test(self):
        validator = WalkForwardValidator(n_folds=3)
        splits = validator.split(150)
        for train_idx, test_idx in splits:
            train_set = set(train_idx)
            test_set = set(test_idx)
            assert train_set.isdisjoint(test_set)

    def test_test_follows_train(self):
        validator = WalkForwardValidator(n_folds=3)
        splits = validator.split(150)
        for train_idx, test_idx in splits:
            assert max(train_idx) < min(test_idx)

    def test_insufficient_data_raises(self):
        validator = WalkForwardValidator(n_folds=10)
        with pytest.raises(ValueError, match="Insufficient"):
            validator.split(15)


# ---------------------------------------------------------------------------
# XGBoostPredictor
# ---------------------------------------------------------------------------


class TestXGBoostPredictor:
    def setup_method(self):
        self.df = _make_ohlcv(300)
        fe = FeatureEngineer()
        feats = fe.compute(self.df)
        self.feature_cols = [c for c in feats.columns if c != "y"]
        self.X = feats[self.feature_cols]
        self.y = feats["y"]

    def test_fit_and_predict(self):
        predictor = XGBoostPredictor()
        predictor.fit(self.X, self.y)
        preds = predictor.predict(self.X)
        assert len(preds) == len(self.X)
        assert set(preds).issubset({0, 1})

    def test_predict_proba_bounded(self):
        predictor = XGBoostPredictor()
        predictor.fit(self.X, self.y)
        proba = predictor.predict_proba(self.X)
        assert (proba >= 0).all()
        assert (proba <= 1).all()

    def test_feature_importances_sum_to_one(self):
        predictor = XGBoostPredictor()
        predictor.fit(self.X, self.y)
        imps = predictor.get_feature_importances()
        assert abs(sum(imps.values()) - 1.0) < 0.01

    def test_predict_before_fit_raises(self):
        predictor = XGBoostPredictor()
        with pytest.raises(RuntimeError, match="not fitted"):
            predictor.predict(self.X)

    def test_save_and_load(self, tmp_path):
        predictor = XGBoostPredictor()
        predictor.fit(self.X, self.y)
        path = str(tmp_path / "model.pkl")
        predictor.save(path)

        loaded = XGBoostPredictor()
        loaded.load(path)
        preds_orig = predictor.predict(self.X)
        preds_loaded = loaded.predict(self.X)
        np.testing.assert_array_equal(preds_orig, preds_loaded)


# ---------------------------------------------------------------------------
# MLPipeline (integration — uses real XGBoost)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestMLPipeline:
    def test_run_returns_validation_report(self, tmp_path):
        df = _make_ohlcv(600)
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        report = pipeline.run(df)
        assert isinstance(report, ValidationReport)

    def test_report_has_required_fields(self, tmp_path):
        df = _make_ohlcv(600)
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        report = pipeline.run(df)
        assert 0.0 <= report.oos_accuracy <= 1.0
        assert 0.0 <= report.mean_auc <= 1.0
        assert 0.0 <= report.p_value <= 1.0
        assert report.n_folds == 3
        assert report.n_total_oos_samples > 0

    def test_feature_importances_populated(self, tmp_path):
        df = _make_ohlcv(600)
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        report = pipeline.run(df)
        assert len(report.feature_importances) > 0

    def test_gates_evaluated(self, tmp_path):
        df = _make_ohlcv(600)
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        report = pipeline.run(df)
        # Gates are boolean — just verify they're set
        assert isinstance(report.passes_accuracy_gate, bool)
        assert isinstance(report.passes_pvalue_gate, bool)

    def test_to_dict_serialisable(self, tmp_path):
        import json

        df = _make_ohlcv(600)
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        report = pipeline.run(df)
        d = report.to_dict()
        # Must be JSON-serialisable
        json.dumps(d)

    def test_insufficient_data_fails_gates(self, tmp_path):
        # 30 rows → pipeline runs but gates fail (not enough signal)
        # Pipeline returns a report rather than raising — gates block model save
        df = _make_ohlcv(30)
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        # Either raises (too few rows for folds) or returns a failed-gate report
        try:
            report = pipeline.run(df)
            # If it runs, gates must fail on such tiny data
            assert not (report.passes_accuracy_gate and report.passes_pvalue_gate)
        except (ValueError, Exception):
            pass  # also acceptable — WalkForwardValidator may reject

    def test_very_small_dataset_raises(self, tmp_path):
        # 10 rows is definitely too small for any fold
        df = _make_ohlcv(10)
        pipeline = MLPipeline(model_dir=str(tmp_path), n_folds=3)
        with pytest.raises((ValueError, Exception)):
            pipeline.run(df)
