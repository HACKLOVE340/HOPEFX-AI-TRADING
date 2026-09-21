# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The assurance rules, enforced where a spatial result crosses into a decision.

`ai/spatial/assurance.py` makes the rules available. Available is not enforced —
that distinction is this repository's most common defect (F176), and a module
holding correct rules that no decision path consults is exactly it.

These predicates are the enforcement side. They are discovered automatically by
`invariants.registry`, so they exist the moment they are named correctly, and
`invariants/enforcement.py` decides what a violation does.

Each predicate answers a question a caller can get wrong while looking right:

* a claim was promoted — did evidence arrive with it?
* a composite rung was published — is it really the weakest part?
* something was called ready — is every required aspect approved by a person?
* a report was produced — does it cover every required aspect, or only the
  flattering ones?
* a spatial result reached a decision — did it declare a rung at all?
"""

from __future__ import annotations

import pytest

from ai.spatial.assurance import Assurance
from invariants.constitution import CONSTITUTIONAL, CRITICAL
from invariants.spatial import (
    verify_composite_assurance,
    verify_structural_claim_requires_solver,
    verify_epistemic_monotonicity,
    verify_no_required_aspect_omitted,
    verify_readiness_requires_approval,
    verify_spatial_result_declares_assurance,
)

pytestmark = pytest.mark.unit


class TestEpistemicMonotonicity:
    """AOS-EVID-028. A record must not move toward 'verified' for free."""

    def test_a_promotion_with_no_new_evidence_is_a_violation(self) -> None:
        v = verify_epistemic_monotonicity(Assurance.ESTIMATED, Assurance.VALIDATED, evidence_added=0)
        assert v and v[0].severity == CONSTITUTIONAL

    def test_a_promotion_backed_by_evidence_passes(self) -> None:
        assert verify_epistemic_monotonicity(Assurance.ESTIMATED, Assurance.VALIDATED, evidence_added=1) == []

    def test_a_demotion_needs_no_evidence(self) -> None:
        assert verify_epistemic_monotonicity(Assurance.VALIDATED, Assurance.ESTIMATED, evidence_added=0) == []

    def test_standing_still_is_not_a_promotion(self) -> None:
        assert verify_epistemic_monotonicity(Assurance.SIMULATED, Assurance.SIMULATED, evidence_added=0) == []

    def test_a_non_numeric_rung_is_refused_rather_than_compared(self) -> None:
        """NaN passes every comparison silently. Every numeric predicate in this
        package guards finiteness first; this one is no exception."""
        v = verify_epistemic_monotonicity(float("nan"), Assurance.VALIDATED, evidence_added=0)
        assert v, "a non-finite rung must be a violation, not a silent pass"


class TestCompositeAssurance:
    def test_a_composite_above_its_weakest_part_is_a_violation(self) -> None:
        v = verify_composite_assurance([Assurance.SIMULATED, Assurance.NOT_ASSESSED], Assurance.SIMULATED)
        assert v and v[0].severity == CONSTITUTIONAL

    def test_the_weakest_part_passes(self) -> None:
        assert verify_composite_assurance([Assurance.SIMULATED, Assurance.NOT_ASSESSED], Assurance.NOT_ASSESSED) == []

    def test_understating_is_allowed(self) -> None:
        """Claiming less than earned is conservative, never dangerous."""
        assert verify_composite_assurance([Assurance.VALIDATED, Assurance.VALIDATED], Assurance.ESTIMATED) == []

    def test_a_composite_over_no_parts_may_not_claim_anything(self) -> None:
        v = verify_composite_assurance([], Assurance.SIMULATED)
        assert v, "a composite of nothing cannot be SIMULATED"

    def test_a_composite_over_no_parts_may_state_not_assessed(self) -> None:
        """Zero parts is honestly reportable — as NOT_ASSESSED and nothing above."""
        assert verify_composite_assurance([], Assurance.NOT_ASSESSED) == []

    def test_a_non_finite_part_is_refused_rather_than_compared(self) -> None:
        """`min()` over a list containing NaN returns whichever element came
        first, so an unguarded composite would publish a rung decided by list
        order. The finite guard is asserted rather than assumed — an untested
        guard is how a NaN reaches a comparison in the first place."""
        assert verify_composite_assurance([Assurance.SIMULATED, float("nan")], Assurance.SIMULATED)
        assert verify_composite_assurance([Assurance.SIMULATED], float("nan"))


class TestReadinessRequiresApproval:
    def test_ready_with_an_unapproved_aspect_is_a_violation(self) -> None:
        v = verify_readiness_requires_approval(
            True, {"structural": Assurance.EXTERNALLY_VERIFIED, "code": Assurance.SIMULATED}
        )
        assert v and v[0].severity == CONSTITUTIONAL

    def test_ready_with_every_aspect_approved_passes(self) -> None:
        assert verify_readiness_requires_approval(True, {"structural": Assurance.HUMAN_APPROVED}) == []

    def test_not_ready_is_never_a_violation(self) -> None:
        assert verify_readiness_requires_approval(False, {"structural": Assurance.NOT_ASSESSED}) == []

    def test_ready_over_no_aspects_is_a_violation(self) -> None:
        """ "Nothing was required, so it is ready" is how a checklist reaches
        zero items and reports success."""
        assert verify_readiness_requires_approval(True, {})


class TestNoRequiredAspectOmitted:
    def test_a_missing_aspect_is_a_violation(self) -> None:
        v = verify_no_required_aspect_omitted(("geometry", "fire_safety"), ("geometry",))
        assert v and v[0].severity == CRITICAL
        assert "fire_safety" in v[0].message

    def test_a_complete_report_passes(self) -> None:
        assert verify_no_required_aspect_omitted(("geometry",), ("geometry", "extra")) == []


class TestASpatialResultAlwaysDeclaresItsRung:
    def test_an_undeclared_result_is_a_violation(self) -> None:
        v = verify_spatial_result_declares_assurance("structural_load", None)
        assert v and v[0].severity == CONSTITUTIONAL

    def test_a_declared_result_passes(self) -> None:
        assert verify_spatial_result_declares_assurance("structural_load", Assurance.SIMULATED) == []


def test_every_predicate_here_is_discovered_by_the_registry() -> None:
    """A predicate the registry cannot see is a check that does not exist. The
    naming convention is the whole registration mechanism, so it is asserted
    rather than trusted."""
    from invariants.registry import discover_predicates

    found = set(discover_predicates().get("spatial", []))
    assert {
        "verify_composite_assurance",
        "verify_epistemic_monotonicity",
        "verify_no_required_aspect_omitted",
        "verify_readiness_requires_approval",
        "verify_spatial_result_declares_assurance",
    } <= found, f"registry sees only {sorted(found)}"


class TestAStructuralClaimNeedsASolverThatRan:
    """`World.removal_impact` returns PROCEDURALLY_GENERATED, correctly — the
    graph is repeating what was declared. Nothing in the type system stops a
    caller republishing that finding as SIMULATED, and "the model says the floor
    stays up" becoming "the floor stays up" is precisely the step that turns a
    drawing into a demolition decision.

    So the rung is checked where the claim is published, not only where it is
    produced. A rule enforced solely at its source is a rule enforced by whoever
    remembers it."""

    def test_a_simulated_claim_with_no_solver_run_is_a_violation(self) -> None:
        v = verify_structural_claim_requires_solver(Assurance.SIMULATED, solver_ran=False)
        assert v and v[0].severity == CONSTITUTIONAL

    def test_a_simulated_claim_backed_by_a_solver_passes(self) -> None:
        assert verify_structural_claim_requires_solver(Assurance.SIMULATED, solver_ran=True) == []

    def test_a_procedurally_generated_claim_needs_no_solver(self) -> None:
        """The graph may always report what was declared. That is what it knows."""
        assert verify_structural_claim_requires_solver(Assurance.PROCEDURALLY_GENERATED, solver_ran=False) == []

    def test_every_rung_above_simulated_also_requires_one(self) -> None:
        for rung in (Assurance.VALIDATED, Assurance.EXTERNALLY_VERIFIED, Assurance.HUMAN_APPROVED):
            assert verify_structural_claim_requires_solver(rung, solver_ran=False), rung.name

    def test_a_non_finite_rung_is_refused_rather_than_compared(self) -> None:
        assert verify_structural_claim_requires_solver(float("nan"), solver_ran=True)
