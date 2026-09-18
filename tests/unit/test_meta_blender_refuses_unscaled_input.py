# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A meta-blender without its scaler must not predict from unscaled input.

MASTER_OUTSTANDING §A8(b), and the half of A8 that is not an owner decision.

`HybridEnsemble._load_meta` reads `saved_models/hybrid_meta.pkl` and takes two
objects out of it: `state["meta"]`, a Ridge model, and `state["scaler"]`, the
StandardScaler that model was fitted behind. The blend path then read:

    if self._meta_scaler is not None:
        meta_input = self._meta_scaler.transform(meta_input)
    blended = float(self._meta.predict(meta_input)[0])

so a missing scaler did not stop the prediction — it removed the transform and
fed **raw probabilities into a model trained on standardised ones**. The Ridge
coefficients are in units of standard deviations from the training mean; handed
raw [0,1] probabilities they produce a number that is not a probability of
anything, which is then clipped to [0,1] and returned as the ensemble's answer.

Three ways the scaler goes missing, none of them exotic:

* `ml/__init__.py::_verify_checksum` refuses an artifact whose recorded sha256
  does not match, and is fail-closed in production. Two artifacts are in exactly
  that state today (A8).
* `_load_meta` catches every exception at WARNING, so a partial or corrupt
  pickle leaves `_meta` set and `_meta_scaler` None.
* An older `hybrid_meta.pkl` written before the scaler was added has no
  `"scaler"` key at all, and `state.get("scaler")` returns None for it.

This is `hopefx-dead-controls`' second sub-shape — success reported for work
that did not happen — on the money path, and the guard that produces it reads
like an ordinary None check.

The fix is not to halt: the weighted average below the meta-blend is a real,
tested path and is what the ensemble used before the blender existed. The fix is
that an unusable meta-blender falls through to it *loudly* instead of
predicting through a transform that is not there.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

pytestmark = pytest.mark.unit

from ml.advanced_predictor import HybridEnsemblePredictor as HybridEnsemble


class _Ridge:
    """Stands in for the trained Ridge. Records what it was handed."""

    def __init__(self) -> None:
        self.seen: list[np.ndarray] = []

    def predict(self, x):
        self.seen.append(np.asarray(x))
        return np.array([0.9])


class _Scaler:
    def __init__(self) -> None:
        self.calls = 0

    def transform(self, x):
        self.calls += 1
        return np.asarray(x) * 0.0 + 0.5


@pytest.fixture(autouse=True)
def _reset_once_per_process_flag():
    """The warning fires once per PROCESS, so it leaks between tests.

    Without this the second test to assert on the log sees zero records and
    fails for a reason that has nothing to do with the code under test — which
    is how it failed on the first run here.
    """
    HybridEnsemble._unscaled_meta_warned = False
    yield
    HybridEnsemble._unscaled_meta_warned = False


def _ensemble(*, scaler) -> tuple[HybridEnsemble, _Ridge]:
    ens = HybridEnsemble()
    meta = _Ridge()
    ens._meta = meta
    ens._meta_trained = True
    ens._meta_blend = True
    ens._meta_scaler = scaler
    return ens, meta


def _blend(ens: HybridEnsemble) -> float:
    return ens._blend_probabilities(0.7, 0.6, 0.55)


def test_the_blender_is_used_when_its_scaler_is_present():
    """The control. A guard that always falls through proves nothing below."""
    scaler = _Scaler()
    ens, meta = _ensemble(scaler=scaler)

    result = _blend(ens)

    assert scaler.calls == 1, "the scaler was not applied"
    assert meta.seen, "the meta-blender was not consulted"
    assert 0.0 <= result <= 1.0


def test_a_missing_scaler_falls_through_instead_of_predicting_unscaled(caplog):
    """The regression. Red against the pre-fix guard.

    Before the fix the Ridge was called with the raw [0.7, 0.6, 0.55] it was
    never fitted on. It must not be called at all.
    """
    ens, meta = _ensemble(scaler=None)

    with caplog.at_level(logging.ERROR):
        result = _blend(ens)

    assert not meta.seen, (
        "the meta-blender predicted from unscaled input — its coefficients are in "
        "standard deviations, so the result is not a probability of anything"
    )
    assert 0.0 <= result <= 1.0, "the weighted-average fallback must still return a probability"

    # Loud, not swallowed at DEBUG: this is a model artifact that did not load.
    assert any("scaler" in r.getMessage().lower() for r in caplog.records), (
        "the fall-through left no ERROR record — evidence nobody has is evidence swallowed"
    )


