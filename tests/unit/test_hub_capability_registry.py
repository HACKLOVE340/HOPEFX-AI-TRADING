# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Every capability the AI Hub specification names, and whether it really exists.

The specification's §30 is explicit about why this file exists:

    "If a capability cannot be completed immediately, implement the
     architectural interface, capability registry, placeholder contract and
     roadmap integration point so it remains part of the system rather than
     being silently omitted."

So the registry is the anti-omission mechanism. A capability that is not in it
does not exist as far as this project is concerned, and one that is in it cannot
be quietly forgotten — it shows up as `planned` in a count somebody reads.

**The registry must not be able to lie.** `scripts/invariant_coverage.py` is the
cautionary tale in this repository (F176): it "certified" components by counting
hand-typed `True` literals, inspected no code, called no predicate, and could not
print anything but full coverage — while three of the components it certified
were provably unprotected. A registry whose `live` entries are self-declared is
the same defect with a different noun.

So every `live` and `staged` entry carries EVIDENCE — a module path, an attribute,
or a file — and `verify()` resolves it. A capability claiming to be live whose
evidence does not resolve is reported as a discrepancy, not as coverage.

These tests fail on the pre-fix tree — `ai.hub.capabilities` does not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── the registry exists and is honest about its shape ─────────────────────────


def test_the_registry_is_not_empty():
    from ai.hub.capabilities import REGISTRY

    assert len(REGISTRY) > 50, f"only {len(REGISTRY)} capabilities; the spec names far more"


def test_every_capability_has_a_unique_id():
    """A duplicate id means one of them is invisible to every count."""
    from ai.hub.capabilities import REGISTRY

    ids = [c.id for c in REGISTRY]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate capability ids: {sorted(dupes)}"


def test_every_capability_names_the_spec_section_it_comes_from():
    """Traceability in both directions: spec to code, code to spec."""
    from ai.hub.capabilities import REGISTRY

    missing = [c.id for c in REGISTRY if not c.section]
    assert not missing, f"capabilities with no spec section: {missing}"


def test_every_state_is_one_of_the_three():
    from ai.hub.capabilities import REGISTRY, STATES

    bad = [(c.id, c.state) for c in REGISTRY if c.state not in STATES]
    assert not bad, f"capabilities in an unknown state: {bad}"


# ── the spec is covered, section by section ───────────────────────────────────


def test_every_requirement_section_of_the_spec_is_represented():
    """§4 through §27 are the requirement sections. §1-3 and §28-31 are framing,
    method and success criteria rather than capabilities.

    This is the completeness check the whole registry exists for: if a section
    has no capability, that section was dropped.
    """
    from ai.hub.capabilities import REGISTRY

    covered = {c.section for c in REGISTRY}
    required = {str(n) for n in range(4, 28)}
    missing = sorted(required - covered, key=int)
    assert not missing, f"spec sections with no capability entry: §{', §'.join(missing)}"


def test_the_four_layers_are_all_represented():
    from ai.hub.capabilities import REGISTRY

    layers = {c.layer for c in REGISTRY}
    for expected in ("A", "B", "C", "D"):
        assert expected in layers, f"no capability belongs to layer {expected}"


@pytest.mark.parametrize(
    "needle",
    [
        "workspace",  # §8, the core differentiator
        "agent",  # §11-13
        "memory",  # §16
        "voice",  # §17
        "camera",  # §18
        "monitor",  # §19
        "presence",  # §7
        "telemetry",  # §22
    ],
)
def test_the_load_bearing_subjects_are_present(needle):
    from ai.hub.capabilities import REGISTRY

    blob = " ".join(f"{c.id} {c.title}".lower() for c in REGISTRY)
    assert needle in blob, f"nothing in the registry mentions {needle!r}"


