# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§5: state uncertainty honestly — which means checking it.

A confidence is a claim about the future: "seven times in ten, this holds." The
only thing that makes it more than a mood is a record of how those claims turned
out, and this is that record.

## An unchecked confidence is reported as unchecked

Not as a low confidence, not as a caveat in small print — as `calibrated=False`
with the count of resolved predictions, which is usually zero. Reporting 62% as
though somebody had verified it is precisely the fake-precision failure §22
exists to stop, and it is more dangerous here than on a dashboard because a
figure attached to an argument gets sized against.

## Calibration annotates a confidence; it never rewrites one

The tempting move is to scale a known-overconfident agent's number down before
showing it. That is worse than the disease: the author put their name to 90%,
the reader sees 60%, and neither of them can explain the number on the screen.
So `assess` reports what was stated, what was observed, and the gap — and leaves
the stated figure exactly as its author wrote it.

## Twenty resolved predictions before it claims anything

Three right in a row is a coincidence. The threshold is a judgement, and the
honest thing is to make it explicit and report the sample size beside every
verdict, so a reader can disagree with the threshold rather than with a number
that hides it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Resolved predictions needed before a calibration verdict means anything.
MIN_SAMPLE = 20

#: How far the observed rate may sit from the stated one and still count as
#: calibrated. Ten points, because a tighter band would report noise.
TOLERANCE = 0.10

#: Predictions kept per agent. A process running for weeks must not hold every
#: prediction it ever made.
MAX_HISTORY = 500


@dataclass
class _Prediction:
    stated: float
    at: str
    correct: bool | None = None


@dataclass(frozen=True)
class CalibrationReport:
    agent: str
    #: What the author said. Returned unchanged, always.
    stated: float
    #: How often predictions in this band actually held, or None when unchecked.
    observed: float | None
    resolved: int
    calibrated: bool
    note: str
    meta: dict[str, Any] = field(default_factory=dict)


_LOCK = threading.Lock()
_HISTORY: dict[str, dict[str, _Prediction]] = {}


def record(agent: str, *, key: str, stated: float, at: datetime | None = None) -> bool:
    """Note that `agent` claimed `stated` confidence about `key`.

    Returns False when this key is already recorded for this agent. Overwriting
    would let a second, luckier prediction replace the one that was actually
    made.
    """
    if not 0.0 <= stated <= 1.0:
        raise ValueError(f"confidence {stated} is not a probability")
    with _LOCK:
        agent_history = _HISTORY.setdefault(agent, {})
        if key in agent_history:
            return False
        agent_history[key] = _Prediction(stated=stated, at=(at or datetime.now(UTC)).isoformat())
        if len(agent_history) > MAX_HISTORY:
            # Oldest first. Insertion order is the order they were made.
            for stale in list(agent_history)[: len(agent_history) - MAX_HISTORY]:
                agent_history.pop(stale, None)
        return True


def resolve(agent: str, *, key: str, correct: bool) -> bool:
    """Record how a prediction turned out. False if there was nothing to resolve.

    A prediction resolves once. Resolving twice would let one outcome count
    twice toward an agent's apparent accuracy, and the second call is usually a
    retry rather than a second fact.
    """
    with _LOCK:
        prediction = _HISTORY.get(agent, {}).get(key)
        if prediction is None or prediction.correct is not None:
            return False
        prediction.correct = correct
        return True


def assess(agent: str, *, stated: float) -> CalibrationReport:
    """How this agent's stated confidences have actually held up."""
    with _LOCK:
        history = list(_HISTORY.get(agent, {}).values())

    # Only predictions in the same confidence band. An agent's accuracy at 90%
    # says nothing about its accuracy at 55%, and pooling them would hide both.
    band = [p for p in history if p.correct is not None and abs(p.stated - stated) <= TOLERANCE]
    resolved = len(band)

    if resolved < MIN_SAMPLE:
        return CalibrationReport(
            agent=agent,
            stated=stated,
            observed=None,
            resolved=resolved,
            calibrated=False,
            note=(
                f"This confidence has not been checked: {resolved} resolved prediction(s) near "
                f"{stated:.0%} from {agent}, and {MIN_SAMPLE} are needed before a rate means anything. "
                "Read it as the author's judgement, not as a measured frequency."
            ),
        )

    observed = sum(1 for p in band if p.correct) / resolved
    gap = observed - stated

    if gap < -TOLERANCE:
        verdict = (
            f"{agent} is overconfident in this range: it said about {stated:.0%} and was right "
            f"{observed:.0%} of the time across {resolved} resolved predictions."
        )
    elif gap > TOLERANCE:
        verdict = (
            f"{agent} is underconfident in this range: it said about {stated:.0%} and was right "
            f"{observed:.0%} of the time across {resolved} resolved predictions."
        )
    else:
        verdict = (
            f"{agent} is well calibrated in this range: {observed:.0%} observed against {stated:.0%} "
            f"stated, over {resolved} resolved predictions."
        )

    return CalibrationReport(
        agent=agent,
        # Unchanged. The author's figure is the author's figure.
        stated=stated,
        observed=round(observed, 4),
        resolved=resolved,
        calibrated=True,
        note=verdict,
    )


def summary() -> dict[str, Any]:
    """Every agent's record, for the observability surface."""
    with _LOCK:
        return {
            agent: {
                "recorded": len(predictions),
                "resolved": sum(1 for p in predictions.values() if p.correct is not None),
                "correct": sum(1 for p in predictions.values() if p.correct),
            }
            for agent, predictions in _HISTORY.items()
        }


def reset_for_testing() -> None:
    with _LOCK:
        _HISTORY.clear()


__all__ = [
    "MAX_HISTORY",
    "MIN_SAMPLE",
    "TOLERANCE",
    "CalibrationReport",
    "assess",
    "record",
    "reset_for_testing",
    "resolve",
    "summary",
]