def test_the_fallback_is_the_weighted_average_not_a_constant():
    """Falling through must produce the ensemble's real answer, not a placeholder.

    Returning a fixed 0.5 would also pass the test above while destroying the
    signal — the fallback has to be the path the ensemble used before the
    blender existed.
    """
    ens, _meta = _ensemble(scaler=None)

    bullish = ens._blend_probabilities(0.9, 0.9, 0.9)
    bearish = ens._blend_probabilities(0.1, 0.1, 0.1)

    assert bullish > bearish, "the fallback ignores its inputs"
    assert bullish > 0.5 > bearish


def test_the_warning_is_emitted_once_not_per_prediction(caplog):
    """A per-tick ERROR on a hot path is a log nobody can read.

    The condition is structural — the scaler does not appear between
    predictions — so it is stated once and then the fall-through is silent.
    """
    ens, _meta = _ensemble(scaler=None)

    with caplog.at_level(logging.ERROR):
        for _ in range(5):
            _blend(ens)

    complaints = [r for r in caplog.records if "scaler" in r.getMessage().lower()]
    assert len(complaints) == 1, f"expected one ERROR across five predictions, got {len(complaints)}"


def test_an_untrained_blender_is_unaffected():
    """The pre-existing path: no meta model at all already falls through."""
    ens = HybridEnsemble()
    ens._meta = None
    ens._meta_trained = False
    ens._meta_blend = True
    ens._meta_scaler = None

    assert 0.0 <= ens._blend_probabilities(0.7, 0.6, 0.55) <= 1.0


# ── The component predictors abstain rather than propagate a failure ──────────
#
# `_xgb_predict`, `_lstm_predict` and `_rl_predict` each return 0.5 when their
# model is unavailable or raises. 0.5 is "no opinion" for a P(up), so abstaining
# is the right answer — an ensemble component that threw would take the whole
# prediction down with it.
#
# What is worth noticing while covering them: each logs the failure at DEBUG.
# DEBUG is off in production, so a component that has been silently abstaining
# for a week looks identical to one that genuinely has no view — the "evidence
# swallowed at DEBUG" shape from `hopefx-dead-controls`. These tests pin the
# abstention, which is correct; they do not pin the log level, which is not this
# commit's subject.


def _bare_ensemble() -> HybridEnsemble:
    ens = HybridEnsemble()
    ens._meta = None
    ens._meta_trained = False
    ens._meta_blend = False
    ens._meta_scaler = None
    return ens


def test_xgb_abstains_at_one_half_when_its_model_will_not_load(monkeypatch):
    """A component with no model must not decide the ensemble's answer."""
    import ml.advanced_predictor as ap

    class _NoModel:
        _model = None
        _lock = __import__("threading").Lock()
        _feature_names: list[str] = []

        def _load(self):
            return None

    monkeypatch.setattr(ap, "get_predictor", lambda: _NoModel())
    assert _bare_ensemble()._xgb_predict(np.zeros((1, 4))) == 0.5


def test_xgb_abstains_when_the_predictor_raises(monkeypatch):
    """The failure path, which is the one that reaches production."""
    import ml.advanced_predictor as ap

    def _boom():
        raise RuntimeError("model store unreachable")

    monkeypatch.setattr(ap, "get_predictor", _boom)
    assert _bare_ensemble()._xgb_predict(np.zeros((1, 4))) == 0.5


def test_lstm_abstains_when_the_component_is_unavailable():
    ens = _bare_ensemble()
    ens._has_lstm = False
    assert ens._lstm_predict(np.zeros((1, 8, 4))) == 0.5


def test_lstm_abstains_when_its_artifact_is_missing(monkeypatch, tmp_path):
    """LISTED BUT ABSENT is the state `lstm_signal.pt` is in today (A7)."""
    ens = _bare_ensemble()
    ens._has_lstm = True
    monkeypatch.setenv("LSTM_MODEL_PATH", str(tmp_path / "not_here.pt"))
    assert ens._lstm_predict(np.zeros((1, 8, 4))) == 0.5


