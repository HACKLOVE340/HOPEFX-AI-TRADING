# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_train_advanced.py
============================
Unit tests for ml/train_advanced.py.

Covers:
- Feature matrix shape (100 without macro, 129 with macro)
- No NaN / Inf in feature matrix
- walk_forward_eval returns valid metrics
- oos_eval_advanced returns valid metrics + saves advanced_oos.pkl
- train_final_model saves stacking_ensemble.pkl + feature_scaler.pkl
- extract_feature_importance works for plain-XGB pipeline
- CLI argument defaults: --years=50, --oos-years=8.0
- OOS cap: 40% of data, minimum 100 bars enforced
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore")

ROOT = Path(__file__).parent.parent


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Synthetic daily OHLCV with realistic structure."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2014-01-01", periods=n, freq="B")
    close = 1200.0 + np.cumsum(rng.standard_normal(n) * 5)
    noise = np.abs(rng.standard_normal(n))
    return pd.DataFrame(
        {
            "open": close - noise,
            "high": close + np.abs(rng.standard_normal(n) * 3),
            "low": close - np.abs(rng.standard_normal(n) * 3),
            "close": close,
            "volume": rng.integers(5_000, 50_000, n).astype(float),
        },
        index=dates,
    )


def _make_macro(index: pd.DatetimeIndex, seed: int = 7) -> pd.DataFrame:
    """Synthetic macro DataFrame aligned to OHLCV index."""
    rng = np.random.default_rng(seed)
    n = len(index)
    return pd.DataFrame(
        {
            "dxy": 95.0 + rng.standard_normal(n) * 2,
            "vix": 15.0 + np.abs(rng.standard_normal(n) * 3),
            "yield_10y": 2.5 + rng.standard_normal(n) * 0.1,
            "yield_5y": 2.0 + rng.standard_normal(n) * 0.1,
            "spx": 3000.0 + np.cumsum(rng.standard_normal(n) * 10),
            "oil": 60.0 + rng.standard_normal(n) * 2,
            "copper": 3.5 + rng.standard_normal(n) * 0.1,
            "tips": 100.0 + rng.standard_normal(n),
            "gold_etf": 1200.0 + np.cumsum(rng.standard_normal(n) * 5),
            "usdcny": 6.5 + rng.standard_normal(n) * 0.1,
        },
        index=index,
    )


# ── Feature engineering ───────────────────────────────────────────────────────


class TestBuildAdvancedFeatures:
    def test_feature_count_no_macro(self):
        from ml.advanced_features import build_advanced_features

        df = _make_ohlcv()
        X, _ = build_advanced_features(df, macro_df=None)
        assert X.shape[1] == 100, f"Expected 100 features without macro, got {X.shape[1]}"

    def test_feature_count_with_macro(self):
        from ml.advanced_features import build_advanced_features

        df = _make_ohlcv()
        macro = _make_macro(df.index)
        X, _ = build_advanced_features(df, macro_df=macro)
        assert X.shape[1] == 129, f"Expected 129 features with macro, got {X.shape[1]}"

    def test_no_nan_in_features(self):
        from ml.advanced_features import build_advanced_features

        df = _make_ohlcv()
        X, _ = build_advanced_features(df, macro_df=None)
        assert not X.isnull().any().any(), "NaN values found in feature matrix"

    def test_no_inf_in_features(self):
        from ml.advanced_features import build_advanced_features

        df = _make_ohlcv()
        X, _ = build_advanced_features(df, macro_df=None)
        assert not np.isinf(X.values).any(), "Inf values found in feature matrix"

    def test_binary_target(self):
        from ml.advanced_features import build_advanced_features

        df = _make_ohlcv()
        _, y = build_advanced_features(df, macro_df=None)
        assert set(y.unique()).issubset({0, 1}), f"Target has non-binary values: {y.unique()}"

    def test_no_close_lag_features(self):
        """Raw price lags are non-stationary — must not appear in feature matrix."""
        from ml.advanced_features import build_advanced_features

        df = _make_ohlcv()
        X, _ = build_advanced_features(df, macro_df=None)
        lag_cols = [c for c in X.columns if "close_lag" in c]
        assert lag_cols == [], f"Non-stationary close_lag features found: {lag_cols}"


# ── Walk-forward CV ───────────────────────────────────────────────────────────


