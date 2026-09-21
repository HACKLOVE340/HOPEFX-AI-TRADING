# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Comparing a branch against its trunk — and refusing to rank them.

Capability #8's second half. Branching exists; this is what makes a branch worth
taking. "What if this building were twice as tall" is only a question if the two
versions can be put side by side.

The discipline is the same as everywhere else in this package, and it bites
hardest here because a comparison is what a decision is made from:

* **Structural deltas are PROCEDURALLY_GENERATED.** What components differ, and
  how the bill of materials changes, are facts about two graphs. Real, cheap,
  and not physics.
* **A ranking needs findings on BOTH sides.** "Which is better on structure" is
  unanswerable when either side was never simulated, and the honest answer is a
  refusal naming the missing side — not a tie, not the one that happens to have
  a number.
* **A refusal is not a verdict.** `better_on` returns `None` plus a reason, and
  the reason is the whole value: "nobody simulated the branch" is actionable,
  "no difference" is a lie.
"""

from __future__ import annotations

import pytest

from ai.spatial.assurance import Assurance
from ai.spatial.compare import compare
from ai.spatial.simulation import Domain, Finding
from ai.spatial.timeline import Construction
from ai.spatial.world import Component, ConnectionKind, World

pytestmark = pytest.mark.unit


def _trunk() -> World:
    w = World(name="house")
    w.add(Component(id="slab", kind="slab", material="concrete"))
    w.add(Component(id="beam", kind="beam", material="steel"))
    w.connect("slab", "beam", ConnectionKind.SUPPORTS)
    return w


def _taller() -> World:
    w = _trunk()
    w.add(Component(id="beam2", kind="beam", material="steel"))
    w.connect("beam", "beam2", ConnectionKind.SUPPORTS)
    return w


def _finding(domain: Domain, rung: Assurance, **detail: float) -> Finding:
    return Finding(domain=domain, assurance=rung, reason="test", solver="double", detail=detail)


class TestStructuralDeltas:
    def test_added_and_removed_components_are_listed(self) -> None:
        c = compare(Construction(_trunk()), Construction(_taller()))
        assert c.added == ("beam2",)
        assert c.removed == ()

    def test_a_removal_is_reported_as_removed(self) -> None:
        c = compare(Construction(_taller()), Construction(_trunk()))
        assert c.removed == ("beam2",)
        assert c.added == ()

    def test_the_bill_of_materials_delta_is_reported(self) -> None:
        c = compare(Construction(_trunk()), Construction(_taller()))
        assert c.bom_delta[("beam", "steel")] == 1

    def test_an_unchanged_line_does_not_appear_in_the_delta(self) -> None:
        """A delta listing zeroes is a diff nobody can read."""
        c = compare(Construction(_trunk()), Construction(_taller()))
        assert ("slab", "concrete") not in c.bom_delta

    def test_comparing_a_model_with_itself_reports_no_change(self) -> None:
        c = compare(Construction(_trunk()), Construction(_trunk()))
        assert c.added == () and c.removed == () and c.bom_delta == {}

    def test_the_structural_delta_is_procedurally_generated(self) -> None:
        """It is a fact about two graphs, not a prediction about two buildings."""
        assert compare(Construction(_trunk()), Construction(_taller())).assurance is (Assurance.PROCEDURALLY_GENERATED)


class TestRankingRefusesWithoutEvidenceOnBothSides:
    def test_no_findings_at_all_refuses_and_says_why(self) -> None:
        c = compare(Construction(_trunk()), Construction(_taller()))
        verdict, reason = c.better_on(Domain.STRUCTURAL, metric="utilisation")
        assert verdict is None
        assert "not assessed" in reason.lower()

    def test_a_finding_on_only_one_side_refuses_and_names_the_missing_side(self) -> None:
        """The dangerous case. One number and one silence must not become a
        winner — silence is not a worse score."""
        c = compare(
            Construction(_trunk()),
            Construction(_taller()),
            trunk_findings={Domain.STRUCTURAL: _finding(Domain.STRUCTURAL, Assurance.SIMULATED, utilisation=0.6)},
        )
        verdict, reason = c.better_on(Domain.STRUCTURAL, metric="utilisation")
        assert verdict is None
        assert "branch" in reason.lower()

    def test_findings_below_simulated_on_either_side_refuse(self) -> None:
        """Two rules of thumb do not make a comparison. ESTIMATED against
        SIMULATED is worse still: it reads as a like-for-like result."""
        c = compare(
            Construction(_trunk()),
            Construction(_taller()),
            trunk_findings={Domain.STRUCTURAL: _finding(Domain.STRUCTURAL, Assurance.ESTIMATED, utilisation=0.6)},
            branch_findings={Domain.STRUCTURAL: _finding(Domain.STRUCTURAL, Assurance.SIMULATED, utilisation=0.4)},
        )
        verdict, reason = c.better_on(Domain.STRUCTURAL, metric="utilisation")
        assert verdict is None
        assert "estimated" in reason.lower()

    def test_a_metric_missing_from_a_finding_refuses(self) -> None:
        c = compare(
            Construction(_trunk()),
            Construction(_taller()),
            trunk_findings={Domain.STRUCTURAL: _finding(Domain.STRUCTURAL, Assurance.SIMULATED, mass=10.0)},
            branch_findings={Domain.STRUCTURAL: _finding(Domain.STRUCTURAL, Assurance.SIMULATED, mass=12.0)},
        )
        verdict, reason = c.better_on(Domain.STRUCTURAL, metric="utilisation")
        assert verdict is None
        assert "utilisation" in reason


class TestRankingWhenBothSidesWereSimulated:
    def _both(self, trunk_value: float, branch_value: float):
        return compare(
            Construction(_trunk()),
            Construction(_taller()),
            trunk_findings={
                Domain.STRUCTURAL: _finding(Domain.STRUCTURAL, Assurance.SIMULATED, utilisation=trunk_value)
            },
            branch_findings={
                Domain.STRUCTURAL: _finding(Domain.STRUCTURAL, Assurance.SIMULATED, utilisation=branch_value)
            },
        )

    def test_lower_is_better_by_default(self) -> None:
        verdict, _ = self._both(0.8, 0.4).better_on(Domain.STRUCTURAL, metric="utilisation")
        assert verdict == "branch"

    def test_the_trunk_can_win(self) -> None:
        verdict, _ = self._both(0.3, 0.9).better_on(Domain.STRUCTURAL, metric="utilisation")
        assert verdict == "trunk"

    def test_higher_is_better_when_asked_for(self) -> None:
        verdict, _ = self._both(0.8, 0.4).better_on(Domain.STRUCTURAL, metric="utilisation", higher_is_better=True)
        assert verdict == "trunk"

    def test_an_exact_tie_is_a_tie_and_not_a_refusal(self) -> None:
        """Both sides measured and equal is a real answer, unlike both unmeasured."""
        verdict, reason = self._both(0.5, 0.5).better_on(Domain.STRUCTURAL, metric="utilisation")
        assert verdict == "tie"
        assert "equal" in reason.lower()

    def test_a_non_finite_value_refuses_rather_than_compares(self) -> None:
        """NaN loses every comparison silently, so the branch would 'win'."""
        verdict, reason = self._both(float("nan"), 0.4).better_on(Domain.STRUCTURAL, metric="utilisation")
        assert verdict is None
        assert "finite" in reason.lower()
