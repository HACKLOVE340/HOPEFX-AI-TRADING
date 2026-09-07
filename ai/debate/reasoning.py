# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§15: the eight parts a consequential answer has to have.

    State the thesis. State the counter-thesis. Show key evidence. Identify
    assumptions. Identify missing information. Give calibrated confidence where
    possible. Explain what would change the conclusion. Provide risk and
    alternative actions.

## Why this is a dataclass that refuses to be constructed

A prompt asking a model to "consider both sides" produces both-sides language
followed by a confident recommendation, and the reader cannot tell from the
shape of it whether the disagreement was real or decorative. Making the parts
into fields does not by itself make the reasoning good — but it makes an
**omission** into an error rather than into a shorter paragraph.

The two that get dropped first under time pressure are the counter-thesis and
"what would change my mind", because they are the two that make the author less
persuasive. So those two are required, and `ReasoningIncomplete` names which are
missing rather than raising a generic error.

## Confidence is calibrated or it is absent

`confidence` may be `None`. What it may not be is a number with no basis: a bare
0.8 is a mood, and on a platform where somebody may size a position against it,
a mood formatted as a probability is worse than no figure. So a confidence
requires `confidence_basis` — a sentence saying what it was derived from — and
constructing one without the other is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai.debate.evidence import Evidence


class ReasoningIncomplete(ValueError):
    """Raised when a reasoning is missing a part §15 requires.

    Carries the field names so a caller can say what to add rather than
    reporting that something, somewhere, was wrong.
    """

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(
            "reasoning is missing "
            + ", ".join(missing)
            + " — §15 requires these; an argument without them is an argument for one side"
        )


@dataclass(frozen=True)
class Reasoning:
    """One structured answer to a consequential question."""

    subject: str
    #: The claim being made.
    thesis: str
    #: The strongest argument AGAINST the thesis. Required.
    counter_thesis: str
    #: What would have to be true, that has not been checked.
    assumptions: tuple[str, ...] = ()
    #: What is not known, stated rather than left as silence.
    missing_information: tuple[str, ...] = ()
    #: The observations the thesis rests on.
    evidence: tuple[Evidence, ...] = ()
    #: Evidence pointing the other way. Kept separate so a reader can see the
    #: balance without re-reading every item.
    counter_evidence: tuple[Evidence, ...] = ()
    #: 0-1, or None for "not calibrated".
    confidence: float | None = None
    #: What the confidence was derived from. Required whenever confidence is set.
    confidence_basis: str = ""
    #: Observations that would overturn the thesis. Required.
    what_would_change_it: tuple[str, ...] = ()
    #: What could go wrong if the thesis is acted on and is wrong.
    risks: tuple[str, ...] = ()
    #: Other courses of action, including doing nothing.
    alternatives: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        missing: list[str] = []
        if not self.subject.strip():
            missing.append("subject")
        if not self.thesis.strip():
            missing.append("thesis")
        # The two that get dropped first, because they are the two that make
        # the author less persuasive.
        if not self.counter_thesis.strip():
            missing.append("counter_thesis")
        if not any(item.strip() for item in self.what_would_change_it):
            missing.append("what_would_change_it")
        if missing:
            raise ReasoningIncomplete(tuple(missing))

        if self.confidence is not None:
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError(f"confidence {self.confidence} is not a probability")
            if not self.confidence_basis.strip():
                # A bare number is a mood. Somebody may size a position against
                # it, and a mood formatted as a probability is worse than none.
                raise ReasoningIncomplete(("confidence_basis",))

    @property
    def is_calibrated(self) -> bool:
        return self.confidence is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "thesis": self.thesis,
            "counter_thesis": self.counter_thesis,
            "assumptions": list(self.assumptions),
            "missing_information": list(self.missing_information),
            "evidence": [_evidence_dict(e) for e in self.evidence],
            "counter_evidence": [_evidence_dict(e) for e in self.counter_evidence],
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "what_would_change_it": list(self.what_would_change_it),
            "risks": list(self.risks),
            "alternatives": list(self.alternatives),
        }

    def as_prose(self) -> str:
        """Readable, in the order §15 lists the parts.

        Confidence renders as "not calibrated" rather than being omitted when it
        is absent. An omitted line reads as an oversight; the words say it was a
        decision.
        """
        lines = [
            f"{self.subject}",
            "",
            f"Thesis: {self.thesis}",
            f"Counter-thesis: {self.counter_thesis}",
        ]
        if self.evidence:
            lines.append("Evidence: " + "; ".join(e.claim for e in self.evidence))
        if self.counter_evidence:
            lines.append("Against: " + "; ".join(e.claim for e in self.counter_evidence))
        if self.assumptions:
            lines.append("Assuming: " + "; ".join(self.assumptions))
        if self.missing_information:
            lines.append("Not known: " + "; ".join(self.missing_information))
        lines.append(
            f"Confidence: {self.confidence:.0%} — {self.confidence_basis}"
            if self.confidence is not None
            else "Confidence: not calibrated."
        )
        lines.append("Would change it: " + "; ".join(self.what_would_change_it))
        if self.risks:
            lines.append("Risks: " + "; ".join(self.risks))
        if self.alternatives:
            lines.append("Alternatives: " + "; ".join(self.alternatives))
        return "\n".join(lines)


def _evidence_dict(e: Evidence) -> dict[str, Any]:
    return {
        "claim": e.claim,
        "source": e.source,
        "quality": e.quality.value,
        "observed_at": e.observed_at.isoformat() if e.observed_at else None,
    }


__all__ = ["Reasoning", "ReasoningIncomplete"]
