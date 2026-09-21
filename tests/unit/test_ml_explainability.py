# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_explainability.py
====================================
`ml/explainability.py` was 158 statements at 35.78 %.

It answers "why did the model say that" for the superadmin ML pages, and it is
built almost entirely out of fallbacks: SHAP if installed, else the estimator's
built-in importances, else linear coefficients, else a uniform prior. Which
branch a deployment lands in depends on what happens to be installed, so all
four need to produce a well-formed answer — and none of them were covered.

Two things here are load-bearing beyond a coverage number.

**Path confinement.** `_load_model` builds `ml/saved_models/<model_name>.pkl`
from a caller-supplied name and then *unpickles it*. Unpickling is arbitrary
code execution, so the `relative_to` check that rejects a name escaping the
model directory is a security control, not a tidiness check. It is asserted
here against traversal, absolute paths and separators.

**Unwrapping `CalibratedClassifierCV`.** Its top-level `.estimator` is the
*unfitted template* and has no `feature_importances_`; the fitted estimators
live in `calibrated_classifiers_[i].estimator`. Reach for the wrong one and the
importances silently come back uniform — a plausible-looking chart that means
nothing.
"""

from __future__ import annotations

import builtins
import pickle
import threading
from types import SimpleNamespace

import numpy as np
import pytest

import ml.explainability as ex
from ml.explainability import (
    _builtin_importance,
    _get_feature_names,
    _load_model,
    _shap_tree_importance,
    _unwrap_calibrated,
    clear_cache,
    get_feature_importance,
    get_shap_values,
)

pytestmark = pytest.mark.unit


class _Tree:
    """A stand-in tree model with built-in importances."""

    def __init__(self, importances=(0.5, 0.3, 0.2), names=None):
        self.feature_importances_ = np.array(importances, dtype=float)
        self.n_features_in_ = len(importances)
        if names is not None:
            self.feature_names_in_ = np.array(names)


class _Linear:
    def __init__(self, coef=(1.0, -3.0, 2.0)):
        self.coef_ = np.array([coef], dtype=float)
        self.n_features_in_ = len(coef)


class _Opaque:
    """Neither importances nor coefficients."""

    def __init__(self, n=4):
        self.n_features_in_ = n


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    d = tmp_path / "saved_models"
    d.mkdir()
    monkeypatch.setattr(ex, "_MODEL_DIR", d)
    return d


def _no_predictor(monkeypatch):
    """Make `from ml.advanced_predictor import get_predictor` fail."""
    real_import = builtins.__import__

    def _fake(name, *args, **kwargs):
        if name == "ml.advanced_predictor":
            raise ImportError("unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake)


def _no_shap(monkeypatch):
    real_import = builtins.__import__

    def _fake(name, *args, **kwargs):
        if name == "shap":
            raise ImportError("no shap")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake)


# ── unwrapping ────────────────────────────────────────────────────────────────


class TestUnwrapCalibrated:
    def test_a_plain_model_passes_through(self):
        model = _Tree()

        assert _unwrap_calibrated(model) is model

    def test_it_reaches_the_fitted_inner_estimator(self):
        """`.estimator` on the wrapper is the *unfitted* template."""
        fitted = _Tree()
        wrapper = SimpleNamespace(
            calibrated_classifiers_=[SimpleNamespace(estimator=fitted)],
            estimator=_Opaque(),
        )

        assert _unwrap_calibrated(wrapper) is fitted

    def test_an_empty_calibration_list_does_not_unwrap(self):
        wrapper = SimpleNamespace(calibrated_classifiers_=[])

        assert _unwrap_calibrated(wrapper) is wrapper

    def test_an_inner_without_importances_is_not_used(self):
        wrapper = SimpleNamespace(
            calibrated_classifiers_=[SimpleNamespace(estimator=_Opaque())],
        )

        assert _unwrap_calibrated(wrapper) is wrapper

    def test_a_direct_estimator_with_importances_is_unwrapped(self):
        inner = _Tree()
        wrapper = SimpleNamespace(estimator=inner)

        assert _unwrap_calibrated(wrapper) is inner


# ── loading, and its path confinement ─────────────────────────────────────────


class TestLoadModelPathConfinement:
    """`_load_model` unpickles whatever path it builds. The guard is security."""

    @pytest.mark.parametrize(
        "name",
        [
            "../../../etc/passwd",
            "../outside",
            "../../secrets",
            "sub/../../escape",
        ],
    )
    def test_a_name_escaping_the_model_directory_is_refused(self, model_dir, monkeypatch, name):
        _no_predictor(monkeypatch)

        assert _load_model(name) is None

    def test_an_absolute_path_is_refused(self, model_dir, monkeypatch, tmp_path):
        _no_predictor(monkeypatch)
        outside = tmp_path / "outside.pkl"
        outside.write_bytes(pickle.dumps(_Tree()))

        assert _load_model(str(tmp_path / "outside")) is None

    def test_a_plain_name_is_allowed(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        (model_dir / "good.pkl").write_bytes(pickle.dumps(_Tree()))

        assert _load_model("good") is not None

    def test_a_missing_file_is_none_rather_than_an_error(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)

        assert _load_model("absent") is None

    def test_an_unreadable_pickle_is_none(self, model_dir, monkeypatch):
        """A truncated artifact must not raise out of the endpoint."""
        _no_predictor(monkeypatch)
        (model_dir / "broken.pkl").write_bytes(b"not a pickle at all")

        assert _load_model("broken") is None


class TestLoadModelUnwrapping:
    def test_a_pipeline_is_reduced_to_its_final_estimator(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        final = _Tree()
        pipeline = SimpleNamespace(steps=[("scale", _Opaque()), ("clf", final)])
        (model_dir / "pipe.pkl").write_bytes(pickle.dumps(pipeline))

        loaded = _load_model("pipe")

        assert hasattr(loaded, "feature_importances_")

    def test_a_calibrated_model_is_unwrapped_on_load(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        wrapper = SimpleNamespace(calibrated_classifiers_=[SimpleNamespace(estimator=_Tree())])
        (model_dir / "cal.pkl").write_bytes(pickle.dumps(wrapper))

        assert hasattr(_load_model("cal"), "feature_importances_")


# ── feature names ─────────────────────────────────────────────────────────────


class TestFeatureNames:
    def test_the_model_s_own_names_win(self):
        model = _Tree(names=["rsi_14", "atr", "macd"])

        assert _get_feature_names(model, "m") == ["rsi_14", "atr", "macd"]

    def test_without_names_it_synthesises_one_per_feature(self, monkeypatch):
        _no_predictor(monkeypatch)

        names = _get_feature_names(_Tree((0.1, 0.2)), "m")

        assert len(names) == 2
        assert names == ["feature_000", "feature_001"]

    def test_a_model_with_no_shape_information_gets_the_default_width(self, monkeypatch):
        _no_predictor(monkeypatch)

        assert len(_get_feature_names(SimpleNamespace(), "m")) == 50


# ── importance computation ────────────────────────────────────────────────────


class TestBuiltinImportance:
    def test_importances_are_normalised_to_sum_to_one(self):
        features = _builtin_importance(_Tree((2.0, 3.0, 5.0)), ["a", "b", "c"])

        assert sum(f["importance"] for f in features) == pytest.approx(1.0, abs=1e-5)

    def test_results_are_ordered_most_important_first(self):
        features = _builtin_importance(_Tree((0.1, 0.7, 0.2)), ["a", "b", "c"])

        assert [f["feature"] for f in features] == ["b", "c", "a"]

    def test_all_zero_importances_do_not_divide_by_zero(self):
        features = _builtin_importance(_Tree((0.0, 0.0)), ["a", "b"])

        assert all(f["importance"] == 0.0 for f in features)

    def test_extra_feature_names_are_ignored_rather_than_misaligned(self):
        features = _builtin_importance(_Tree((0.5, 0.5)), ["a", "b", "c", "d"])

        assert len(features) == 2


class TestShapTreeImportance:
    def test_it_normalises_and_sorts(self, monkeypatch):
        class _Explainer:
            def __init__(self, model):
                pass

            def shap_values(self, background):
                return np.array([[0.1, 0.9, 0.3], [0.1, 0.9, 0.3]])

        monkeypatch.setitem(__import__("sys").modules, "shap", SimpleNamespace(TreeExplainer=_Explainer))
        monkeypatch.setattr(ex, "_get_sample_data", lambda *a: np.zeros((2, 3)))

        features = _shap_tree_importance(_Tree(), ["a", "b", "c"])

        assert [f["feature"] for f in features] == ["b", "c", "a"]
        assert sum(f["importance"] for f in features) == pytest.approx(1.0, abs=1e-5)

    def test_a_multiclass_list_uses_the_bullish_class(self, monkeypatch):
        """Class 1 is the bullish probability; class 0 would invert the ranking."""

        class _Explainer:
            def __init__(self, model):
                pass

            def shap_values(self, background):
                return [
                    np.array([[9.0, 0.0, 0.0]]),  # class 0 — must NOT be used
                    np.array([[0.0, 0.0, 9.0]]),  # class 1
                ]

        monkeypatch.setitem(__import__("sys").modules, "shap", SimpleNamespace(TreeExplainer=_Explainer))
        monkeypatch.setattr(ex, "_get_sample_data", lambda *a: np.zeros((1, 3)))

        features = _shap_tree_importance(_Tree(), ["a", "b", "c"])

        assert features[0]["feature"] == "c"

    def test_each_entry_reports_its_raw_mean(self, monkeypatch):
        class _Explainer:
            def __init__(self, model):
                pass

            def shap_values(self, background):
                return np.array([[0.2, 0.4]])

        monkeypatch.setitem(__import__("sys").modules, "shap", SimpleNamespace(TreeExplainer=_Explainer))
        monkeypatch.setattr(ex, "_get_sample_data", lambda *a: np.zeros((1, 2)))

        features = _shap_tree_importance(_Tree((0.5, 0.5)), ["a", "b"])

        assert "shap_mean" in features[0]


# ── the four fallback tiers ───────────────────────────────────────────────────


class TestGetShapValuesTiers:
    def test_a_missing_model_is_reported_as_unavailable(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)

        result = get_shap_values("nope")

        assert result["method"] == "unavailable"
        assert result["features"] == []
        assert result["total_features"] == 0
        assert "not found" in result["message"]

    def test_without_shap_it_falls_back_to_builtin_importances(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))
        _no_shap(monkeypatch)

        result = get_shap_values("tree")

        assert result["method"] == "feature_importances"
        assert len(result["features"]) == 3

    def test_a_failing_shap_falls_back_rather_than_raising(self, model_dir, monkeypatch):
        """SHAP is fussy about model internals; a failure must degrade, not 500."""
        _no_predictor(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))

        def _boom(model, names):
            raise RuntimeError("shap exploded")

        monkeypatch.setitem(__import__("sys").modules, "shap", SimpleNamespace())
        monkeypatch.setattr(ex, "_shap_tree_importance", _boom)

        result = get_shap_values("tree")

        assert result["method"] == "feature_importances"
        assert result["features"]

    def test_a_linear_model_uses_its_coefficients(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        (model_dir / "lin.pkl").write_bytes(pickle.dumps(_Linear()))

        result = get_shap_values("lin")

        assert result["method"] == "linear_coef"
        assert result["features"][0]["feature"] == "feature_001"  # |−3| is largest

    def test_linear_coefficients_use_magnitude_not_sign(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        (model_dir / "lin.pkl").write_bytes(pickle.dumps(_Linear((-9.0, 1.0))))

        result = get_shap_values("lin")

        assert result["features"][0]["feature"] == "feature_000"
        assert all(f["importance"] >= 0 for f in result["features"])

    def test_an_opaque_model_gets_a_uniform_prior(self, model_dir, monkeypatch):
        """Uniform is an honest 'I cannot tell', not a fabricated ranking."""
        _no_predictor(monkeypatch)
        (model_dir / "op.pkl").write_bytes(pickle.dumps(_Opaque(4)))

        result = get_shap_values("op")

        assert result["method"] == "uniform"
        assert all(f["importance"] == pytest.approx(0.25) for f in result["features"])

    def test_every_tier_produces_the_same_response_shape(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))
        (model_dir / "lin.pkl").write_bytes(pickle.dumps(_Linear()))
        (model_dir / "op.pkl").write_bytes(pickle.dumps(_Opaque()))

        for name in ("tree", "lin", "op", "absent"):
            result = get_shap_values(name)
            assert set(result) >= {"model", "method", "features", "total_features", "computed_at"}


class TestTopN:
    def test_the_response_is_truncated_to_top_n(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "wide.pkl").write_bytes(pickle.dumps(_Tree(tuple(range(1, 41)))))

        result = get_shap_values("wide", top_n=5)

        assert len(result["features"]) == 5

    def test_the_total_still_reports_every_feature(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "wide.pkl").write_bytes(pickle.dumps(_Tree(tuple(range(1, 41)))))

        assert get_shap_values("wide", top_n=5)["total_features"] == 40


# ── caching ───────────────────────────────────────────────────────────────────


class TestCaching:
    def test_a_second_call_does_not_reload_the_model(self, model_dir, monkeypatch):
        """SHAP is expensive; the hour-long cache is the reason this is servable."""
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))

        get_shap_values("tree")
        calls = {"n": 0}
        real_load = ex._load_model

        def _counting(name):
            calls["n"] += 1
            return real_load(name)

        monkeypatch.setattr(ex, "_load_model", _counting)
        get_shap_values("tree")

        assert calls["n"] == 0

    def test_the_cache_bookkeeping_key_is_not_returned_to_callers(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))

        get_shap_values("tree")
        second = get_shap_values("tree")

        assert not any(k.startswith("_") for k in second)

    def test_an_expired_entry_is_recomputed(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))
        get_shap_values("tree")

        ex._CACHE["tree"]["_cached_at"] = 0.0  # long expired
        calls = {"n": 0}
        real_load = ex._load_model

        def _counting(name):
            calls["n"] += 1
            return real_load(name)

        monkeypatch.setattr(ex, "_load_model", _counting)
        get_shap_values("tree")

        assert calls["n"] == 1

    def test_a_failed_lookup_is_not_cached(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)

        get_shap_values("absent")

        assert "absent" not in ex._CACHE

    def test_clearing_one_model_leaves_the_others(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "a.pkl").write_bytes(pickle.dumps(_Tree()))
        (model_dir / "b.pkl").write_bytes(pickle.dumps(_Tree()))
        get_shap_values("a")
        get_shap_values("b")

        clear_cache("a")

        assert "a" not in ex._CACHE
        assert "b" in ex._CACHE

    def test_clearing_everything_empties_the_cache(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "a.pkl").write_bytes(pickle.dumps(_Tree()))
        get_shap_values("a")

        clear_cache()

        assert ex._CACHE == {}

    def test_clearing_an_unknown_model_is_not_an_error(self):
        clear_cache("never-seen")

    def test_concurrent_reads_are_safe(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        _no_shap(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))
        errors = []

        def _worker():
            try:
                for _ in range(20):
                    get_shap_values("tree")
            except Exception as exc:  # pragma: no cover - only on a real race
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ── the built-in-only entry point ─────────────────────────────────────────────


class TestGetFeatureImportance:
    def test_a_missing_model_returns_an_empty_answer(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)

        result = get_feature_importance("absent")

        assert result["features"] == []
        assert result["model"] == "absent"

    def test_it_reports_the_builtin_method(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))

        assert get_feature_importance("tree")["method"] == "feature_importances"

    def test_it_never_calls_shap(self, model_dir, monkeypatch):
        """The whole point of this entry point is being the fast one."""
        _no_predictor(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))

        def _boom(*a, **k):
            raise AssertionError("SHAP must not be reached")

        monkeypatch.setattr(ex, "_shap_tree_importance", _boom)

        assert get_feature_importance("tree")["features"]

    def test_an_opaque_model_gets_a_uniform_prior(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        (model_dir / "op.pkl").write_bytes(pickle.dumps(_Opaque(5)))

        result = get_feature_importance("op")

        assert all(f["importance"] == pytest.approx(0.2) for f in result["features"])

    def test_it_honours_top_n(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        (model_dir / "wide.pkl").write_bytes(pickle.dumps(_Tree(tuple(range(1, 41)))))

        assert len(get_feature_importance("wide", top_n=3)["features"]) == 3

    def test_it_does_not_use_the_cache(self, model_dir, monkeypatch):
        _no_predictor(monkeypatch)
        (model_dir / "tree.pkl").write_bytes(pickle.dumps(_Tree()))

        get_feature_importance("tree")

        assert "tree" not in ex._CACHE


class TestSampleData:
    def test_it_degrades_to_none_when_data_is_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _no_predictor(monkeypatch)

        assert ex._get_sample_data("m", _Tree()) is None
