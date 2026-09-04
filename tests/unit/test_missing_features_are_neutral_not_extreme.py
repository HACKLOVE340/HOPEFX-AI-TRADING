# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A feature the live pipeline could not produce must reach the model as neutral.

`StackingEnsemblePredictor.predict_proba` aligns the live frame to the training
feature contract, which is correct in principle. The *ordering* is the defect:

    for col in self._feature_cols:
        if col not in X_in.columns:
            X_in[col] = 0.0            # <- fill, in RAW space
    X_in = X_in.replace(...).fillna(0.0)
    X_in = self._scaler.transform(X_in)    # <- scale, AFTERWARDS

so a missing feature arrives at the model as ``z = (0 - mean) / std``, not as 0.
For feature scales typical of a gold model that is (F145):

    close price   mean 3000  std 200   ->  z = -15.0     extreme
    RSI_14        mean   50  std  15   ->  z =  -3.33    extreme
    ATR_14        mean   12  std   4   ->  z =  -3.0
    MACD_hist     mean    0  std 1.5   ->  z =   0.0     neutral

Only features already centred on zero land near neutral. With 48.2% of the
vector missing live (F24), the model is not handed an incomplete observation —
it is handed a confident description of a market that has never existed, which
is consistent with an OOS score the live distribution never reproduces.

The fix is the ordering, not the fill value: scale first, then set the missing
cells to 0.0 in *scaled* space, where 0.0 means "at the training mean".

Two fail-opens on the same path are covered here too: `scaler.transform` raising
was logged at DEBUG and the **unscaled** frame passed on to the base learners.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit


class _Scaler:
    """A standard scaler with the means and stds from the finding."""

    def __init__(self, means, stds):
        self.means = np.asarray(means, dtype=float)
        self.stds = np.asarray(stds, dtype=float)
        self.seen: list = []

    def transform(self, X):
        arr = np.asarray(X, dtype=float)
        return (arr - self.means) / self.stds


class _RecordingLearner:
    """Records exactly what the model was handed."""

    def __init__(self):
        self.seen: list = []

    def predict_proba(self, X):
        arr = np.asarray(X, dtype=float)
        self.seen.append(arr.copy())
        return np.column_stack([np.full(arr.shape[0], 0.5), np.full(arr.shape[0], 0.5)])


class _Meta:
    def predict_proba(self, X):
        n = np.asarray(X).shape[0]
        return np.column_stack([np.full(n, 0.5), np.full(n, 0.5)])


FEATURES = ["close", "rsi_14", "macd_hist"]
MEANS = [3000.0, 50.0, 0.0]
STDS = [200.0, 15.0, 1.5]


def _predictor(learner=None, scaler=None):
    from ml import StackingEnsemblePredictor

    learner = learner or _RecordingLearner()
    return (
        StackingEnsemblePredictor(
            {
                "base_learners": [learner],
                "meta_model": _Meta(),
                "feature_cols": FEATURES,
                "scaler": scaler if scaler is not None else _Scaler(MEANS, STDS),
            }
        ),
        learner,
    )


# ── The finding ──────────────────────────────────────────────────────────────


def test_a_missing_price_feature_does_not_arrive_at_minus_fifteen_sigma():
    predictor, learner = _predictor()
    # "close" is absent — exactly the live case.
    predictor.predict_proba(pd.DataFrame({"rsi_14": [50.0], "macd_hist": [0.0]}))

    seen = learner.seen[0]
    close_z = seen[0, FEATURES.index("close")]
    assert close_z == pytest.approx(0.0), (
        f"a missing price feature reached the model at z={close_z:.2f} — "
        "the fill happened in raw space and the scaler ran afterwards (F145)"
    )


def test_every_missing_feature_lands_at_the_training_mean():
    predictor, learner = _predictor()
    predictor.predict_proba(pd.DataFrame({"macd_hist": [0.0]}))

    seen = learner.seen[0]
    assert seen[0, FEATURES.index("close")] == pytest.approx(0.0)
    assert seen[0, FEATURES.index("rsi_14")] == pytest.approx(0.0)


def test_a_present_feature_is_still_scaled_exactly_as_before():
    """The fix must not touch the values that were correct."""
    predictor, learner = _predictor()
    predictor.predict_proba(pd.DataFrame({"close": [3200.0], "rsi_14": [65.0], "macd_hist": [3.0]}))

    seen = learner.seen[0]
    assert seen[0, 0] == pytest.approx((3200.0 - 3000.0) / 200.0)
    assert seen[0, 1] == pytest.approx((65.0 - 50.0) / 15.0)
    assert seen[0, 2] == pytest.approx((3.0 - 0.0) / 1.5)


def test_a_nan_value_in_a_present_column_is_also_neutral():
    """`fillna(0.0)` before scaling is the same defect for a column that exists
    but has no value on this bar."""
    predictor, learner = _predictor()
    predictor.predict_proba(pd.DataFrame({"close": [np.nan], "rsi_14": [65.0], "macd_hist": [1.0]}))

    seen = learner.seen[0]
    assert seen[0, 0] == pytest.approx(0.0), "a NaN price was scaled as if it were 0.0"
    assert seen[0, 1] == pytest.approx((65.0 - 50.0) / 15.0), "the neighbouring value was disturbed"


