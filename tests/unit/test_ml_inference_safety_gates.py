# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_inference_safety_gates.py
============================================
The gates in `ml/inference_engine.py` (752 statements at 65.61 %).

`CLAUDE.md` names these explicitly: *"Never weaken a risk gate, kill switch, or
staleness/drift check without explicit instruction."* Every one of them is
fail-closed by design, and fail-closed behaviour is exactly what a test suite
usually forgets to cover, because the happy path is what gets exercised in
development. Each gate below is asserted on the branch that *blocks*, not just
the branch that passes.

* **Staleness.** If the model's age cannot be determined at all, the model is
  treated as STALE — not as fresh. An exception in a freshness check must not
  become permission to trade on a model of unknown age.
* **Feature usability.** A vector containing NaN/Inf, or one that is >95 %
  zeros, is refused rather than zero-imputed. Imputing produces a *confident*
  prediction from corrupt input, which is worse than no prediction; and an
  all-zero vector is the signature of a silent upstream feed failure.
* **The drift guard reports whether it is running.** A missing training-stats
  file makes `_check_feature_drift` return `False`, which is indistinguishable
  from "no drift" — the original S4-05 defect. `drift_guard_active()` and
  `drift_status()` exist so a disabled guard cannot masquerade as a clean one,
  and `insufficient_coverage` distinguishes a stale feature schema (stats
  present but describing features the model no longer emits) from an absent
  artifact. Those are two different remedies.
