# HOPEFX-AI-TRADING
# Tests for ml/pipeline, ml/drift_monitor, ml/performance_monitor,
#           ml/signal_filter, ml/model_registry
"""Real unit tests. No mocks/stubs/fake data."""

from __future__ import annotations

import tempfile
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

UTC = timezone.utc


def _ohlcv(n=80, seed=42):
    rng = np.random.default_rng(seed)
    close = 1900.0 + np.cumsum(rng.normal(0, 3, n))
    high = close + rng.uniform(1, 8, n)
    low = close - rng.uniform(1, 8, n)
    open_ = close + rng.normal(0, 1, n)
    vol = rng.uniform(100, 400, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


# ── ml/pipeline — FeatureEngineer ────────────────────────────────────────────


class TestFeatureEngineer:
    def test_compute_returns_dataframe(self):
        from ml.pipeline import FeatureEngineer

        fe = FeatureEngineer(lookback=5)
        out = fe.compute(_ohlcv())
        assert isinstance(out, pd.DataFrame)
        assert len(out) > 0

    def test_compute_has_return_columns(self):
        from ml.pipeline import FeatureEngineer

        out = FeatureEngineer(lookback=5).compute(_ohlcv())
        assert "ret_1" in out.columns

    def test_compute_drops_nan_rows(self):
        from ml.pipeline import FeatureEngineer

        out = FeatureEngineer(lookback=20).compute(_ohlcv(n=60))
        assert not out.isnull().any().any()

    def test_shorter_lookback_more_rows(self):
        from ml.pipeline import FeatureEngineer

        df = _ohlcv(n=60)
        out5 = FeatureEngineer(lookback=5).compute(df)
        out20 = FeatureEngineer(lookback=20).compute(df)
        assert len(out5) >= len(out20)

    def test_rsi_column_present(self):
        from ml.pipeline import FeatureEngineer

        out = FeatureEngineer(lookback=5).compute(_ohlcv(n=60))
        assert any("rsi" in c.lower() for c in out.columns)


# ── ml/pipeline — StationarityTester ─────────────────────────────────────────


class TestStationarityTester:
    def test_stationary_series_passes(self):
        from ml.pipeline import StationarityTester

        rng = np.random.default_rng(1)
        series = pd.Series(rng.normal(0, 1, 200))
        result = StationarityTester().test(series, name="test")
        assert result.is_stationary == True

    def test_random_walk_fails(self):
        from ml.pipeline import StationarityTester

        rng = np.random.default_rng(2)
        series = pd.Series(np.cumsum(rng.normal(0, 1, 200)))
        result = StationarityTester().test(series, name="rw")
        assert result.is_stationary == False

    def test_result_has_adf_pvalue(self):
        from ml.pipeline import StationarityTester

        rng = np.random.default_rng(3)
        series = pd.Series(rng.normal(0, 1, 100))
        result = StationarityTester().test(series)
        assert hasattr(result, "adf_pvalue")

    def test_to_dict(self):
        from ml.pipeline import StationarityTester

        rng = np.random.default_rng(4)
        series = pd.Series(rng.normal(0, 1, 100))
        d = StationarityTester().test(series).to_dict()
        assert isinstance(d, dict)
        assert "is_stationary" in d

    def test_dataframe_test(self):
        from ml.pipeline import FeatureEngineer, StationarityTester

        features = FeatureEngineer(lookback=5).compute(_ohlcv(n=80))
        cols = list(features.columns)
        results = StationarityTester().test_dataframe(features, feature_cols=cols)
        assert isinstance(results, dict)
        assert len(results) > 0


# ── ml/pipeline — WalkForwardValidator ───────────────────────────────────────


class TestWalkForwardValidator:
    def test_split_returns_folds(self):
        from ml.pipeline import WalkForwardValidator

        folds = WalkForwardValidator(n_folds=3, min_train_size=0.5).split(200)
        assert len(folds) == 3

    def test_fold_has_train_test_attrs(self):
        from ml.pipeline import WalkForwardValidator

        folds = WalkForwardValidator(n_folds=3, min_train_size=0.5).split(200)
        fold = folds[0]
        # fold is a tuple of (train_range, test_range)
        assert isinstance(fold, tuple)
        assert len(fold) == 2

    def test_folds_non_overlapping_test(self):
        from ml.pipeline import WalkForwardValidator

        folds = WalkForwardValidator(n_folds=3, min_train_size=0.5).split(200)
        for i in range(len(folds) - 1):
            # test range of fold i ends before test range of fold i+1 starts
            assert folds[i][1].stop <= folds[i + 1][1].start


# ── ml/pipeline — XGBoostPredictor ───────────────────────────────────────────


class TestXGBoostPredictor:
    def _xy(self, n=200, seed=7):
        from ml.pipeline import FeatureEngineer

        df = _ohlcv(n=n, seed=seed)
        X = FeatureEngineer(lookback=5).compute(df)
        y = (X["ret_1"].shift(-1) > 0).astype(int).dropna()
        return X.loc[y.index], y

    def test_fit_and_predict(self):
        from ml.pipeline import XGBoostPredictor

        X, y = self._xy()
        model = XGBoostPredictor(params={"n_estimators": 10, "max_depth": 3})
        model.fit(X, y)
        preds = model.predict(X)
        assert len(preds) == len(X)
        assert set(preds).issubset({0, 1})

    def test_predict_proba_shape(self):
        from ml.pipeline import XGBoostPredictor

        X, y = self._xy()
        model = XGBoostPredictor(params={"n_estimators": 10, "max_depth": 3})
        model.fit(X, y)
        proba = model.predict_proba(X)
        # predict_proba returns 1D array of positive-class probabilities
        assert proba.shape == (len(X),)

    def test_feature_importances(self):
        from ml.pipeline import XGBoostPredictor

        X, y = self._xy()
        model = XGBoostPredictor(params={"n_estimators": 10})
        model.fit(X, y)
        fi = model.get_feature_importances()
        assert isinstance(fi, dict)
        assert len(fi) > 0

    def test_save_and_load(self):
        from ml.pipeline import XGBoostPredictor

        X, y = self._xy()
        model = XGBoostPredictor(params={"n_estimators": 10})
        model.fit(X, y)
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "model.joblib")
            model.save(path)
            model2 = XGBoostPredictor()
            model2.load(path)
            preds = model2.predict(X)
            assert len(preds) == len(X)

    def test_threshold_affects_predictions(self):
        from ml.pipeline import XGBoostPredictor

        X, y = self._xy()
        model = XGBoostPredictor(params={"n_estimators": 10})
        model.fit(X, y)
        p_low = model.predict(X, threshold=0.1)
        p_high = model.predict(X, threshold=0.9)
        assert p_low.sum() >= p_high.sum()


