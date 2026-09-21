# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§5: adapt explanation depth **without changing the intelligence**.

That second half is the whole specification. Rendering an argument shorter is
trivial; rendering it shorter without turning it into a different argument is
the part that takes a rule, because the parts a writer drops first under length
pressure are exactly the parts that make the argument honest.

## Three things survive every depth

* **Every number.** "4.10%" softened to "a bit down" in the plain register is a
  different statement about the account, and the operator who asked for plain
  language has no way to know they were handed one.
* **The counter-thesis.** A shorter version with the other side removed is not
  shorter, it is one-sided.
* **What would change the conclusion.** An argument with no stated way to be
  wrong is an assertion, at any length.

Depth changes how much scaffolding goes round those. It never removes them, and
`ai/core/` has tests that render every depth and look for each one.

## Absence is stated, not omitted

A reasoning with no calibrated confidence says "not calibrated" in every
register including the shortest. An omitted line reads as an oversight; the
words say it was a decision.
"""

from __future__ import annotations

from ai.debate.reasoning import Reasoning

#: Least to most scaffolding. Named for what the reader gets, not for a level
#: number, so a caller has to think about who is reading.
DEPTHS: tuple[str, ...] = ("headline", "plain", "standard", "detailed", "full")


def _confidence_line(reasoning: Reasoning) -> str:
    if reasoning.confidence is None:
        return "Confidence: not calibrated."
    return f"Confidence: {reasoning.confidence:.0%} — {reasoning.confidence_basis}"


def _short_confidence(reasoning: Reasoning) -> str:
    """The same figure, fewer words. Never a word instead of the figure."""
    if reasoning.confidence is None:
        return "not calibrated"
    return f"{reasoning.confidence:.0%} sure"


def explain(reasoning: Reasoning, *, depth: str = "standard") -> str:
    """Render one reasoning for one reader.

    An unknown depth is refused rather than defaulted: defaulting hands somebody
    the standard register while they believe they asked for the plain one, and
    nothing on the page says which they got.
    """
    if depth not in DEPTHS:
        raise ValueError(f"depth {depth!r} is not one of {DEPTHS}")

    # Assembled once and used by every branch, so a branch cannot quietly omit
    # one of the three load-bearing parts by forgetting to reference it.
    thesis = reasoning.thesis
    counter = reasoning.counter_thesis
    falsifier = "; ".join(reasoning.what_would_change_it)

    if depth == "headline":
        return f"{thesis} Against it: {counter} Changes if: {falsifier} ({_short_confidence(reasoning)})"

    if depth == "plain":
        # Ordinary words around the same figures. The numbers are pasted through
        # untouched — this register rewrites the sentences, never the values.
        return "\n".join(
            [
                f"What I think: {thesis}",
                f"What argues against it: {counter}",
                f"What would change my mind: {falsifier}",
                f"How sure I am: {_short_confidence(reasoning)}.",
            ]
        )

    if depth == "standard":
        lines = [
            reasoning.subject,
            "",
            f"Thesis: {thesis}",
            f"Counter-thesis: {counter}",
            _confidence_line(reasoning),
            f"Would change it: {falsifier}",
        ]
        return "\n".join(lines)

    lines = [
        reasoning.subject,
        "",
        f"Thesis: {thesis}",
        f"Counter-thesis: {counter}",
    ]
    if reasoning.evidence:
        lines.append("Evidence: " + "; ".join(e.claim for e in reasoning.evidence))
    if reasoning.counter_evidence:
        lines.append("Against: " + "; ".join(e.claim for e in reasoning.counter_evidence))
    if reasoning.assumptions:
        lines.append("Assuming: " + "; ".join(reasoning.assumptions))
    if reasoning.missing_information:
        lines.append("Not known: " + "; ".join(reasoning.missing_information))
    lines.append(_confidence_line(reasoning))
    lines.append(f"Would change it: {falsifier}")

    if depth == "detailed":
        return "\n".join(lines)

    # full — everything, including the parts a reader usually skips.
    if reasoning.risks:
        lines.append("Risks: " + "; ".join(reasoning.risks))
    if reasoning.alternatives:
        lines.append("Alternatives: " + "; ".join(reasoning.alternatives))
    if reasoning.evidence or reasoning.counter_evidence:
        lines.append("")
        lines.append("Sources:")
        for e in (*reasoning.evidence, *reasoning.counter_evidence):
            when = e.observed_at.isoformat() if e.observed_at else "no timestamp recorded"
            lines.append(f"  {e.source} [{e.quality.value}, {when}]: {e.claim}")
    return "\n".join(lines)


__all__ = ["DEPTHS", "explain"]
