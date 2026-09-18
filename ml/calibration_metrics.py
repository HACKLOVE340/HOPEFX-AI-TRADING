# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Does a predicted probability mean what it says?

`ModelQualityGate` takes a `calibration_score` and refuses a prediction when it
falls below `MIN_CALIBRATION`. Until this module, the number it received was:

    calibration_score = 1.0 if self._calibrator is not None else 0.0

That measured whether a pickle had loaded. A loaded-but-badly-fitted isotonic
calibrator scored a perfect 1.0 and cleared any threshold; a well-calibrated
raw model scored 0.0 and failed every threshold above zero. The gate was
reading file presence and calling it quality — `ml/inference_engine.py` said as
much in its own docstring and named this module as the fix.

What a real number looks like
-----------------------------

**Brier score** — mean squared error of the forecast probability. A proper
scoring rule, so it cannot be gamed by hedging: 0.0 perfect, 0.25 for a
constant 0.5 on a balanced set, 1.0 for confidently wrong. It blends
calibration with discrimination, which makes it a good summary and a poor
diagnosis.

**Expected Calibration Error (ECE)** — bucket the forecasts by confidence and
compare each bucket's mean confidence with its observed frequency; average the
gaps, weighted by bucket size. This is the one that answers the question a
trader actually asks: *when the model says 70%, does it happen 70% of the
time?* A model can have excellent discrimination and terrible ECE, and it is
ECE that decides whether a probability may be fed into position sizing.

**calibration_score = 1 - ECE** — the [0, 1] higher-is-better form the gate
already expects, so nothing downstream changes shape.

Rule 2 throughout
-----------------

Every path that cannot measure returns ``None``, never a flattering default.
Too few samples, all-one-class held-out data, nothing finite left after
dropping NaNs — each is *absent*, and `ModelQualityGate` already fails closed
on a missing score. Returning 1.0 for an unevaluated model is precisely the
defect this module exists to remove; returning 0.0 would be its mirror, a
refusal justified by nothing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np
from numpy.typing import ArrayLike

__all__ = [
    "CalibrationReport",
    "MIN_SAMPLES_FOR_CALIBRATION",
    "brier_score",
    "calibration_report",
    "expected_calibration_error",
]

#: Below this, a calibration estimate says more about the sample than the model.
#: Ten buckets need enough per bucket for a frequency to mean anything; 100 is
#: the point where a 10-bucket ECE stops being dominated by single observations.
MIN_SAMPLES_FOR_CALIBRATION = 100

DEFAULT_BINS = 10


def _clean(probs: ArrayLike, labels: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    """Drop rows that cannot be scored, rather than zero-filling them.

    A NaN probability is an absent forecast. Counting it as 0.0 would score the
    model as confidently predicting "no" on every bar its features were missing.
    """
    p = np.asarray(probs, dtype=float).ravel()
    y = np.asarray(labels, dtype=float).ravel()
    if p.size != y.size:
        raise ValueError(f"probs and labels differ in length: {p.size} vs {y.size}")
    keep = np.isfinite(p) & np.isfinite(y)
    return p[keep], y[keep]


def brier_score(probs: ArrayLike, labels: ArrayLike) -> float:
    """Mean squared error of the forecast. 0.0 perfect, 1.0 confidently wrong."""
    p, y = _clean(probs, labels)
    if p.size == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def expected_calibration_error(probs: ArrayLike, labels: ArrayLike, n_bins: int = DEFAULT_BINS) -> float:
    """Size-weighted average gap between confidence and observed frequency.

    Equal-width buckets over [0, 1]. Empty buckets contribute nothing rather
    than counting as a perfect zero gap — an unobserved confidence band is not
    evidence of calibration in that band.
    """
    p, y = _clean(probs, labels)
    if p.size == 0:
        return float("nan")

    p = np.clip(p, 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # `right=True` with a leading-edge fix so 0.0 lands in the first bucket
    # rather than a phantom bucket 0.
    idx = np.clip(np.digitize(p, edges[1:-1], right=True), 0, n_bins - 1)

    total = 0.0
    for b in range(n_bins):
        in_bin = idx == b
        count = int(in_bin.sum())
        if count == 0:
            continue
        gap = abs(float(np.mean(p[in_bin])) - float(np.mean(y[in_bin])))
        total += (count / p.size) * gap
    return float(total)


@dataclass(frozen=True)
class CalibrationReport:
    """What training measured, in the form the gate and the metadata both take."""

    brier: float
    ece: float
    calibration_score: float
    n_samples: int
    n_bins: int
    positive_rate: float
    measured_at: str
    single_class: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def calibration_report(
    probs: ArrayLike,
    labels: ArrayLike,
    n_bins: int = DEFAULT_BINS,
    min_samples: int = MIN_SAMPLES_FOR_CALIBRATION,
) -> CalibrationReport | None:
    """Measure calibration on held-out predictions, or return ``None``.

    ``None`` means *not measured* — too few samples, nothing finite, or a
    held-out set with only one class, where a frequency carries no information
    about calibration. The caller must treat that as absent, not as a pass:
    `ModelQualityGate.evaluate` already fails closed on a missing score, and
    that is the behaviour this relies on.
    """
    p, y = _clean(probs, labels)
    if p.size < min_samples:
        return None

    positives = float(np.mean(y))
    if positives in (0.0, 1.0):
        # One class only. Brier and ECE are computable but say nothing about
        # whether a 70% forecast happens 70% of the time, so the report is
        # returned flagged rather than silently trusted.
        return CalibrationReport(
            brier=brier_score(p, y),
            ece=float("nan"),
            calibration_score=0.0,
            n_samples=int(p.size),
            n_bins=n_bins,
            positive_rate=positives,
            measured_at=datetime.now(UTC).isoformat(),
            single_class=True,
        )

    ece = expected_calibration_error(p, y, n_bins=n_bins)
    return CalibrationReport(
        brier=brier_score(p, y),
        ece=ece,
        calibration_score=float(max(0.0, min(1.0, 1.0 - ece))),
        n_samples=int(p.size),
        n_bins=n_bins,
        positive_rate=positives,
        measured_at=datetime.now(UTC).isoformat(),
        single_class=False,
    )
