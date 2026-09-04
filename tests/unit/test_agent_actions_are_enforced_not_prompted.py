# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
An agent's permission scope must be enforced, not prompted.

`docs/audit/AI_CORE_SPEC_INTAKE.md` names this the load-bearing requirement of
the entire AI Core build, quoting the spec back at itself:

> per-agent permission scoping enforced at the tool layer, not just prompted —
> so a compromised agent can't call an action outside its scope even if tricked.

and states the acceptance criterion to adopt **before any agent code is
written**:

> a test that constructs an agent, calls an action outside its scope directly
> (bypassing the prompt), and **fails the build if the call succeeds**. Same for
> the approval queue: a test that executes a proposal without an approval record
> and fails if anything moves. Without those, this spec describes F176 at a
> larger scale.

This file is those tests.

The predicates already existed — `verify_agent_action_authorized`,
`verify_tool_allowed`, `verify_agent_no_self_escalation`,
`verify_agent_authority`, `verify_autonomous_capital_limit`,
`verify_no_self_replication`, `verify_autonomous_strategy_control` — sixteen
CONSTITUTIONAL checks across `invariants/ai.py` and
`invariants/ai_governance.py`, covering exactly what the spec promises.

**Not one of them was reachable from an enforcement path.** `ai_governance` was
imported by nothing outside its own tests, there was no `agent_action` kind in
`KNOWN_KINDS`, and no `enforce_agent_*` wrapper existed. A control that is
written, documented and never invoked is this codebase's signature defect
(F177, and the `hopefx-dead-controls` skill); building the AI Core on top of it
would have been that defect with more autonomy.

Note on mode: `HOPEFX_INVARIANT_MODE` defaults to `monitor`, where `allowed` is
True even for a CONSTITUTIONAL violation. These tests assert **both** halves —
that the violation is *detected* whatever the mode, and that it is *refused* in
`enforce`. A gate that only detects is the thing being fixed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def enforcing(monkeypatch):
    """Run the constitution in enforce mode for this test."""
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    monkeypatch.delenv("HOPEFX_INVARIANT_KINDS_OFF", raising=False)
    monkeypatch.delenv("HOPEFX_INVARIANT_KINDS_MONITOR", raising=False)
    from invariants import enforcement

    return enforcement


@pytest.fixture
def monitoring(monkeypatch):
    from invariants import enforcement

    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    return enforcement


def _agent(**overrides):
    """A well-formed action request from an agent with a narrow scope."""
    request = {
        "agent_id": "research-1",
        "action": "propose_strategy",
        "allowed_actions": {"propose_strategy", "read_market_data"},
        "tool": "market_data.read",
        "allowed_tools": {"market_data.read"},
    }
    request.update(overrides)
    return request


# ── Acceptance criterion 1: scope is enforced at the tool layer ──────────────


def test_an_action_outside_scope_is_refused(enforcing):
    """The criterion, stated literally: call an action outside the agent's scope
    directly, bypassing any prompt. If this passes, the scope is decorative."""
    result = enforcing.enforce_agent_action(_agent(action="place_order"))

    assert result.allowed is False, (
        "an agent called an action outside its granted scope and the platform allowed it — "
        "the permission scope is prompt-level only"
    )
    assert any("place_order" in v.message for v in result.violations)


def test_a_tool_outside_scope_is_refused(enforcing):
    """'Enforced at the tool layer' is the spec's own wording: the action name
    passing is not enough if the tool it reaches for is not granted."""
    result = enforcing.enforce_agent_action(_agent(tool="broker.place_order"))

    assert result.allowed is False, "an agent invoked a tool outside its grant"


def test_an_agent_cannot_widen_its_own_permissions(enforcing):
    result = enforcing.enforce_agent_action(_agent(modified_own_permissions=True))

    assert result.allowed is False, "an agent modified its own permissions and the action proceeded"


def test_an_in_scope_action_is_allowed(enforcing):
    """The gate must not simply refuse everything — that would pass every test
    above while making the platform useless, and would be indistinguishable
    from a working control until someone tried to use it."""
    result = enforcing.enforce_agent_action(_agent())

    assert result.allowed is True, f"a well-formed in-scope action was refused: {result.reason}"
    assert result.violations == []


