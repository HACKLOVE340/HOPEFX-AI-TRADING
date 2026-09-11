# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The Simulation Laboratory: pick the right solver, and refuse when there is none.

Capability #4. The specification's own words are the hard part:

    "The AI chooses the appropriate simulation rather than pretending every
     result is physically accurate."

A laboratory that always returns a number is the most dangerous thing in the
spatial system. `removal_impact` is honest because it is labelled
PROCEDURALLY_GENERATED and everybody can see the graph behind it. A simulation
result LOOKS like physics. If the lab answers a structural question with a
thermal solver, or with a plausible default because no solver was registered,
the answer is indistinguishable from one a finite-element run produced.

So five rules, and four of them are refusals:

1. No solver for the domain -> NOT_ASSESSED, naming the domain. Never estimated,
   never defaulted.
2. A solver that declines the world -> NOT_ASSESSED. Never fall back to a solver
   from another domain: answering a structural question with a thermal model is
   worse than not answering.
3. A solver that raises -> NOT_ASSESSED, carrying the failure. Never a silent
   pass and never a default value.
4. A result is SIMULATED AT MOST. A solver cannot self-certify as validated,
   externally verified, or approved.
5. Selecting a solver is not running one.
"""

from __future__ import annotations

import pytest

from ai.spatial.assurance import Assurance
from ai.spatial.simulation import Domain, Laboratory, SolverResult
from ai.spatial.world import Component, ConnectionKind, World

pytestmark = pytest.mark.unit


def _world() -> World:
    w = World(name="w")
    w.add(Component(id="slab", kind="slab", material="concrete"))
    w.add(Component(id="beam", kind="beam", material="steel"))
    w.connect("slab", "beam", ConnectionKind.SUPPORTS)
    return w


class _Solver:
    """A test double with a real shape — not a MagicMock.

    A mock with no spec agrees with every call, including calls the real
    protocol would reject (F242, F248). These tests depend on the signature, so
    the double implements it.
    """

    def __init__(
        self,
        domain: Domain,
        *,
        name: str = "double",
        applicable: bool = True,
        raises: Exception | None = None,
        raises_on_applicable: Exception | None = None,
        result: SolverResult | None = None,
    ) -> None:
        self.domain = domain
        self.name = name
        self._applicable = applicable
        self._raises = raises
        self._raises_on_applicable = raises_on_applicable
        self._result = result
        self.run_count = 0

    def applicable_to(self, world: World) -> bool:
        if self._raises_on_applicable is not None:
            raise self._raises_on_applicable
        return self._applicable

    def run(self, world: World) -> SolverResult:
        self.run_count += 1
        if self._raises is not None:
            raise self._raises
        return self._result or SolverResult(summary="ok", detail={"utilisation": 0.62})


# ── Rule 1: nothing registered means nothing is known ───────────────────────


class TestNoSolver:
    def test_an_unserved_domain_is_not_assessed(self) -> None:
        finding = Laboratory().assess(_world(), Domain.STRUCTURAL)
        assert finding.assurance is Assurance.NOT_ASSESSED
        assert finding.solver is None

    def test_the_reason_names_the_domain_so_the_gap_is_actionable(self) -> None:
        finding = Laboratory().assess(_world(), Domain.AERODYNAMIC)
        assert "aerodynamic" in finding.reason.lower()

    def test_it_does_not_fall_back_to_a_solver_from_another_domain(self) -> None:
        """Rule 2. Answering a structural question with a thermal model is worse
        than not answering, because the answer looks like physics."""
        thermal = _Solver(Domain.THERMAL)
        lab = Laboratory()
        lab.register(thermal)
        finding = lab.assess(_world(), Domain.STRUCTURAL)
        assert finding.assurance is Assurance.NOT_ASSESSED
        assert thermal.run_count == 0, "a thermal solver was run for a structural question"


# ── The happy path, and its ceiling ─────────────────────────────────────────


class TestASolverThatRuns:
    def test_a_successful_run_is_simulated(self) -> None:
        lab = Laboratory()
        lab.register(_Solver(Domain.STRUCTURAL, name="fea"))
        finding = lab.assess(_world(), Domain.STRUCTURAL)
        assert finding.assurance is Assurance.SIMULATED
        assert finding.solver == "fea"
        assert finding.detail["utilisation"] == pytest.approx(0.62)

    def test_a_solver_cannot_certify_itself_above_simulated(self) -> None:
        """Rule 4. A solver claiming VALIDATED has validated nothing — validation
        is a comparison against acceptance criteria, made outside the thing being
        validated."""
        lab = Laboratory()
        lab.register(
            _Solver(
                Domain.STRUCTURAL,
                result=SolverResult(summary="fine", detail={}, claims=Assurance.HUMAN_APPROVED),
            )
        )
        assert lab.assess(_world(), Domain.STRUCTURAL).assurance is Assurance.SIMULATED

    def test_a_solver_may_claim_less_than_simulated(self) -> None:
        """A solver that knows it is a rough model should be able to say so.
        Clamping is a ceiling, not a floor."""
        lab = Laboratory()
        lab.register(
            _Solver(
                Domain.THERMAL,
                result=SolverResult(summary="rule of thumb", detail={}, claims=Assurance.ESTIMATED),
            )
        )
        assert lab.assess(_world(), Domain.THERMAL).assurance is Assurance.ESTIMATED


# ── Rules 2 and 3: declining and failing are both "not assessed" ────────────


class TestWhenTheSolverCannotAnswer:
    def test_a_solver_that_declines_the_world_yields_not_assessed(self) -> None:
        lab = Laboratory()
        lab.register(_Solver(Domain.STRUCTURAL, applicable=False))
        finding = lab.assess(_world(), Domain.STRUCTURAL)
        assert finding.assurance is Assurance.NOT_ASSESSED
        assert "not applicable" in finding.reason.lower()

    def test_a_solver_that_raises_yields_not_assessed_carrying_the_failure(self) -> None:
        """Rule 3. The failure is reported, never swallowed — a solver crash that
        returned a default would be a value nothing computed."""
        lab = Laboratory()
        lab.register(_Solver(Domain.STRUCTURAL, name="fea", raises=RuntimeError("mesh did not converge")))
        finding = lab.assess(_world(), Domain.STRUCTURAL)
        assert finding.assurance is Assurance.NOT_ASSESSED
        assert "mesh did not converge" in finding.reason
        assert finding.solver == "fea", "the solver that failed must still be named"

    def test_a_solver_that_fails_while_deciding_applicability_yields_not_assessed(self) -> None:
        """A solver that cannot decide whether it applies has not decided.

        Written after coverage showed this handler was the one branch in the
        module no test reached — an untested handler on a safety path is the
        shape `hopefx-dead-controls` is about, and this one sits between a
        crash and a finding.
        """
        lab = Laboratory()
        lab.register(_Solver(Domain.STRUCTURAL, name="fea", raises_on_applicable=RuntimeError("bad geometry")))
        finding = lab.assess(_world(), Domain.STRUCTURAL)
        assert finding.assurance is Assurance.NOT_ASSESSED
        assert "bad geometry" in finding.reason
        assert finding.solver == "fea"

    def test_a_failing_solver_does_not_poison_another_domain(self) -> None:
        lab = Laboratory()
        lab.register(_Solver(Domain.STRUCTURAL, raises=RuntimeError("boom")))
        lab.register(_Solver(Domain.THERMAL, name="thermal"))
        assert lab.assess(_world(), Domain.THERMAL).assurance is Assurance.SIMULATED


# ── Rule 5, and registration ────────────────────────────────────────────────


class TestSelectionAndRegistration:
    def test_selecting_does_not_run(self) -> None:
        solver = _Solver(Domain.STRUCTURAL)
        lab = Laboratory()
        lab.register(solver)
        assert lab.select(Domain.STRUCTURAL) is solver
        assert solver.run_count == 0

    def test_selecting_an_unserved_domain_returns_none(self) -> None:
        assert Laboratory().select(Domain.FLUID) is None

    def test_a_second_solver_for_a_domain_is_refused(self) -> None:
        """Two solvers for one domain means the lab picks, and a silent pick
        between two physics models is a decision nobody made."""
        lab = Laboratory()
        lab.register(_Solver(Domain.STRUCTURAL, name="a"))
        with pytest.raises(ValueError, match="structural"):
            lab.register(_Solver(Domain.STRUCTURAL, name="b"))

    def test_the_domains_it_can_answer_are_reportable(self) -> None:
        lab = Laboratory()
        lab.register(_Solver(Domain.STRUCTURAL))
        lab.register(_Solver(Domain.THERMAL))
        assert set(lab.served_domains()) == {Domain.STRUCTURAL, Domain.THERMAL}

    def test_an_empty_laboratory_serves_nothing_and_says_so(self) -> None:
        assert Laboratory().served_domains() == ()


# ── The whole point, end to end ─────────────────────────────────────────────


def test_a_model_with_no_solvers_reports_every_domain_as_unassessed() -> None:
    """The state the platform is actually in today: a builder and no physics.

    The report must say that about every domain rather than omitting them, for
    the same reason `readiness_report` lists aspects nobody assessed — an absent
    row reads as a row with nothing wrong.
    """
    lab = Laboratory()
    findings = lab.assess_all(_world(), (Domain.STRUCTURAL, Domain.THERMAL, Domain.AERODYNAMIC))
    assert set(findings) == {Domain.STRUCTURAL, Domain.THERMAL, Domain.AERODYNAMIC}
    assert all(f.assurance is Assurance.NOT_ASSESSED for f in findings.values())
