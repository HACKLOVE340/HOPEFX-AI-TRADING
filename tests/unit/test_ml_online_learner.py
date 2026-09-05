# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_online_learner.py
====================================
`ml/online_learner.py` was 452 statements at 56.57 %.

The uncovered half is the part that runs in production. `EWCRegularizer`,
`OnlineLearner` and `EnsemblePredictor` are `nn.Module`-based and inert without
PyTorch (which is not installed here or in CI); `SklearnOnlineLearner` is the
class `HourlyTrainer._online_update()` actually calls, every hour, on live bars.

Three of its behaviours are security controls rather than features, and those
get the most attention here:

* **`_assert_safe_model_path`** confines every load and save to
  `ml/saved_models`. The path is built from a caller-supplied symbol and then
  handed to joblib, so a traversal escape is arbitrary file write — and, on
  load, arbitrary code execution.
* **`SklearnOnlineLearner.load` refuses to deserialize by default.** joblib
  load is unpickling; the class requires an explicit
  `HOPEFX_ALLOW_TRUSTED_MODEL_LOAD` opt-in. A test that only checked the happy
  path would not notice if that gate were removed, so the refusal is asserted
  first and the opt-in second.
* **`_validate_symbol`** is the allowlist that keeps separators and traversal
  sequences out of the generated filename in the first place.