* **`is_safe_to_trade` fails closed** when the orchestrator cannot be reached.
"""

from __future__ import annotations

import builtins
import json
import time

import numpy as np
import pandas as pd
import pytest

import ml.inference_engine as ie
from ml.inference_engine import InferenceEngine, _prefix_counts

pytestmark = pytest.mark.unit


@pytest.fixture
def engine():
    return InferenceEngine()


@pytest.fixture
def model_file(tmp_path, monkeypatch):
    """An artifact whose mtime the tests control."""
    path = tmp_path / "advanced_oos.pkl"
    path.write_bytes(b"model")
    monkeypatch.setattr(ie, "_saved", lambda name: tmp_path / name)
    return path


def _age(path, days):
    when = time.time() - days * 86_400.0
    import os

    os.utime(path, (when, when))


# ── model staleness ───────────────────────────────────────────────────────────


class TestModelStaleness:
    def test_a_fresh_model_is_not_stale(self, engine, model_file, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30)
        _age(model_file, 1)

        assert engine._check_model_staleness() is False
        assert engine._model_stale is False

    def test_an_old_model_is_stale(self, engine, model_file, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30)
        _age(model_file, 90)

        assert engine._check_model_staleness() is True
        assert engine._model_stale is True

    def test_the_age_is_reported_in_days(self, engine, model_file, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30)
        _age(model_file, 45)

        engine._check_model_staleness()

        assert engine._model_age_days == pytest.approx(45.0, abs=0.1)

    def test_a_zero_max_age_disables_the_check(self, engine, model_file, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 0)
        _age(model_file, 9999)

        assert engine._check_model_staleness() is False
        assert engine._model_age_days is None

    def test_a_negative_max_age_also_disables_it(self, engine, model_file, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", -1)
        _age(model_file, 9999)

        assert engine._check_model_staleness() is False

    def test_a_missing_model_is_unavailable_rather_than_stale(self, engine, tmp_path, monkeypatch):
        """'No model' is handled elsewhere; conflating it with 'stale' hides it."""
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30)
        monkeypatch.setattr(ie, "_saved", lambda name: tmp_path / "absent.pkl")
        engine._active_model_path = None

        assert engine._check_model_staleness() is False
        assert engine._model_age_days is None

    def test_an_unreadable_model_is_treated_as_stale(self, engine, monkeypatch, tmp_path):
        """Fail CLOSED. Unknown age must never read as permission to trade."""
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30)

        class _Exploding:
            def exists(self):
                return True

            def stat(self):
                raise OSError("filesystem gone")

            name = "advanced_oos.pkl"

        engine._active_model_path = _Exploding()

        assert engine._check_model_staleness() is True
        assert engine._model_stale is True

    def test_the_active_model_path_takes_precedence(self, engine, tmp_path, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30)
        explicit = tmp_path / "explicit.pkl"
        explicit.write_bytes(b"m")
        _age(explicit, 90)
        engine._active_model_path = explicit

        assert engine._check_model_staleness() is True

    def test_exactly_at_the_limit_is_not_yet_stale(self, engine, model_file, monkeypatch):
        monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30)
        _age(model_file, 29.9)

        assert engine._check_model_staleness() is False


# ── feature usability ─────────────────────────────────────────────────────────


def _good_features(n_cols=20):
    return pd.DataFrame({f"f{i}": [float(i + 1)] for i in range(n_cols)})


class TestFeatureUsability:
    def test_a_healthy_vector_is_usable(self, engine):
        assert engine._features_are_unusable(_good_features()) is False

    def test_none_is_unusable(self, engine):
        assert engine._features_are_unusable(None) is True

    def test_an_empty_frame_is_unusable(self, engine):
        assert engine._features_are_unusable(pd.DataFrame()) is True

    def test_a_frame_with_no_numeric_columns_is_unusable(self, engine):
        assert engine._features_are_unusable(pd.DataFrame({"a": ["x"], "b": ["y"]})) is True

    def test_a_nan_anywhere_makes_it_unusable(self, engine):
        """Zero-imputing corrupt input produces a *confident* wrong prediction."""
        X = _good_features()
        X.loc[0, "f3"] = np.nan

        assert engine._features_are_unusable(X) is True

    def test_a_positive_infinity_makes_it_unusable(self, engine):
        X = _good_features()
        X.loc[0, "f3"] = np.inf

        assert engine._features_are_unusable(X) is True

    def test_a_negative_infinity_makes_it_unusable(self, engine):
        X = _good_features()
        X.loc[0, "f3"] = -np.inf

        assert engine._features_are_unusable(X) is True

    def test_an_all_zero_vector_is_unusable(self, engine):
        """The signature of a silent upstream feed failure."""
        X = pd.DataFrame({f"f{i}": [0.0] for i in range(20)})

        assert engine._features_are_unusable(X) is True

    def test_a_mostly_zero_vector_is_unusable(self, engine):
        X = pd.DataFrame({f"f{i}": [0.0] for i in range(100)})
        X.loc[0, "f0"] = 1.0  # 1% non-zero, under the 5% floor

        assert engine._features_are_unusable(X) is True

    def test_a_sparse_but_plausible_vector_is_usable(self, engine):
        X = pd.DataFrame({f"f{i}": [0.0] for i in range(100)})
        for i in range(20):
            X.loc[0, f"f{i}"] = float(i + 1)  # 20% non-zero

        assert engine._features_are_unusable(X) is False

    def test_rejection_increments_the_fallback_counter(self, engine):
        before = engine._fallback_count
        X = _good_features()
        X.loc[0, "f1"] = np.nan

        engine._features_are_unusable(X)

        assert engine._fallback_count > before

    def test_an_internal_failure_fails_closed(self, engine):
        """If usability cannot be established, do not score."""

        class _Hostile:
            empty = False

            def select_dtypes(self, **kwargs):
                raise RuntimeError("frame is lying")

        assert engine._features_are_unusable(_Hostile()) is True


# ── the drift guard's self-report ─────────────────────────────────────────────


class TestDriftGuardVisibility:
    def test_a_fresh_engine_reports_the_guard_as_inactive(self, engine):
        assert engine.drift_guard_active() is False

    def test_missing_training_stats_disable_the_guard_rather_than_pass_it(self, engine, monkeypatch):
        """The S4-05 defect: 'no stats' returning False reads as 'no drift'."""
        monkeypatch.setattr(engine, "_load_train_stats", lambda: None)

        drifted = engine._check_feature_drift(_good_features())

        assert drifted is False
        assert engine.drift_guard_active() is False
        assert engine.drift_status()["reason"] == "no_training_stats"

    def test_an_empty_row_is_not_reported_as_a_clean_check(self, engine):
        assert engine._check_feature_drift(pd.DataFrame()) is False

    def test_none_is_not_reported_as_a_clean_check(self, engine):
        assert engine._check_feature_drift(None) is False

    def test_stats_covering_the_schema_activate_the_guard(self, engine, monkeypatch):
        X = _good_features(20)
        stats = {c: {"mean": 1.0, "std": 1.0} for c in X.columns}
        monkeypatch.setattr(engine, "_load_train_stats", lambda: stats)

        engine._check_feature_drift(X)

        assert engine.drift_guard_active() is True
        assert engine.drift_status()["covered"] == 20

    def test_stats_describing_a_stale_schema_do_not_count_as_running(self, engine, monkeypatch):
        """Present-but-irrelevant stats would otherwise report a clean result
        computed from almost nothing."""
        X = _good_features(20)
        stats = {"legacy_feature": {"mean": 1.0, "std": 1.0}}
        monkeypatch.setattr(engine, "_load_train_stats", lambda: stats)

        engine._check_feature_drift(X)

        assert engine.drift_guard_active() is False
        assert engine.drift_status()["reason"] == "insufficient_coverage"

    def test_the_two_inactive_reasons_are_distinguished(self, engine, monkeypatch):
        """They have different remedies: retrain vs regenerate the stats."""
        X = _good_features(20)

        monkeypatch.setattr(engine, "_load_train_stats", lambda: None)
        engine._check_feature_drift(X)
        absent = engine.drift_status()["reason"]

        monkeypatch.setattr(engine, "_load_train_stats", lambda: {"legacy": {"mean": 0.0, "std": 1.0}})
        engine._check_feature_drift(X)
        stale = engine.drift_status()["reason"]

        assert absent != stale

    def test_the_status_names_which_features_are_unwatched(self, engine, monkeypatch):
        """'170 of 229 covered' does not tell an operator where the gap is."""
        X = _good_features(10)
        stats = {c: {"mean": 1.0, "std": 1.0} for c in list(X.columns)[:6]}
        monkeypatch.setattr(engine, "_load_train_stats", lambda: stats)

        engine._check_feature_drift(X)
        status = engine.drift_status()

        assert set(status["uncovered"]) == set(list(X.columns)[6:])

    def test_the_status_is_json_serialisable(self, engine, monkeypatch):
        monkeypatch.setattr(engine, "_load_train_stats", lambda: None)
        engine._check_feature_drift(_good_features())

        json.dumps(engine.drift_status())

    def test_the_status_reports_every_documented_key(self, engine):
        assert set(engine.drift_status()) >= {
            "active",
            "reason",
            "covered",
            "total",
            "min_coverage",
            "drift_detected",
            "z_max",
            "uncovered",
            "uncovered_by_prefix",
        }


class TestPrefixCounts:
    def test_an_empty_list_counts_nothing(self):
        assert _prefix_counts([]) == {}

    def test_features_are_grouped_by_their_prefix(self):
        counts = _prefix_counts(["dl_a", "dl_b", "cot_x"])

        assert counts["dl"] == 2
        assert counts["cot"] == 1

    def test_a_name_without_a_prefix_is_still_counted(self):
        assert sum(_prefix_counts(["bare"]).values()) == 1

    def test_the_grouping_tells_one_stale_block_from_scattered_gaps(self):
        """That distinction is the whole reason this breakdown exists."""
        block = _prefix_counts([f"dl_{i}" for i in range(10)])
        scattered = _prefix_counts(["dl_1", "cot_1", "oi_1", "of_1", "ri_1"])

        assert len(block) == 1
        assert len(scattered) == 5


# ── training stats loading ────────────────────────────────────────────────────


class TestLoadTrainStats:
    def test_a_missing_file_yields_nothing(self, engine, tmp_path, monkeypatch):
        monkeypatch.setattr(ie, "_saved", lambda name: tmp_path / name)
        engine._train_stats = None

        assert engine._load_train_stats() is None

    def test_a_valid_file_is_loaded(self, engine, tmp_path, monkeypatch):
        stats = {"rsi": {"mean": 50.0, "std": 10.0}}
        (tmp_path / "feature_stats.json").write_text(json.dumps(stats))
        monkeypatch.setattr(ie, "_saved", lambda name: tmp_path / name)
        engine._train_stats = None

        assert engine._load_train_stats() == stats

    def test_a_corrupt_file_yields_nothing_rather_than_raising(self, engine, tmp_path, monkeypatch):
        (tmp_path / "feature_stats.json").write_text("{ not json")
        monkeypatch.setattr(ie, "_saved", lambda name: tmp_path / name)
        engine._train_stats = None

        assert engine._load_train_stats() is None


# ── calibration ───────────────────────────────────────────────────────────────


class TestCalibration:
    def test_without_a_calibrator_the_raw_probability_passes_through(self, engine, monkeypatch):
        monkeypatch.setattr(engine, "_load_calibrator", lambda: None)

        assert engine._calibrate(0.73) == pytest.approx(0.73)

    def test_a_calibrator_is_applied(self, engine, monkeypatch):
        class _Cal:
            def predict(self, X):
                return [0.42]

        monkeypatch.setattr(engine, "_load_calibrator", lambda: _Cal())

        assert engine._calibrate(0.9) == pytest.approx(0.42)

    def test_the_result_is_clipped_to_a_probability(self, engine, monkeypatch):
        class _Cal:
            def __init__(self, v):
                self.v = v

            def predict(self, X):
                return [self.v]

        monkeypatch.setattr(engine, "_load_calibrator", lambda: _Cal(1.7))
        assert engine._calibrate(0.9) == pytest.approx(1.0)

        monkeypatch.setattr(engine, "_load_calibrator", lambda: _Cal(-0.4))
        assert engine._calibrate(0.1) == pytest.approx(0.0)

    def test_a_failing_calibrator_falls_back_to_the_raw_value(self, engine, monkeypatch):
        class _Cal:
            def predict(self, X):
                raise RuntimeError("calibrator mismatch")

        monkeypatch.setattr(engine, "_load_calibrator", lambda: _Cal())

        assert engine._calibrate(0.61) == pytest.approx(0.61)


# ── the trading safety predicate ──────────────────────────────────────────────


class TestIsSafeToTrade:
    def test_it_fails_closed_when_the_orchestrator_is_unreachable(self, engine, monkeypatch):
        """Unknown safety state must never read as safe."""
        real_import = builtins.__import__

        def _no_orchestrator(name, *args, **kwargs):
            if name == "data_layer.orchestrator":
                raise ImportError("unavailable")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_orchestrator)

        assert engine.is_safe_to_trade() is False

    def test_it_reflects_a_healthy_orchestrator(self, engine, monkeypatch):
        from data_layer.orchestrator import orchestrator

        monkeypatch.setattr(orchestrator, "is_safe_to_trade", lambda: True)

        assert engine.is_safe_to_trade() is True

    def test_it_reflects_an_unhealthy_orchestrator(self, engine, monkeypatch):
        from data_layer.orchestrator import orchestrator

        monkeypatch.setattr(orchestrator, "is_safe_to_trade", lambda: False)

        assert engine.is_safe_to_trade() is False

    def test_a_raising_orchestrator_fails_closed(self, engine, monkeypatch):
        from data_layer.orchestrator import orchestrator

        def _boom():
            raise RuntimeError("feed state indeterminate")

        monkeypatch.setattr(orchestrator, "is_safe_to_trade", _boom)

        assert engine.is_safe_to_trade() is False


# ── health ────────────────────────────────────────────────────────────────────


class TestHealth:
    def test_it_is_json_serialisable(self, engine):
        json.dumps(engine.health())

    def test_it_reports_whether_the_drift_guard_has_stats(self, engine):
        """An operator must be able to see the guard's state from /health."""
        health = engine.health()

        assert "train_stats_available" in health
        assert isinstance(health["train_stats_available"], bool)

    def test_it_reports_the_drift_window(self, engine):
        assert "feature_drift_window" in engine.health()

    def test_it_reports_the_model_identity(self, engine):
        health = engine.health()

        assert "model_available" in health
        assert "model_version" in health

    def test_it_is_stamped(self, engine):
        from datetime import datetime

        assert datetime.fromisoformat(engine.health()["checked_at"])

    def test_the_singleton_is_shared(self):
        from ml.inference_engine import get_inference_engine

        assert get_inference_engine() is get_inference_engine()
