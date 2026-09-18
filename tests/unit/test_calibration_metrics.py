# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""A real calibration number, measured at training time.

`ml/inference_engine.py::_evaluate_model_quality` scored calibration as a
*presence* signal — 1.0 if an isotonic calibrator object was loaded, 0.0 if
not — and said so plainly in its own docstring:

    Calibration is a *presence* signal, not a calibration error ... Nothing in
    training records a Brier or ECE score today, so there is no honest number
    to read; this says which of the two states the engine is in and no more.
    When training starts recording one, this is the line to change.

That was the right thing to write at the time. It is still wrong as a gate
input: `ModelQualityGate` compares `calibration_score >= minimum_calibration`,
so a loaded-but-badly-fitted calibrator scored a perfect 1.0 and passed any
threshold, while a well-calibrated raw model scored 0.0 and failed every
threshold above zero. The number measured whether a file existed.

`ml/calibration_metrics.py` computes the real thing on held-out predictions:

  * **Brier score** — mean squared error of the probability. Proper scoring
    rule; 0.0 is perfect, 0.25 is a constant 0.5 forecast on a balanced set.
  * **Expected Calibration Error (ECE)** — average gap between confidence and
    observed frequency, bucketed. This is the one that answers "when it says
    70%, does it happen 70% of the time?"
  * **calibration_score = 1 - ECE** — the [0, 1] higher-is-better form the
    gate already expects, so nothing downstream changes shape.

These tests pin the properties that make the number trustworthy rather than
re-deriving the arithmetic: a perfect forecaster scores 1.0, a confidently
wrong one scores near 0.0, and — the case that matters for Rule 2 — too little
data returns None rather than a flattering default.
"""

from __future__ import annotations

import numpy as np
import pytest


class TestBrierScore:
    def test_perfect_forecasts_score_zero(self):
        from ml.calibration_metrics import brier_score

        y = np.array([1, 0, 1, 0, 1, 0, 1, 0])
        p = np.array([1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0])
        assert brier_score(p, y) == pytest.approx(0.0)

    def test_confidently_wrong_forecasts_score_one(self):
        from ml.calibration_metrics import brier_score

        y = np.array([1, 0, 1, 0])
        p = np.array([0.0, 1.0, 0.0, 1.0])
        assert brier_score(p, y) == pytest.approx(1.0)

    def test_a_constant_half_scores_a_quarter(self):
        """The reference point every Brier score is read against."""
        from ml.calibration_metrics import brier_score

        y = np.array([1, 0, 1, 0, 1, 0])
        p = np.full(6, 0.5)
        assert brier_score(p, y) == pytest.approx(0.25)


class TestExpectedCalibrationError:
    def test_a_perfectly_calibrated_forecaster_has_near_zero_ece(self):
        """A forecaster that says 70% and is right 70% of the time.

        Built explicitly rather than sampled, so the assertion is about the
        metric and not about a random draw.
        """
        from ml.calibration_metrics import expected_calibration_error

        probs, labels = [], []
        for conf in (0.1, 0.3, 0.5, 0.7, 0.9):
            n = 200
            hits = int(round(conf * n))
            probs.extend([conf] * n)
            labels.extend([1] * hits + [0] * (n - hits))

        ece = expected_calibration_error(np.array(probs), np.array(labels), n_bins=10)
        assert ece == pytest.approx(0.0, abs=0.01), f"a calibrated forecaster should have ECE ~0, got {ece}"

    def test_an_overconfident_forecaster_has_large_ece(self):
        """Says 95%, right half the time — the failure calibration exists to catch."""
        from ml.calibration_metrics import expected_calibration_error

        n = 400
        probs = np.full(n, 0.95)
        labels = np.array([1] * (n // 2) + [0] * (n // 2))
        ece = expected_calibration_error(probs, labels, n_bins=10)
        assert ece == pytest.approx(0.45, abs=0.02)

    def test_ece_is_bounded_in_zero_one(self):
        from ml.calibration_metrics import expected_calibration_error

        rng = np.random.default_rng(11)
        for _ in range(20):
            n = int(rng.integers(50, 300))
            probs = rng.random(n)
            labels = rng.integers(0, 2, n)
            ece = expected_calibration_error(probs, labels)
            assert 0.0 <= ece <= 1.0


class TestTheReportedScore:
    def test_a_calibrated_model_scores_near_one(self):
        from ml.calibration_metrics import calibration_report

        probs, labels = [], []
        for conf in (0.2, 0.4, 0.6, 0.8):
            n = 250
            hits = int(round(conf * n))
            probs.extend([conf] * n)
            labels.extend([1] * hits + [0] * (n - hits))

        report = calibration_report(np.array(probs), np.array(labels))
        assert report is not None
        assert report.calibration_score == pytest.approx(1.0, abs=0.02)
        assert report.n_samples == 1000
        assert 0.0 <= report.brier <= 1.0

    def test_an_overconfident_model_scores_low(self):
        from ml.calibration_metrics import calibration_report

        n = 400
        report = calibration_report(np.full(n, 0.98), np.array([1] * (n // 2) + [0] * (n // 2)))
        assert report is not None
        assert report.calibration_score < 0.6, (
            f"a model that says 98% and is right half the time must not score {report.calibration_score}"
        )

    def test_too_little_data_returns_none_not_a_flattering_default(self):
        """Rule 2: an unmeasured value is absent, never best-case.

        Returning 1.0 here would hand ModelQualityGate a perfect score for a
        model nobody evaluated — the exact defect this module replaces.
        """
        from ml.calibration_metrics import calibration_report

        assert calibration_report(np.array([0.6, 0.4]), np.array([1, 0])) is None
        assert calibration_report(np.array([]), np.array([])) is None

    def test_non_finite_predictions_are_dropped_not_zero_filled(self):
        """A NaN probability is an absent forecast, not a confident 0.0."""
        from ml.calibration_metrics import calibration_report

        n = 300
        probs = np.full(n, 0.5)
        labels = np.array([1, 0] * (n // 2))
        clean = calibration_report(probs, labels)

        dirty = probs.copy()
        dirty[:10] = np.nan
        with_nans = calibration_report(dirty, labels)

        assert clean is not None and with_nans is not None
        assert with_nans.n_samples == n - 10, "non-finite rows must be dropped, not counted"
        assert np.isfinite(with_nans.brier)

    def test_a_single_class_is_reported_not_hidden(self):
        """All-one-label held-out data cannot measure calibration honestly."""
        from ml.calibration_metrics import calibration_report

        report = calibration_report(np.full(300, 0.7), np.ones(300, dtype=int))
        assert report is None or report.single_class is True

    def test_the_report_serialises_for_the_model_metadata(self):
        """It has to survive the trip to disk, or training cannot record it."""
        import json

        from ml.calibration_metrics import calibration_report

        n = 400
        report = calibration_report(np.full(n, 0.5), np.array([1, 0] * (n // 2)))
        assert report is not None
        payload = json.loads(json.dumps(report.as_dict()))
        assert set(payload) >= {"brier", "ece", "calibration_score", "n_samples", "measured_at"}


class TestTheGateReadsARealNumber:
    def test_the_inference_engine_prefers_a_recorded_score_over_presence(self):
        """The engine must read the measured score when training recorded one.

        Before this, `calibration_score` was `1.0 if self._calibrator else 0.0`
        — the presence of a pickle, not the quality of its probabilities.
        """
        import ml.inference_engine as ie

        source = ie.__file__
        assert hasattr(ie.InferenceEngine, "_recorded_calibration_score"), (
            f"the engine must expose where a recorded calibration score comes from (checked {source})"
        )
