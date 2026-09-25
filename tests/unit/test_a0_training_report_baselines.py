# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A0 fix #8 — every accuracy in a training report sits next to its baselines.

The dry run's OOS accuracy of 0.387 was read as a "sign inversion". It was the
window's base rate: 65.5% of OOS bars went up and the model called "down" on
84.5% of them. Only the OOS block recorded a majority baseline (fix #1); the
walk-forward folds and the final holdout reported bare accuracy.

Every evaluated window now records balanced accuracy, the always-majority,
always-up and always-down accuracies on the SAME window, the predicted-up rate
and a prior-shift flag (predicted-up rate differing from the label rate by more
than 20 points). One helper computes them — ``ml.oos_skill.base_rate_baselines``
— and ``oos_skill_metrics`` (fix #1) uses it, so the two cannot disagree.
"""

from __future__ import annotations


import numpy as np
import pandas as pd
import pytest


BASELINE_KEYS = (
    "accuracy",
    "balanced_accuracy",
    "base_rate",
    "majority_baseline_accuracy",
    "always_up_accuracy",
    "always_down_accuracy",
    "predicted_up_rate",
    "prior_shift",
    "prior_shift_flagged",
)


def test_always_up_on_a_rising_window_is_exactly_its_baseline():
    from ml.oos_skill import base_rate_baselines

    y = np.array([1] * 65 + [0] * 35)
    b = base_rate_baselines(y, np.ones(100, dtype=int))
    assert b["accuracy"] == pytest.approx(0.65)
    assert b["majority_baseline_accuracy"] == pytest.approx(0.65)
    assert b["always_up_accuracy"] == pytest.approx(0.65)
    assert b["always_down_accuracy"] == pytest.approx(0.35)
    assert b["balanced_accuracy"] == pytest.approx(0.5)
    assert b["predicted_up_rate"] == pytest.approx(1.0)
    assert b["prior_shift"] == pytest.approx(0.35)
    assert b["prior_shift_flagged"] is True


def test_the_dry_run_pattern_is_flagged_not_read_as_inversion():
    """65.5% up, 84.5% predicted down: accuracy below 0.5 with balanced ~0.5."""
    from ml.oos_skill import base_rate_baselines

    rng = np.random.default_rng(0)
    y = (rng.uniform(size=2000) < 0.655).astype(int)
    preds = (rng.uniform(size=2000) >= 0.845).astype(int)
    b = base_rate_baselines(y, preds)
    assert b["accuracy"] < 0.45
    assert b["balanced_accuracy"] == pytest.approx(0.5, abs=0.04)
    assert b["prior_shift_flagged"] is True


def test_oos_skill_metrics_reuses_the_helper():
    from ml.oos_skill import base_rate_baselines, oos_skill_metrics

    rng = np.random.default_rng(1)
    y = (rng.uniform(size=300) < 0.6).astype(int)
    p = rng.uniform(size=300)
    m = oos_skill_metrics(y, p, n_boot=50)
    b = base_rate_baselines(y, (p >= 0.5).astype(int))
    for k in BASELINE_KEYS:
        assert m[f"oos_{k}"] == b[k], k


def _xy(n=400, seed=2):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    X = pd.DataFrame(rng.normal(size=(n, 4)), index=idx, columns=list("abcd"))
    y = pd.Series((X["a"] + rng.normal(0, 1, n) > -0.3).astype(int), index=idx)
    return X, y


def test_walk_forward_folds_and_summary_carry_baselines():
    from ml.train_advanced import walk_forward_eval

    X, y = _xy()
    wf = walk_forward_eval(X, y, n_splits=3, horizon=5)
    for fold in wf["folds"]:
        for k in BASELINE_KEYS:
            assert k in fold, f"fold {fold['fold']} has no {k}"
    for k in ("mean_balanced_accuracy", "mean_majority_baseline_accuracy", "folds_beating_majority"):
        assert k in wf, f"walk-forward summary has no {k}"


def test_final_holdout_carries_baselines(tmp_path, monkeypatch):
    import ml.train_advanced as ta

    monkeypatch.setattr(ta, "MODEL_DIR", tmp_path)
    X, y = _xy()
    _, metrics = ta.train_final_model(X, y)
    for k in BASELINE_KEYS:
        assert k in metrics, f"final holdout metrics have no {k}"


def test_oos_block_carries_baselines(tmp_path, monkeypatch):
    import ml.train_advanced as ta

    monkeypatch.setattr(ta, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(ta, "_archival_registry", lambda: None)
    X, y = _xy()
    out = ta.oos_eval_advanced(X.iloc[:300], y.iloc[:300], X.iloc[300:], y.iloc[300:])
    for k in BASELINE_KEYS:
        assert f"oos_{k}" in out, f"OOS result has no oos_{k}"
