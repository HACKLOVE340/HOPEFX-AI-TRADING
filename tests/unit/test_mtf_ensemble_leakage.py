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

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
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
        side_effect=lambda X: np.column_stack(
            [
                np.full(len(X), 1 - proba_val),
                np.full(len(X), proba_val),
            ]
        )
    )
    mock.predict = MagicMock(side_effect=lambda X: np.ones(len(X), dtype=int))
    return mock


# ── Test: calibration never re-fits the base model ───────────────────────────


class TestCalibrationNeverRefits:
    """The base model must not be re-fitted while its probabilities are calibrated.

    That is the whole leakage property. `cv=3` re-trained the base learners on
    sub-splits of the test fold and produced ~99% walk-forward accuracy that was
    not there.

    **These tests asserted a mechanism that no longer exists.** They patched
    `sklearn.calibration.CalibratedClassifierCV` and checked the `cv=` argument
    — but `cv='prefit'` was removed in scikit-learn 1.4 and the code was
    rewritten to fit an `IsotonicRegression` on the base model's output instead
    (`_calibrate_prefit`). Nothing has constructed a `CalibratedClassifierCV`
    since, so the tracking list was always empty, every `for cv_arg in ...` loop
    ran zero times, and both tests passed having measured nothing.

    Proven rather than argued: `_calibrate_prefit` was deleted from
    `train_xgboost` entirely — no calibration at all — and this file stayed
    green. A leakage guard that survives the removal of the thing it guards is
    the F176 shape (`.claude/skills/hopefx-dead-controls`), sitting on the
    control that protects the number the model is judged by.

    They now assert the property against the mechanism that is actually there:
    the estimator carried by the returned wrapper is the SAME OBJECT that was
    fitted, and it was fitted exactly once.
    """

    def test_train_xgboost_does_not_refit_the_base_model(self):
        import xgboost

        import scripts.retrain_mtf_accuracy as rma

        X_train, y_train = _make_xy(200)
        X_test, y_test = _make_xy(50, seed=99)

        fits: list[int] = []
        built: list[object] = []

        _real_xgb = xgboost.XGBClassifier

        def _counting_xgb(*a, **kw):
            kw["n_estimators"] = 5  # 500 is irrelevant here, and cost 131s against a 120s timeout
            model = _real_xgb(*a, **kw)
            built.append(model)
            real_fit = model.fit

            def _fit(*fa, **fkw):
                fits.append(1)
                return real_fit(*fa, **fkw)

            model.fit = _fit
            return model

        with patch.object(xgboost, "XGBClassifier", _counting_xgb):
            calibrated = rma.train_xgboost(X_train, y_train, X_test, y_test)

        assert built, "no XGBClassifier was constructed, so nothing was checked"
        assert sum(fits) == 1, f"the base model was fitted {sum(fits)} times — calibration must not re-fit it"
        assert getattr(calibrated, "estimator", None) is built[0], (
            "the returned model does not carry the estimator that was fitted, so the "
            "calibration layer replaced it rather than wrapping it"
        )

    def test_train_random_forest_does_not_refit_the_base_model(self):
        import sklearn.ensemble

        import scripts.retrain_mtf_accuracy as rma

        X_train, y_train = _make_xy(200)

        fits: list[int] = []
        built: list[object] = []
        _real_rf = sklearn.ensemble.RandomForestClassifier

        def _counting_rf(*a, **kw):
            kw["n_estimators"] = 5  # 300 is irrelevant to this assertion
            model = _real_rf(*a, **kw)
            built.append(model)
            real_fit = model.fit

            def _fit(*fa, **fkw):
                fits.append(1)
                return real_fit(*fa, **fkw)

            model.fit = _fit
            return model

        with patch.object(sklearn.ensemble, "RandomForestClassifier", _counting_rf):
            calibrated = rma.train_random_forest(X_train, y_train)

        assert built, "no RandomForestClassifier was constructed, so nothing was checked"
        assert sum(fits) == 1, f"the base model was fitted {sum(fits)} times — calibration must not re-fit it"
        assert getattr(calibrated, "estimator", None) is built[0]

    def test_the_calibrator_is_fitted_on_the_base_models_output_only(self):
        """The isotonic layer sees probabilities, never the features.

        This is what makes re-fitting impossible by construction, and it is the
        sentence `_calibrate_prefit`'s docstring makes. A calibrator handed `X`
        could refit; one handed a 1-D probability vector cannot.
        """
        import scripts.retrain_mtf_accuracy as rma

        X_val, y_val = _make_xy(60, seed=7)
        base = _make_calibrated_mock(0.6)

        seen: list[tuple[int, ...]] = []
        import sklearn.isotonic

        _real_iso = sklearn.isotonic.IsotonicRegression

        def _tracking_iso(*a, **kw):
            iso = _real_iso(*a, **kw)
            real_fit = iso.fit

            def _fit(X, y, **fkw):
                seen.append(np.asarray(X).shape)
                return real_fit(X, y, **fkw)

            iso.fit = _fit
            return iso

        with patch.object(sklearn.isotonic, "IsotonicRegression", _tracking_iso):
            rma._calibrate_prefit(base, X_val, y_val)

        assert seen, "the isotonic calibrator was never fitted, so nothing was checked"
        assert seen[0] == (len(X_val),), (
            f"the calibrator was fitted on an array of shape {seen[0]} — it must see the "
            f"base model's probabilities ({len(X_val)},), not the {X_val.shape} feature matrix"
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

        # Same vacuity trap as the two tests above: an empty list satisfies the
        # loop below, and the list is empty if train_stacking_ensemble stops
        # calling its base learners at all.
        assert fit_sizes_seen, "train_stacking_ensemble trained no base learners, so nothing was checked"

        # Base learners must be trained on a subset of X_train, not X_cal
        cal_size = len(X_cal)
        for label, size in fit_sizes_seen:
            assert size != cal_size or label.endswith("_oof"), (
                f"{label} was called with size={size} which equals X_cal size={cal_size}. "
                "Base learners must not train on the calibration set."
            )
            # Fit set must be smaller than X_train (it's a 75% split)
            if label.endswith("_fit"):
                assert size < len(X_train), f"{label} fit size {size} >= X_train size {len(X_train)} — no split applied"

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
            side_effect=lambda X: (
                meta_inputs_seen.append(X),
                np.column_stack([np.full(len(X), 0.4), np.full(len(X), 0.6)]),
            )[1]
        )
        meta_mock.predict = MagicMock(return_value=np.ones(100, dtype=int))

        rma.evaluate(meta_mock, X_test, y_test, base_learners=[bl1, bl2])

        assert meta_inputs_seen, "meta-model predict_proba was never called"
        meta_X = meta_inputs_seen[0]

        # meta_X must have 2 columns (one per base learner)
        assert meta_X.shape[1] == 2, f"meta_X has {meta_X.shape[1]} columns, expected 2 (one per base learner)"
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
            side_effect=lambda X: (
                raw_inputs_seen.append(X),
                np.column_stack([np.full(len(X), 0.45), np.full(len(X), 0.55)]),
            )[1]
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
        model_mock.predict_proba = MagicMock(return_value=np.column_stack([np.full(80, 0.4), np.full(80, 0.6)]))
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
        model_mock.predict_proba = MagicMock(return_value=np.column_stack([1 - probas, probas]))
        model_mock.predict = MagicMock(return_value=(probas > 0.5).astype(int))

        result = rma.evaluate(model_mock, X_test, y_test)

        assert 0.0 <= result["abstain_rate"] <= 1.0, f"abstain_rate={result['abstain_rate']} out of [0, 1]"