def test_rl_abstains_when_the_component_is_unavailable():
    ens = _bare_ensemble()
    ens._has_rl = False
    assert ens._rl_predict(np.zeros(4)) == 0.5


def test_rl_maps_each_action_to_a_probability(monkeypatch):
    """0=HOLD, 1=BUY, 2=SELL. An inverted map would short every buy signal."""
    import ml.advanced_predictor as ap

    class _Agent:
        def __init__(self, action):
            self.action = action

        def predict(self, obs):
            return self.action, 1.0

    for action, expected in ((0, 0.5), (1, 0.8), (2, 0.2), (99, 0.5)):
        monkeypatch.setattr(ap, "get_rl_agent", lambda a=action: _Agent(a), raising=False)
        monkeypatch.setitem(
            __import__("sys").modules,
            "ml.rl_agent",
            type("M", (), {"get_rl_agent": staticmethod(lambda a=action: _Agent(a))}),
        )
        ens = _bare_ensemble()
        ens._has_rl = True
        assert ens._rl_predict(np.zeros(4)) == expected, f"action {action} mapped wrongly"


def test_rl_abstains_when_there_is_no_agent(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "ml.rl_agent",
        type("M", (), {"get_rl_agent": staticmethod(lambda: None)}),
    )
    ens = _bare_ensemble()
    ens._has_rl = True
    assert ens._rl_predict(np.zeros(4)) == 0.5


def test_predict_proba_returns_a_probability_with_every_component_abstaining(monkeypatch):
    """End to end: all three abstain, so the ensemble must say 0.5, not crash.

    This is the state a fresh deployment with no artifacts is in, and the
    ensemble has to survive it — an exception here takes down the decision
    pipeline rather than declining to trade.
    """
    import ml.advanced_predictor as ap

    def _boom():
        raise RuntimeError("nothing installed")

    monkeypatch.setattr(ap, "get_predictor", _boom)
    ens = _bare_ensemble()
    ens._has_lstm = False
    ens._has_rl = False

    result = ens.predict_proba(np.zeros((1, 4)))
    assert result == pytest.approx(0.5, abs=1e-9), f"abstaining components produced {result}"


def test_predict_proba_counts_its_calls(monkeypatch):
    """The counter is what a dashboard reads to tell 'quiet' from 'stopped'."""
    import ml.advanced_predictor as ap

    monkeypatch.setattr(ap, "get_predictor", lambda: (_ for _ in ()).throw(RuntimeError()))
    ens = _bare_ensemble()
    ens._has_lstm = False
    ens._has_rl = False

    before = ens._predict_count
    ens.predict_proba(np.zeros((1, 4)))
    ens.predict_proba(np.zeros((1, 4)))
    assert ens._predict_count == before + 2


# ── Feature building degrades visibly, or not at all ─────────────────────────
#
# `AdvancedPredictor._build_features` is the widest untested block in this
# module, and it carries the platform's only throttled degradation warning:
# when the data layer is unreachable it keeps predicting on the base features
# and logs at WARNING on the 1st, 11th, 21st failure and DEBUG in between.
#
# That throttle is the interesting part. Degrading silently would be the defect;
# logging every tick would be a log nobody reads, which is the same defect with
# more output. Both edges are asserted, because a `% 10 == 0` instead of
# `% 10 == 1` would move the first warning to the tenth failure — nine silent
# degraded predictions before anyone hears about it.


def _ohlcv(rows: int = 60):
    import pandas as pd

    idx = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": np.linspace(2000, 2050, rows),
            "high": np.linspace(2001, 2051, rows),
            "low": np.linspace(1999, 2049, rows),
            "close": np.linspace(2000, 2050, rows),
            "volume": np.full(rows, 1000.0),
        },
        index=idx,
    )


def _predictor():
    from ml.advanced_predictor import AdvancedPredictor

    return AdvancedPredictor()


def _features(rows: int = 5):
    import pandas as pd

    return pd.DataFrame({"a": np.arange(rows, dtype=float), "b": np.arange(rows, dtype=float)})