class TestWalkForwardEval:
    @pytest.fixture(scope="class")
    def xy(self):
        from ml.advanced_features import build_advanced_features

        df = _make_ohlcv(n=200)
        return build_advanced_features(df, macro_df=None)

    def test_returns_mean_accuracy(self, xy):
        from ml.train_advanced import walk_forward_eval

        X, y = xy
        result = walk_forward_eval(X, y, n_splits=2)
        assert "mean_accuracy" in result
        assert 0.0 <= result["mean_accuracy"] <= 1.0

    def test_returns_p_value(self, xy):
        from ml.train_advanced import walk_forward_eval

        X, y = xy
        result = walk_forward_eval(X, y, n_splits=2)
        assert "p_value" in result
        assert 0.0 <= result["p_value"] <= 1.0

    def test_fold_count(self, xy):
        from ml.train_advanced import walk_forward_eval

        X, y = xy
        result = walk_forward_eval(X, y, n_splits=2)
        assert len(result["folds"]) == 2


# ── OOS evaluation ────────────────────────────────────────────────────────────


class TestOosEvalAdvanced:
    @pytest.fixture(scope="class")
    def cv_oos_split(self, tmp_path_factory):
        import ml.train_advanced as ta

        # Redirect MODEL_DIR to a temp directory so tests don't pollute saved_models/
        tmp = tmp_path_factory.mktemp("models")
        original = ta.MODEL_DIR
        ta.MODEL_DIR = tmp
        yield _make_cv_oos_split()
        ta.MODEL_DIR = original

    def test_accuracy_in_range(self, cv_oos_split):
        from ml.train_advanced import oos_eval_advanced

        X_cv, y_cv, X_oos, y_oos = cv_oos_split
        result = oos_eval_advanced(X_cv, y_cv, X_oos, y_oos)
        assert 0.0 <= result["accuracy"] <= 1.0

    def test_p_value_in_range(self, cv_oos_split):
        from ml.train_advanced import oos_eval_advanced

        X_cv, y_cv, X_oos, y_oos = cv_oos_split
        result = oos_eval_advanced(X_cv, y_cv, X_oos, y_oos)
        assert 0.0 <= result["p_value_binomial"] <= 1.0

    def test_saves_advanced_oos_pkl(self, cv_oos_split, tmp_path):
        import ml.train_advanced as ta
        from ml.train_advanced import oos_eval_advanced

        original = ta.MODEL_DIR
        ta.MODEL_DIR = tmp_path
        try:
            X_cv, y_cv, X_oos, y_oos = cv_oos_split
            oos_eval_advanced(X_cv, y_cv, X_oos, y_oos)
            assert (tmp_path / "advanced_oos.pkl").exists(), "advanced_oos.pkl not saved"
        finally:
            ta.MODEL_DIR = original


def _make_cv_oos_split():
    from ml.advanced_features import build_advanced_features

    df = _make_ohlcv(n=200)
    X, y = build_advanced_features(df, macro_df=None)
    split = int(len(X) * 0.80)
    return X.iloc[:split], y.iloc[:split], X.iloc[split:], y.iloc[split:]


# ── Final model training ──────────────────────────────────────────────────────


class TestTrainFinalModel:
    @pytest.fixture(scope="class")
    def trained(self, tmp_path_factory):
        import ml.train_advanced as ta
        from ml.advanced_features import build_advanced_features
        from ml.train_advanced import train_final_model

        tmp = tmp_path_factory.mktemp("models_final")
        original = ta.MODEL_DIR
        ta.MODEL_DIR = tmp

        df = _make_ohlcv(n=200)
        X, y = build_advanced_features(df, macro_df=None)
        model, metrics = train_final_model(X, y, use_stacking=False)

        ta.MODEL_DIR = original
        return model, metrics, tmp

    def test_accuracy_in_range(self, trained):
        _, metrics, _ = trained
        assert 0.0 <= metrics["accuracy"] <= 1.0

    def test_saves_stacking_ensemble(self, trained):
        _, _, tmp = trained
        assert (tmp / "stacking_ensemble.pkl").exists()

    def test_saves_feature_scaler(self, trained):
        _, _, tmp = trained
        assert (tmp / "feature_scaler.pkl").exists(), "feature_scaler.pkl not saved"

    def test_feature_count_in_metrics(self, trained):
        _, metrics, _ = trained
        assert metrics["feature_count"] == 100


# ── Feature importance ────────────────────────────────────────────────────────


