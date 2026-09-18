# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§13: opposing perspectives, recorded claims, and no forced consensus.

## The rule that shapes everything here

    "Do not force artificial consensus."

Every merging function wants to produce an answer. Averaging two confidences,
picking the higher-weighted side, taking the majority — each is one line, each
always returns something, and each destroys the single most valuable output a
multi-agent system can produce: **the finding that the agents do not agree, and
that the evidence does not separate them.**

So `debate()` returns `UNRESOLVED` when the sides are close, and `UNRESOLVED` is
not a weaker `RESOLVED`. It carries both positions and both sets of evidence,
and the caller is expected to put the disagreement in front of a person rather
than to unwrap it into whichever side happened to score higher.

## Weight, not vote

Positions are scored by the weight of their evidence (`ai/debate/evidence.py`),
not by how many agents hold them. Four agents recalling the same unsourced claim
should not outrank one agent with a measured number, and a headcount makes that
outcome inevitable.

## An agent with no evidence has not made an argument

A position with no evidence scores zero and is recorded as `unsupported`. It is
not dropped — an unsupported dissent is still a fact about what the workforce
believes — but it cannot decide anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ai.debate.evidence import Evidence, Weighed, weigh

#: How much stronger one side must be before the debate is called.
#:
#: 1.5× rather than "any margin at all". Two sides within a few percent of each
#: other have not been separated by the evidence, and calling that a resolution
#: is the artificial consensus §13 forbids, wearing a decimal point.
DECISIVE_RATIO = 1.5

#: Below this, the winning side is too weak to call anything even if it leads.
MIN_DECISIVE_WEIGHT = 0.3

#: A debate needs two sides. One stance is a position, and calling it a debate
#: implies an opposing view was sought and found wanting.
MIN_STANCES = 2


@dataclass(frozen=True)
class Position:
    """One agent's stance on the question, and what it is resting on."""

    agent: str
    stance: str
    argument: str
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        if not self.agent.strip():
            raise ValueError("a position needs an agent to attribute it to")
        if not self.stance.strip():
            raise ValueError("a position needs a stance")
        if not self.argument.strip():
            raise ValueError("a position needs an argument a human can read")


@dataclass(frozen=True)
class ScoredPosition:
    position: Position
    weight: float
    weighed_evidence: tuple[Weighed, ...]
    #: True when the position rests on nothing. Recorded, not dropped.
    unsupported: bool
    #: True when everything it rests on is stale or undated.
    all_stale: bool


@dataclass
class DebateResult:
    subject: str
    #: "resolved" or "unresolved". Never "consensus" — a resolved debate is one
    #: where the evidence separated the sides, not one where everybody agreed.
    outcome: str
    #: The leading stance, or None when unresolved.
    leading: str | None
    positions: list[ScoredPosition] = field(default_factory=list)
    #: Why it could not be called, when it could not.
    unresolved_reason: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def resolved(self) -> bool:
        return self.outcome == "resolved"

    def by_stance(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for scored in self.positions:
            totals[scored.position.stance] = totals.get(scored.position.stance, 0.0) + scored.weight
        return totals

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "outcome": self.outcome,
            "leading": self.leading,
            "unresolved_reason": self.unresolved_reason,
            "at": self.at,
            "weights": self.by_stance(),
            "positions": [
                {
                    "agent": s.position.agent,
                    "stance": s.position.stance,
                    "argument": s.position.argument,
                    "weight": s.weight,
                    "unsupported": s.unsupported,
                    "all_stale": s.all_stale,
                    "evidence": [
                        {
                            "claim": w.evidence.claim,
                            "source": w.evidence.source,
                            "quality": w.evidence.quality.value,
                            "weight": w.weight,
                            "stale": w.stale,
                            "unmeasured_age": w.unmeasured_age,
                        }
                        for w in s.weighed_evidence
                    ],
                }
                for s in self.positions
            ],
        }

    def as_prose(self) -> str:
        lines = [f"{self.subject}", ""]
        for scored in sorted(self.positions, key=lambda s: -s.weight):
            note = ""
            if scored.unsupported:
                note = " (no evidence offered)"
            elif scored.all_stale:
                note = " (all evidence stale or undated)"
            lines.append(
                f"  {scored.position.agent} — {scored.position.stance} "
                f"[weight {scored.weight:.2f}]{note}: {scored.position.argument}"
            )
        lines.append("")
        if self.resolved:
            lines.append(f"The evidence favours: {self.leading}.")
        else:
            # Said as a finding, not as a failure. This is often the most
            # valuable thing the workforce can report.
            lines.append(f"Unresolved. {self.unresolved_reason}")
        return "\n".join(lines)


def debate(*, subject: str, positions: list[Position], now: datetime | None = None) -> DebateResult:
    """Score opposing positions and say which the evidence favours — or that it does not.

    Refuses to run on fewer than two distinct stances: a "debate" with one side
    is a position, and dressing it as a debate implies an opposing view was
    sought and found wanting.
    """
    if not positions:
        raise ValueError("cannot hold a debate with no positions")

    scored: list[ScoredPosition] = []
    for position in positions:
        weighed = tuple(weigh(e, now=now) for e in position.evidence)
        total = round(sum(w.weight for w in weighed), 4)
        scored.append(
            ScoredPosition(
                position=position,
                weight=total,
                weighed_evidence=weighed,
                unsupported=not weighed,
                all_stale=bool(weighed) and all(w.stale for w in weighed),
            )
        )

    result = DebateResult(subject=subject, outcome="unresolved", leading=None, positions=scored)

    stances = {p.stance for p in positions}
    if len(stances) < MIN_STANCES:
        result.unresolved_reason = (
            f"Only one stance was offered ({next(iter(stances))}). No opposing perspective was "
            "put, so nothing has been weighed against it."
        )
        return result

    totals = result.by_stance()
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    top_stance, top_weight = ranked[0]
    runner_weight = ranked[1][1]

    if top_weight < MIN_DECISIVE_WEIGHT:
        result.unresolved_reason = (
            f"The strongest side carries a weight of only {top_weight:.2f}. Nothing here rests on "
            "evidence solid or fresh enough to decide on."
        )
        return result

    if runner_weight > 0 and top_weight < runner_weight * DECISIVE_RATIO:
        result.unresolved_reason = (
            f"{top_stance} leads {top_weight:.2f} to {runner_weight:.2f}, which is not a margin. "
            "The evidence does not separate these positions; this needs a person."
        )
        return result

    result.outcome = "resolved"
    result.leading = top_stance
    return result


__all__ = [
    "DECISIVE_RATIO",
    "MIN_DECISIVE_WEIGHT",
    "MIN_STANCES",
    "DebateResult",
    "Position",
    "ScoredPosition",
    "debate",
]
