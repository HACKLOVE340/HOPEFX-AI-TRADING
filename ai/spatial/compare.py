# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Comparing a branch against its trunk — and refusing to rank them.

Capability #8's second half. Branching makes two versions exist; this is what
makes taking one worth anything. *"What if this building were twice as tall"* is
only a question if the two can be put side by side.

The discipline bites hardest here, because a comparison is the thing a decision
gets made from, and a side-by-side table is the most persuasive artifact the
spatial system can produce.

## Two kinds of answer, and only one of them is cheap

**Structural deltas** — which components differ, how the bill of materials
changes — are facts about two graphs. `PROCEDURALLY_GENERATED`, always
available, and not physics.

**A ranking** needs findings on *both* sides, both at `SIMULATED` or better.
The failure to avoid is specific: one side simulated and the other silent must
never produce a winner. Silence is not a worse score, and a table showing `0.62`
against a blank cell reads as though the blank lost.

`better_on` therefore returns `(None, reason)` rather than a verdict whenever it
cannot honestly rank, and **the reason is the deliverable**: "the branch was
never assessed for structural" is actionable; "no significant difference" is a
lie that closes the question.

A tie is different from a refusal and is reported as one: both sides measured
and equal is a real result.

Non-finite values refuse rather than compare. `NaN < x` is `False` in both
directions, so an unguarded comparison hands the win to whichever side is
checked second.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from ai.spatial.assurance import Assurance
from ai.spatial.simulation import Domain, Finding
from ai.spatial.timeline import Construction

__all__ = ["Comparison", "compare"]

#: The rung both sides must reach before a ranking is allowed. A comparison is
#: only as strong as its weaker side — the composite rule from
#: `ai/spatial/assurance.py`, applied to two models instead of one design.
_RANKABLE = Assurance.SIMULATED


@dataclass(frozen=True)
class Comparison:
    """Two constructions, side by side."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    bom_delta: dict[tuple[str, str], int]
    trunk_findings: Mapping[Domain, Finding] = field(default_factory=dict)
    branch_findings: Mapping[Domain, Finding] = field(default_factory=dict)
    assurance: Assurance = Assurance.PROCEDURALLY_GENERATED

    def better_on(self, domain: Domain, metric: str, *, higher_is_better: bool = False) -> tuple[str | None, str]:
        """Which side wins on one metric, or why the question cannot be answered.

        Returns `("trunk" | "branch" | "tie", reason)` or `(None, reason)`.
        """
        for side, findings in (("trunk", self.trunk_findings), ("branch", self.branch_findings)):
            finding = findings.get(domain)
            if finding is None:
                return None, (
                    f"the {side} was not assessed for {domain.value}; "
                    "a side with no finding has not scored badly, it has not been measured"
                )
            if finding.assurance < _RANKABLE:
                return None, (
                    f"the {side}'s {domain.value} finding is {finding.assurance.name.lower()}, "
                    f"below {_RANKABLE.name.lower()}; ranking it against a simulated result would "
                    "read as a like-for-like comparison"
                )
            if metric not in finding.detail:
                return None, f"the {side}'s {domain.value} finding carries no {metric!r} value"

        trunk_value = self.trunk_findings[domain].detail[metric]
        branch_value = self.branch_findings[domain].detail[metric]
        for side, value in (("trunk", trunk_value), ("branch", branch_value)):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                return None, f"the {side}'s {metric!r} is not a finite number ({value!r})"

        if trunk_value == branch_value:
            return "tie", f"both sides report an equal {metric} of {trunk_value}"
        trunk_wins = trunk_value > branch_value if higher_is_better else trunk_value < branch_value
        winner = "trunk" if trunk_wins else "branch"
        return winner, (
            f"{winner} is better on {metric} "
            f"(trunk {trunk_value}, branch {branch_value}, "
            f"{'higher' if higher_is_better else 'lower'} is better)"
        )


def compare(
    trunk: Construction,
    branch: Construction,
    *,
    trunk_findings: Mapping[Domain, Finding] | None = None,
    branch_findings: Mapping[Domain, Finding] | None = None,
) -> Comparison:
    """Put two constructions side by side.

    Findings are passed in rather than computed here: this module compares, and
    `ai.spatial.simulation.Laboratory` assesses. Merging the two would let a
    comparison quietly run a solver, and then a side-by-side table would be the
    thing deciding which physics ran.
    """
    trunk_ids = set(trunk.world.component_ids())
    branch_ids = set(branch.world.component_ids())

    trunk_bom = Counter(trunk.world.bill_of_materials())
    branch_bom = Counter(branch.world.bill_of_materials())
    delta = {
        line: branch_bom.get(line, 0) - trunk_bom.get(line, 0)
        for line in set(trunk_bom) | set(branch_bom)
        # A delta listing zeroes is a diff nobody can read.
        if branch_bom.get(line, 0) != trunk_bom.get(line, 0)
    }

    return Comparison(
        added=tuple(sorted(branch_ids - trunk_ids)),
        removed=tuple(sorted(trunk_ids - branch_ids)),
        bom_delta=delta,
        trunk_findings=dict(trunk_findings or {}),
        branch_findings=dict(branch_findings or {}),
    )
