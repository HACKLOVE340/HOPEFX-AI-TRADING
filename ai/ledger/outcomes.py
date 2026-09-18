# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Outcome and failure memory — Group 3 Chapter 8.

    decision ──► prediction ──► action ──► observed outcome ──► accuracy ──► lesson

Chapter 8 exists to make the platform *experienced* rather than merely
knowledgeable. `ai/ledger/decisions.py` already refuses a decision that states
no prediction; this is the half that uses it.

## An outcome is attached once, and never revised

A record whose outcome can be rewritten is one that eventually agrees with
whoever looked last, and learning from it is learning from a retelling. The
decision itself is never touched: attaching an outcome replaces the frozen entry
with a copy carrying an extra field, and every field already recorded about the
decision is identical.

## A refusal has no outcome

Nothing was done, so there is nothing to observe. Scoring a refusal as a wrong
call is exactly backwards — it would teach a system to refuse less, which is the
opposite of what the refusals in this ledger are evidence of.

## Accuracy is stated, not inferred

`held` is a required argument. Comparing a free-text prediction against a
free-text observation is not a measurement, and a module that produced a number
from that comparison would be manufacturing exactly the kind of unmeasured
figure the rest of this work has been removing. What this guarantees is that the
question was ASKED.

## Failure memory is not a log

Five questions, all required. The third — how was it detected? — is the one
usually skipped and the most valuable: a failure found by a customer and one
found by a test are the same failure with very different lessons, and only the
answer to that question distinguishes them.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any, Final

from ai.guardrails.output import scan_output
from ai.ledger import decisions

logger = logging.getLogger(__name__)

MAX_FAILURES: Final = 500

_FAILURES: deque[Failure] = deque(maxlen=MAX_FAILURES)  # type: ignore[name-defined]

#: The five questions, and the reason each is required. Kept as data so the
#: refusal can quote the reason rather than name a field, which is the
#: difference between a message that teaches and one that annoys.
_QUESTIONS: Final[dict[str, str]] = {
    "what": "what failed — the observable, without which the entry describes nothing",
    "why": "why it failed — the cause, not the symptom; a symptom recurs under a new name",
    "detected": (
        "how it was detected — the question usually skipped and the most valuable, because it reveals "
        "whether detection was luck: a failure found by a customer and one found by a test are the same "
        "failure with very different lessons"
    ),
    "fixed": "how it was fixed — the repair, so the next reader can tell whether it still applies",
    "prevented": "how recurrence is prevented — the control added, and its injection evidence",
}


@dataclasses.dataclass(frozen=True)
class Failure:
    id: str
    at: str
    what: str
    why: str
    detected: str
    fixed: str
    prevented: str
    decision_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def observe(
    decision_id: str,
    *,
    observed: str,
    held: bool,
    lesson: str = "",
) -> dict[str, Any]:
    """Attach what actually happened to a decision that was taken.

    `held` says whether the stated prediction turned out to be right. It is
    required and it is a boolean, because the alternative — reading two pieces
    of prose and producing a number — is a fabricated measurement.
    """
    entry = decisions.get(decision_id)
    if entry is None:
        raise KeyError(f"no decision {decision_id!r} in the ledger")
    if entry.refused:
        raise ValueError(
            f"{decision_id} is a refusal, and a refusal has no outcome: nothing was done, so there is "
            "nothing to observe. Scoring it would teach the system to refuse less."
        )
    if entry.outcome is not None:
        raise ValueError(
            f"{decision_id} already has an outcome; it is attached once. A record whose outcome can be "
            "revised is one that agrees with whoever looked last."
        )

    scan_output(f"{observed} {lesson}")

    outcome = {
        "observed": str(observed),
        "held": bool(held),
        # Carried so the pair reads from one row: "what did we expect, and what
        # happened" should not need a second lookup.
        "predicted": entry.prediction,
        "lesson": str(lesson),
        "at": datetime.now(UTC).isoformat(),
    }
    decisions._replace(dataclasses.replace(entry, outcome=outcome))

    _resolve_calibration(entry, held=held)
    return outcome


def _resolve_calibration(entry: decisions.Decision, *, held: bool) -> None:
    """Close the loop `ai/core/calibration.py` was built for and never given.

    That module has `record` and `resolve`. Without an outcome linkage nothing
    ever called `resolve`, so every stated confidence stayed unscored and
    `assess` had nothing to assess — a measurement apparatus with no inputs,
    which reads as working.
    """
    if entry.confidence is None:
        return
    try:
        from ai.core import calibration

        calibration.record(entry.actor, key=entry.id, stated=entry.confidence)
        calibration.resolve(entry.actor, key=entry.id, correct=held)
    except Exception as exc:  # pragma: no cover - advisory path
        logger.warning("ledger: could not resolve calibration for %s: %s", entry.id, exc)


def record_failure(
    *,
    what: str,
    why: str,
    detected: str,
    fixed: str,
    prevented: str,
    decision_id: str | None = None,
) -> Failure:
    """One failure, answered five ways. Not a log entry."""
    given = {"what": what, "why": why, "detected": detected, "fixed": fixed, "prevented": prevented}
    for field, reason in _QUESTIONS.items():
        if not str(given[field]).strip():
            raise ValueError(f"{field}: {reason}")

    if decision_id is not None and decisions.get(decision_id) is None:
        raise KeyError(f"no decision {decision_id!r} to attach this failure to")

    scan_output(" ".join(str(v) for v in given.values()))

    failure = Failure(
        id=uuid.uuid4().hex,
        at=datetime.now(UTC).isoformat(),
        what=str(what),
        why=str(why),
        detected=str(detected),
        fixed=str(fixed),
        prevented=str(prevented),
        decision_id=decision_id,
    )
    _FAILURES.append(failure)
    return failure


def failures(*, limit: int = 100) -> list[Failure]:
    return list(_FAILURES)[-max(0, limit) :]


def lessons(*, limit: int = 100) -> list[dict[str, Any]]:
    """Every lesson recorded, from both halves of Chapter 8.

    Outcomes carry a lesson when the observer wrote one; failures carry the
    prevention, which is the same thing at a different scale. Reading them
    together is the point — a lesson filed in two places is a lesson nobody
    finds.
    """
    out: list[dict[str, Any]] = []
    for entry in decisions.entries(limit=10_000):
        if entry.outcome and entry.outcome.get("lesson"):
            out.append(
                {
                    "source": "outcome",
                    "at": entry.outcome["at"],
                    "lesson": entry.outcome["lesson"],
                    "held": entry.outcome["held"],
                    "decision_id": entry.id,
                }
            )
    for failure in _FAILURES:
        out.append(
            {
                "source": "failure",
                "at": failure.at,
                "lesson": failure.prevented,
                "held": False,
                "decision_id": failure.decision_id,
            }
        )
    out.sort(key=lambda row: row["at"])
    return out[-max(0, limit) :]


def reset_for_testing() -> None:
    _FAILURES.clear()