def test_the_capabilities_the_spec_claims_exist_but_do_not_are_tracked():
    """§3 lists five things to PRESERVE that are not in this repository. They must
    be in the registry as work, or they vanish — which is exactly the omission
    the registry exists to prevent."""
    from ai.hub.capabilities import REGISTRY

    blob = " ".join(f"{c.id} {c.title}".lower() for c in REGISTRY)
    for absent in ("particle", "cognitive stream", "neural engine", "sleep", "gpu"):
        assert absent in blob, f"§3 names {absent!r} and the registry does not track it"


# ── the registry cannot lie about what is live ────────────────────────────────


def test_a_live_capability_must_carry_evidence():
    from ai.hub.capabilities import REGISTRY

    unevidenced = [c.id for c in REGISTRY if c.state in {"live", "staged"} and not c.evidence]
    assert not unevidenced, f"claimed built with nothing to check: {unevidenced}"


def test_a_planned_capability_carries_no_evidence():
    """Otherwise 'planned' entries accumulate stale pointers that read as progress."""
    from ai.hub.capabilities import REGISTRY

    wrong = [c.id for c in REGISTRY if c.state == "planned" and c.evidence]
    assert not wrong, f"planned capabilities pointing at evidence: {wrong}"


def test_verify_resolves_every_claim_rather_than_trusting_it():
    """The F176 lesson. This is the assertion that makes the registry a
    measurement rather than a declaration."""
    from ai.hub.capabilities import verify

    report = verify()
    assert report.checked > 0, "verify() checked nothing, so it cannot fail"
    assert not report.discrepancies, "capabilities claim to be built and their evidence does not resolve: " + "; ".join(
        f"{d.id} -> {d.detail}" for d in report.discrepancies
    )


def test_verify_catches_a_lie():
    """Prove the check can fail. A verifier that always passes is F176 again."""
    from ai.hub.capabilities import Capability, verify_one

    fake = Capability(
        id="test.invented",
        section="4",
        layer="B",
        title="A capability that does not exist",
        state="live",
        evidence="ai.hub.this_module_does_not_exist",
    )
    problem = verify_one(fake)
    assert problem is not None, "verify_one passed a capability whose evidence cannot resolve"
    assert "this_module_does_not_exist" in problem.detail


def test_verify_accepts_a_real_module():
    from ai.hub.capabilities import Capability, verify_one

    real = Capability(
        id="test.real",
        section="4",
        layer="B",
        title="The gateway, which does exist",
        state="live",
        evidence="ai.gateway.client:GatewayClient",
    )
    assert verify_one(real) is None


def test_evidence_can_point_at_an_attribute_and_the_attribute_is_checked():
    """A module that imports is not proof the thing inside it exists."""
    from ai.hub.capabilities import Capability, verify_one

    bad_attr = Capability(
        id="test.badattr",
        section="4",
        layer="B",
        title="Right module, wrong symbol",
        state="live",
        evidence="ai.gateway.client:NoSuchSymbol",
    )
    problem = verify_one(bad_attr)
    assert problem is not None
    assert "NoSuchSymbol" in problem.detail


# ── what a human reads ────────────────────────────────────────────────────────


def test_coverage_counts_by_state_and_says_what_was_measured():
    """A number with no denominator, and no statement of what was probed, is the
    shape of a report that cannot say 'no'."""
    from ai.hub.capabilities import coverage

    c = coverage()
    assert c["total"] == c["live"] + c["staged"] + c["planned"]
    assert c["total"] > 50
    assert "verified" in c, "coverage does not distinguish what it MEASURED from what it was TOLD"


def test_coverage_is_measured_rather_than_asserted():
    """This used to demand `planned > 20`, which was a snapshot of the day it
    was written and failed as soon as the work it was watching got done.

    The intent behind it survives and is stated properly here: the registry
    must be substantial, must not claim everything is finished while rows are
    still open, and — the part F176 was actually about — must have RESOLVED
    every claim it counts rather than trusting it. A count of hand-typed
    `planned` entries never proved any of that.
    """
    from ai.hub.capabilities import REGISTRY, coverage

    c = coverage()
    assert c["total"] > 200, f"only {c['total']} capabilities — the registry is a stub"
    assert c["total"] == len(REGISTRY)
    assert c["live"] + c["staged"] + c["planned"] == c["total"], "the states do not account for every row"
    assert c["verified"] == c["checked"], "a claim was counted without being resolved"
    assert c["discrepancies"] == [], c["discrepancies"]


