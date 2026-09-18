# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The Decision Ledger — Group 3 Chapter 7.

Where an ADR records a *design* decision by a human (`scripts/adr.py`), this
records an *operational* decision by the system: which model was chosen, which
agent was trusted, which recommendation was accepted, which action was refused.

## Why one schema rather than better per-component logging

The components already record their own decisions in their own shapes —
`ai/gateway/audit.py` has model calls, `ai/improve/proposal.py` has proposed
changes, approvals live in pull requests — and that is precisely why nobody can
answer "what did the platform decide today?". One schema across all actors is
what turns per-component logging into a ledger.

## Refusals are first-class entries, not absences

The property that makes this worth having. A ledger of actions *taken* cannot
distinguish a system that was never asked from one that refused, and on a
governed platform the refusals are the evidence that governance worked — the
`data_quality:unmeasured` refusals from MASTER_OUTSTANDING §E12 are the clearest
example in this repository.

A refusal must name the control that produced it. "Something said no" is not
evidence, and a refusal whose control is unnamed cannot be checked against the
control's own logs — which is Chapter 7's stated KPI: refusals recorded versus
refusals observed, where a gap means the ledger is missing entries.

## A prediction is required, because Chapter 8 depends on it

Without a stated expectation, an observed outcome has nothing to be compared
against and "learning" degrades into narrative. A decision therefore cannot be
recorded without saying what it expects. A *refusal* needs none: nothing
happened, so there is no outcome to compare.

## Unmeasured stays unmeasured

Confidence is `None` when nobody stated one — never 0.5 — and its calibration
class is `None` with it. A governance record is the worst possible place to
reintroduce the defect this repository has spent the most time removing.

## One option is allowed here, unlike an ADR

`scripts/adr.py` refuses a record with a single option, because a human weighing
one path is writing justification afterwards. An automated router legitimately
has one candidate when the others are unavailable, and demanding a second would
make the ledger describe a choice nobody had.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any, Final

from ai.guardrails.output import scan_output
from ai.policy import roles

logger = logging.getLogger(__name__)

#: The tiers Group 2 Chapter 10 defines, imported rather than restated. A second
#: list of tier names is a list that drifts, and the drift is invisible until a
#: record claims an authority nothing enforces.
AUTHORITY_TIERS: Final[tuple[str, ...]] = (roles.VIEW, roles.PROPOSE, roles.APPROVE, roles.EXECUTE)

#: Who decided. Kept small on purpose: three kinds cover the spec's scope and a
#: free-text field would make "what did agents decide today?" unanswerable.
ACTOR_KINDS: Final[tuple[str, ...]] = ("human", "agent", "system")

#: Entries kept in process. The durable record is the installed backend; this is
#: a working window, the same shape `ai/memory/store.py` uses and for the same
#: reason — a store that only grows is a liability on a platform that moves money.
MAX_ENTRIES: Final = 2000

_ENTRIES: deque[Decision] = deque(maxlen=MAX_ENTRIES)  # type: ignore[name-defined]
_BACKEND: Any | None = None


@dataclasses.dataclass(frozen=True)
class Decision:
    """One decision, or one refusal, by any actor.

    Frozen: an append-only ledger whose entries can be edited is a ledger of
    what we currently believe was decided. The outcome is attached by
    `ai.ledger.outcomes`, which replaces the entry rather than mutating it.
    """

    id: str
    at: str
    actor: str
    actor_kind: str
    authority_tier: str
    context: str
    options: tuple[str, ...]
    chosen: str | None
    prediction: str | None
    evidence: dict[str, Any]
    confidence: float | None
    calibration_class: str | None
    refused: bool
    refused_by: str | None
    outcome: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def set_backend(backend: Any | None) -> None:
    """Install (or remove) the durable sink.

    None keeps everything process-local, which is correct on a dev box and
    honest about it — `backend_is_durable()` says which, rather than letting a
    caller assume.
    """
    global _BACKEND
    _BACKEND = backend


def backend_is_durable() -> bool:
    return _BACKEND is not None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check_tier(tier: str) -> str:
    if tier not in AUTHORITY_TIERS:
        raise ValueError(
            f"{tier!r} is not an authority tier; expected one of {AUTHORITY_TIERS}. "
            "A typo must not create a tier nothing enforces."
        )
    return tier


def _check_actor_kind(kind: str) -> str:
    if kind not in ACTOR_KINDS:
        raise ValueError(f"{kind!r} is not an actor kind; expected one of {ACTOR_KINDS}")
    return kind


def _check_options(options: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    values = tuple(str(o) for o in options)
    if not values:
        raise ValueError("a decision needs at least one option; a record with none says nothing about how it decided")
    return values


def _check_confidence(confidence: float | None) -> float | None:
    if confidence is None:
        return None
    value = float(confidence)
    if math.isnan(value) or math.isinf(value):
        # Finiteness before the comparison — NaN passes every one of them.
        raise ValueError("confidence must be a finite number; NaN and infinity are not confidences")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"confidence {value} is outside [0, 1]")
    return value


def _screen(*values: Any) -> None:
    """Refuse anything carrying a credential, before it becomes durable.

    The ledger outlives the request that produced it, so a token written here
    survives the incident that leaked it. Same reasoning, same scanner, as
    `ai/memory/store.py`.
    """
    scan_output(json.dumps(values, sort_keys=True, default=str))


