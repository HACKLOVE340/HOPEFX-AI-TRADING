"""A0 fix #1 — promotion must beat the base rate, not 0.5.

``ModelRegistry.promote()`` judged a candidate against absolute thresholds
(accuracy >= 0.60, binomial p against 0.5). On a window where gold rose on 65%
of bars, *always predict up* scores 0.65 and is "significant" against 0.5, so a
model with no ranking skill at all could clear the bar. The incumbent's 0.5734
was below always-up (0.5516 on its own window, 0.558 on clean data) once the
leaky 50Y bars are removed — see docs/audit/2026-09-24-a0-no-edge-investigation.md.

The gate added here refuses unless the candidate's RECORDED out-of-sample
evaluation shows BOTH:

  * ``oos_accuracy`` strictly above ``oos_majority_baseline_accuracy`` — the
    accuracy of always predicting the majority class of the SAME OOS window;
  * ``oos_auc_ci_low`` — the lower bound of a 95% moving-block bootstrap CI on
    OOS AUC — strictly above 0.5.

A missing or non-finite metric is a refusal (fail closed). Every fixture below
clears the recency gate, the absolute accuracy / p-value / Sharpe gate and the
P&L gate, so the only thing left that can refuse is the new check; each refusal
is asserted by TYPE and MESSAGE so an earlier gate cannot make a test pass.
All registries live under ``tmp_path``; nothing touches ``ml/saved_models``.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from ml.model_registry import ModelRegistry, NoSkillOverBaseRateError, StaleTrainingDataError

_TODAY = dt.date.today().isoformat()

# Clears every pre-existing gate: acc >= 0.60, p < 0.05, Sharpe gate, fresh data.
_PASSES_OLD_GATES = {
    "oos_p_value": 0.001,
    "sharpe_gate_passed": True,
    "data_end": _TODAY,
}


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_MAX_AGE_DAYS", "30")
    art = tmp_path / "m.pkl"
    art.write_bytes(b"candidate")
    r = ModelRegistry(tmp_path / "registry.json")
    with patch.object(ModelRegistry, "_pnl_reconciliation_check", return_value=(True, "ok")):
        yield r, art


def _assert_not_promoted(r: ModelRegistry, name: str) -> None:
    assert r.get_version(name)["state"] == "staging"
    assert json.loads(r._path.read_text())["active_version"] is None


# ── (a) accuracy at or below the always-majority baseline ─────────────────────


def test_refuses_candidate_below_majority_baseline(reg):
    """0.62 clears the old 0.60 bar, but the window was 65% up."""
    r, art = reg
    r.register(
        "cand",
        art,
        oos_accuracy=0.62,
        oos_majority_baseline_accuracy=0.65,
        oos_auc_ci_low=0.56,
        **_PASSES_OLD_GATES,
    )
    with pytest.raises(NoSkillOverBaseRateError, match=r"0\.6200 .*not above .*always-majority .*0\.6500"):
        r.promote("cand")
    _assert_not_promoted(r, "cand")


def test_refuses_candidate_equal_to_majority_baseline(reg):
    """An always-up predictor ties the baseline exactly; strictly above means refuse."""
    r, art = reg
    r.register(
        "cand",
        art,
        oos_accuracy=0.65,
        oos_majority_baseline_accuracy=0.65,
        oos_auc_ci_low=0.56,
        **_PASSES_OLD_GATES,
    )
    with pytest.raises(NoSkillOverBaseRateError, match="not above"):
        r.promote("cand")
    _assert_not_promoted(r, "cand")


# ── (b) AUC lower confidence bound at or below 0.5 ────────────────────────────


@pytest.mark.parametrize("ci_low", [0.5, 0.47])
def test_refuses_candidate_whose_auc_lower_bound_is_not_above_half(reg, ci_low):
    r, art = reg
    r.register(
        "cand",
        art,
        oos_accuracy=0.70,
        oos_majority_baseline_accuracy=0.55,
        oos_auc_ci_low=ci_low,
        **_PASSES_OLD_GATES,
    )
    with pytest.raises(NoSkillOverBaseRateError, match=r"AUC .*lower bound .* not above 0\.5"):
        r.promote("cand")
    _assert_not_promoted(r, "cand")


# ── (c) missing metrics: fail closed ──────────────────────────────────────────


def test_refuses_candidate_with_no_base_rate_metrics(reg):
    """What every entry registered before this gate looks like."""
    r, art = reg
    r.register("cand", art, oos_accuracy=0.90, **_PASSES_OLD_GATES)
    with pytest.raises(NoSkillOverBaseRateError, match="oos_majority_baseline_accuracy.*missing"):
        r.promote("cand")
    _assert_not_promoted(r, "cand")


def test_refuses_candidate_missing_only_the_auc_bound(reg):
    r, art = reg
    r.register("cand", art, oos_accuracy=0.90, oos_majority_baseline_accuracy=0.55, **_PASSES_OLD_GATES)
    with pytest.raises(NoSkillOverBaseRateError, match="oos_auc_ci_low.*missing"):
        r.promote("cand")


@pytest.mark.parametrize("bad", [math.nan, math.inf, "0.7", None])
def test_refuses_non_finite_or_non_numeric_metric(reg, bad):
    r, art = reg
    r.register(
        "cand", art, oos_accuracy=0.90, oos_majority_baseline_accuracy=0.55, oos_auc_ci_low=0.6, **_PASSES_OLD_GATES
    )
    manifest = json.loads(r._path.read_text())
    manifest["versions"]["cand"]["oos_auc_ci_low"] = bad
    r._path.write_text(json.dumps(manifest))
    with pytest.raises(NoSkillOverBaseRateError):
        r.promote("cand")


def test_refusal_is_catchable_as_runtime_and_value_error(reg):
    """bootstrap_from_meta and the superadmin deploy path catch RuntimeError."""
    r, art = reg
    r.register("cand", art, oos_accuracy=0.90, **_PASSES_OLD_GATES)
    with pytest.raises(RuntimeError):
        r.promote("cand")
    with pytest.raises(ValueError):
        r.promote("cand")


# ── (d) a genuinely skilful candidate is accepted ─────────────────────────────


def test_accepts_candidate_that_beats_base_rate_with_auc_bound_above_half(reg):
    """The gate must be able to open, or it is a wall, not a gate."""
    r, art = reg
    r.register(
        "cand",
        art,
        oos_accuracy=0.70,
        oos_majority_baseline_accuracy=0.55,
        oos_auc_ci_low=0.58,
        **_PASSES_OLD_GATES,
    )
    entry = r.promote("cand")
    assert entry["state"] == "active"
    assert r.active_version()["name"] == "cand"


def test_register_records_the_base_rate_metrics(reg):
    r, art = reg
    entry = r.register(
        "cand",
        art,
        oos_accuracy=0.70,
        oos_majority_baseline_accuracy=0.55,
        oos_auc_ci_low=0.58,
        oos_balanced_accuracy=0.66,
        oos_base_rate=0.55,
        **_PASSES_OLD_GATES,
    )
    stored = r.get_version("cand")
    for key, value in {
        "oos_majority_baseline_accuracy": 0.55,
        "oos_auc_ci_low": 0.58,
        "oos_balanced_accuracy": 0.66,
        "oos_base_rate": 0.55,
    }.items():
        assert entry[key] == value
        assert stored[key] == value


# ── (e) the existing gates still fire ─────────────────────────────────────────

_SKILFUL = {"oos_accuracy": 0.70, "oos_majority_baseline_accuracy": 0.55, "oos_auc_ci_low": 0.58}


def test_stale_training_data_gate_still_fires(reg):
    r, art = reg
    old = (dt.date.today() - dt.timedelta(days=183)).isoformat()
    r.register("cand", art, oos_p_value=0.001, sharpe_gate_passed=True, data_end=old, **_SKILFUL)
    with pytest.raises(StaleTrainingDataError, match="183 days old > MODEL_MAX_AGE_DAYS"):
        r.promote("cand")
    _assert_not_promoted(r, "cand")


def test_stale_gate_fires_before_the_skill_gate(reg):
    """Stale AND skill-less: the recency refusal is the one reported."""
    r, art = reg
    old = (dt.date.today() - dt.timedelta(days=183)).isoformat()
    r.register("cand", art, oos_accuracy=0.90, oos_p_value=0.001, sharpe_gate_passed=True, data_end=old)
    with pytest.raises(StaleTrainingDataError):
        r.promote("cand")


def test_sharpe_gate_still_fires(reg):
    r, art = reg
    r.register("cand", art, oos_p_value=0.001, sharpe_gate_passed=False, data_end=_TODAY, **_SKILFUL)
    with pytest.raises(RuntimeError, match="Sharpe gate not passed") as exc_info:
        r.promote("cand")
    assert not isinstance(exc_info.value, NoSkillOverBaseRateError)
    _assert_not_promoted(r, "cand")


def test_rollback_stays_ungated(reg):
    """An emergency restore of a model with no base-rate metrics stays possible."""
    r, art = reg
    r.register("old", art, oos_accuracy=0.5734)
    entry = r.rollback("old")
    assert entry["state"] == "active"


# ── The metric computation: the gate's input is measured, not typed ───────────


def _window(n: int = 1200, p_up: float = 0.65, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.random(n) < p_up).astype(int)


def test_always_up_predictor_ties_the_baseline_and_is_refused():
    from ml.oos_skill import oos_skill_metrics, skill_over_base_rate_check

    y = _window()
    proba = np.full(len(y), 0.9)
    m = oos_skill_metrics(y, proba, preds=np.ones(len(y), dtype=int))
    assert m["oos_accuracy"] == m["oos_majority_baseline_accuracy"]
    assert m["oos_majority_baseline_accuracy"] == pytest.approx(y.mean(), abs=1e-4)
    ok, reason = skill_over_base_rate_check(m)
    assert ok is False, reason


def test_random_predictor_biased_like_the_window_is_refused():
    from ml.oos_skill import oos_skill_metrics, skill_over_base_rate_check

    y = _window()
    rng = np.random.default_rng(7)
    proba = np.clip(rng.normal(0.62, 0.1, len(y)), 0, 1)  # says "up" most of the time, knows nothing
    m = oos_skill_metrics(y, proba)
    assert m["oos_auc_ci_low"] <= 0.5 < m["oos_auc_ci_high"]
    ok, _ = skill_over_base_rate_check(m)
    assert ok is False


def test_skilful_predictor_passes_the_computed_check():
    from ml.oos_skill import oos_skill_metrics, skill_over_base_rate_check

    rng = np.random.default_rng(3)
    signal = rng.normal(0.4, 1.0, 1200)
    y = (signal + rng.normal(0, 0.8, 1200) > 0).astype(int)
    proba = 1.0 / (1.0 + np.exp(-2.0 * signal))
    m = oos_skill_metrics(y, proba)
    assert m["oos_accuracy"] > m["oos_majority_baseline_accuracy"]
    assert m["oos_auc_ci_low"] > 0.5
    assert m["oos_auc_ci_method"].startswith("moving-block bootstrap")
    ok, reason = skill_over_base_rate_check(m)
    assert ok is True, reason


def test_single_class_window_cannot_be_measured():
    """No AUC exists on a one-class window, so no bound — and no promotion."""
    from ml.oos_skill import oos_skill_metrics, skill_over_base_rate_check

    y = np.ones(300, dtype=int)
    m = oos_skill_metrics(y, np.full(300, 0.7))
    assert m["oos_auc_ci_low"] is None
    assert skill_over_base_rate_check(m)[0] is False


def test_computed_metrics_flow_through_register_and_promote(reg):
    """End to end: measured on predictions, recorded, and the gate opens."""
    from ml.oos_skill import oos_skill_metrics

    r, art = reg
    rng = np.random.default_rng(3)
    signal = rng.normal(0.4, 1.0, 1200)
    y = (signal + rng.normal(0, 0.8, 1200) > 0).astype(int)
    m = oos_skill_metrics(y, 1.0 / (1.0 + np.exp(-2.0 * signal)))
    r.register(
        "cand",
        art,
        oos_accuracy=m["oos_accuracy"],
        oos_majority_baseline_accuracy=m["oos_majority_baseline_accuracy"],
        oos_auc_ci_low=m["oos_auc_ci_low"],
        oos_p_value=0.001,
        sharpe_gate_passed=True,
        data_end=_TODAY,
    )
    assert r.promote("cand")["state"] == "active"


# ── The trainer records them; bootstrap carries them into the registry ────────


def _synthetic_split(n_cv: int = 260, n_oos: int = 140, seed: int = 11):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n_cv + n_oos, freq="B")
    X = pd.DataFrame(rng.normal(size=(n_cv + n_oos, 6)), index=idx, columns=[f"f{i}" for i in range(6)])
    y = pd.Series((X["f0"] + rng.normal(0, 1.0, len(X)) > 0).astype(int), index=idx)
    return X.iloc[:n_cv], y.iloc[:n_cv], X.iloc[n_cv:], y.iloc[n_cv:]


def test_oos_eval_advanced_records_base_rate_metrics(tmp_path, monkeypatch):
    import ml.train_advanced as ta

    monkeypatch.setattr(ta, "MODEL_DIR", tmp_path)
    X_cv, y_cv, X_oos, y_oos = _synthetic_split()
    result = ta.oos_eval_advanced(X_cv, y_cv, X_oos, y_oos)
    meta = json.loads((tmp_path / "advanced_oos_meta.json").read_text())

    majority = max(float(y_oos.mean()), 1.0 - float(y_oos.mean()))
    for source in (meta, result):
        assert source["oos_majority_baseline_accuracy"] == pytest.approx(majority, abs=1e-4)
        assert source["oos_base_rate"] == pytest.approx(float(y_oos.mean()), abs=1e-4)
        assert source["oos_auc_ci_low"] is not None
        assert 0.0 <= source["oos_auc_ci_low"] <= source["oos_auc_ci_high"] <= 1.0
        assert "oos_balanced_accuracy" in source
    # Recorded at the same precision as oos_accuracy, so a tie stays a tie.
    assert meta["oos_accuracy"] == round(meta["oos_accuracy"], 4)
    assert meta["oos_majority_baseline_accuracy"] == round(meta["oos_majority_baseline_accuracy"], 4)


def test_bootstrap_from_meta_carries_the_base_rate_metrics(reg, tmp_path):
    r, art = reg
    meta = tmp_path / "meta.json"
    meta.write_text(
        json.dumps(
            {
                "oos_accuracy": 0.70,
                "oos_p_value": 0.001,
                "oos_majority_baseline_accuracy": 0.55,
                "oos_auc_ci_low": 0.58,
                "oos_balanced_accuracy": 0.66,
                "oos_base_rate": 0.55,
                "data_end": _TODAY,
                "sharpe_gate": {"gate_passed": True},
            }
        )
    )
    entry = r.bootstrap_from_meta(meta_path=meta, model_path=art, name="boot", promote=True)
    assert entry["oos_majority_baseline_accuracy"] == 0.55
    assert entry["oos_auc_ci_low"] == 0.58
    assert entry["state"] == "active"