# ── Test: registry records the fix ───────────────────────────────────────────


class TestRegistryLeakageFix:
    """The leakage fix must stay on the record.

    These four tests read ``MODEL_IDENTITY.md``, not ``registry.json``.

    The record used to live on the ``mtf_ensemble_v1`` registry entry
    (``leakage_bug_fixed``, ``leakage_fix_date``, ``leakage_fix_description``,
    and the ``notes`` field). That entry pointed at
    ``ml/saved_models/mtf_ensemble.pkl``, which does not exist, and was pruned
    on 2026-08-14 with ``repair_model_registry.py --prune-missing`` — which
    deleted the leakage-fix provenance along with it.

    Losing an audit trail of a data-leakage fix is worse than the dangling
    entry was, so the record was moved to MODEL_IDENTITY.md rather than
    dropped, and these tests follow it there. The artifact is gone; the reason
    its CV accuracy cannot be trusted must not be.
    """

    @staticmethod
    def _identity_doc() -> str:
        path = ROOT / "ml" / "saved_models" / "MODEL_IDENTITY.md"
        assert path.exists(), "MODEL_IDENTITY.md not found"
        return path.read_text(encoding="utf-8")

    def test_registry_records_leakage_fix(self):
        """The fix must be recorded as done, not merely described."""
        doc = self._identity_doc()
        assert "Leakage bug — fixed" in doc, "MODEL_IDENTITY.md no longer records that the MTF leakage bug was fixed"

    def test_registry_records_fix_date(self):
        doc = self._identity_doc()
        assert "2026-04-20" in doc, "the leakage fix date is no longer recorded"

    def test_registry_records_fix_description(self):
        """The mechanism, so a future reader can tell whether a retrain kept it."""
        doc = self._identity_doc().lower()
        assert "prefit" in doc or "three-way" in doc or "oof" in doc, (
            "the fix mechanism (prefit / three-way split / OOF) is no longer described"
        )

    def test_registry_mtf_notes_mention_fix(self):
        """The spurious 99% must stay labelled as spurious.

        It is the highest accuracy figure anywhere in this repo. Without the
        explanation attached, someone will eventually quote it.
        """
        doc = self._identity_doc()
        assert "99%" in doc, "the spurious CV figure is no longer mentioned"
        lowered = doc.lower()
        assert "leakage" in lowered, "the 99% figure is no longer tied to the leakage that caused it"
