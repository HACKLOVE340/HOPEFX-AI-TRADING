# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/oos_skill.py
===============
Out-of-sample skill measured against the base rate, not against 0.5.

Why this exists (A0, docs/audit/2026-09-24-a0-no-edge-investigation.md)
----------------------------------------------------------------------
The trainer tested OOS accuracy with a binomial test against p = 0.5 and the
registry promoted on an absolute accuracy floor. On a window where gold rose on
65% of bars, *always predict up* scores 0.65 and is "significant" against 0.5,
so a classifier with no ranking skill passes. The incumbent's recorded 0.5734
was 2.2 points above always-up (0.5516) on a window partly built from
synthetic bars, and BELOW always-up on clean data (0.534 against 0.558).

Two measurements answer "does this model know anything?":

* **Accuracy against the always-majority baseline on the same window.** The
  baseline is ``max(p, 1 - p)`` where ``p`` is the OOS window's own share of
  up labels. That uses hindsight about the window's class balance on purpose:
  it is the strictest trivial predictor, so beating it cannot be an artefact
  of a base-rate shift between training and OOS.
* **A lower confidence bound on OOS AUC.** AUC is threshold-free, so it
  measures ranking skill that a biased threshold hides. The bound comes from a
  **moving-block bootstrap**: labels are forward returns over ``horizon`` bars,
  so neighbouring rows overlap and an iid bootstrap would understate the
  variance (the investigation's own caveat). Blocks of ``block_len`` rows are
  resampled with replacement and concatenated to the window length.

:func:`skill_over_base_rate_check` is the ONE statement of the rule. The model
registry's promotion gate and ``scripts/retrain_with_ticks.py`` both call it,
so a script and the gate cannot disagree about what "better" means.

Heavy imports (numpy, scipy) are local to the functions that need them, so the
registry can import the check without pulling in the numerical stack.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

#: Rows per bootstrap block. The production label is a 5-bar forward return.
DEFAULT_BLOCK_LEN = 5
#: Bootstrap resamples. 1,000 gives a 2.5th percentile stable to ~0.005 AUC.
DEFAULT_N_BOOT = 1000
#: Two-sided confidence level of the AUC interval.
CI_LEVEL = 0.95
#: Recorded precision. oos_accuracy has always been written at 4 dp; the
#: baseline MUST use the same, or an exact tie (always-up) can round into a
#: "win" — 0.551587 recorded beside 0.5516 would pass a strict comparison.
ROUND_DP = 4
#: A bound is reported only when at least this share of resamples contained
#: both classes; otherwise the window cannot support an AUC and none is given.
_MIN_VALID_RESAMPLE_SHARE = 0.9

#: Keys the promotion gate requires. Absent or non-finite → refusal.
REQUIRED_KEYS = ("oos_accuracy", "oos_majority_baseline_accuracy", "oos_auc_ci_low")


def _rank_auc(y: Any, s: Any) -> Any:
    """Row-wise Mann-Whitney AUC for 2-D arrays ``y`` (0/1) and ``s`` (scores).

    Ties in ``s`` get average ranks, so a constant score is exactly 0.5.
    Rows with a single class return NaN.
    """
    import numpy as np
    from scipy.stats import rankdata

    ranks = rankdata(s, axis=1)
    n_pos = y.sum(axis=1)
    n_neg = y.shape[1] - n_pos
    sum_pos = (ranks * y).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        auc = (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    auc[(n_pos == 0) | (n_neg == 0)] = np.nan
    return auc


def block_bootstrap_auc_ci(
    y_true: Any,
    scores: Any,
    *,
    block_len: int = DEFAULT_BLOCK_LEN,
    n_boot: int = DEFAULT_N_BOOT,
    level: float = CI_LEVEL,
    seed: int = 42,
) -> tuple[float, float] | None:
    """Percentile CI for AUC from a moving-block bootstrap, or ``None``.

    ``None`` means the window cannot support the measurement (fewer than two
    blocks, a single class, or too many single-class resamples). A caller must
    treat ``None`` as unmeasured, never as a pass.
    """
    import numpy as np

    y = np.asarray(y_true, dtype=float).ravel()
    s = np.asarray(scores, dtype=float).ravel()
    n = len(y)
    block_len = max(int(block_len), 1)
    if n != len(s) or n < 2 * block_len or len(np.unique(y)) < 2 or not np.all(np.isfinite(s)):
        return None

    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block_len)
    starts = rng.integers(0, n - block_len + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block_len)[None, None, :]).reshape(n_boot, -1)[:, :n]
    aucs = _rank_auc(y[idx], s[idx])
    valid = aucs[np.isfinite(aucs)]
    if len(valid) < _MIN_VALID_RESAMPLE_SHARE * n_boot:
        return None
    alpha = (1.0 - level) / 2.0
    return float(np.quantile(valid, alpha)), float(np.quantile(valid, 1.0 - alpha))