The learning behaviour worth pinning is the **drift reset**: the KS detector
needs a full window before it will say anything, must establish its reference
from that first window rather than firing on it, and a reset must preserve the
scaler while incrementing the counters that operators watch.
"""

from __future__ import annotations

import pathlib
import pickle
import threading

import numpy as np
import pandas as pd
import pytest

import ml.online_learner as ol
from ml.online_learner import (
    SklearnOnlineLearner,
    _assert_safe_model_path,
    _trusted_pickle_load_enabled,
    _validate_symbol,
    get_online_learner,
)

pytestmark = pytest.mark.unit


def _bars(n=40, start=2000.0, step=1.0, volume=100.0):
    closes = [start + i * step for i in range(n)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [volume] * n,
        }
    )


@pytest.fixture
def learner():
    return SklearnOnlineLearner(symbol="XAU_USD", n_features=64)


@pytest.fixture(autouse=True)
def _clear_registry():
    ol._learner_registry.clear()
    yield
    ol._learner_registry.clear()


# ── path confinement ──────────────────────────────────────────────────────────


class TestModelPathConfinement:
    """Every load and save goes through this. joblib.load is unpickling."""

    def test_a_path_inside_the_model_root_is_allowed(self):
        target = ol._MODEL_ROOT / "online_learner_XAU_USD.pkl"

        assert _assert_safe_model_path(target) == target.resolve()

    def test_a_nested_path_inside_the_root_is_allowed(self):
        target = ol._MODEL_ROOT / "nested" / "model.pkl"

        assert _assert_safe_model_path(target).is_relative_to(ol._MODEL_ROOT)

    @pytest.mark.parametrize(
        "escape",
        [
            "../evil.pkl",
            "../../evil.pkl",
            "../../../etc/passwd",
            "sub/../../escape.pkl",
        ],
    )
    def test_a_traversal_escape_is_refused(self, escape):
        with pytest.raises(ValueError, match="outside the permitted directory"):
            _assert_safe_model_path(ol._MODEL_ROOT / escape)

    def test_an_absolute_path_outside_the_root_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="outside the permitted directory"):
            _assert_safe_model_path(tmp_path / "evil.pkl")

    def test_a_sibling_directory_is_refused(self):
        with pytest.raises(ValueError, match="outside the permitted directory"):
            _assert_safe_model_path(ol._MODEL_ROOT.parent / "saved_models_evil" / "x.pkl")

    def test_the_returned_path_is_resolved(self):
        """Callers must use the returned Path, not the tainted input."""
        returned = _assert_safe_model_path(ol._MODEL_ROOT / "." / "model.pkl")

        assert ".." not in str(returned)
        assert returned.is_absolute()

    def test_the_model_root_is_inside_the_ml_package(self):
        assert ol._MODEL_ROOT.name == "saved_models"
        assert ol._MODEL_ROOT.parent.name == "ml"


# ── the pickle opt-in ─────────────────────────────────────────────────────────


class TestTrustedPickleGate:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "  yes  ", "True"])
    def test_recognised_opt_ins(self, monkeypatch, value):
        monkeypatch.setenv("HOPEFX_ALLOW_TRUSTED_MODEL_LOAD", value)

        assert _trusted_pickle_load_enabled() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe", "y"])
    def test_anything_else_is_off(self, monkeypatch, value):
        monkeypatch.setenv("HOPEFX_ALLOW_TRUSTED_MODEL_LOAD", value)

        assert _trusted_pickle_load_enabled() is False

    def test_it_is_off_when_unset(self, monkeypatch):
        """Deserialising untrusted pickle is code execution — default deny."""
        monkeypatch.delenv("HOPEFX_ALLOW_TRUSTED_MODEL_LOAD", raising=False)

        assert _trusted_pickle_load_enabled() is False


class TestLoadRefusesByDefault:
    def test_load_refuses_without_the_opt_in(self, monkeypatch):
        monkeypatch.delenv("HOPEFX_ALLOW_TRUSTED_MODEL_LOAD", raising=False)
        target = ol._MODEL_ROOT / "whatever.pkl"

        with pytest.raises(RuntimeError, match="Refusing to deserialize"):
            SklearnOnlineLearner.load(str(target))

    def test_the_path_check_runs_before_the_opt_in_check(self, monkeypatch, tmp_path):
        """An escaping path must be rejected even with loading enabled."""
        monkeypatch.setenv("HOPEFX_ALLOW_TRUSTED_MODEL_LOAD", "1")

        with pytest.raises(ValueError, match="outside the permitted directory"):
            SklearnOnlineLearner.load(str(tmp_path / "evil.pkl"))

    def test_with_the_opt_in_a_persisted_learner_round_trips(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_ALLOW_TRUSTED_MODEL_LOAD", "1")
        ol._MODEL_ROOT.mkdir(parents=True, exist_ok=True)
        path = ol._MODEL_ROOT / "test_round_trip.pkl"
        original = SklearnOnlineLearner(symbol="TEST_RT", n_features=32, persist_path=str(path))
        try:
            original._save()

            loaded = SklearnOnlineLearner.load(str(path))

            assert loaded.symbol == "TEST_RT"
            assert loaded.n_features == 32
        finally:
            path.unlink(missing_ok=True)


# ── symbol allowlist ──────────────────────────────────────────────────────────


class TestValidateSymbol:
    @pytest.mark.parametrize("symbol", ["XAU_USD", "EURUSD", "btc-usd", "A", "x" * 32])
    def test_permitted_symbols_pass_through(self, symbol):
        assert _validate_symbol(symbol) == symbol

    @pytest.mark.parametrize(
        "symbol",
        [
            "",
            "x" * 33,
            "../escape",
            "a/b",
            "a\\b",
            "with space",
            "semi;colon",
            "dot.dot",
            "null\x00byte",
            "..",
        ],
    )
    def test_anything_that_could_shape_a_path_is_refused(self, symbol):
        with pytest.raises(ValueError, match="not permitted in a model"):
            _validate_symbol(symbol)


class TestGetOnlineLearner:
    def test_it_returns_a_learner(self):
        assert isinstance(get_online_learner("TESTSYM"), SklearnOnlineLearner)

    def test_the_instance_is_shared_per_symbol(self):
        assert get_online_learner("TESTSYM") is get_online_learner("TESTSYM")

    def test_different_symbols_get_different_learners(self):
        assert get_online_learner("AAA") is not get_online_learner("BBB")

    def test_the_symbol_is_recorded_on_the_learner(self):
        assert get_online_learner("TESTSYM").symbol == "TESTSYM"

    @pytest.mark.parametrize("symbol", ["../escape", "a/b", "with space", ""])
    def test_an_unsafe_symbol_is_refused_before_any_io(self, symbol):
        with pytest.raises(ValueError, match="not permitted in a model"):
            get_online_learner(symbol)

    def test_the_default_persist_path_lands_in_the_model_root(self):
        learner = get_online_learner("TESTSYM")

        assert pathlib.Path(learner.persist_path).parent == ol._MODEL_ROOT
        assert pathlib.Path(learner.persist_path).name == "online_learner_TESTSYM.pkl"

    def test_an_explicit_persist_path_outside_the_root_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="outside the permitted directory"):
            get_online_learner("TESTSYM", persist_path=str(tmp_path / "evil.pkl"))


# ── construction and pickling ─────────────────────────────────────────────────


class TestConstruction:
    def test_a_fresh_learner_is_unfitted(self, learner):
        assert learner._fitted is False
        assert learner._update_count == 0
        assert learner._reset_count == 0

    def test_the_model_and_scaler_are_built(self, learner):
        assert learner._model is not None
        assert learner._scaler is not None

    def test_the_probability_window_is_bounded(self, learner):
        assert learner._prob_window.maxlen == SklearnOnlineLearner._DRIFT_WINDOW

    def test_the_accuracy_window_is_bounded(self, learner):
        assert learner._correct_window.maxlen == SklearnOnlineLearner._PERF_WINDOW

    def test_rolling_accuracy_starts_at_chance(self, learner):
        assert learner._rolling_accuracy == 0.5

    def test_without_sklearn_it_degrades_to_a_no_op(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _no_sklearn(name, *args, **kwargs):
            if name.startswith("sklearn"):
                raise ImportError("no sklearn")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_sklearn)
        inert = SklearnOnlineLearner(symbol="X")

        assert inert._model is None
        assert inert.partial_fit(_bars()) is False
        assert inert.predict_proba(_bars()) is None


class TestPickling:
    def test_the_lock_is_dropped_from_the_pickled_state(self, learner):
        """threading.Lock is not picklable; persistence would fail without this."""
        assert "_lock" not in learner.__getstate__()

    def test_a_round_trip_restores_a_usable_lock(self, learner):
        restored = pickle.loads(pickle.dumps(learner))

        assert restored._lock is not None
        with restored._lock:
            pass

    def test_a_round_trip_preserves_the_counters(self, learner):
        learner._update_count = 7
        learner._reset_count = 2

        restored = pickle.loads(pickle.dumps(learner))

        assert restored._update_count == 7
        assert restored._reset_count == 2


# ── labels and features ───────────────────────────────────────────────────────


class TestExtractLabel:
    def test_a_rising_window_is_labelled_up(self, learner):
        assert learner._extract_label(_bars(step=1.0))[0] == 1

    def test_a_falling_window_is_labelled_down(self, learner):
        assert learner._extract_label(_bars(step=-1.0))[0] == 0

    def test_a_flat_window_is_labelled_down(self, learner):
        """Strictly greater, so flat is not 'up'."""
        assert learner._extract_label(_bars(step=0.0))[0] == 0

    def test_a_frame_without_close_yields_no_label(self, learner):
        assert learner._extract_label(pd.DataFrame({"open": [1.0, 2.0]})) is None


class TestExtractFeatures:
    def test_it_produces_exactly_n_features(self, learner):
        assert learner._extract_features(_bars()).shape == (1, learner.n_features)

    def test_a_frame_with_no_ohlcv_columns_yields_nothing(self, learner):
        assert learner._extract_features(pd.DataFrame({"unrelated": [1, 2, 3]})) is None

    def test_the_width_is_stable_across_window_lengths(self, learner):
        """Padding/truncation is what keeps the model's input width fixed."""
        for n in (5, 20, 100):
            assert learner._extract_features(_bars(n)).shape == (1, learner.n_features)

    def test_nan_prices_do_not_produce_nan_features(self, learner):
        bars = _bars()
        bars.loc[3:6, "close"] = np.nan

        features = learner._extract_features(bars)

        assert np.all(np.isfinite(features))

    def test_non_positive_prices_do_not_produce_infinities(self, learner):
        """log() of a zero close would be -inf without the clamp."""
        bars = _bars()
        bars.loc[5, "close"] = 0.0

        assert np.all(np.isfinite(learner._extract_features(bars)))


