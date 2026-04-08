"""
tests/unit/test_drift_monitor.py

Tests for ml/drift_monitor.py — PSI + KS-test feature drift detection.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ml.drift_monitor import (
    DriftMonitor,
    FeatureDrift,
    _psi,
    _ks_pvalue,
    _empty_report,
    get_drift_monitor,
)


# ── _psi tests ────────────────────────────────────────────────────────────────


class TestPSI:
    def test_identical_distributions_return_zero(self):
        rng = np.random.default_rng(0)
        arr = rng.normal(0, 1, 1000)
        result = _psi(arr, arr)
        assert result < 0.01

    def test_shifted_distribution_returns_nonzero(self):
        rng = np.random.default_rng(0)
        expected = rng.normal(0, 1, 1000)
        actual = rng.normal(5, 1, 1000)  # large shift
        result = _psi(expected, actual)
        assert result > 0.25  # significant drift

    def test_short_array_returns_zero(self):
        assert _psi(np.array([1.0]), np.array([2.0])) == 0.0

    def test_result_is_non_negative(self):
        rng = np.random.default_rng(0)
        expected = rng.normal(0, 1, 500)
        actual = rng.normal(1, 1, 500)
        assert _psi(expected, actual) >= 0.0


# ── _ks_pvalue tests ──────────────────────────────────────────────────────────


class TestKSPValue:
    def test_identical_returns_high_pvalue(self):
        rng = np.random.default_rng(0)
        arr = rng.normal(0, 1, 500)
        p = _ks_pvalue(arr, arr)
        assert p > 0.05

    def test_very_different_returns_low_pvalue(self):
        rng = np.random.default_rng(0)
        ref = rng.normal(0, 1, 500)
        live = rng.normal(10, 1, 500)  # far shifted
        p = _ks_pvalue(ref, live)
        assert p < 0.05


# ── FeatureDrift tests ────────────────────────────────────────────────────────


class TestFeatureDrift:
    def _make(self, psi: float, ks_p: float) -> FeatureDrift:
        return FeatureDrift(
            feature="f",
            psi=psi,
            ks_pvalue=ks_p,
            z_score=1.0,
            train_mean=0.0,
            train_std=1.0,
            live_mean=0.1,
            live_std=0.9,
        )

    def test_psi_level_green(self):
        assert self._make(0.05, 0.5).psi_level == "green"

    def test_psi_level_yellow(self):
        assert self._make(0.15, 0.5).psi_level == "yellow"

    def test_psi_level_red(self):
        assert self._make(0.30, 0.5).psi_level == "red"

    def test_ks_alarm_true(self):
        assert self._make(0.0, 0.01).ks_alarm is True

    def test_ks_alarm_false(self):
        assert self._make(0.0, 0.10).ks_alarm is False

    def test_to_dict_has_expected_keys(self):
        d = self._make(0.05, 0.5).to_dict()
        for key in ("feature", "psi", "psi_level", "ks_pvalue", "ks_alarm", "z_score"):
            assert key in d


# ── DriftMonitor tests ────────────────────────────────────────────────────────


def _make_stats(features: list[str]) -> dict:
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 1000)
    percentiles = np.percentile(ref, np.linspace(0, 100, 20)).tolist()
    return {f: {"mean": 0.0, "std": 1.0, "percentiles": percentiles} for f in features}


class TestDriftMonitorInit:
    def test_empty_stats_no_alarm(self):
        monitor = DriftMonitor({})
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"a": rng.normal(0, 1, 100), "b": rng.normal(0, 1, 100)})
        report = monitor.compute(df)
        assert report.requires_retrain is False
        assert report.n_features_checked == 0

    def test_from_feature_stats_missing_file_returns_empty(self, tmp_path):
        monitor = DriftMonitor.from_feature_stats(tmp_path / "does_not_exist.json")
        assert monitor._stats == {}

    def test_from_feature_stats_valid_file(self, tmp_path):
        stats = {"f1": {"mean": 1.0, "std": 0.5}, "f2": {"mean": -1.0, "std": 2.0}}
        p = tmp_path / "stats.json"
        p.write_text(json.dumps(stats))
        monitor = DriftMonitor.from_feature_stats(p)
        assert "f1" in monitor._stats
        assert "f2" in monitor._stats


class TestDriftMonitorCompute:
    def test_insufficient_samples_returns_empty(self):
        monitor = DriftMonitor(_make_stats(["f1"]))
        df = pd.DataFrame({"f1": [1.0] * 10})  # < 50
        report = monitor.compute(df)
        assert report.n_features_checked == 0
        assert report.live_samples == 10

    def test_clean_data_no_retrain(self):
        rng = np.random.default_rng(42)
        feats = ["f1", "f2", "f3"]
        # Generate training reference from the same seed so distributions match
        ref = rng.normal(0, 1, 1000)
        percentiles = np.percentile(ref, np.linspace(0, 100, 20)).tolist()
        stats = {f: {"mean": 0.0, "std": 1.0, "percentiles": percentiles} for f in feats}
        monitor = DriftMonitor(stats)
        # Live data drawn from same distribution (N(0,1), 500 samples for stability)
        rng2 = np.random.default_rng(0)
        df = pd.DataFrame({f: rng2.normal(0, 1, 500) for f in feats})
        report = monitor.compute(df)
        # Should be green or yellow (no red, no retrain)
        assert report.n_red == 0
        assert report.requires_retrain is False

    def test_severely_drifted_data_triggers_retrain(self):
        feats = ["f1", "f2", "f3", "f4", "f5"]
        monitor = DriftMonitor(_make_stats(feats))
        # All features shifted 10 standard deviations
        rng = np.random.default_rng(1)
        df = pd.DataFrame({f: rng.normal(10, 1, 100) for f in feats})
        report = monitor.compute(df)
        assert report.requires_retrain is True
        assert report.overall_status == "red"

    def test_report_feature_list_populated(self):
        rng = np.random.default_rng(42)
        feats = ["a", "b"]
        monitor = DriftMonitor(_make_stats(feats))
        df = pd.DataFrame({f: rng.normal(0, 1, 100) for f in feats})
        report = monitor.compute(df)
        assert len(report.features) == 2

    def test_to_dict_structure(self):
        rng = np.random.default_rng(42)
        feats = ["x"]
        monitor = DriftMonitor(_make_stats(feats))
        df = pd.DataFrame({"x": rng.normal(0, 1, 100)})
        d = monitor.compute(df).to_dict()
        for key in ("overall_status", "requires_retrain", "n_features_checked", "max_psi", "features"):
            assert key in d


# ── Singleton tests ───────────────────────────────────────────────────────────


class TestGetDriftMonitor:
    def test_returns_drift_monitor_instance(self, tmp_path):
        stats = {"f1": {"mean": 0.0, "std": 1.0}}
        p = tmp_path / "stats.json"
        p.write_text(json.dumps(stats))
        monitor = get_drift_monitor(stats_path=p, force_reload=True)
        assert isinstance(monitor, DriftMonitor)

    def test_force_reload_refreshes_singleton(self, tmp_path):
        stats_v1 = {"f1": {"mean": 0.0, "std": 1.0}}
        stats_v2 = {"f1": {"mean": 0.0, "std": 1.0}, "f2": {"mean": 5.0, "std": 2.0}}
        p = tmp_path / "stats.json"
        p.write_text(json.dumps(stats_v1))
        m1 = get_drift_monitor(stats_path=p, force_reload=True)
        p.write_text(json.dumps(stats_v2))
        m2 = get_drift_monitor(stats_path=p, force_reload=True)
        assert len(m2._stats) > len(m1._stats)


# ── DriftReport tests ─────────────────────────────────────────────────────────


class TestDriftReport:
    def test_overall_status_green(self):
        r = _empty_report(100)
        r.n_green = 5
        assert r.overall_status == "green"

    def test_overall_status_red_when_n_red_gt_0(self):
        r = _empty_report(100)
        r.n_red = 1
        assert r.overall_status == "red"


# ── _empty_report tests ───────────────────────────────────────────────────────


class TestEmptyReport:
    def test_empty_report_does_not_require_retrain(self):
        r = _empty_report(25)
        assert r.requires_retrain is False
        assert r.live_samples == 25
        assert r.n_features_checked == 0
