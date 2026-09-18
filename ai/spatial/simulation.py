# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The Simulation Laboratory — pick the right solver, and refuse when there is none.

Capability #4, whose specification contains the hard part in one sentence:

    "The AI chooses the appropriate simulation rather than pretending every
     result is physically accurate."

A laboratory that always returns a number is the most dangerous component in the
spatial system. `World.removal_impact` is safe because it is labelled
`PROCEDURALLY_GENERATED` and the graph behind it is visible. **A simulation
result looks like physics.** Answer a structural question with a thermal solver,
or with a plausible default because nothing was registered, and the answer is
indistinguishable from one a finite-element run produced — by the operator, by
the report, and by whatever decides to build the thing.

So the lab is mostly refusals:

* **No solver for the domain** → `NOT_ASSESSED`, naming the domain so the gap is
  actionable. Never estimated, never defaulted.
* **A solver that declines this world** → `NOT_ASSESSED`. Never fall back to
  another domain's solver.
* **A solver that raises** → `NOT_ASSESSED`, carrying the failure text and still
  naming the solver. A crash that returned a default would be a value nothing
  computed, which is the defect this whole package exists to prevent.
* **A result is `SIMULATED` at most.** A solver claiming `VALIDATED` has
  validated nothing: validation is a comparison against acceptance criteria made
  *outside* the thing being validated. The clamp is a ceiling and not a floor —
  a solver that knows it is a rule of thumb may say `ESTIMATED`.
* **Two solvers for one domain is refused at registration.** A silent pick
  between two physics models is a decision nobody made.

`assess_all` reports every domain asked about, including the ones nothing serves,
for the same reason `readiness_report` lists unassessed aspects: an absent row
reads as a row with nothing wrong.

Pure and side-effect free apart from whatever a registered solver does. The lab
itself performs no I/O and holds no state beyond its registry.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ai.spatial.assurance import Assurance
from ai.spatial.world import World

__all__ = ["Domain", "Finding", "Laboratory", "Solver", "SolverResult"]

#: The ceiling any solver's own claim is clamped to. Named rather than inlined:
#: it is the constant somebody will want to raise "just for this one trusted
#: solver", and a named constant is easier to defend in review than a literal.
_SOLVER_CEILING = Assurance.SIMULATED


class Domain(Enum):
    """The kinds of question the laboratory can be asked.

    From the specification's list. A domain exists here whether or not anything
    serves it — an unserved domain must be nameable in order to be reported as
    unassessed.
    """

    STRUCTURAL = "structural"
    FLUID = "fluid"
    THERMAL = "thermal"
    AERODYNAMIC = "aerodynamic"
    LIGHTING = "lighting"
    ELECTRICAL = "electrical"
    TRAFFIC = "traffic"
    ROBOTICS = "robotics"
    RIGID_BODY = "rigid_body"


@dataclass(frozen=True)
class SolverResult:
    """What a solver returns.

    `claims` is the solver's own view of how strong its result is. It is clamped
    to `_SOLVER_CEILING` on the way out, so the field is a way to claim LESS.
    """

    summary: str
    detail: Mapping[str, Any] = field(default_factory=dict)
    claims: Assurance = Assurance.SIMULATED


@dataclass(frozen=True)
class Finding:
    """One domain's answer, with the rung it earned and why.

    `reason` is populated on every outcome, not only failures: a finding that
    says `NOT_ASSESSED` without saying why is a dead end for whoever reads it.
    """

    domain: Domain
    assurance: Assurance
    reason: str
    solver: str | None = None
    summary: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Solver(Protocol):
    """What the laboratory requires of a physics engine.

    A Protocol rather than a base class so a real solver can be a thin adapter
    over an external package without inheriting from this repository.
    """

    domain: Domain
    name: str

    # The bodies are structural declarations, never executed: a Protocol
    # describes a shape, and the implementations live in adapters elsewhere.
    # Marked rather than left as an unexplained partial branch, and rather than
    # given a test that would only be exercising `...`.
    def applicable_to(self, world: World) -> bool: ...  # pragma: no cover

    def run(self, world: World) -> SolverResult: ...  # pragma: no cover


class Laboratory:
    """A registry of solvers, and the rules for when they may answer."""

    def __init__(self) -> None:
        self._solvers: dict[Domain, Solver] = {}

    def register(self, solver: Solver) -> None:
        existing = self._solvers.get(solver.domain)
        if existing is not None:
            raise ValueError(
                f"{solver.domain.value} is already served by {existing.name!r}; "
                "two solvers for one domain would make the lab pick silently between physics models"
            )
        self._solvers[solver.domain] = solver

    def select(self, domain: Domain) -> Solver | None:
        """The solver for a domain, or None. Selecting is not running."""
        return self._solvers.get(domain)

    def served_domains(self) -> tuple[Domain, ...]:
        return tuple(self._solvers)

    def assess(self, world: World, domain: Domain) -> Finding:
        """Answer one question about `world`, or say honestly that nothing can."""
        solver = self._solvers.get(domain)
        if solver is None:
            return Finding(
                domain=domain,
                assurance=Assurance.NOT_ASSESSED,
                reason=f"no solver is registered for the {domain.value} domain",
            )

        try:
            applicable = solver.applicable_to(world)
        except Exception as exc:  # a solver that cannot decide has not decided
            return Finding(
                domain=domain,
                assurance=Assurance.NOT_ASSESSED,
                reason=f"{solver.name} failed while deciding applicability: {exc}",
                solver=solver.name,
            )

        if not applicable:
            return Finding(
                domain=domain,
                assurance=Assurance.NOT_ASSESSED,
                reason=f"{solver.name} reports this model is not applicable to it",
                solver=solver.name,
            )

        try:
            result = solver.run(world)
        except Exception as exc:
            # Reported, never swallowed. A default here would be a value nothing
            # computed, wearing the appearance of one that was.
            return Finding(
                domain=domain,
                assurance=Assurance.NOT_ASSESSED,
                reason=f"{solver.name} failed: {exc}",
                solver=solver.name,
            )

        earned = min(result.claims, _SOLVER_CEILING)
        return Finding(
            domain=domain,
            assurance=earned,
            reason=f"{solver.name} ran to completion",
            solver=solver.name,
            summary=result.summary,
            detail=dict(result.detail),
        )

    def assess_all(self, world: World, domains: Iterable[Domain]) -> dict[Domain, Finding]:
        """Every domain asked about appears, including the ones nothing serves."""
        return {domain: self.assess(world, domain) for domain in domains}
