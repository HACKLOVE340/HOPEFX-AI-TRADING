# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§20: a trade thesis, its counter-thesis, and an explanation somebody can audit.

This is §15's structure applied to the one subject where getting it wrong costs
money, plus the constraint the rest of this platform already lives under:

    **An analysis is not a permission.**

`TradeAnalysis` carries no order, no size and no side that anything can execute.
It is a document. Execution stays where it has always been — behind
`risk/manager.py`'s pre-trade gate and `ai/tools/bus.py`'s fail-closed permission
check — and this module cannot reach either. A structure that produced something
an order router would accept would be one refactor away from an AI placing
trades because its own argument convinced it.

## Why the counter-thesis is not optional here

A trade thesis without one is a pitch. The section this implements asks for
both, and the field is required by `Reasoning`, so an analysis missing it fails
to construct rather than shipping as a confident half-argument.

## Confidence has to say where it came from

`analyse_trade` derives confidence from the weight of the evidence on each side
and states that derivation in `confidence_basis`. It is not the model's feeling
about the trade; it is a function of what was measured and how fresh it was, and
a reader can disagree with it by disagreeing with the inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ai.debate.evidence import Evidence, weigh
from ai.debate.reasoning import Reasoning, ReasoningIncomplete
from ai.debate.session import DebateResult, Position, debate


@dataclass(frozen=True)
class TradeAnalysis:
    """A structured argument about an instrument. Not an instruction."""

    symbol: str
    reasoning: Reasoning
    #: The scored disagreement behind it, kept so an operator can see the
    #: competing claims rather than only the conclusion (§13).
    debate: DebateResult

    @property
    def actionable(self) -> bool:
        """Always False.

        Present as a field rather than as an omission so that anything reaching
        for it gets a definite `False` instead of an `AttributeError` that a
        `getattr(..., True)` somewhere would paper over.
        """
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "actionable": False,
            "reasoning": self.reasoning.as_dict(),
            "debate": self.debate.as_dict(),
        }

    def explain(self) -> str:
        """§20 explainability: the whole argument, in the order it was built."""
        return f"{self.reasoning.as_prose()}\n\n--- how this was reached ---\n{self.debate.as_prose()}"


def analyse_trade(
    *,
    symbol: str,
    thesis: str,
    counter_thesis: str,
    supporting: list[Evidence],
    opposing: list[Evidence],
    assumptions: list[str] | None = None,
    missing: list[str] | None = None,
    what_would_change_it: list[str] | None = None,
    risks: list[str] | None = None,
    alternatives: list[str] | None = None,
    now: datetime | None = None,
) -> TradeAnalysis:
    """Build the argument, both sides, with a confidence derived from the evidence."""
    # Checked before the debate is held, not after. Building the debate first
    # raised `ValueError: a position needs an argument` from `Position` — a true
    # statement about the wrong thing. The caller omitted a counter-thesis, and
    # `ReasoningIncomplete` is what names that, in §15's own vocabulary.
    missing: list[str] = []
    if not thesis.strip():
        missing.append("thesis")
    if not counter_thesis.strip():
        missing.append("counter_thesis")
    if missing:
        raise ReasoningIncomplete(tuple(missing))

    held = debate(
        subject=f"{symbol}: {thesis}",
        positions=[
            Position(agent="thesis", stance="for", argument=thesis, evidence=tuple(supporting)),
            Position(agent="counter", stance="against", argument=counter_thesis, evidence=tuple(opposing)),
        ],
        now=now,
    )

    for_weight = round(sum(weigh(e, now=now).weight for e in supporting), 4)
    against_weight = round(sum(weigh(e, now=now).weight for e in opposing), 4)
    total = for_weight + against_weight

    if total <= 0:
        # No evidence on either side. A confidence here would be a number
        # describing nothing, so there is none, and the reason says so.
        confidence: float | None = None
        basis = ""
    else:
        confidence = round(for_weight / total, 3)
        basis = (
            f"Derived from evidence weight: {for_weight:.2f} for against {against_weight:.2f} "
            "against, each item scored by source quality and how recently it was observed. "
            "This is not a probability of the trade working."
        )

    # Always stated, never inferred into silence: an unresolved debate must
    # reach the reader of the reasoning too, not only the reader of the debate.
    derived_missing = list(missing or [])
    if not held.resolved:
        derived_missing.append(f"The evidence does not separate the two sides. {held.unresolved_reason}")

    derived_change = list(what_would_change_it or [])
    if not derived_change:
        # Required by `Reasoning`. Rather than fabricating something specific,
        # this says the honest general thing and points at the weakest input.
        weakest = min(
            (weigh(e, now=now) for e in [*supporting, *opposing]),
            key=lambda w: w.weight,
            default=None,
        )
        derived_change.append(
            f"A fresher or better-sourced reading than {weakest.evidence.source!r}, "
            "which is currently the weakest input on either side."
            if weakest is not None
            else "Any evidence at all — there is none on either side."
        )

    reasoning = Reasoning(
        subject=f"{symbol} — trade analysis",
        thesis=thesis,
        counter_thesis=counter_thesis,
        assumptions=tuple(assumptions or []),
        missing_information=tuple(derived_missing),
        evidence=tuple(supporting),
        counter_evidence=tuple(opposing),
        confidence=confidence,
        confidence_basis=basis,
        what_would_change_it=tuple(derived_change),
        risks=tuple(risks or []),
        alternatives=tuple(alternatives or ["Do nothing and wait for a better-supported setup."]),
        meta={"symbol": symbol},
    )
    return TradeAnalysis(symbol=symbol, reasoning=reasoning, debate=held)


__all__ = ["TradeAnalysis", "analyse_trade"]
