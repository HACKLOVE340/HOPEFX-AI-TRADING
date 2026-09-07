# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§5: challenge weak assumptions and present counterarguments.

An assistant that agrees is pleasant and useless. This looks at a finished
`Reasoning` and says where it is thin — before somebody sizes a position
against it.

## It states the counterargument, not the flaw

"This assumption is unsupported" tells a reader nothing they can act on. "You
are assuming liquidity holds into the close; if it does not, your stop is a
suggestion" tells them what to check. Every `Challenge` carries both, and the
counterargument is asserted to be a sentence rather than a label.

## It is allowed to find nothing

The tempting design finds at least one weakness in everything, because a
checker that sometimes says "this looks sound" feels like it is not working.
It is the opposite: a challenger that always fires is a challenger nobody
reads, and the third time it manufactures a quibble about a solid argument, the
operator stops looking at it. A well-supported reasoning returns an empty list.

## The checks are about the SHAPE of the argument

Not about whether the conclusion is right — nothing here can know that. Every
check below asks a question that can be answered from the structure: is this
assumption supported by anything, is the evidence sourced, is it fresh, does
the confidence match the weight behind it, did anybody look for the other side.
A checker that guessed at the subject matter would be a second opinion nobody
asked for and nobody could audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ai.debate.evidence import EvidenceQuality, weigh
from ai.debate.reasoning import Reasoning

#: Above this, a confidence needs real evidence weight behind it.
_HIGH_CONFIDENCE = 0.8

#: The evidence weight a high confidence ought to be able to point at.
_WEIGHT_FOR_HIGH_CONFIDENCE = 1.0

_SEVERITY_RANK = {"high": 2, "medium": 1, "low": 0}

#: Shorter than this and a counterargument is a label. A reader can act on
#: a sentence; they cannot act on "unsupported".
_MIN_COUNTERARGUMENT = 30

#: Words shorter than this carry no subject matter — "will", "hold", "the".
_MIN_CONTENT_WORD = 5


@dataclass(frozen=True)
class Challenge:
    """One weak point, and what to say about it."""

    #: What is weak, in a few words.
    about: str
    #: The argument against it, in a sentence somebody can act on.
    counterargument: str
    severity: str  # high | medium | low

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITY_RANK:
            raise ValueError(f"severity {self.severity!r} is not one of {tuple(_SEVERITY_RANK)}")
        if len(self.counterargument) < _MIN_COUNTERARGUMENT:
            # A label is not a counterargument. Enforced here rather than left
            # to review, because the short version is what gets written when
            # somebody is adding a check in a hurry.
            raise ValueError("a challenge must state the counterargument, not just name the flaw")


def challenge(reasoning: Reasoning, *, now: datetime | None = None) -> list[Challenge]:
    """Find the weak points in an argument. Empty when there are none."""
    moment = now or datetime.now(UTC)
    found: list[Challenge] = []

    weighed = [weigh(e, now=moment) for e in reasoning.evidence]
    total_weight = sum(w.weight for w in weighed)

    # ── the confidence against what is behind it ─────────────────────────────
    if (
        reasoning.confidence is not None
        and reasoning.confidence >= _HIGH_CONFIDENCE
        and total_weight < _WEIGHT_FOR_HIGH_CONFIDENCE
    ):
        found.append(
            Challenge(
                about="The confidence outruns the evidence",
                counterargument=(
                    f"You state {reasoning.confidence:.0%} confidence, but the evidence behind the thesis "
                    f"weighs {total_weight:.2f} once source quality and age are taken into account. A number "
                    "that high should be able to point at something; this one is describing a feeling."
                ),
                severity="high",
            )
        )

    # ── evidence that nobody can check ───────────────────────────────────────
    if weighed and all(w.evidence.quality is EvidenceQuality.RECALLED for w in weighed):
        found.append(
            Challenge(
                about="Nothing here is sourced — it is all recalled",
                counterargument=(
                    "Every item supporting this is a recollection with no measurement behind it. "
                    "Recollection is the weakest thing that is still evidence, and a conclusion built "
                    "entirely on it should be checked against the books before it is acted on."
                ),
                severity="high",
            )
        )

    # ── evidence that has gone off ───────────────────────────────────────────
    if weighed and all(w.stale for w in weighed):
        found.append(
            Challenge(
                about="Every reading behind this is stale",
                counterargument=(
                    "Nothing supporting this was observed recently enough to describe the current state. "
                    "A correct reading of the book from hours ago is a wrong reading of the book now, and "
                    "old evidence is exactly the kind that still feels true."
                ),
                severity="high",
            )
        )

    # ── nobody looked for the other side ─────────────────────────────────────
    if not reasoning.counter_evidence:
        found.append(
            Challenge(
                about="No evidence against this was gathered",
                counterargument=(
                    "There is a counter-thesis but nothing measured behind it. That is not evidence the "
                    "thesis is right; it is evidence nobody went looking, and the two are easy to confuse "
                    "when only one side of the page is full."
                ),
                severity="medium",
            )
        )

    # ── assumptions holding weight nothing supports ──────────────────────────
    for assumption in reasoning.assumptions:
        if _is_supported(assumption, reasoning):
            continue
        found.append(
            Challenge(
                about=f"Unsupported assumption: {assumption}",
                counterargument=(
                    f"The argument rests on “{assumption.rstrip('.')}” and nothing gathered here "
                    "establishes it. If it turns out to be false the conclusion does not weaken, it stops "
                    "following at all."
                ),
                severity="medium",
            )
        )

    found.sort(key=lambda c: -_SEVERITY_RANK[c.severity])
    return found


def _is_supported(assumption: str, reasoning: Reasoning) -> bool:
    """Whether any evidence plausibly speaks to this assumption.

    Word overlap, deliberately generous: the job here is to avoid crying wolf
    about an assumption the evidence obviously covers, not to judge whether the
    evidence actually establishes it. A stricter test would flag almost every
    assumption and become noise, which is the failure this module is most at
    risk of.
    """
    words = {w for w in assumption.lower().replace(".", "").split() if len(w) >= _MIN_CONTENT_WORD}
    if not words:
        return True
    for e in (*reasoning.evidence, *reasoning.counter_evidence):
        hay = f"{e.claim} {e.source}".lower()
        if any(word in hay for word in words):
            return True
    return False


__all__ = ["Challenge", "challenge"]