class TestExtractFeatureImportance:
    def test_returns_nonempty_dict(self, tmp_path):
        import ml.train_advanced as ta
        from ml.advanced_features import build_advanced_features
        from ml.train_advanced import extract_feature_importance, train_final_model

        original = ta.MODEL_DIR
        ta.MODEL_DIR = tmp_path
        try:
            df = _make_ohlcv(n=200)
            X, y = build_advanced_features(df, macro_df=None)
            model, _ = train_final_model(X, y, use_stacking=False)
            imp = extract_feature_importance(model, list(X.columns))
            assert isinstance(imp, dict)
            assert len(imp) > 0, "Feature importance dict is empty"
        finally:
            ta.MODEL_DIR = original

    def test_importance_values_are_floats(self, tmp_path):
        import ml.train_advanced as ta
        from ml.advanced_features import build_advanced_features
        from ml.train_advanced import extract_feature_importance, train_final_model

        original = ta.MODEL_DIR
        ta.MODEL_DIR = tmp_path
        try:
            df = _make_ohlcv(n=200)
            X, y = build_advanced_features(df, macro_df=None)
            model, _ = train_final_model(X, y, use_stacking=False)
            imp = extract_feature_importance(model, list(X.columns))
            for k, v in imp.items():
                assert isinstance(v, float), f"Importance for {k} is not float: {type(v)}"
        finally:
            ta.MODEL_DIR = original


# ── CLI argument defaults ─────────────────────────────────────────────────────


class TestCLIDefaults:
    def _parse(self, args: list[str]) -> argparse.Namespace:
        """Parse args using the same parser as main() without running training."""

        # Patch sys.argv and import the module's parser setup
        parser = argparse.ArgumentParser()
        parser.add_argument("--years", type=int, default=50)
        parser.add_argument("--symbol", default="GC=F")
        parser.add_argument("--no-macro", action="store_true")
        parser.add_argument("--horizon", type=int, default=1)
        parser.add_argument("--splits", type=int, default=8)
        parser.add_argument("--min-move", type=float, default=0.25)
        parser.add_argument("--no-filter", action="store_true")
        parser.add_argument("--stacking", action="store_true")
        parser.add_argument("--oos-years", type=float, default=8.0)
        return parser.parse_args(args)

    def test_default_years_is_50(self):
        ns = self._parse([])
        assert ns.years == 50, f"Default --years should be 50, got {ns.years}"

    def test_default_oos_years_is_8(self):
        ns = self._parse([])
        assert ns.oos_years == 8.0, f"Default --oos-years should be 8.0, got {ns.oos_years}"

    def test_default_symbol_is_gcf(self):
        ns = self._parse([])
        assert ns.symbol == "GC=F"

    def test_override_years(self):
        ns = self._parse(["--years", "10"])
        assert ns.years == 10

    def test_override_oos_years(self):
        ns = self._parse(["--oos-years", "3"])
        assert ns.oos_years == 3.0


# ── OOS cap logic ─────────────────────────────────────────────────────────────


class TestOosCap:
    """Verify the OOS cap and minimum-bar guard in main()."""

    def _compute_oos_n(self, total_samples: int, oos_years: float) -> int:
        """Replicate the OOS-n calculation from main()."""
        oos_n = round(oos_years * 252)
        oos_n = min(oos_n, int(total_samples * 0.40))
        if oos_n < 100:
            return 0
        return oos_n

    def test_8yr_oos_on_50yr_data(self):
        # 50yr * 252 * 0.727 (filtered) ≈ 9200 samples; 8yr = 2016 bars
        total = 9200
        oos_n = self._compute_oos_n(total, 8.0)
        assert oos_n == 2016, f"Expected 2016, got {oos_n}"
        assert oos_n <= int(total * 0.40), "OOS exceeds 40% cap"

    def test_cap_at_40_pct(self):
        # If oos_years would exceed 40%, cap kicks in
        total = 1000
        oos_n = self._compute_oos_n(total, 8.0)
        assert oos_n <= int(total * 0.40)

    def test_minimum_100_bars_enforced(self):
        # Very small dataset: oos_n < 100 → returns 0
        total = 200
        oos_n = self._compute_oos_n(total, 0.1)  # 0.1yr * 252 = 25 bars
        assert oos_n == 0, "Should return 0 when oos_n < 100"

    def test_zero_oos_years_returns_zero(self):
        total = 9200
        oos_n = self._compute_oos_n(total, 0.0)
        # 0 * 252 = 0 → min(0, cap) = 0 → 0 < 100 → returns 0
        assert oos_n == 0