# ── Acceptance criterion 2: the approval queue is enforced ───────────────────


def test_an_action_requiring_approval_is_refused_without_an_approval_record(enforcing):
    """The spec: "Nothing places a trade, deploys code, rotates a credential, or
    changes a setting without passing through the superadmin approval queue."
    Executed without an approval record, nothing may move."""
    result = enforcing.enforce_agent_action(
        _agent(
            action="deploy_strategy",
            allowed_actions={"deploy_strategy"},
            tool="deploy.strategy",
            allowed_tools={"deploy.strategy"},
            approval_required={"deploy_strategy", "place_order", "rotate_credential", "change_setting"},
        )
    )

    assert result.allowed is False, (
        "an action on the approval-required list executed with no approval record — "
        "the approval queue is enforced by convention only"
    )


def test_an_approved_action_proceeds(enforcing):
    result = enforcing.enforce_agent_action(
        _agent(
            action="deploy_strategy",
            allowed_actions={"deploy_strategy"},
            tool="deploy.strategy",
            allowed_tools={"deploy.strategy"},
            approval_required={"deploy_strategy"},
            approved_by="superadmin-1",
            human_approved=True,
        )
    )

    assert result.allowed is True, f"an approved action was refused: {result.reason}"


def test_an_empty_approver_is_not_an_approval(enforcing):
    """A blank string is the shape a missing field takes when it travels through
    JSON. It must not read as a named human."""
    for approver in ("", "   ", None):
        result = enforcing.enforce_agent_action(
            _agent(
                action="rotate_credential",
                allowed_actions={"rotate_credential"},
                tool="vault.rotate",
                allowed_tools={"vault.rotate"},
                approval_required={"rotate_credential"},
                approved_by=approver,
            )
        )
        assert result.allowed is False, f"approver {approver!r} was accepted as a human approval"


# ── The autonomy limits the spec promises ────────────────────────────────────


def test_an_agent_cannot_allocate_beyond_its_capital_limit(enforcing):
    result = enforcing.enforce_agent_action(_agent(capital_allocated=50_000.0, capital_limit=10_000.0))

    assert result.allowed is False, "an agent allocated capital beyond its hard limit"


def test_an_agent_cannot_spawn_sub_agents_without_approval(enforcing):
    result = enforcing.enforce_agent_action(_agent(spawned_agents=3, spawn_approved=False))

    assert result.allowed is False, "an agent spawned an uncontrolled agent chain"


def test_a_strategy_cannot_reach_production_without_a_human(enforcing):
    result = enforcing.enforce_agent_action(_agent(strategy_auto_deployed=True, human_approved=False))

    assert result.allowed is False, "a strategy was auto-deployed to production with no human approval"


# ── The gate must exist, and be visible ──────────────────────────────────────


def test_the_violation_is_detected_even_in_monitor_mode(monitoring):
    """Monitor mode allows the action — that is its documented purpose — but the
    violation must still be recorded, or switching to enforce would be a leap in
    the dark."""
    result = monitoring.enforce_agent_action(_agent(action="place_order"))

    assert result.allowed is True, "monitor mode should not block"
    assert result.violations, "monitor mode recorded no violation — the check did not run"


def test_agent_action_is_a_known_enforcement_kind():
    """A kind absent from KNOWN_KINDS has no per-kind mode override and does not
    appear in the enforcement status endpoint — it would be invisible to an
    operator asking what is switched on."""
    from invariants.enforcement import KNOWN_KINDS

    assert "agent_action" in KNOWN_KINDS


def test_the_ai_governance_predicates_are_reachable_from_enforcement():
    """The finding this file closes: sixteen CONSTITUTIONAL predicates governing
    agent autonomy, imported by nothing outside their own tests."""
    import inspect

    from invariants import enforcement

    source = inspect.getsource(enforcement)
    for predicate in (
        "verify_agent_action_authorized",
        "verify_tool_allowed",
        "verify_agent_no_self_escalation",
        "verify_autonomous_capital_limit",
        "verify_no_self_replication",
        "verify_autonomous_strategy_control",
    ):
        assert predicate in source, f"{predicate} is still unreachable from any enforcement path"
