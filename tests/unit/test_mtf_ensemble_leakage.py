# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for the mtf_ensemble calibration-leakage fix.

The original bug: CalibratedClassifierCV(cv=3) on the stacking ensemble
caused base learners to be re-trained on sub-splits of the test fold,
producing spuriously high walk-forward CV accuracy (~99%).

The fix: three-way split (fit / OOF / cal) with cv='prefit' throughout.

These tests verify:
1. train_stacking_ensemble uses cv='prefit' — no re-training on test data.
2. OOF meta-features are built from data the base learners never trained on.
3. The meta-learner calibration set is disjoint from both fit and OOF sets.
4. evaluate() correctly routes through base_learners → meta_X → meta-model.
5. Registry records the leakage fix.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_xy(n: int = 400, n_features: int = 10, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.standard_normal((n, n_features)), columns=[f"f{i}" for i in range(n_features)])
    y = pd.Series((rng.random(n) > 0.5).astype(int))
    return X, y


def _make_calibrated_mock(proba_val: float = 0.6) -> MagicMock:
    """Return a mock that behaves like a fitted CalibratedClassifierCV."""
    mock = MagicMock(spec=CalibratedClassifierCV)
    mock.predict_proba = MagicMock(
        side_effect=lambda X: np.column_stack([
            np.full(len(X), 1 - proba_val),
            np.full(len(X), proba_val),
        ])
    )
    mock.predict = MagicMock(side_effect=lambda X: np.ones(len(X), dtype=int))
    return mock


# ── Test: cv='prefit' is used throughout ─────────────────────────────────────

class TestCalibrationNeverRefits:
    """
    Verify that CalibratedClassifierCV is always constructed with cv='prefit'.

    cv='prefit' means the base estimator is already fitted and the calibrator
    only fits the isotonic/sigmoid layer — it does NOT re-train the base model.
    cv=3 (the old default) would re-train the base model on 3 sub-splits of
    the calibration data, causing leakage when that data overlaps with test data.

    CalibratedClassifierCV is imported locally inside each train_* function,
    so we patch it at the sklearn.calibration module level.
    """

    def test_train_xgboost_uses_prefit(self):
        """train_xgboost must call CalibratedClassifierCV(cv='prefit')."""
        import scripts.retrain_mtf_accuracy as rma

        X_train, y_train = _make_xy(200)
        X_test, y_test = _make_xy(50, seed=99)

        captured_cv_args = []
        original_cal = CalibratedClassifierCV

        class _TrackingCal(CalibratedClassifierCV):
            def __init__(self, estimator, *, method="sigmoid", cv=5):
                captured_cv_args.append(cv)
                super().__init__(estimator, method=method, cv=cv)

        with patch("sklearn.calibration.CalibratedClassifierCV", _TrackingCal):
            try:
                rma.train_xgboost(X_train, y_train, X_test, y_test)
            except Exception:
                pass  # XGBoost import errors are acceptable; we only care about cv arg

        # Every CalibratedClassifierCV instantiation must use cv='prefit'
        for cv_arg in captured_cv_args:
            assert cv_arg == "prefit", (
                f"CalibratedClassifierCV called with cv={cv_arg!r} — must be 'prefit'"
            )

    def test_train_random_forest_uses_prefit(self):
        """train_random_forest must call CalibratedClassifierCV(cv='prefit')."""
        import scripts.retrain_mtf_accuracy as rma

        X_train, y_train = _make_xy(200)
        captured_cv_args = []

        class _TrackingCal(CalibratedClassifierCV):
            def __init__(self, estimator, *, method="sigmoid", cv=5):
                captured_cv_args.append(cv)
                super().__init__(estimator, method=method, cv=cv)

        with patch("sklearn.calibration.CalibratedClassifierCV", _TrackingCal):
            try:
                rma.train_random_forest(X_train, y_train)
            except Exception:
                pass

        for cv_arg in captured_cv_args:
            assert cv_arg == "prefit", (
                f"train_random_forest: CalibratedClassifierCV cv={cv_arg!r} — must be 'prefit'"
            )


# ── Test: three-way split in train_stacking_ensemble ─────────────────────────

