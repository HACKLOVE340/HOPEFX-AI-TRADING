# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A rendered thing is not a verified thing.

The spatial system generates convincing artifacts: a house that looks built, a
car that looks engineered, a simulation that returns a number. Every one of them
is an unmeasured value presented as though something had measured it — the exact
defect class this repository has spent a programme removing, with the largest
blast radius yet, because the output is *beautiful* and beauty reads as
correctness.

So a spatial claim carries its assurance rung, and the rules below are what stop
"the render is finished" from becoming "the house is safe to build".

The four rules, each tested here:

1. A claim rises only on evidence that supports the rung (AOS-EVID-028).
2. A claim may always fall. New contradicting information needs no permit.
3. A composite is the MINIMUM of its parts, never the maximum or the mean.
4. Readiness is never inferred from assurance, however high.

And the floor: an aspect nobody assessed is NOT_ASSESSED and appears in the
report. Omitting it reads as fine (Rule 2 — an unmeasured value is absent, never
best-case).
"""

from __future__ import annotations

import pytest

from ai.spatial.assurance import (
    Assurance,
    AssuranceRefused,
    Claim,
    Evidence,
    overall,
    readiness_report,
    raise_to,
)

pytestmark = pytest.mark.unit


def _ev(supports: Assurance, kind: str = "simulation", ref: str = "run-1") -> Evidence:
    return Evidence(kind=kind, reference=ref, supports=supports)


# ── The ladder itself ───────────────────────────────────────────────────────


def test_the_rungs_are_ordered_lowest_to_highest() -> None:
    assert (
        Assurance.NOT_ASSESSED
        < Assurance.VISUALIZED
        < Assurance.PROCEDURALLY_GENERATED
        < Assurance.ESTIMATED
        < Assurance.SIMULATED
        < Assurance.VALIDATED
        < Assurance.EXTERNALLY_VERIFIED
        < Assurance.HUMAN_APPROVED
    )


def test_an_unassessed_aspect_is_the_default_not_an_absence() -> None:
    """A claim with no evidence is NOT_ASSESSED — it is not omitted, and it is
    not optimistically VISUALIZED."""
    assert Claim(aspect="fire_safety").assurance is Assurance.NOT_ASSESSED


# ── Rule 1: rising requires evidence that supports the rung ─────────────────


def test_a_claim_cannot_rise_without_evidence() -> None:
    claim = Claim(aspect="structural")
    with pytest.raises(AssuranceRefused, match="no evidence"):
        raise_to(claim, Assurance.SIMULATED, evidence=None)


def test_a_claim_cannot_rise_above_what_its_evidence_supports() -> None:
    """A simulation run is evidence for SIMULATED. It is not evidence that a
    human approved anything."""
    claim = Claim(aspect="structural")
    with pytest.raises(AssuranceRefused, match="supports at most"):
        raise_to(claim, Assurance.HUMAN_APPROVED, evidence=_ev(Assurance.SIMULATED))


def test_a_claim_rises_when_the_evidence_supports_it() -> None:
    claim = raise_to(Claim(aspect="structural"), Assurance.SIMULATED, evidence=_ev(Assurance.SIMULATED))
    assert claim.assurance is Assurance.SIMULATED
    assert len(claim.evidence) == 1


def test_the_evidence_is_retained_so_a_claim_can_be_audited() -> None:
    claim = Claim(aspect="structural")
    claim = raise_to(claim, Assurance.ESTIMATED, evidence=_ev(Assurance.ESTIMATED, ref="heuristic-a"))
    claim = raise_to(claim, Assurance.SIMULATED, evidence=_ev(Assurance.SIMULATED, ref="fea-run-42"))
    assert [e.reference for e in claim.evidence] == ["heuristic-a", "fea-run-42"]


# ── Rule 2: falling is always allowed ───────────────────────────────────────


def test_a_claim_may_always_fall_without_evidence() -> None:
    """Learning that something is worse than believed must never require a
    permit. A system that made downgrades expensive would hold stale assurance."""
    claim = raise_to(Claim(aspect="aero"), Assurance.SIMULATED, evidence=_ev(Assurance.SIMULATED))
    dropped = raise_to(claim, Assurance.VISUALIZED, evidence=None)
    assert dropped.assurance is Assurance.VISUALIZED


# ── Rule 3: a composite is the minimum of its parts ─────────────────────────


def test_the_overall_assurance_is_the_weakest_part() -> None:
    """THE rule. A structural simulation that passed does not make an
    unverified building code claim safe — the design as a whole is only as
    sound as the thing nobody checked."""
    claims = [
        Claim(aspect="geometry", assurance=Assurance.PROCEDURALLY_GENERATED),
        Claim(aspect="structural", assurance=Assurance.SIMULATED),
        Claim(aspect="code_compliance", assurance=Assurance.NOT_ASSESSED),
    ]
    assert overall(claims) is Assurance.NOT_ASSESSED


def test_overall_is_not_the_average_and_not_the_best() -> None:
    claims = [
        Claim(aspect="a", assurance=Assurance.HUMAN_APPROVED),
        Claim(aspect="b", assurance=Assurance.HUMAN_APPROVED),
        Claim(aspect="c", assurance=Assurance.VISUALIZED),
    ]
    assert overall(claims) is Assurance.VISUALIZED


def test_overall_of_nothing_is_not_assessed_not_an_error_and_not_high() -> None:
    assert overall([]) is Assurance.NOT_ASSESSED


# ── Rule 4: readiness is never inferred ─────────────────────────────────────


def test_a_fully_simulated_design_is_still_not_construction_ready() -> None:
    """The scenario in the brief: the AI must not conclude "this house is safe
    to build" from a clean simulation."""
    claims = [
        Claim(aspect="geometry", assurance=Assurance.PROCEDURALLY_GENERATED),
        Claim(aspect="structural", assurance=Assurance.SIMULATED),
        Claim(aspect="thermal", assurance=Assurance.SIMULATED),
    ]
    report = readiness_report(claims, required=("geometry", "structural", "thermal", "code_compliance"))
    assert report.ready is False
    assert "code_compliance" in report.blocking
    assert report.overall is Assurance.NOT_ASSESSED


def test_a_required_aspect_nobody_assessed_appears_in_the_report() -> None:
    """It must be listed as NOT_ASSESSED, not silently missing. An absent row
    reads as a row with nothing wrong."""
    report = readiness_report([Claim(aspect="geometry")], required=("geometry", "structural"))
    assert report.by_aspect["structural"] is Assurance.NOT_ASSESSED


def test_readiness_requires_human_approval_however_good_the_simulations() -> None:
    claims = [Claim(aspect=a, assurance=Assurance.EXTERNALLY_VERIFIED) for a in ("geometry", "structural")]
    report = readiness_report(claims, required=("geometry", "structural"))
    assert report.overall is Assurance.EXTERNALLY_VERIFIED
    assert report.ready is False, "externally verified is still not a person taking responsibility"


def test_readiness_is_granted_only_when_every_required_aspect_is_human_approved() -> None:
    claims = [Claim(aspect=a, assurance=Assurance.HUMAN_APPROVED) for a in ("geometry", "structural")]
    report = readiness_report(claims, required=("geometry", "structural"))
    assert report.ready is True
    assert report.blocking == ()