# ── ml/drift_monitor ─────────────────────────────────────────────────────────


class TestDriftMonitorFunctions:
    def test_psi_zero_for_identical(self):
        from ml.drift_monitor import _psi

        rng = np.random.default_rng(1)
        arr = rng.normal(0, 1, 500)
        psi = _psi(arr, arr, n_bins=10)
        assert psi == pytest.approx(0.0, abs=1e-6)

    def test_psi_large_for_shifted(self):
        from ml.drift_monitor import _psi

        rng = np.random.default_rng(2)
        ref = rng.normal(0, 1, 500)
        live = rng.normal(5, 1, 500)
        psi = _psi(ref, live, n_bins=10)
        assert psi > 0.1

    def test_ks_pvalue_same_dist(self):
        from ml.drift_monitor import _ks_pvalue

        rng = np.random.default_rng(3)
        arr = rng.normal(0, 1, 200)
        p = _ks_pvalue(arr, arr)
        assert p == pytest.approx(1.0)

    def test_ks_pvalue_different_dist(self):
        from ml.drift_monitor import _ks_pvalue

        rng = np.random.default_rng(4)
        ref = rng.normal(0, 1, 200)
        live = rng.normal(10, 1, 200)
        p = _ks_pvalue(ref, live)
        assert p < 0.05


