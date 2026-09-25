# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A0 fix #5, the compatibility half: a model trained on the OLD feature
definitions must never be fed the NEW ones.

Fix #5 changes what four ``ri_*`` features mean (they were constant 0.0 or
degenerate, D3) and retires ``inst_poc`` / ``inst_vah`` / ``inst_val`` (raw
price levels, D4). The committed active model, ``xgb_horizon5_v3``
(``advanced_oos.pkl``, sha256 ``dc7454d8…``), consumes all seven.

Before this, the live scorer (``ml/live_inference.py``) zero-filled any
expected column it did not find and only logged. So after the rename the old
model would have been scored with ``inst_poc = 0`` — a gold price of zero — and
with ``ri_vol_adj_mom`` carrying values it had only ever seen as 0.0. Nothing
would have refused. The staleness gate refuses this artifact today, but that is
a coincidence of its age, not a defence: re-register it with a fresh
timestamp, or roll back to it, and it would score.

The decision (option b in the task): the feature set is versioned, a trained
artifact carries the version it was built on, and an artifact that consumes a
feature whose definition changed after its version is REFUSED with
``FeatureSetMismatchError``. Option (a) — keeping the old definitions alive
for the old model — was rejected: the "old definitions" are the defects
themselves (a constant and a raw price level), and reproducing them on purpose
would keep them in the tree.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_ARTIFACT = ROOT / "ml" / "saved_models" / "advanced_oos.pkl"


class _FakeModel:
    """Stands in for a fitted sklearn pipeline: names in, probabilities out."""

    def __init__(self, names, version=None):
        self.feature_names_in_ = np.array(list(names))
        if version is not None:
            from ml.feature_set import MODEL_ATTR

            setattr(self, MODEL_ATTR, version)
        self.calls = 0

    def predict_proba(self, X):
        self.calls += 1
        return np.array([[0.1, 0.9]] * len(X))


# ── the rule ──────────────────────────────────────────────────────────────────


def test_the_committed_active_model_is_refused(tmp_path):
    """The real artifact, not a stand-in. Loaded from a COPY under tmp_path."""
    import joblib

    from ml.feature_set import FeatureSetMismatchError, assert_feature_set_compatible

    copy = tmp_path / "advanced_oos_copy.pkl"
    shutil.copyfile(ACTIVE_ARTIFACT, copy)
    model = joblib.load(copy)  # nosec B301 - a copy of a checksummed committed artifact, test only

    with pytest.raises(FeatureSetMismatchError) as exc:
        assert_feature_set_compatible(model)
    msg = str(exc.value)
    for name in ("inst_poc", "inst_vah", "inst_val", "ri_regime_mom", "ri_vol_adj_mom", "ri_trend_vol_confirm"):
        assert name in msg, f"the refusal does not name {name}: {msg}"
    assert "feature set 1" in msg and "feature set 2" in msg, msg


def test_a_legacy_model_that_consumes_no_changed_feature_is_allowed():
    """Unaffected by the change, so there is nothing to refuse."""
    from ml.feature_set import assert_feature_set_compatible

    assert_feature_set_compatible(_FakeModel(["mom_20", "rvol_20", "inst_dist_poc"]))


@pytest.mark.parametrize("name", ["inst_poc", "ri_regime_mom", "ri_signal_alignment"])
def test_a_legacy_model_that_consumes_one_changed_feature_is_refused(name):
    from ml.feature_set import FeatureSetMismatchError, assert_feature_set_compatible

    with pytest.raises(FeatureSetMismatchError, match=name):
        assert_feature_set_compatible(_FakeModel(["mom_20", name]))


def test_a_model_stamped_with_the_current_version_is_allowed():
    from ml.feature_set import FEATURE_SET_VERSION, assert_feature_set_compatible

    assert_feature_set_compatible(
        _FakeModel(["ri_regime_mom", "inst_poc_dist_atr"], version=FEATURE_SET_VERSION),
    )


def test_a_model_from_a_newer_feature_set_is_refused():
    from ml.feature_set import FEATURE_SET_VERSION, FeatureSetMismatchError, assert_feature_set_compatible

    with pytest.raises(FeatureSetMismatchError, match="newer"):
        assert_feature_set_compatible(_FakeModel(["mom_20"], version=FEATURE_SET_VERSION + 1))


