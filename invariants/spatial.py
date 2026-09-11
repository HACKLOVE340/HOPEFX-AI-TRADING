# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.spatial — a generated world may not claim more than it has earned.

`ai/spatial/assurance.py` defines the assurance ladder and makes its rules
available. Available is not enforced. A module holding correct rules that no
decision path consults is this repository's most common defect (F176), and it
would be a particularly expensive one here: the spatial system's output is
persuasive by construction, so the moment a rendered result reaches a decision
without its rung attached, the decision is being made on a picture.

These predicates are the enforcement side, at the boundary where a spatial
result crosses into something that matters — a readiness report, a published
assurance level, a build decision.

Constitutional rules used, both pre-existing — a new constitutional rule is a
platform-governance decision, not a code change:

* **No Unverified AI Decision** — a claim that rose without evidence, a
  composite overstating its weakest part, a readiness granted without a person,
  a result carrying no rung at all.
* **No Silent Failure** — a required aspect missing from a report. Absence reads
  as "nothing wrong here", which is the quietest failure in the set.

Pure, side-effect free, `list[Violation]`. Finite-checked before compared, like
every numeric predicate in this package: `NaN > x` is `False`, so an unguarded
comparison turns a non-finite rung into a silent pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    Violation,
    _is_finite_number,
    _v,
)

# The rung a person must reach for a build to be authorised. Named rather than
# inlined: it is the value most likely to be "just lowered a little" under
# schedule pressure, and a constant is easier to defend in review than a literal.
_APPROVED = 7  # Assurance.HUMAN_APPROVED


def verify_epistemic_monotonicity(previous_rung: Any, current_rung: Any, evidence_added: int) -> list[Violation]:
    """A claim may not move toward 'verified' without new evidence (AOS-EVID-028).

    Falling is always permitted and needs nothing: learning that something is
    worse than believed must never require a permit, or the system sits on stale
    assurance.
    """
    if not _is_finite_number(previous_rung) or not _is_finite_number(current_rung):
        return [
            _v(
                "No Unverified AI Decision",
                CONSTITUTIONAL,
                f"assurance rung is not a finite value (previous={previous_rung!r}, current={current_rung!r})",
            )
        ]
    if current_rung > previous_rung and evidence_added <= 0:
        return [
            _v(
                "No Unverified AI Decision",
                CONSTITUTIONAL,
                "assurance rose with no new evidence",
                previous=int(previous_rung),
                current=int(current_rung),
                evidence_added=evidence_added,
            )
        ]
    return []


def verify_composite_assurance(part_rungs: Iterable[Any], stated_rung: Any) -> list[Violation]:
    """A composite is the MINIMUM of its parts — never the mean, never the best.

    Overstating is the violation; understating is conservative and allowed. A
    composite over no parts may claim nothing above NOT_ASSESSED, because a
    checklist with zero items reporting success is how the count gets gamed.
    """
    rungs = list(part_rungs)
    if not _is_finite_number(stated_rung) or any(not _is_finite_number(r) for r in rungs):
        return [_v("No Unverified AI Decision", CONSTITUTIONAL, "a composite assurance rung is not finite")]
    if not rungs:
        if stated_rung > 0:
            return [
                _v(
                    "No Unverified AI Decision",
                    CONSTITUTIONAL,
                    "a composite over no assessed parts claims an assurance rung",
                    stated=int(stated_rung),
                )
            ]
        return []
    weakest = min(int(r) for r in rungs)
    if stated_rung > weakest:
        return [
            _v(
                "No Unverified AI Decision",
                CONSTITUTIONAL,
                "composite assurance exceeds its weakest part",
                stated=int(stated_rung),
                weakest=weakest,
                parts=len(rungs),
            )
        ]
    return []


def verify_readiness_requires_approval(ready_claimed: bool, aspect_rungs: Mapping[str, Any]) -> list[Violation]:
    """Readiness is granted by a person, never deduced from a solver.

    EXTERNALLY_VERIFIED says the thing is as described. Approval says somebody is
    willing to build it. No amount of the first becomes the second.
    """
    if not ready_claimed:
        return []
    if not aspect_rungs:
        return [
            _v(
                "No Unverified AI Decision",
                CONSTITUTIONAL,
                "readiness claimed over no required aspects — an empty checklist cannot pass",
            )
        ]
    unapproved = sorted(
        aspect for aspect, rung in aspect_rungs.items() if not _is_finite_number(rung) or int(rung) < _APPROVED
    )
    if unapproved:
        return [
            _v(
                "No Unverified AI Decision",
                CONSTITUTIONAL,
                f"readiness claimed while {len(unapproved)} aspect(s) lack human approval: {unapproved}",
                unapproved=unapproved,
            )
        ]
    return []


def verify_no_required_aspect_omitted(
    required_aspects: Iterable[str], reported_aspects: Iterable[str]
) -> list[Violation]:
    """Every required aspect appears in the report, assessed or not.

    A missing row reads as a row with nothing wrong, so a report that quietly
    drops what nobody examined gets shorter as the work gets sloppier.
    """
    missing = sorted(set(required_aspects) - set(reported_aspects))
    if missing:
        return [
            _v(
                "No Silent Failure",
                CRITICAL,
                f"assurance report omits required aspect(s): {missing}",
                missing=missing,
            )
        ]
    return []


def verify_spatial_result_declares_assurance(result_name: str, declared_rung: Any) -> list[Violation]:
    """Nothing crosses out of the spatial system as a bare result.

    A number with no rung is indistinguishable from a measured one at the point
    it is read, which is the whole failure this package exists to prevent.
    """
    if declared_rung is None or not _is_finite_number(declared_rung):
        return [
            _v(
                "No Unverified AI Decision",
                CONSTITUTIONAL,
                f"spatial result {result_name!r} declares no assurance rung",
                result=result_name,
            )
        ]
    return []


# The rung at and above which a claim about structural behaviour stops being a
# restatement of the model and starts being a prediction about a building.
_PREDICTS_REALITY = 4  # Assurance.SIMULATED


def verify_structural_claim_requires_solver(claimed_rung: Any, solver_ran: bool) -> list[Violation]:
    """A structural claim at SIMULATED or above requires a solver to have run.

    `ai.spatial.world.World.removal_impact` returns PROCEDURALLY_GENERATED,
    correctly: the graph repeats what somebody declared about the model. Nothing
    in the type system stops a caller republishing that finding as SIMULATED,
    and "the model says the floor stays up" becoming "the floor stays up" is the
    step that turns a drawing into a demolition decision.

    Checked where the claim is PUBLISHED rather than only where it is produced,
    because a rule enforced solely at its source is a rule enforced by whoever
    remembers it.
    """
    if not _is_finite_number(claimed_rung):
        return [
            _v(
                "No Unverified AI Decision",
                CONSTITUTIONAL,
                f"structural claim declares a non-finite assurance rung ({claimed_rung!r})",
            )
        ]
    if int(claimed_rung) >= _PREDICTS_REALITY and not solver_ran:
        return [
            _v(
                "No Unverified AI Decision",
                CONSTITUTIONAL,
                "structural claim asserts simulated-or-better assurance with no solver run",
                claimed=int(claimed_rung),
                minimum_requiring_a_solver=_PREDICTS_REALITY,
            )
        ]
    return []