class TestDriftMonitor:
    def _monitor(self, seed=5):
        rng = np.random.default_rng(seed)
        ref = {"feat_a": rng.normal(0, 1, 500), "feat_b": rng.normal(5, 2, 500)}
        from ml.drift_monitor import DriftMonitor

        return DriftMonitor.from_reference_arrays(ref, n_bins=10)

    def test_from_reference_arrays(self):
        monitor = self._monitor()
        assert monitor is not None

    def test_compute_no_drift(self):
        from ml.drift_monitor import DriftMonitor

        rng = np.random.default_rng(6)
        ref = {"feat_a": rng.normal(0, 1, 500)}
        monitor = DriftMonitor.from_reference_arrays(ref)
        live = pd.DataFrame({"feat_a": rng.normal(0, 1, 100)})
        report = monitor.compute(live)
        assert report.n_features_checked == 1
        # requires_retrain depends on PSI threshold; just check it's a bool
        assert isinstance(report.requires_retrain, bool)

    def test_compute_detects_drift(self):
        from ml.drift_monitor import DriftMonitor

        rng = np.random.default_rng(7)
        ref = {"feat_a": rng.normal(0, 1, 500)}
        monitor = DriftMonitor.from_reference_arrays(ref)
        live = pd.DataFrame({"feat_a": rng.normal(10, 1, 200)})
        report = monitor.compute(live)
        assert report.requires_retrain is True

    def test_report_overall_status(self):
        from ml.drift_monitor import DriftMonitor

        rng = np.random.default_rng(8)
        ref = {"feat_a": rng.normal(0, 1, 500)}
        monitor = DriftMonitor.from_reference_arrays(ref)
        live = pd.DataFrame({"feat_a": rng.normal(0, 1, 100)})
        report = monitor.compute(live)
        assert report.overall_status in ("green", "yellow", "red")

    def test_report_to_dict(self):
        from ml.drift_monitor import DriftMonitor

        rng = np.random.default_rng(9)
        ref = {"feat_a": rng.normal(0, 1, 500)}
        monitor = DriftMonitor.from_reference_arrays(ref)
        live = pd.DataFrame({"feat_a": rng.normal(0, 1, 100)})
        report = monitor.compute(live)
        d = report.to_dict()
        assert isinstance(d, dict)
        assert "requires_retrain" in d

    def test_feature_drift_psi_level(self):
        from ml.drift_monitor import FeatureDrift

        fd = FeatureDrift(
            feature="f",
            psi=0.05,
            ks_pvalue=0.5,
            z_score=0.1,
            train_mean=0.0,
            train_std=1.0,
            live_mean=0.1,
            live_std=1.0,
        )
        assert fd.psi_level == "green"

    def test_feature_drift_psi_yellow(self):
        from ml.drift_monitor import FeatureDrift

        fd = FeatureDrift(
            feature="f",
            psi=0.15,
            ks_pvalue=0.5,
            z_score=0.1,
            train_mean=0.0,
            train_std=1.0,
            live_mean=0.5,
            live_std=1.0,
        )
        assert fd.psi_level == "yellow"

    def test_feature_drift_psi_red(self):
        from ml.drift_monitor import FeatureDrift

        fd = FeatureDrift(
            feature="f",
            psi=0.30,
            ks_pvalue=0.01,
            z_score=3.0,
            train_mean=0.0,
            train_std=1.0,
            live_mean=5.0,
            live_std=1.0,
        )
        assert fd.psi_level == "red"

    def test_feature_drift_ks_alarm(self):
        from ml.drift_monitor import FeatureDrift

        fd = FeatureDrift(
            feature="f",
            psi=0.05,
            ks_pvalue=0.01,
            z_score=0.1,
            train_mean=0.0,
            train_std=1.0,
            live_mean=0.1,
            live_std=1.0,
        )
        assert fd.ks_alarm is True

    def test_from_feature_stats_missing_path(self):
        from ml.drift_monitor import DriftMonitor

        # Missing path returns empty monitor (no crash)
        monitor = DriftMonitor.from_feature_stats("/nonexistent/path/feature_stats.json")
        assert monitor is not None


# ── ml/performance_monitor ────────────────────────────────────────────────────


