# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What the spatial system knows, and — the part that matters — what it does not.

A 3D system produces convincing artifacts. A generated house looks built; a
generated car looks engineered; a solver returns a number to four decimal
places. Every one of those is a value nothing verified, presented as though
something had. That is the defect class this repository has spent a programme
removing, and here it has the largest blast radius it has ever had, because the
output is *beautiful* and beauty reads as correctness.

So nothing in the spatial system reports a bare result. Every claim carries the
rung it has earned on this ladder:

    NOT_ASSESSED            nobody looked
    VISUALIZED              it has been drawn. A claim about pixels, nothing more
    PROCEDURALLY_GENERATED  a rule produced it. Self-consistent, unchecked
    ESTIMATED               a heuristic produced a number
    SIMULATED               a solver ran. True inside its own assumptions
    VALIDATED               checked against acceptance criteria in this system
    EXTERNALLY_VERIFIED     confirmed outside this system — measurement, standard
    HUMAN_APPROVED          a named person accepted responsibility

## The four rules

**1. A claim rises only on evidence that supports the rung.** This is
AOS-EVID-028, Epistemic Monotonicity, which the conformance register recorded as
ABSENT. A simulation run is evidence for SIMULATED; it is not evidence that
anyone approved anything. Raising without evidence is refused, not logged.

**2. A claim may always fall, and needs no evidence to.** Learning something is
worse than believed must never require a permit. A system that made downgrades
expensive would sit on stale assurance, which is the failure this module exists
to prevent, arrived at from the other side.

**3. A composite is the MINIMUM of its parts.** Not the mean, not the best, not
"mostly simulated". A structural analysis that passed does not redeem a building
code box nobody ticked: the design as a whole is exactly as sound as the weakest
thing in it. This single rule is what stops "the render finished" from becoming
"the house is safe to build".

**4. Readiness is never inferred from assurance, however high.** EXTERNALLY
VERIFIED is not approval. Approval is a person, named, on every required aspect.
No quantity of solver time substitutes for it.

## And the floor

An aspect nobody assessed is `NOT_ASSESSED` **and appears in the report**. It is
never omitted, because a missing row reads as a row with nothing wrong — Rule 2
of this codebase, an unmeasured value is absent and never best-case, applied to
a domain where the unmeasured thing is whether a building stands up.

Pure and side-effect free: no solver, no renderer, no I/O. The predicates in
`invariants/spatial.py` enforce these same rules at the points where a spatial
result crosses into a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

__all__ = [
    "Assurance",
    "AssuranceRefused",
    "Claim",
    "Evidence",
    "ReadinessReport",
    "overall",
    "raise_to",
    "readiness_report",
]


class Assurance(IntEnum):
    """The ladder. Ordered, so `min()` over parts is rule 3 directly.

    `IntEnum` rather than `Enum` because the ordering IS the semantics here, and
    a comparison that silently failed would turn rule 3 into a coin toss.
    """

    NOT_ASSESSED = 0
    VISUALIZED = 1
    PROCEDURALLY_GENERATED = 2
    ESTIMATED = 3
    SIMULATED = 4
    VALIDATED = 5
    EXTERNALLY_VERIFIED = 6
    HUMAN_APPROVED = 7


class AssuranceRefused(ValueError):
    """A claim tried to rise further than its evidence allows.

    Raised rather than returned because there is no sensible degraded answer: a
    caller that ignored a returned failure would carry on holding a claim it has
    not earned, which is the entire failure mode.
    """


@dataclass(frozen=True)
class Evidence:
    """Why a claim may occupy a rung.

    `supports` is the HIGHEST rung this evidence can justify — a finite-element
    run supports SIMULATED no matter how confident its report reads.
    """

    kind: str
    reference: str
    supports: Assurance


@dataclass(frozen=True)
class Claim:
    """One assessable aspect of a spatial artifact, and what is known about it."""

    aspect: str
    assurance: Assurance = Assurance.NOT_ASSESSED
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReadinessReport:
    """Whether the thing may be built, and everything standing in the way.

    `by_aspect` covers every REQUIRED aspect, including the ones nobody
    assessed. That completeness is the point: a report that listed only what was
    examined would get shorter as the work got sloppier.
    """

    ready: bool
    overall: Assurance
    by_aspect: dict[str, Assurance]
    blocking: tuple[str, ...]


def raise_to(claim: Claim, target: Assurance, evidence: Evidence | None) -> Claim:
    """Move `claim` to `target`, refusing an unearned rise (rules 1 and 2)."""
    if target <= claim.assurance:
        # Falling, or standing still. Always permitted, no evidence required.
        return Claim(
            aspect=claim.aspect,
            assurance=target,
            evidence=claim.evidence + ((evidence,) if evidence is not None else ()),
        )

    if evidence is None:
        raise AssuranceRefused(
            f"{claim.aspect!r}: cannot rise from {claim.assurance.name} to {target.name} with no evidence"
        )
    if evidence.supports < target:
        raise AssuranceRefused(
            f"{claim.aspect!r}: {evidence.kind} {evidence.reference!r} supports at most "
            f"{evidence.supports.name}, which does not reach {target.name}"
        )
    return Claim(aspect=claim.aspect, assurance=target, evidence=claim.evidence + (evidence,))


def overall(claims: object) -> Assurance:
    """Rule 3 — the weakest part governs.

    Empty is NOT_ASSESSED rather than an error or a high value: a design with no
    claims has been assessed in no respect, and that is a fact worth reporting
    rather than a condition worth crashing on.
    """
    rungs = [c.assurance for c in claims]  # type: ignore[attr-defined]
    return min(rungs) if rungs else Assurance.NOT_ASSESSED


def readiness_report(claims: object, required: tuple[str, ...]) -> ReadinessReport:
    """Rule 4 — readiness is granted, never deduced.

    Every required aspect must be HUMAN_APPROVED. A design that is externally
    verified throughout is still not ready, because verification says the thing
    is as described and approval says somebody is willing to build it.
    """
    held = {c.aspect: c.assurance for c in claims}  # type: ignore[attr-defined]
    by_aspect = {aspect: held.get(aspect, Assurance.NOT_ASSESSED) for aspect in required}
    blocking = tuple(a for a, rung in by_aspect.items() if rung < Assurance.HUMAN_APPROVED)
    return ReadinessReport(
        ready=not blocking,
        overall=min(by_aspect.values()) if by_aspect else Assurance.NOT_ASSESSED,
        by_aspect=by_aspect,
        blocking=blocking,
    )