def _append(entry: Decision) -> Decision:
    _ENTRIES.append(entry)
    if _BACKEND is not None:
        try:
            _BACKEND.write(entry.to_dict())
        except Exception as exc:  # pragma: no cover - backend-specific
            # Loud, not silent: a ledger that lost an entry and said nothing is
            # a ledger whose coverage KPI is a fiction.
            logger.error("decision ledger: durable write FAILED for %s: %s", entry.id, exc)
    return entry


def record(
    *,
    actor: str,
    actor_kind: str,
    authority_tier: str,
    context: str,
    options: tuple[str, ...] | list[str],
    chosen: str,
    prediction: str,
    evidence: dict[str, Any] | None = None,
    confidence: float | None = None,
) -> Decision:
    """Record a decision that was taken.

    Raises rather than returning a sentinel: a malformed governance record that
    silently becomes a slightly-wrong one is the failure mode this whole chapter
    exists to prevent.
    """
    _check_actor_kind(actor_kind)
    _check_tier(authority_tier)
    values = _check_options(options)
    confidence = _check_confidence(confidence)

    if not str(prediction).strip():
        raise ValueError(
            "a decision needs a stated prediction; without one an observed outcome has nothing to be "
            "compared against and learning degrades into narrative (Group 3 Ch 8)"
        )
    if chosen not in values:
        raise ValueError(
            f"the chosen option {chosen!r} is not among the options {values}; a record saying the system "
            "picked something it never considered is a false account of how it decided"
        )

    _screen(actor, context, values, chosen, prediction, evidence)

    calibration_class = _calibration_class(actor, confidence)
    return _append(
        Decision(
            id=uuid.uuid4().hex,
            at=_now(),
            actor=actor,
            actor_kind=actor_kind,
            authority_tier=authority_tier,
            context=context,
            options=values,
            chosen=chosen,
            prediction=str(prediction),
            evidence=dict(evidence or {}),
            confidence=confidence,
            calibration_class=calibration_class,
            refused=False,
            refused_by=None,
        )
    )


def refuse(
    *,
    actor: str,
    actor_kind: str,
    authority_tier: str,
    context: str,
    options: tuple[str, ...] | list[str],
    by: str,
    evidence: dict[str, Any] | None = None,
) -> Decision:
    """Record that an action was refused, and by which control.

    A first-class entry. The alternative — an absence — cannot be told apart
    from never having been asked, and the refusals are the evidence that
    governance worked at all.
    """
    _check_actor_kind(actor_kind)
    _check_tier(authority_tier)
    values = _check_options(options)

    if not str(by).strip():
        raise ValueError(
            "a refusal must name the control that produced it; 'something said no' cannot be checked "
            "against that control's own logs, which is how a missing entry is detected"
        )

    _screen(actor, context, values, by, evidence)

    return _append(
        Decision(
            id=uuid.uuid4().hex,
            at=_now(),
            actor=actor,
            actor_kind=actor_kind,
            authority_tier=authority_tier,
            context=context,
            options=values,
            chosen=None,
            prediction=None,
            evidence=dict(evidence or {}),
            confidence=None,
            calibration_class=None,
            refused=True,
            refused_by=str(by).strip(),
        )
    )


def _calibration_class(actor: str, confidence: float | None) -> str | None:
    """What this actor's stated confidence has historically been worth.

    None when no confidence was stated — an unmeasured value is absent, not
    average. Delegated to `ai/core/calibration.py` rather than reimplemented,
    because a second notion of calibration is a second answer to the same
    question.
    """
    if confidence is None:
        return None
    try:
        from ai.core import calibration

        report = calibration.assess(actor, stated=confidence)
        return getattr(report, "calibration_class", None) or getattr(report, "verdict", None) or "unresolved"
    except Exception:  # pragma: no cover - calibration is advisory here
        return "unresolved"


def entries(*, limit: int = 200, refused_only: bool = False) -> list[Decision]:
    """Newest last. A copy, because a caller holding the deque could clear it."""
    rows = [e for e in _ENTRIES if (e.refused or not refused_only)]
    return list(rows)[-max(0, limit) :]


def get(decision_id: str) -> Decision | None:
    for entry in _ENTRIES:
        if entry.id == decision_id:
            return entry
    return None


def _replace(entry: Decision) -> None:
    """Swap an entry for an updated copy, preserving order.

    Used only by `ai.ledger.outcomes` to attach an outcome. Frozen entries mean
    this is a replacement rather than a mutation, and the replacement is
    append-only in spirit: nothing already recorded about the decision changes.
    """
    for index, existing in enumerate(_ENTRIES):
        if existing.id == entry.id:
            _ENTRIES[index] = entry
            return
    raise KeyError(entry.id)


def summary() -> dict[str, Any]:
    total = len(_ENTRIES)
    refused = sum(1 for e in _ENTRIES if e.refused)
    with_outcome = sum(1 for e in _ENTRIES if e.outcome is not None)
    decided = total - refused
    return {
        "total": total,
        "decided": decided,
        "refused": refused,
        "with_outcome": with_outcome,
        # Chapter 7's KPI. Reported as a fraction of DECIDED entries, because a
        # refusal has no outcome to attach and counting it as missing one would
        # make governance look like a gap.
        "outcome_coverage": (with_outcome / decided) if decided else None,
        "durable": backend_is_durable(),
    }


def reset_for_testing() -> None:
    _ENTRIES.clear()
