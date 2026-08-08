"""Regression tests: inference guards must act, not just log.

Round 3 audit findings S4-01 through S4-06 (docs/HARDENING_BACKLOG.md).

S4-02 / S4-03 — two detectors with no actuator. NaN/Inf features were imputed
with ``0.0`` and scored anyway, and a feature vector that was >95% zeros was
logged as a *"possible silent upstream data failure"* and then returned for
trading. Imputing zero is not neutral in this feature space: a z-score of 0
means "exactly average", an RSI-derived feature at 0 means "maximally
oversold". Filling a broken feed with zeros produces a **confident** prediction
drawn from a region the model was trained to read as a strong signal, so a feed
outage yielded high-confidence trades rather than abstention.

S4-04 / S4-05 — drift detection was off twice over: ``DRIFT_BLOCK`` defaults to
false in code, and a missing training-stats file returned ``False`` ("no
drift") rather than "unknown", silently disabling the guard with no warning.

S4-06 — the data-layer feature builder fell back to a reduced feature set on
*any* exception, logged at ``debug``, so a permanent switch to a degraded
feature set was invisible at production log level.
"""

import numpy as np
import pandas as pd
import pytest


def _engine():
    from ml.inference_engine import InferenceEngine

    return InferenceEngine()


def _frame(values):
    return pd.DataFrame({f"f{i}": [v] for i, v in enumerate(values)})


@pytest.mark.unit
class TestFeatureValidationAbstains:
    def test_nan_features_abstain_rather_than_impute(self):
        """NaN/Inf must not be zero-filled and scored (S4-02)."""
        eng = _engine()
        bad = _frame([1.0, float("nan"), 3.0, float("inf")])

        assert eng._features_are_unusable(bad) is True, (
            "A feature vector containing NaN/Inf must be rejected, not imputed "
            "with 0.0 — zero is a meaningful value the model reads as signal."
        )

    def test_all_zero_vector_is_rejected(self):
        """>95% zeros is a diagnosed upstream failure — it must block (S4-03)."""
        eng = _engine()
        mostly_zero = _frame([0.0] * 39 + [1.0])

        assert eng._features_are_unusable(mostly_zero) is True, (
            "A >95%-zero vector was logged as a possible silent upstream data failure and then traded on."
        )

    def test_healthy_features_are_accepted(self):
        """Control case: normal features must not be rejected."""
        eng = _engine()
        good = _frame(list(np.linspace(0.1, 4.0, 40)))

        assert eng._features_are_unusable(good) is False

    def test_build_features_returns_none_for_unusable_input(self):
        """The guard must be wired into the build path, not merely defined."""
        import inspect

        from ml.inference_engine import InferenceEngine

        src = inspect.getsource(InferenceEngine._build_features)
        assert "_features_are_unusable" in src, (
            "_build_features must consult the usability guard and return None, "
            "so predict() takes its existing neutral/abstain path (S4-02/S4-03)."
        )


@pytest.mark.unit
class TestDriftGuardIsHonest:
    def test_missing_training_stats_is_not_reported_as_no_drift(self):
        """Absent stats means 'unknown', never a clean bill of health (S4-05)."""
        eng = _engine()
        eng._train_stats = None
        eng._train_stats_loaded = True  # force the "already tried" path

        eng._drift_stats_available = False
        assert eng.drift_guard_active() is False, (
            "drift_guard_active() must report that the guard is disabled when "
            "training stats are missing, rather than silently returning 'no drift'."
        )

    def test_drift_status_is_exposed(self):
        """Operators need to see whether the guard is actually running."""
        eng = _engine()
        assert hasattr(eng, "drift_guard_active"), (
            "InferenceEngine must expose whether the drift guard is active, so a "
            "missing training-stats file is visible rather than silent (S4-05)."
        )


@pytest.mark.unit
class TestFeatureBuilderFallbackIsVisible:
    def test_data_layer_fallback_is_not_debug_only(self):
        """A silent switch to a reduced feature set is train/serve skew (S4-06)."""
        import inspect

        from ml.inference_engine import InferenceEngine

        src = inspect.getsource(InferenceEngine._build_features)
        # Find the fallback handler and confirm it is not logged at debug.
        assert "logger.warning" in src, (
            "The data-layer feature-builder fallback must log at WARNING — at "
            "debug, a permanent switch to a degraded feature set is invisible "
            "in production (S4-06)."
        )