# ── drift detection ───────────────────────────────────────────────────────────


class TestDriftDetection:
    def test_a_partial_window_never_reports_drift(self, learner):
        flags = [learner._check_drift(0.5) for _ in range(learner._DRIFT_WINDOW - 1)]

        assert not any(flags)

    def test_the_first_full_window_becomes_the_reference_rather_than_an_alarm(self, learner):
        flags = [learner._check_drift(0.5) for _ in range(learner._DRIFT_WINDOW)]

        assert not any(flags)
        assert learner._ref_probs is not None

    def test_a_stable_stream_does_not_drift(self, learner):
        rng = np.random.default_rng(0)
        for v in rng.normal(0.5, 0.05, learner._DRIFT_WINDOW):
            learner._check_drift(float(v))

        flags = [learner._check_drift(float(v)) for v in rng.normal(0.5, 0.05, learner._DRIFT_WINDOW)]

        assert not any(flags)

    def test_a_shifted_stream_drifts(self, learner):
        for _ in range(learner._DRIFT_WINDOW):
            learner._check_drift(0.2)

        flags = [learner._check_drift(0.9) for _ in range(learner._DRIFT_WINDOW)]

        assert any(flags)

    def test_the_window_stays_bounded_under_a_long_stream(self, learner):
        for i in range(500):
            learner._check_drift(i / 500)

        assert len(learner._prob_window) == learner._DRIFT_WINDOW