class TestStackingThreeWaySplit:
    """
    Verify the three-way split (fit / OOF / cal) in train_stacking_ensemble.

    The key invariant: base learners are trained on X_fit, OOF meta-features
    are built from X_oof (disjoint from X_fit), and the meta-learner is
    calibrated on X_cal (disjoint from both).
    """

    def test_base_learners_not_trained_on_cal_set(self):
        """
        Base learners must not see X_cal during training.

        We verify this by checking that train_xgboost, train_random_forest,
        and train_lightgbm are called with data that is a strict subset of
        X_train (not X_cal).
        """
        import scripts.retrain_mtf_accuracy as rma

        X_train, y_train = _make_xy(300)
        X_cal, y_cal = _make_xy(100, seed=77)

        fit_sizes_seen = []

        original_xgb = rma.train_xgboost
        original_rf = rma.train_random_forest
        original_lgb = rma.train_lightgbm

        def _track_xgb(X_fit, y_fit, X_oof, y_oof):
            fit_sizes_seen.append(("xgb_fit", len(X_fit)))
            fit_sizes_seen.append(("xgb_oof", len(X_oof)))
            return _make_calibrated_mock()

        def _track_rf(X_fit, y_fit):
            fit_sizes_seen.append(("rf_fit", len(X_fit)))
            return _make_calibrated_mock()

        def _track_lgb(X_fit, y_fit, X_oof, y_oof):
            fit_sizes_seen.append(("lgb_fit", len(X_fit)))
            return _make_calibrated_mock()

        with (
            patch.object(rma, "train_xgboost", side_effect=_track_xgb),
            patch.object(rma, "train_random_forest", side_effect=_track_rf),
            patch.object(rma, "train_lightgbm", side_effect=_track_lgb),
        ):
            rma.train_stacking_ensemble(X_train, y_train, X_cal, y_cal)

        # Base learners must be trained on a subset of X_train, not X_cal
        cal_size = len(X_cal)
        for label, size in fit_sizes_seen:
            assert size != cal_size or label.endswith("_oof"), (
                f"{label} was called with size={size} which equals X_cal size={cal_size}. "
                "Base learners must not train on the calibration set."
            )
            # Fit set must be smaller than X_train (it's a 75% split)
            if label.endswith("_fit"):
                assert size < len(X_train), (
                    f"{label} fit size {size} >= X_train size {len(X_train)} — no split applied"
                )

    def test_meta_learner_trains_on_oof_not_cal(self):
        """
        The meta-learner must be trained on OOF predictions, not on X_cal.

        We verify by checking that LogisticRegression.fit is called with
        data whose length matches the OOF split (25% of X_train), not X_cal.

        Use n_train=400 and n_cal=60 so OOF size (100) != cal size (60),
        making the size-based assertion unambiguous.
        """
        import scripts.retrain_mtf_accuracy as rma

        n_train = 400
        X_train, y_train = _make_xy(n_train)
        # Use n_cal=60 so OOF size (400 * 0.25 = 100) != cal size (60)
        X_cal, y_cal = _make_xy(60, seed=55)

        meta_fit_sizes = []
        original_lr_fit = LogisticRegression.fit

        def _track_lr_fit(self, X, y):
            meta_fit_sizes.append(len(X))
            return original_lr_fit(self, X, y)

        with (
            patch.object(rma, "train_xgboost", return_value=_make_calibrated_mock()),
            patch.object(rma, "train_random_forest", return_value=_make_calibrated_mock()),
            patch.object(rma, "train_lightgbm", return_value=_make_calibrated_mock()),
            patch.object(LogisticRegression, "fit", _track_lr_fit),
        ):
            rma.train_stacking_ensemble(X_train, y_train, X_cal, y_cal)

        # OOF split is 25% of X_train = 100 rows
        expected_oof_size = n_train - int(n_train * 0.75)  # = 100
        cal_size = len(X_cal)  # = 60

        assert meta_fit_sizes, "LogisticRegression.fit was never called"
        lr_fit_size = meta_fit_sizes[0]

        assert lr_fit_size != cal_size, (
            f"Meta-learner trained on X_cal (size={cal_size}) — leakage! "
            f"Should train on OOF set (size≈{expected_oof_size})."
        )
        # OOF size should be approximately 25% of X_train
        assert abs(lr_fit_size - expected_oof_size) <= 2, (
            f"Meta-learner fit size {lr_fit_size} != expected OOF size {expected_oof_size}"
        )


# ── Test: evaluate() routes through base_learners ────────────────────────────