# ── it has to be readable, or it is a control nobody runs ─────────────────────


@pytest.mark.asyncio
async def test_an_endpoint_exposes_the_registry():
    """A registry nothing reads is the defect it exists to prevent, one level up.
    §30 wants the roadmap to be part of the system, which means visible from it."""
    from api.ai_core import ai_core_capability_registry
    from api.auth import TokenPayload

    body = await ai_core_capability_registry(TokenPayload(sub="owner", role="superadmin"))
    assert body["total"] > 50
    # Not a floor on `planned`: that number falls as the work lands, and a test
    # that fails because the roadmap is being delivered is measuring the wrong
    # thing. What matters is that the endpoint reports the same accounting the
    # registry does.
    assert body["live"] + body["staged"] + body["planned"] == body["total"]
    assert "verified" in body and "checked" in body


@pytest.mark.asyncio
async def test_the_endpoint_reports_discrepancies_rather_than_hiding_them():
    """If a claim stops resolving — a module renamed, a symbol deleted — the
    endpoint must say so. Silently dropping it would restore F176 exactly."""
    import inspect

    import api.ai_core as core

    src = inspect.getsource(core.ai_core_capability_registry)
    assert "discrepanc" in src.lower(), "the endpoint does not surface failed evidence checks"


def test_the_registry_is_registered_in_the_route_table():
    import inspect

    import api.ai_core as core

    src = inspect.getsource(core)
    assert "/capabilities/registry" in src


# ── evidence in TypeScript is checked as strictly as evidence in Python ───────


def test_a_typescript_locator_can_name_a_symbol_and_the_symbol_is_checked():
    """`path/to/file:Symbol` had no handler: the verifier read the whole string
    as a filename and reported "file does not exist". Half the platform is
    TypeScript, so half the registry had no equivalent of the attribute check —
    a file whose export was renamed would have verified green."""
    from ai.hub.capabilities import Capability, verify_one

    def cap(evidence: str) -> Capability:
        return Capability(id="probe", section="8", layer="D", title="probe", state="live", evidence=evidence, note="")

    assert verify_one(cap("frontend/src/hub/layout.ts:LAYOUTS")) is None

    missing = verify_one(cap("frontend/src/hub/layout.ts:NOT_AN_EXPORT"))
    assert missing is not None
    assert "does not name" in missing.detail

    gone = verify_one(cap("frontend/src/hub/does_not_exist.ts:LAYOUTS"))
    assert gone is not None
    assert "file does not exist" in gone.detail


def test_a_symbol_match_is_word_bounded():
    """Otherwise `LAYOUT` verifies against a file that only mentions
    `DEFAULT_LAYOUTS_LEGACY`, which is the substring problem this repository
    has already been bitten by twice in search code."""
    from ai.hub.capabilities import Capability, verify_one

    partial = verify_one(
        Capability(
            id="probe",
            section="8",
            layer="D",
            title="probe",
            state="live",
            evidence="frontend/src/hub/layout.ts:LAYOUT",
            note="",
        )
    )
    assert partial is not None, "`LAYOUT` matched the file that exports `LAYOUTS`"


def test_a_directory_locator_cannot_claim_a_symbol():
    """Some evidence is a whole directory. Grepping one for a name would make
    the strictest locator shape the loosest, so it is refused instead."""
    from ai.hub.capabilities import Capability, verify_one

    result = verify_one(
        Capability(
            id="probe",
            section="21",
            layer="D",
            title="probe",
            state="live",
            evidence="frontend/src/features/chart-bot:Something",
            note="",
        )
    )
    assert result is not None
    assert "directory" in result.detail