class TestRegimeReset:
    def test_a_reset_increments_both_counters(self, learner):
        learner._reset_for_new_regime()

        assert learner._reset_count == 1
        assert learner._drift_count == 1

    def test_a_reset_marks_the_model_unfitted(self, learner):
        learner._fitted = True
        learner._reset_for_new_regime()

        assert learner._fitted is False

    def test_a_reset_rebuilds_the_model(self, learner):
        before = learner._model
        learner._reset_for_new_regime()

        assert learner._model is not before

    def test_a_reset_adopts_the_current_window_as_the_new_reference(self, learner):
        for _ in range(learner._DRIFT_WINDOW):
            learner._check_drift(0.7)

        learner._reset_for_new_regime()

        assert learner._ref_probs is not None
        assert float(np.mean(learner._ref_probs)) == pytest.approx(0.7)

    def test_the_public_reset_is_the_same_operation(self, learner):
        learner.reset()

        assert learner._reset_count == 1


# ── EWC anchoring ─────────────────────────────────────────────────────────────


class TestEwcAnchor:
    def test_anchoring_an_unfitted_model_is_a_no_op(self, learner):
        learner._update_ewc_anchor()

        assert learner._anchor_coef is None

    def test_the_penalty_is_a_no_op_without_an_anchor(self, learner):
        before = learner._model.alpha
        learner._apply_ewc_penalty()

        assert learner._model.alpha == before

    def test_a_fitted_model_can_be_anchored(self, learner):
        learner.partial_fit(_bars())

        learner._update_ewc_anchor()

        assert learner._anchor_coef is not None
        assert learner._anchor_intercept is not None

    def test_the_penalty_never_falls_below_the_base_alpha(self, learner):
        learner.partial_fit(_bars())
        learner._update_ewc_anchor()

        learner._apply_ewc_penalty()

        assert learner._model.alpha >= learner._base_alpha

    def test_the_penalty_is_capped(self, learner):
        """Unbounded alpha would freeze the model outright."""
        learner.partial_fit(_bars())
        learner._update_ewc_anchor()
        learner._anchor_coef = learner._model.coef_ - 1e6  # enormous apparent drift

        learner._apply_ewc_penalty()

        assert learner._model.alpha <= learner._base_alpha * 100

    def test_a_zero_lambda_disables_the_penalty(self):
        off = SklearnOnlineLearner(symbol="X", n_features=64, ewc_lambda=0.0)
        off.partial_fit(_bars())
        off._update_ewc_anchor()
        before = off._model.alpha

        off._apply_ewc_penalty()

        assert off._model.alpha == before