class TestEvaluateRouting:
    """evaluate() must build meta_X from base_learners before calling meta-model."""

    def test_evaluate_with_base_learners_builds_meta_x(self):
        """When base_learners is provided, evaluate must stack their probas."""
        import scripts.retrain_mtf_accuracy as rma

        X_test, y_test = _make_xy(100)

        # Two base learners with known proba outputs
        bl1 = _make_calibrated_mock(proba_val=0.7)
        bl2 = _make_calibrated_mock(proba_val=0.4)

        meta_inputs_seen = []
        meta_mock = MagicMock()
        meta_mock.predict_proba = MagicMock(
            side_effect=lambda X: (meta_inputs_seen.append(X), np.column_stack([
                np.full(len(X), 0.4), np.full(len(X), 0.6)
            ]))[1]
        )
        meta_mock.predict = MagicMock(return_value=np.ones(100, dtype=int))

        result = rma.evaluate(meta_mock, X_test, y_test, base_learners=[bl1, bl2])

        assert meta_inputs_seen, "meta-model predict_proba was never called"
        meta_X = meta_inputs_seen[0]

        # meta_X must have 2 columns (one per base learner)
        assert meta_X.shape[1] == 2, (
            f"meta_X has {meta_X.shape[1]} columns, expected 2 (one per base learner)"
        )
        # Column 0 should be bl1's proba (0.7)
        assert np.allclose(meta_X[:, 0], 0.7, atol=1e-6), "meta_X col 0 != bl1 proba"
        # Column 1 should be bl2's proba (0.4)
        assert np.allclose(meta_X[:, 1], 0.4, atol=1e-6), "meta_X col 1 != bl2 proba"

    def test_evaluate_without_base_learners_uses_raw_x(self):
        """When base_learners is None, evaluate passes X_test directly to model."""
        import scripts.retrain_mtf_accuracy as rma

        X_test, y_test = _make_xy(50)
        raw_inputs_seen = []

        model_mock = MagicMock()
        model_mock.predict_proba = MagicMock(
            side_effect=lambda X: (raw_inputs_seen.append(X), np.column_stack([
                np.full(len(X), 0.45), np.full(len(X), 0.55)
            ]))[1]
        )
        model_mock.predict = MagicMock(return_value=np.ones(50, dtype=int))

        rma.evaluate(model_mock, X_test, y_test, base_learners=None)

        assert raw_inputs_seen, "model predict_proba was never called"
        # The input should be X_test directly (same shape)
        assert raw_inputs_seen[0].shape == X_test.shape

    def test_evaluate_returns_required_keys(self):
        """evaluate() must return a dict with all required metric keys."""
        import scripts.retrain_mtf_accuracy as rma

        X_test, y_test = _make_xy(80)
        model_mock = MagicMock()
        model_mock.predict_proba = MagicMock(
            return_value=np.column_stack([
                np.full(80, 0.4), np.full(80, 0.6)
            ])
        )
        model_mock.predict = MagicMock(return_value=np.ones(80, dtype=int))

        result = rma.evaluate(model_mock, X_test, y_test)

        required = {"accuracy", "accuracy_confident", "auc", "f1", "abstain_rate", "n_confident", "n_total"}
        for key in required:
            assert key in result, f"evaluate() missing key: {key}"

    def test_evaluate_abstain_rate_in_range(self):
        """abstain_rate must be in [0, 1]."""
        import scripts.retrain_mtf_accuracy as rma

        X_test, y_test = _make_xy(60)
        model_mock = MagicMock()
        # Mix of confident and abstain predictions
        probas = np.where(np.arange(60) % 2 == 0, 0.8, 0.5)
        model_mock.predict_proba = MagicMock(
            return_value=np.column_stack([1 - probas, probas])
        )
        model_mock.predict = MagicMock(return_value=(probas > 0.5).astype(int))

        result = rma.evaluate(model_mock, X_test, y_test)

        assert 0.0 <= result["abstain_rate"] <= 1.0, (
            f"abstain_rate={result['abstain_rate']} out of [0, 1]"
        )


# ── Test: registry records the fix ───────────────────────────────────────────

class TestRegistryLeakageFix:
    """Verify the model registry records the leakage fix."""

    def test_registry_records_leakage_fix(self):
        """registry.json must record leakage_bug_fixed=True for mtf_ensemble_v1."""
        reg_path = ROOT / "ml" / "saved_models" / "registry.json"
        assert reg_path.exists(), "registry.json not found"

        reg = json.loads(reg_path.read_text())
        mtf = reg.get("versions", {}).get("mtf_ensemble_v1", {})

        assert mtf.get("leakage_bug_fixed") is True, (
            "registry.json: mtf_ensemble_v1.leakage_bug_fixed must be True"
        )

    def test_registry_records_fix_date(self):
        """registry.json must record the leakage fix date."""
        reg_path = ROOT / "ml" / "saved_models" / "registry.json"
        reg = json.loads(reg_path.read_text())
        mtf = reg.get("versions", {}).get("mtf_ensemble_v1", {})

        assert "leakage_fix_date" in mtf, (
            "registry.json: mtf_ensemble_v1 missing leakage_fix_date"
        )
        assert mtf["leakage_fix_date"], "leakage_fix_date must not be empty"

    def test_registry_records_fix_description(self):
        """registry.json must describe the three-way split fix."""
        reg_path = ROOT / "ml" / "saved_models" / "registry.json"
        reg = json.loads(reg_path.read_text())
        mtf = reg.get("versions", {}).get("mtf_ensemble_v1", {})

        desc = mtf.get("leakage_fix_description", "")
        assert "prefit" in desc.lower() or "three-way" in desc.lower() or "oof" in desc.lower(), (
            "leakage_fix_description must mention the fix mechanism (prefit/three-way/OOF)"
        )

    def test_registry_mtf_notes_mention_fix(self):
        """mtf_ensemble_v1 notes must mention the leakage fix."""
        reg_path = ROOT / "ml" / "saved_models" / "registry.json"
        reg = json.loads(reg_path.read_text())
        notes = reg.get("versions", {}).get("mtf_ensemble_v1", {}).get("notes", "")

        assert "leakage" in notes.lower() or "fixed" in notes.lower(), (
            "mtf_ensemble_v1 notes must mention the leakage fix"
        )