#: A predicted-up rate this far from the window's label rate is flagged: the
#: model's accuracy then mostly measures the prior shift, not skill (A0 #8).
PRIOR_SHIFT_FLAG = 0.20


def base_rate_baselines(y_true: Any, preds: Any) -> dict[str, Any]:
    """Accuracy of ``preds`` next to what trivial predictors score on the SAME window.

    One definition for every evaluated window in a training report (walk-forward
    folds, final holdout, OOS), so an accuracy is never reported without the
    base rate it has to beat. A0 fix #8: the dry run's 0.387 was read as a sign
    inversion; it was a 65.5%-up window scored by a model that said "down" 84.5%
    of the time — balanced accuracy ~0.5, and a prior-shift flag, say so.

    ``balanced_accuracy`` is the mean recall of the two classes (0.5 for any
    constant predictor) and ``None`` on a one-class window.
    """
    import numpy as np

    y = np.asarray(y_true, dtype=int).ravel()
    yhat = np.asarray(preds, dtype=int).ravel()
    n = len(y)
    if n == 0 or len(yhat) != n:
        raise ValueError(f"base_rate_baselines: need equal, non-empty inputs (y={n}, preds={len(yhat)})")

    n_up = int(y.sum())
    base_rate = n_up / n
    majority_class = 1 if n_up * 2 >= n else 0
    recalls = [float(np.mean(yhat[y == c] == c)) for c in (0, 1) if np.any(y == c)]
    balanced = sum(recalls) / 2.0 if len(recalls) == 2 else None
    pred_up = float(np.mean(yhat == 1))
    shift = pred_up - base_rate
    return {
        "accuracy": round(float(np.mean(yhat == y)), ROUND_DP),
        "balanced_accuracy": None if balanced is None else round(balanced, ROUND_DP),
        "base_rate": round(base_rate, ROUND_DP),
        "majority_class": majority_class,
        "majority_baseline_accuracy": round((n_up if majority_class == 1 else n - n_up) / n, ROUND_DP),
        "always_up_accuracy": round(base_rate, ROUND_DP),
        "always_down_accuracy": round((n - n_up) / n, ROUND_DP),
        "predicted_up_rate": round(pred_up, ROUND_DP),
        "prior_shift": round(shift, ROUND_DP),
        "prior_shift_flagged": bool(abs(shift) > PRIOR_SHIFT_FLAG),
    }