# ── the learning loop ─────────────────────────────────────────────────────────


class TestPartialFit:
    def test_a_first_fit_succeeds_and_marks_fitted(self, learner):
        assert learner.partial_fit(_bars()) is True
        assert learner._fitted is True
        assert learner._update_count == 1

    def test_unusable_bars_are_reported_as_failure_not_raised(self, learner):
        assert learner.partial_fit(pd.DataFrame({"unrelated": [1, 2]})) is False

    def test_an_empty_frame_is_a_failure(self, learner):
        assert learner.partial_fit(pd.DataFrame()) is False

    def test_repeated_fits_advance_the_counter(self, learner):
        for _ in range(5):
            learner.partial_fit(_bars())

        assert learner._update_count == 5

    def test_the_anchor_is_taken_on_the_scheduled_update(self, learner):
        for _ in range(learner._EWC_ANCHOR_EVERY):
            learner.partial_fit(_bars())

        assert learner._anchor_coef is not None

    def test_rolling_accuracy_is_reported_once_there_is_enough_history(self, learner):
        for i in range(15):
            learner.partial_fit(_bars(step=1.0 if i % 2 else -1.0))

        assert 0.0 <= learner._rolling_accuracy <= 1.0

    def test_concurrent_fits_do_not_lose_updates(self, learner):
        """partial_fit and predict_proba share a lock and are called from
        different threads by the hourly trainer."""

        def _worker():
            for _ in range(10):
                learner.partial_fit(_bars())

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert learner._update_count == 40


class TestPredictProba:
    def test_an_unfitted_learner_declines_to_guess(self, learner):
        assert learner.predict_proba(_bars()) is None

    def test_a_fitted_learner_returns_a_probability(self, learner):
        learner.partial_fit(_bars())

        prob = learner.predict_proba(_bars())

        assert prob is not None
        assert 0.0 <= prob <= 1.0

    def test_unusable_bars_return_none_rather_than_raising(self, learner):
        learner.partial_fit(_bars())

        assert learner.predict_proba(pd.DataFrame({"unrelated": [1]})) is None


# ── status ────────────────────────────────────────────────────────────────────


class TestStatus:
    def test_it_reports_a_clean_initial_state(self, learner):
        status = learner.status()

        assert status["symbol"] == "XAU_USD"
        assert status["fitted"] is False
        assert status["update_count"] == 0
        assert status["reset_count"] == 0
        assert status["has_anchor"] is False

    def test_it_reflects_training(self, learner):
        learner.partial_fit(_bars())

        status = learner.status()

        assert status["fitted"] is True
        assert status["update_count"] == 1

    def test_it_reflects_resets(self, learner):
        learner.reset()

        assert learner.status()["reset_count"] == 1

    def test_it_is_json_serialisable(self, learner):
        import json

        learner.partial_fit(_bars())

        json.dumps(learner.status())

    def test_it_reports_every_documented_key(self, learner):
        assert set(learner.status()) == {
            "symbol",
            "fitted",
            "update_count",
            "reset_count",
            "drift_count",
            "rolling_accuracy",
            "ewc_lambda",
            "n_features",
            "persist_path",
            "prob_window_size",
            "has_anchor",
        }