def test_an_infinite_value_is_neutral_too():
    predictor, learner = _predictor()
    predictor.predict_proba(pd.DataFrame({"close": [np.inf], "rsi_14": [50.0], "macd_hist": [0.0]}))

    assert learner.seen[0][0, 0] == pytest.approx(0.0)


def test_multiple_rows_keep_their_own_imputation():
    """The mask is per cell, not per column: one bar missing a feature must not
    neutralise that feature on a bar that has it."""
    predictor, learner = _predictor()
    predictor.predict_proba(pd.DataFrame({"close": [3200.0, np.nan], "rsi_14": [65.0, 65.0], "macd_hist": [0.0, 0.0]}))

    seen = learner.seen[0]
    assert seen[0, 0] == pytest.approx((3200.0 - 3000.0) / 200.0)
    assert seen[1, 0] == pytest.approx(0.0)


# ── The fail-opens on the same path ──────────────────────────────────────────


def test_a_failed_scaler_does_not_hand_the_learners_an_unscaled_frame():
    """`scaler.transform` raising was caught, logged at DEBUG — off in
    production — and the raw frame passed straight through. A price of 3200
    where the model expects a z-score is not a degraded prediction, it is a
    meaningless one."""

    class _BrokenScaler:
        def transform(self, X):
            raise RuntimeError("scaler state does not match the frame")

    predictor, learner = _predictor(scaler=_BrokenScaler())

    with pytest.raises(RuntimeError, match="refusing to predict"):
        predictor.predict_proba(pd.DataFrame({"close": [3200.0], "rsi_14": [65.0], "macd_hist": [0.0]}))

    assert learner.seen == [], f"the learners were called with an unscaled frame: {learner.seen}"


def test_low_feature_coverage_is_reported(caplog):
    """F146 records that the engine already measures coverage and never acts on
    it. The predictor is where the number is knowable; at minimum it must say
    so."""
    import logging

    predictor, _ = _predictor()
    with caplog.at_level(logging.WARNING):
        predictor.predict_proba(pd.DataFrame({"macd_hist": [0.0]}))

    assert any("coverage" in r.message.lower() or "missing" in r.message.lower() for r in caplog.records), (
        "two of three features were imputed and nothing was reported"
    )


# ── The refusal must degrade, not crash ──────────────────────────────────────


def test_a_refused_prediction_degrades_the_signal_instead_of_crashing_it(monkeypatch, caplog):
    """Making `predict_proba` raise is only correct if the signal path treats it
    as "no ML available" rather than propagating out of the request.

    `_predict_basic` calls `active_model.predict_proba(X)` with no local guard;
    the protection is one level up, in `_compute_ml_probability`'s
    `except Exception` (core/signal_engine.py). That is a load-bearing detail of
    a change that turned a silent wrong answer into a refusal, so it is asserted
    rather than assumed.
    """
    import logging

    import core.signal_engine as se

    class _Refusing:
        def predict_proba(self, X):
            raise RuntimeError("feature scaling failed; refusing to predict on an unscaled frame")

    monkeypatch.setattr(se, "get_active_model", lambda: _Refusing(), raising=False)
    monkeypatch.setattr(se, "get_model_version", lambda: "stacking_v1", raising=False)
    monkeypatch.setattr(se, "get_advanced_predictor", lambda: None, raising=False)

    data = {"close": 3000.0, "prices": [3000.0 + i for i in range(30)], "volume": 100.0}

    with caplog.at_level(logging.DEBUG):
        prob, version = se._compute_ml_probability(data, "XAUUSD", base_confidence=0.61)

    assert prob == pytest.approx(0.61), "a refused prediction did not fall back to the base confidence"
    assert version == "none", f"a refused prediction was reported as model {version!r}"


def test_the_refusal_itself_is_logged_at_error_by_the_predictor():
    """The fallback above is logged at DEBUG — off in production — so the only
    operator-visible trace of a refusal is the predictor's own ERROR. If that
    were quiet, the platform would silently trade on base confidence with no
    signal that its model had stopped contributing."""
    import logging

    class _BrokenScaler:
        def transform(self, X):
            raise RuntimeError("scaler state does not match the frame")

    predictor, _ = _predictor(scaler=_BrokenScaler())

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    from ml import _ml_logger

    handler = _Capture()
    _ml_logger.addHandler(handler)
    try:
        with pytest.raises(RuntimeError):
            predictor.predict_proba(pd.DataFrame({"close": [3200.0], "rsi_14": [65.0], "macd_hist": [0.0]}))
    finally:
        _ml_logger.removeHandler(handler)

    assert any(r.levelno >= logging.ERROR for r in records), (
        "the refusal left no ERROR-level trace; an operator would see silence"
    )
