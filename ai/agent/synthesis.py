# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""One coherent recommendation from several departments. Spec §3 concept 3.

With four departments watching independently, one market event produces four
separate queue entries. An operator at 3am reading "drawdown limit breached",
"broker unavailable", "volatility regime shift" and "broken imports" has to work
out for themselves whether that is one incident or four. The spec's line is "add
a synthesis stage so the queue gets one coherent recommendation, not
disconnected proposals".

## A disagreement is recorded, never averaged

Spec §6 asks for disagreement logging explicitly. If Risk & Compliance says the
exposure is dangerous and Research & Intelligence says the regime is favourable,
the output states both. Averaging them into a comfortable middle is how a system
launders a real warning into a shrug — and on a platform that moves money the
dissent is usually the part worth reading.

## A lone dissenter is never outvoted

Three departments saying "fine" and one saying "critical" is not a 3-1 vote for
fine. The concern survives into the headline. The cost of over-reporting here is
an operator reading one extra line; the cost of under-reporting is a drawdown.
This is the same asymmetry `bounded_severity` encodes for an uncorroborated
model claim, and the same one the invariants take when they fail closed.

## "I could not tell" is not a vote

An `unknown` stance is listed under `unresolved` rather than counted as
agreement. A department that could not get a reading has not endorsed anything,
and treating silence as assent is how a gap becomes a green light.

Like an observation, a synthesis reports and does not act: its proposal carries
no change, and this module never touches the tool bus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Ordered least to most severe, so `max` over this is the escalation rule.
SEVERITY_ORDER = ("info", "warning", "critical")

#: What a department is saying about the subject.
#:
#: `unknown` is first-class and deliberately distinct from `clear`: "I looked
#: and it is fine" and "I could not get a reading" are different facts, and
#: collapsing them is how a blind spot reads as an all-clear.
STANCES = ("concern", "clear", "unknown")


@dataclass(frozen=True)
class Finding:
    """One department's position on one subject."""

    department: str
    stance: str
    severity: str
    summary: str

    def __post_init__(self) -> None:
        if self.stance not in STANCES:
            raise ValueError(f"stance {self.stance!r} is not one of {STANCES}")
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"severity {self.severity!r} is not one of {SEVERITY_ORDER}")
        if not self.summary.strip():
            raise ValueError("a finding needs a summary a human can read")


@dataclass
class Recommendation:
    subject: str
    headline: str
    severity: str
    confidence: float
    contributing: list[str] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def as_proposal(self) -> dict[str, Any]:
        """Render for the same approval queue everything else lands in.

        The disagreement text is part of `reason`, not a separate field, because
        a field an operator has to expand is a field that does not get read at
        3am. If two departments disagree, that sentence is in the body.
        """
        lines = [self.headline, ""]
        for finding in self.findings:
            lines.append(f"  {finding.department} [{finding.stance}/{finding.severity}]: {finding.summary}")
        if self.disagreements:
            lines.extend(["", "Departments disagree:"])
            lines.extend(f"  - {d}" for d in self.disagreements)
        if self.unresolved:
            lines.extend(["", f"No reading from: {', '.join(self.unresolved)}"])

        return {
            "id": f"synthesis-{self.subject}-{datetime.now(UTC).timestamp():.0f}".replace(" ", "-"),
            "title": f"[{self.severity}] {self.subject}",
            # Its own kind, so an operator can tell a merged view from a single
            # department's observation. Like `observation`, deliberately not
            # `repair`/`upgrade`, so it never inherits the superadmin quorum
            # meant for changes that act.
            "kind": "synthesis",
            "scope": self.subject,
            "reason": "\n".join(lines),
            "changes": "None. This is a merged view; no change has been prepared.",
            "evidence_ids": [],
            "rollback_plan": "Not applicable — nothing was changed.",
            "status": "pending",
            "created_by": f"synthesis:{'+'.join(sorted(self.contributing))}",
            "created_at": datetime.now(UTC).isoformat(),
            "severity": self.severity,
            "confidence": self.confidence,
            "disagreements": list(self.disagreements),
        }


def synthesise(*, subject: str, findings: list[Finding]) -> Recommendation:
    """Merge findings about one subject into a single recommendation."""
    if not findings:
        # An empty verdict reads as "nothing is wrong", which is a claim nobody
        # made. Refusing is the honest answer.
        raise ValueError("cannot synthesise a recommendation from no findings")

    concerns = [f for f in findings if f.stance == "concern"]
    clears = [f for f in findings if f.stance == "clear"]
    unknowns = [f for f in findings if f.stance == "unknown"]

    # The escalation rule: the highest severity among the CONCERNS wins, not the
    # average and not the majority. A lone dissenter is not outvoted.
    if concerns:
        worst = max(concerns, key=lambda f: SEVERITY_ORDER.index(f.severity))
        severity = worst.severity
        headline = f"{worst.department}: {worst.summary}"
    else:
        severity = max((f.severity for f in findings), key=SEVERITY_ORDER.index)
        headline = f"No department raised a concern about {subject}."

    disagreements: list[str] = []
    if concerns and clears:
        for concern in concerns:
            for clear in clears:
                disagreements.append(
                    f"{concern.department} reports a concern ({concern.severity}) — "
                    f"{concern.summary} — while {clear.department} reports it clear: {clear.summary}"
                )

    # Confidence is a statement about how much the departments agree, not about
    # how bad the situation is. A split verdict is genuinely less certain and
    # has to say so rather than presenting one side with full confidence.
    positioned = len(concerns) + len(clears)
    if positioned == 0:
        confidence = 0.0
    else:
        majority = max(len(concerns), len(clears))
        confidence = majority / positioned
    # Every department that could not get a reading is a gap, not a vote — so it
    # lowers confidence without shifting the verdict either way.
    if unknowns:
        confidence *= positioned / (positioned + len(unknowns)) if positioned else 0.0

    return Recommendation(
        subject=subject,
        headline=headline,
        severity=severity,
        confidence=round(confidence, 3),
        contributing=[f.department for f in findings],
        disagreements=disagreements,
        unresolved=[f.department for f in unknowns],
        findings=list(findings),
    )


def group_observations(observations: list[dict[str, Any]], *, window_s: float = 300.0) -> list[list[dict[str, Any]]]:
    """Cluster observations that are probably about one incident.

    Time proximity, because that is the signal actually available: four
    departments noticing something within five minutes of each other is one
    event far more often than four. Deliberately not clever — a wrong merge
    hides a second incident inside the first, so the rule stays one an operator
    can predict.
    """
    if not observations:
        return []

    ordered = sorted(observations, key=lambda o: float(o.get("at") or 0.0))
    groups: list[list[dict[str, Any]]] = [[ordered[0]]]
    for observation in ordered[1:]:
        previous = float(groups[-1][-1].get("at") or 0.0)
        if float(observation.get("at") or 0.0) - previous <= window_s:
            groups[-1].append(observation)
        else:
            groups.append([observation])
    return groups


__all__ = [
    "SEVERITY_ORDER",
    "STANCES",
    "Finding",
    "Recommendation",
    "group_observations",
    "synthesise",
]