def test_build_features_returns_only_the_last_row(monkeypatch):
    """Point-in-time: a prediction uses one row, the most recent."""
    import ml.advanced_features as af
    import ml.features_extended as fe

    frame = _features(5)
    monkeypatch.setattr(af, "build_advanced_features", lambda *a, **k: (frame, None))
    monkeypatch.setattr(fe, "add_data_layer_features", lambda X, **k: X)

    out = _predictor()._build_features(_ohlcv())
    assert out is not None
    assert len(out) == 1, "more than one row would let a caller predict on stale bars"
    assert out.iloc[0]["a"] == 4.0, "the row returned is not the most recent one"


def test_build_features_returns_none_when_there_are_no_features(monkeypatch):
    import ml.advanced_features as af
    import pandas as pd

    monkeypatch.setattr(af, "build_advanced_features", lambda *a, **k: (pd.DataFrame(), None))
    assert _predictor()._build_features(_ohlcv()) is None


def test_build_features_returns_none_when_the_build_raises(monkeypatch, caplog):
    """A failed build must not hand back a half-built frame."""
    import ml.advanced_features as af

    def _boom(*a, **k):
        raise ValueError("indicator window longer than the data")

    monkeypatch.setattr(af, "build_advanced_features", _boom)

    with caplog.at_level(logging.WARNING):
        assert _predictor()._build_features(_ohlcv(), symbol="XAUUSD") is None
    assert any("Feature build failed" in r.getMessage() for r in caplog.records)


def test_an_unreachable_data_layer_degrades_visibly_rather_than_silently(monkeypatch, caplog):
    """The first failure is announced, not swallowed.

    The prediction continues on the base features, which is the right call — but
    a caller reading the result has no way to know it is degraded, so the log is
    the only signal that exists.
    """
    import ml.advanced_features as af
    import ml.features_extended as fe

    monkeypatch.setattr(af, "build_advanced_features", lambda *a, **k: (_features(3), None))

    def _unreachable(X, **k):
        raise ConnectionError("tick store unreachable")

    monkeypatch.setattr(fe, "add_data_layer_features", _unreachable)

    predictor = _predictor()
    with caplog.at_level(logging.WARNING):
        out = predictor._build_features(_ohlcv())

    assert out is not None, "an unreachable data layer must not stop the prediction"
    assert predictor._dl_failure_count == 1
    assert any("data layer unavailable" in r.getMessage() for r in caplog.records), (
        "the first degraded prediction was silent"
    )


def test_the_degradation_warning_is_throttled_but_keeps_recurring(monkeypatch, caplog):
    """WARNING on the 1st and 11th failure, DEBUG in between.

    `% 10 == 1` rather than `% 10 == 0` is what puts the first one first. The
    off-by-one would cost nine silent degraded predictions before the first
    warning, and both forms read correctly.
    """
    import ml.advanced_features as af
    import ml.features_extended as fe

    monkeypatch.setattr(af, "build_advanced_features", lambda *a, **k: (_features(3), None))
    monkeypatch.setattr(fe, "add_data_layer_features", lambda X, **k: (_ for _ in ()).throw(ConnectionError("down")))

    predictor = _predictor()
    with caplog.at_level(logging.WARNING):
        for _ in range(11):
            predictor._build_features(_ohlcv())

    warnings = [r for r in caplog.records if "data layer unavailable" in r.getMessage()]
    assert predictor._dl_failure_count == 11
    assert len(warnings) == 2, f"expected warnings at failure 1 and 11, got {len(warnings)}"


def test_the_failure_counter_resets_once_the_data_layer_returns(monkeypatch):
    """Otherwise the throttle drifts and the next outage is announced late."""
    import ml.advanced_features as af
    import ml.features_extended as fe

    monkeypatch.setattr(af, "build_advanced_features", lambda *a, **k: (_features(3), None))

    state = {"fail": True}

    def _flaky(X, **k):
        if state["fail"]:
            raise ConnectionError("down")
        return X

    monkeypatch.setattr(fe, "add_data_layer_features", _flaky)

    predictor = _predictor()
    predictor._build_features(_ohlcv())
    assert predictor._dl_failure_count == 1

    state["fail"] = False
    predictor._build_features(_ohlcv())
    assert predictor._dl_failure_count == 0, "the counter did not reset on success"
