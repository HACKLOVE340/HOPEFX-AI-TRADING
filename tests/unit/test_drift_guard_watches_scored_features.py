# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_drift_guard_watches_scored_features.py
======================================================
Round 3 audit, Slice 4 (docs/HARDENING_BACKLOG.md S4-01).

A single ``InferenceEngine.predict()`` call built features **twice**:

    predict()
    ├── X = self._build_features(...)        # path A — validated, drift-checked
    └── predictor.predict_proba(ohlcv, ...)  # path B — builds its OWN features

``X`` was never passed to the model. The model received the raw OHLCV frame and
rebuilt features internally, and nothing asserted the two agreed in content,
order or count.

So the drift guard reported on a vector nobody scored. If path A fell back to a
reduced feature set (macro pipeline stalled, say), its drift buffer filled with
vectors from the fallback distribution and reported "no drift" — internally
consistent and completely uninformative about the features actually driving
predictions. Drift on what the model sees was invisible; drift on what nobody
scores raised alerts.

The fix makes the predictor record the matrix it really scored, and the guard
watch that. These tests pin both halves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ── the predictor must expose what it scored ──────────────────────────────────


def test_predictor_records_the_matrix_it_scored():
    """Without this the guard has nothing truthful to check."""
    from ml.live_inference import AdvancedModelPredictor

    p = AdvancedModelPredictor()
    assert hasattr(p, "last_scored_features"), (
        "AdvancedModelPredictor does not expose the feature matrix it scored, so the "
        "drift guard cannot watch the features the model actually uses (S4-01)"
    )
    # Nothing scored yet.
    assert p.last_scored_features is None


class _FakeModel:
    """Stands in for the loaded sklearn pipeline."""

    feature_names_in_ = np.array(["f_a", "f_b"])

    def __init__(self):
        self.seen: pd.DataFrame | None = None

    def predict_proba(self, X):
        self.seen = X.copy()
        return np.array([[0.4, 0.6]])


def _predictor_with_fake_model():
    from ml.live_inference import AdvancedModelPredictor

    p = AdvancedModelPredictor()
    model = _FakeModel()
    p._model = model
    p._load = lambda: True  # type: ignore[method-assign]
    p.min_bars = 1
    # The predictor's own builder — deliberately different from anything the
    # InferenceEngine would build, which is the whole point of S4-01.
    p._build_features = lambda ohlcv, macro_df=None, symbol="XAUUSD": pd.DataFrame(  # type: ignore[method-assign]
        {"f_a": [1.5], "f_b": [2.5], "f_unused": [9.9]}
    )
    return p, model


def test_recorded_matrix_is_exactly_what_the_model_received():
    p, model = _predictor_with_fake_model()
    ohlcv = pd.DataFrame({"close": [2350.0, 2351.0]})

    prob = p.predict_proba(ohlcv, symbol="XAUUSD")

    assert 0.0 <= prob <= 1.0
    assert model.seen is not None, "the fake model was never called"
    recorded = p.last_scored_features
    assert recorded is not None, "the predictor scored a matrix but recorded nothing"
    # Same columns, same order, same values as the model actually saw.
    assert list(recorded.columns) == list(model.seen.columns)
    pd.testing.assert_frame_equal(recorded, model.seen)
    # And it reflects the model's expected schema, not the raw builder output.
    assert "f_unused" not in recorded.columns


def test_recorded_matrix_is_cleared_when_scoring_does_not_happen():
    """A stale row must never be mistaken for this prediction's features."""
    p, _ = _predictor_with_fake_model()
    ohlcv = pd.DataFrame({"close": [2350.0, 2351.0]})
    p.predict_proba(ohlcv)
    assert p.last_scored_features is not None

    # Too few bars — returns neutral without scoring.
    p.min_bars = 100
    assert p.predict_proba(pd.DataFrame({"close": [2350.0]})) == pytest.approx(0.5)
    assert p.last_scored_features is None, (
        "features from a previous call survived a prediction that never scored — "
        "the drift guard would check a stale vector"
    )


# ── the guard must watch the scored matrix ────────────────────────────────────


class _StubPredictor:
    is_available = True
    version = "stub-1"

    def __init__(self, scored: pd.DataFrame):
        self._scored = scored

    @property
    def last_scored_features(self):
        return self._scored

    def predict_proba(self, ohlcv, macro_df=None, symbol="XAUUSD", mtf_df=None):
        return 0.62


def test_drift_buffer_receives_the_scored_features_not_the_engines_own():
    """The buffer must fill with what the model saw.

    This is the assertion that would have caught S4-01: the engine's own
    builder and the predictor's builder produce different columns, and only one
    of them drives predictions.
    """
    from ml.inference_engine import InferenceEngine

    engine = InferenceEngine()

    scored = pd.DataFrame({"model_feat_1": [1.0], "model_feat_2": [2.0]})
    engine._predictor = _StubPredictor(scored)

    engine._drift_buffer.clear()
    # Pretend training stats exist so the guard actually runs.
    engine._load_train_stats = lambda: {  # type: ignore[method-assign]
        "model_feat_1": {"mean": 1.0, "std": 1.0},
        "model_feat_2": {"mean": 2.0, "std": 1.0},
    }

    engine._check_feature_drift(engine._features_for_drift_check(scored, fallback=None))

    assert len(engine._drift_buffer) == 1
    np.testing.assert_allclose(engine._drift_buffer[0], np.array([1.0, 2.0]))


def test_falls_back_to_the_engine_vector_only_when_the_predictor_offers_none():
    """Degraded coverage is acceptable; silent degraded coverage is not."""
    from ml.inference_engine import InferenceEngine

    engine = InferenceEngine()
    own = pd.DataFrame({"engine_feat": [7.0]})

    chosen = engine._features_for_drift_check(None, fallback=own)
    pd.testing.assert_frame_equal(chosen, own)


def test_prefers_the_scored_vector_when_both_are_available():
    from ml.inference_engine import InferenceEngine

    engine = InferenceEngine()
    scored = pd.DataFrame({"model_feat": [1.0]})
    own = pd.DataFrame({"engine_feat": [7.0]})

    chosen = engine._features_for_drift_check(scored, fallback=own)
    pd.testing.assert_frame_equal(chosen, scored)