def test_every_retired_name_is_absent_from_the_builder_and_every_added_name_present():
    """The declared change list and the builder cannot drift apart."""
    from ml.feature_set import FEATURE_SET_CHANGES, FEATURE_SET_VERSION
    from ml.features_extended import build_extended_features

    rng = np.random.default_rng(3)
    n = 320
    close = 1800 + np.cumsum(rng.normal(0, 5, n))
    df = pd.DataFrame(
        {
            "open": close + rng.normal(0, 1, n),
            "high": close + 4,
            "low": close - 4,
            "close": close,
            "volume": rng.uniform(1e3, 5e3, n),
        },
        index=pd.bdate_range("2021-01-01", periods=n),
    )
    X, _ = build_extended_features(df, horizon=5, smoke=True)
    change = FEATURE_SET_CHANGES[FEATURE_SET_VERSION]
    assert not (set(change["removed"]) & set(X.columns))
    assert set(change["added"]) <= set(X.columns)
    assert set(change["redefined"]) <= set(X.columns)
    assert X.attrs.get("feature_set_version") == FEATURE_SET_VERSION


# ── the live scorer enforces it ───────────────────────────────────────────────


def test_live_scorer_refuses_rather_than_zero_filling():
    from ml.feature_set import FeatureSetMismatchError
    from ml.live_inference import AdvancedModelPredictor

    model = _FakeModel(["f_a", "ri_vol_adj_mom"])  # legacy: no version stamp
    p = AdvancedModelPredictor()
    p._model = model
    p._load = lambda: True  # type: ignore[method-assign]
    p.min_bars = 1
    p._build_features = lambda ohlcv, macro_df=None, symbol="XAUUSD": pd.DataFrame(  # type: ignore[method-assign]
        {"f_a": [1.0], "ri_vol_adj_mom": [0.7]}
    )

    with pytest.raises(FeatureSetMismatchError):
        p.predict_proba(pd.DataFrame({"close": [1.0, 2.0]}))
    assert model.calls == 0, "the mismatched model was scored before the refusal"
    assert p.last_scored_features is None


class _RefusingPredictor:
    is_available = True
    version = "legacy-v1"
    last_scored_features = None

    def predict_proba(self, ohlcv, macro_df=None, symbol="XAUUSD", mtf_df=None):
        from ml.feature_set import FeatureSetMismatchError

        raise FeatureSetMismatchError("model built on feature set 1 consumes redefined features: ['inst_poc']")


class _EagerOnlineLearner:
    """Would push the blend over the long threshold if the engine let it."""

    def predict_proba(self, ohlcv):
        return 0.99


def _daily(n=150):
    rng = np.random.default_rng(1)
    close = 2000 + np.cumsum(rng.normal(0, 5, n))
    return pd.DataFrame(
        {"open": close, "high": close + 3, "low": close - 3, "close": close, "volume": 1000.0},
        index=pd.bdate_range("2024-01-01", periods=n, tz="UTC"),
    )


def test_inference_engine_abstains_on_a_feature_set_mismatch_without_the_staleness_gate():
    """The defence must not depend on the model being old: staleness is stubbed
    to 'fresh', and the engine must still refuse to trade on the mismatch."""
    from ml.inference_engine import InferenceEngine

    engine = InferenceEngine()
    engine._predictor = _RefusingPredictor()
    engine._online_learner = _EagerOnlineLearner()
    engine._get_online_learner = lambda: _EagerOnlineLearner()  # type: ignore[method-assign]
    engine._check_model_staleness = lambda: False  # type: ignore[method-assign]
    engine._build_features = (
        lambda ohlcv, macro_df, mtf_df, symbol: pd.DataFrame(  # type: ignore[method-assign]
            {"f_a": [1.0], "f_b": [2.0]}, index=ohlcv.index[-1:]
        )
    )

    res = engine.predict(_daily(), symbol="XAU_USD")

    assert res["direction"] == "neutral", res
    assert res.get("reason") == "feature_set_mismatch", res
    assert res.get("fallback") is True


# ── training stamps what it built on ──────────────────────────────────────────


def test_oos_eval_stamps_the_artifact_and_its_metadata(tmp_path, monkeypatch):
    import json

    import joblib

    import ml.train_advanced as ta
    from ml.feature_set import FEATURE_SET_VERSION, model_feature_set_version

    monkeypatch.setattr(ta, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(ta, "_archival_registry", lambda: None)
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2020-01-01", periods=400)
    X = pd.DataFrame(rng.normal(size=(400, 4)), index=idx, columns=["a", "b", "c", "d"])
    y = pd.Series((X["a"] + rng.normal(0, 1, 400) > 0).astype(int), index=idx)

    out = ta.oos_eval_advanced(X.iloc[:300], y.iloc[:300], X.iloc[300:], y.iloc[300:])

    model = joblib.load(tmp_path / "advanced_oos.pkl")  # nosec B301 - written by this test
    assert model_feature_set_version(model) == FEATURE_SET_VERSION
    meta = json.loads((tmp_path / "advanced_oos_meta.json").read_text())
    assert meta["feature_set_version"] == FEATURE_SET_VERSION
    assert out["feature_set_version"] == FEATURE_SET_VERSION
