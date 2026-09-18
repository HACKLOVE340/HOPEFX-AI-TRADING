# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A feature the feed could not supply is absent, not drifted.

`_check_feature_drift` computes, per feature,

    z = |live_mean - train_mean| / train_std

and a feature the pipeline zero-filled arrives as `live_mean == 0.0`. When the
training mean is not near zero that produces a large z — so **absent data reads
as drift**, and with `DRIFT_BLOCK=true` it halts inference and reports the halt
as `feature_drift`.

This is not hypothetical. `python scripts/drift_guard_report.py` against the
shipped stats, today:

    compared            176
    zero-filled         103
    over z=4.0           14
      of which zero-filled  12   <- absent data, not drift
      of which drifted       2

Twelve of the fourteen features that would trip the block are features nothing
supplied. On the deployed chart (`DRIFT_Z_THRESHOLD: 3.0`) it is fifteen.

So a feed outage would stop the desk and the log would blame the model. That is
the shape this repository keeps finding — a control that fires, but not on what
it names — and it is worse than a control that does not fire, because the
operator chases a retrain while the real fault is a dead feed.

`drift_guard_report.py` already draws the distinction with
`live == 0.0 and mean != 0.0`. The engine did not. These tests make the engine
use the same rule, so the block fires on distribution change and absence is
reported as absence.

**What this deliberately does NOT do:** decide whether absent features should
halt inference on their own. They arguably should — a model predicting from 103
zero-filled features is not predicting from much — but that is a new gate with
its own blast radius, and inventing it here would be the same mistake in the
other direction. Absence is now logged at ERROR, counted, and exposed on the
status payload so it cannot pass silently; whether it blocks is named as an
owner decision (DRIFT-ABSENCE).
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

pytestmark = pytest.mark.unit


def _engine():
    from ml.inference_engine import InferenceEngine

    return InferenceEngine()


def _row(values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame({n: [v] for n, v in values.items()})


def _fill(eng, values: dict[str, float]) -> bool:
    """Push a full window of identical rows through the guard."""
    import ml.inference_engine as ie

    result = False
    for _ in range(ie._DRIFT_WINDOW + 1):
        result = eng._check_feature_drift(_row(values))
    return result


#: Ten features, training mean far from zero — the shape that makes a
#: zero-filled live value look like a large z.
_TRAIN = {f"f{i}": {"mean": 100.0, "std": 1.0} for i in range(10)}


def test_a_zero_filled_feature_is_not_reported_as_drift():
    """The regression. Every feature absent, nothing drifted."""
    eng = _engine()
    eng._train_stats = dict(_TRAIN)

    drifted = _fill(eng, dict.fromkeys(_TRAIN, 0.0))

    assert drifted is False, (
        "features the feed could not supply were reported as drift — with DRIFT_BLOCK=true "
        "a feed outage halts the desk and the log blames the model"
    )


def test_a_genuinely_drifted_feature_is_still_caught():
    """The control, and the one that matters most.

    A guard that stopped reporting drift would pass the test above. This is a
    real distribution move: non-zero live values, far from the training mean.
    """
    eng = _engine()
    eng._train_stats = dict(_TRAIN)

    drifted = _fill(eng, dict.fromkeys(_TRAIN, 130.0))

    assert drifted is True, "a genuine 30-sigma move was not reported as drift"


def test_absence_and_drift_are_counted_separately():
    """Mixed: half the features absent, half genuinely moved."""
    eng = _engine()
    eng._train_stats = dict(_TRAIN)

    values = {n: (0.0 if i < 5 else 130.0) for i, n in enumerate(_TRAIN)}
    drifted = _fill(eng, values)

    assert drifted is True, "real drift alongside absence must still be reported"
    assert eng._drift_absent_count == 5, f"expected 5 absent, got {eng._drift_absent_count}"
    assert eng._drift_drifted_count == 5, f"expected 5 drifted, got {eng._drift_drifted_count}"


def test_the_drift_z_max_excludes_absent_features():
    """`_drift_z_max` feeds model-quality scoring.

    Letting absence inflate it means a dead feed degrades the model's quality
    score, which is a second wrong conclusion drawn from the same bad input.
    """
    eng = _engine()
    eng._train_stats = dict(_TRAIN)

    _fill(eng, dict.fromkeys(_TRAIN, 0.0))

    assert eng._drift_z_max == 0.0, (
        f"z_max is {eng._drift_z_max} with every feature absent — absence is inflating the "
        "drift score that model quality reads"
    )


def test_a_feature_legitimately_zero_in_training_is_not_treated_as_absent():
    """The false-positive guard on the rule itself.

    `live == 0.0 and mean != 0.0` is the report's rule. A binary feature whose
    training mean IS ~0 must not be silently exempted from drift detection just
    because its live value is 0 — that would be a hole in the guard rather than
    a fix to it.
    """
    eng = _engine()
    # Training mean is exactly 0: a live 0.0 is normal, not absence.
    eng._train_stats = {f"b{i}": {"mean": 0.0, "std": 1.0} for i in range(10)}

    _fill(eng, {f"b{i}": 0.0 for i in range(10)})

    assert eng._drift_absent_count == 0, (
        "a feature whose training mean is zero was classified as absent; the rule must be "
        "'live is zero AND training mean is not', or it exempts real features"
    )


def test_absence_is_reported_loudly_not_swallowed(caplog):
    """Evidence swallowed is evidence nobody has.

    Absence no longer blocks, so the log is the only thing that says the feed is
    degraded. It is an ERROR, not a DEBUG.
    """
    import ml.inference_engine as ie

    eng = _engine()
    eng._train_stats = dict(_TRAIN)

    with caplog.at_level(logging.ERROR, logger=ie.logger.name):
        _fill(eng, dict.fromkeys(_TRAIN, 0.0))

    absent = [r for r in caplog.records if "absent" in r.getMessage().lower()]
    assert absent, "every feature was zero-filled and nothing was logged at ERROR"
    assert any("drift" not in r.getMessage().lower().split("absent")[0] for r in absent), (
        "the absence message should not lead with 'drift' — that is the mislabelling this fixes"
    )


def test_the_status_payload_exposes_the_split():
    """An operator must be able to tell the two apart without reading logs."""
    eng = _engine()
    eng._train_stats = dict(_TRAIN)
    _fill(eng, dict.fromkeys(_TRAIN, 0.0))

    status = eng.drift_status() if hasattr(eng, "drift_status") else {}
    assert status.get("absent_features") == 10, f"absent count missing from status: {status}"
    assert status.get("drifted_features") == 0