def oos_skill_metrics(
    y_true: Any,
    proba: Any,
    preds: Any = None,
    *,
    block_len: int = DEFAULT_BLOCK_LEN,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = 42,
) -> dict[str, Any]:
    """Measure OOS skill against the base rate of the SAME window.

    Parameters
    ----------
    y_true : 0/1 labels of the OOS window, in time order.
    proba  : predicted P(label == 1) for the same rows.
    preds  : hard predictions; defaults to ``proba >= 0.5``.

    Returns the keys the model metadata and registry record. Every value is a
    plain float/int/str/None so it serialises to JSON unchanged.
    """
    import numpy as np
    from scipy.stats import binomtest

    y = np.asarray(y_true, dtype=int).ravel()
    p = np.asarray(proba, dtype=float).ravel()
    yhat = (p >= 0.5).astype(int) if preds is None else np.asarray(preds, dtype=int).ravel()
    n = len(y)
    if n == 0 or len(p) != n or len(yhat) != n:
        raise ValueError(f"oos_skill_metrics: need equal, non-empty inputs (y={n}, proba={len(p)}, preds={len(yhat)})")

    n_up = int(y.sum())
    majority_class = 1 if n_up * 2 >= n else 0
    majority_hits = n_up if majority_class == 1 else n - n_up
    hits = int(np.sum(yhat == y))
    # Accuracy, balanced accuracy and the trivial baselines: one definition
    # shared with every other window in the training report (A0 fix #8).
    baselines = base_rate_baselines(y, yhat)

    ci = block_bootstrap_auc_ci(y, p, block_len=block_len, n_boot=n_boot, seed=seed)
    try:
        from sklearn.metrics import roc_auc_score

        auc = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None
    except ValueError:
        auc = None

    # One-sided binomial against the majority rate — the test the trainer's
    # p = 0.5 test should have been (D5). Recorded for the reader; the gate
    # uses the accuracy comparison and the AUC bound.
    p_vs_majority = (
        float(binomtest(hits, n, p=majority_hits / n, alternative="greater").pvalue) if majority_hits < n else 1.0
    )

    return {
        "oos_n": n,
        **{f"oos_{k}": v for k, v in baselines.items()},
        "oos_p_value_vs_majority": round(p_vs_majority, 6),
        "oos_auc": None if auc is None else round(auc, ROUND_DP),
        "oos_auc_ci_low": None if ci is None else round(ci[0], ROUND_DP),
        "oos_auc_ci_high": None if ci is None else round(ci[1], ROUND_DP),
        "oos_auc_ci_method": (
            f"moving-block bootstrap, block={max(int(block_len), 1)}, n_boot={n_boot}, "
            f"{int(CI_LEVEL * 100)}% percentile, seed={seed}"
        ),
    }


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def skill_over_base_rate_check(metrics: Mapping[str, Any]) -> tuple[bool, str]:
    """The promotion rule. Returns ``(passed, reason)``; fails closed.

    Passes only when ALL hold on the recorded OOS evaluation:

    1. ``oos_accuracy`` > ``oos_majority_baseline_accuracy`` (strictly);
    2. ``oos_auc_ci_low`` > 0.5 (strictly).

    A missing, non-numeric or non-finite value refuses, as does a baseline
    outside [0.5, 1.0] — the majority class is right at least half the time by
    definition, so anything else was not computed by :func:`oos_skill_metrics`.
    """
    values: dict[str, float] = {}
    for key in REQUIRED_KEYS:
        raw = metrics.get(key)
        num = _finite_number(raw)
        if num is None:
            return False, (
                f"{key} is missing or not a finite number ({raw!r}) — the OOS evaluation did not record "
                "skill against the base rate, so none can be shown (fail closed)"
            )
        values[key] = num

    acc = values["oos_accuracy"]
    base = values["oos_majority_baseline_accuracy"]
    auc_low = values["oos_auc_ci_low"]
    if not 0.5 <= base <= 1.0:
        return False, f"oos_majority_baseline_accuracy {base:.4f} is outside [0.5, 1.0]; it cannot be a majority rate"
    if not acc > base:
        return False, (
            f"OOS accuracy {acc:.4f} is not above the always-majority baseline {base:.4f} on the same window — "
            "a constant predictor does at least as well"
        )
    if not auc_low > 0.5:
        return False, (
            f"OOS AUC 95% lower bound {auc_low:.4f} is not above 0.5 — ranking skill is not distinguishable from none"
        )
    return True, f"beats base rate: acc {acc:.4f} > majority {base:.4f}, AUC lower bound {auc_low:.4f} > 0.5"