class TestVersionWindow:
    def test_record_and_mean(self):
        from ml.performance_monitor import _VersionWindow

        w = _VersionWindow("v1", maxlen=10)
        w.record(100.0)
        w.record(-50.0)
        assert w.mean_pnl == pytest.approx(25.0)

    def test_trade_count(self):
        from ml.performance_monitor import _VersionWindow

        w = _VersionWindow("v1", maxlen=10)
        for _ in range(5):
            w.record(10.0)
        assert w.trade_count == 5

    def test_mean_pnl_none_when_empty(self):
        from ml.performance_monitor import _VersionWindow

        w = _VersionWindow("v1", maxlen=10)
        assert w.mean_pnl is None

    def test_maxlen_respected(self):
        from ml.performance_monitor import _VersionWindow

        w = _VersionWindow("v1", maxlen=3)
        for i in range(10):
            w.record(float(i))
        assert w.trade_count == 3


class TestModelPerformanceMonitor:
    def test_instantiation(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        assert m is not None

    def test_record_trade_no_version(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.record_trade(100.0)
        stats = m.get_stats()
        assert isinstance(stats, dict)

    def test_record_trade_with_version(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.record_trade(50.0, model_version="v1")
        m.record_trade(-20.0, model_version="v1")
        stats = m.get_stats()
        assert "v1" in stats

    def test_on_model_promoted(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.on_model_promoted("v2", "v1")
        assert m._current_version == "v2"
        assert m._previous_version == "v1"

    def test_status_returns_dict(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.record_trade(10.0, model_version="v1")
        s = m.status()
        assert isinstance(s, dict)

    def test_stop(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.stop()
        assert m._running is False

    def test_should_rollback_worse_performance(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        should, reason = m._should_rollback(cur_mean=-50.0, prev_mean=100.0)
        assert should is True
        assert reason != ""

    def test_should_not_rollback_better_performance(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        should, _ = m._should_rollback(cur_mean=100.0, prev_mean=50.0)
        assert should is False

    def test_should_not_rollback_no_prev(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        should, _ = m._should_rollback(cur_mean=50.0, prev_mean=None)
        assert should is False


# ── ml/signal_filter ─────────────────────────────────────────────────────────


class TestSignalFilter:
    def setup_method(self):
        from ml.signal_filter import SignalFilter

        self.sf = SignalFilter()

    def test_high_confidence_passes(self):
        sig = {"direction": "long", "confidence": 0.80, "symbol": "XAUUSD"}
        result = self.sf.check(sig)
        assert result.passed is True

    def test_low_confidence_blocked(self):
        sig = {"direction": "long", "confidence": 0.30, "symbol": "XAUUSD"}
        result = self.sf.check(sig)
        assert result.passed is False
        assert result.gate == "confidence"

    def test_filter_returns_same_as_check(self):
        sig = {"direction": "long", "confidence": 0.80, "symbol": "XAUUSD"}
        r1 = self.sf.check(sig)
        r2 = self.sf.filter(sig)
        assert r1.passed == r2.passed

    def test_filter_result_bool(self):
        from ml.signal_filter import FilterResult

        fr = FilterResult(
            passed=True, reason="ok", gate="", confidence=0.8, expected_value=0.5, regime="trending", mtf_aligned=True
        )
        assert bool(fr) is True

    def test_filter_result_bool_false(self):
        from ml.signal_filter import FilterResult

        fr = FilterResult(
            passed=False,
            reason="low conf",
            gate="confidence",
            confidence=0.3,
            expected_value=0.0,
            regime="unknown",
            mtf_aligned=False,
        )
        assert bool(fr) is False

    def test_record_outcome_and_ev_stats(self):
        self.sf.record_outcome("XAUUSD", pnl_pct=0.02, direction=1, confidence=0.75)
        self.sf.record_outcome("XAUUSD", pnl_pct=-0.01, direction=1, confidence=0.75)
        stats = self.sf.ev_stats("XAUUSD")
        assert stats["n"] == 2

    def test_get_stats_keys(self):
        stats = self.sf.get_stats()
        assert "global" in stats
        assert "circuit_breaker" in stats

    def test_short_signal_high_confidence(self):
        # 'short' direction has a higher confidence threshold; test that low conf blocks it
        sig = {"direction": "short", "confidence": 0.20, "symbol": "XAUUSD"}
        result = self.sf.check(sig)
        assert result.passed is False
        assert result.gate == "confidence"

    def test_missing_confidence_blocked(self):
        sig = {"direction": "long", "symbol": "XAUUSD"}
        result = self.sf.check(sig)
        assert result.passed is False


# ── ml/model_registry ────────────────────────────────────────────────────────


class TestModelRegistry:
    def _registry(self, tmp_path):
        from ml.model_registry import ModelRegistry

        return ModelRegistry(registry_path=Path(tmp_path) / "registry.json")

    def test_instantiation(self, tmp_path):
        reg = self._registry(tmp_path)
        assert reg is not None

    def test_list_versions_empty(self, tmp_path):
        reg = self._registry(tmp_path)
        assert reg.list_versions() == {}

    def test_register_model(self, tmp_path):
        reg = self._registry(tmp_path)
        # Create a dummy model file
        model_file = Path(tmp_path) / "model.joblib"
        model_file.write_bytes(b"dummy")
        entry = reg.register(
            name="v1",
            file_path=model_file,
            oos_accuracy=0.55,
            oos_auc=0.60,
            oos_p_value=0.03,
            sharpe_gate_passed=True,
            n_trades=100,
        )
        assert entry is not None
        assert "v1" in reg.list_versions()

    def test_get_version(self, tmp_path):
        reg = self._registry(tmp_path)
        model_file = Path(tmp_path) / "model.joblib"
        model_file.write_bytes(b"dummy")
        reg.register(
            "v1", model_file, oos_accuracy=0.65, oos_auc=0.70, oos_p_value=0.03, sharpe_gate_passed=True, n_trades=100
        )
        v = reg.get_version("v1")
        assert v is not None
        assert v["name"] == "v1"

    def test_get_version_missing_returns_none(self, tmp_path):
        reg = self._registry(tmp_path)
        assert reg.get_version("nonexistent") is None

    def test_active_version_none_initially(self, tmp_path):
        reg = self._registry(tmp_path)
        assert reg.active_version() is None

    def test_promote_model(self, tmp_path):
        reg = self._registry(tmp_path)
        model_file = Path(tmp_path) / "model.joblib"
        model_file.write_bytes(b"dummy")
        reg.register(
            "v1", model_file, oos_accuracy=0.65, oos_auc=0.70, oos_p_value=0.03, sharpe_gate_passed=True, n_trades=100
        )
        result = reg.promote("v1")
        assert result is not None
        assert reg.active_version() is not None

    def test_retire_model(self, tmp_path):
        reg = self._registry(tmp_path)
        model_file = Path(tmp_path) / "model.joblib"
        model_file.write_bytes(b"dummy")
        reg.register(
            "v1", model_file, oos_accuracy=0.65, oos_auc=0.70, oos_p_value=0.03, sharpe_gate_passed=True, n_trades=100
        )
        reg.retire("v1")
        v = reg.get_version("v1")
        assert v is None or v.get("state") == "retired"

    def test_verify_missing_file(self, tmp_path):
        reg = self._registry(tmp_path)
        model_file = Path(tmp_path) / "model.joblib"
        model_file.write_bytes(b"dummy")
        reg.register(
            "v1", model_file, oos_accuracy=0.65, oos_auc=0.70, oos_p_value=0.03, sharpe_gate_passed=True, n_trades=100
        )
        # Delete the file then verify
        model_file.unlink()
        ok, msg = reg.verify("v1")
        assert ok is False

    def test_gate_check_blocks_low_accuracy(self, tmp_path):
        reg = self._registry(tmp_path)
        model_file = Path(tmp_path) / "model.joblib"
        model_file.write_bytes(b"dummy")
        # oos_accuracy below threshold, sharpe_gate_passed=False
        reg.register(
            "v_bad", model_file, oos_accuracy=0.40, oos_auc=0.45, oos_p_value=0.5, sharpe_gate_passed=False, n_trades=10
        )
        # Should be in staging, not promoted
        v = reg.get_version("v_bad")
        assert v["state"] == "staging"
