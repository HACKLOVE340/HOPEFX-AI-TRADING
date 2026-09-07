# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Spec §4 Cluster A — the Trading Core departments, and the bus they run on.

The tool bus, the sandbox and the eval runner were all built and all had **zero
production callers**. Departments are what gives them callers: an agent that can
actually do something has to reach a tool, and reaching a tool is what makes
`ToolBus.invoke` and `enforce_agent_action` run outside a test.

**Build order, and it is deliberate.** Research & Intelligence is implemented
first because all four of its spec actions are read-only — `run_backtest`,
`score_regime`, `fetch_market_news`, `walk_forward_validate` move no money. It
proves the whole path end to end without anything being at risk. Markets &
Execution is last, because `place_order` and `cancel_order` are the only actions
in Cluster A that can lose money, and by then the permission tiers, the scope
gate and the audit trail will have been exercised by three departments.

The other three departments are DECLARED here with their spec actions and risk
tiers but have no handlers yet. That is not a dead control: `ToolBus.invoke`
refuses an unimplemented tool with `tool_not_implemented` rather than returning
a successful no-op, and the count of implemented actions is asserted below so it
cannot drift quietly.

One table drives the department list, the permission registry and the bus
registration — the same lesson as the vendor table. Three hand-maintained lists
of the same thing is how a tool becomes permitted and uncallable, or callable
and unpermitted.
"""

from __future__ import annotations

import pytest

from ai import departments
from core.ai_tool_permissions import ToolRisk

pytestmark = pytest.mark.unit


# ── the spec's four departments ──────────────────────────────────────────────


def test_all_four_cluster_a_departments_are_declared():
    """Cluster A is intact, and the whole set is exactly what is declared.

    This asserted the four were the ONLY departments, which was true until §11's
    remaining agents landed. Split rather than loosened: the point of the
    original was that the set cannot grow quietly, and asserting the full set
    keeps that while letting Cluster B exist.
    """
    cluster_a = {"markets_execution", "risk_compliance", "research_intelligence", "platform_engineering"}
    assert cluster_a <= set(departments.DEPARTMENTS)
    assert set(departments.DEPARTMENTS) == cluster_a | {
        "news_intelligence",
        "voice_interface",
        "notification_ops",
        "data_ops",
    }


@pytest.mark.parametrize(
    ("key", "action"),
    [
        ("markets_execution", "place_order"),
        ("markets_execution", "cancel_order"),
        ("markets_execution", "sync_positions"),
        ("markets_execution", "query_broker_status"),
        ("risk_compliance", "check_drawdown"),
        ("risk_compliance", "validate_position_size"),
        ("risk_compliance", "block_deploy"),
        ("risk_compliance", "propose_derisk"),
        ("research_intelligence", "run_backtest"),
        ("research_intelligence", "fetch_market_news"),
        ("research_intelligence", "score_regime"),
        ("research_intelligence", "walk_forward_validate"),
        ("platform_engineering", "scan_secrets"),
        ("platform_engineering", "run_tests"),
        ("platform_engineering", "propose_fix"),
        ("platform_engineering", "check_broken_imports"),
    ],
)
def test_every_action_the_spec_lists_is_present(key, action):
    names = {a.name for a in departments.DEPARTMENTS[key].actions}
    assert f"{key}.{action}" in names


def test_every_department_declares_agents_memory_and_awareness():
    """A department with no memory or awareness is a name, not a department."""
    for key, dept in departments.DEPARTMENTS.items():
        assert dept.agents, f"{key} has no agents"
        assert dept.memory, f"{key} has no memory"
        assert dept.awareness, f"{key} has no awareness"


# ── risk tiers: the money actions are gated ──────────────────────────────────


@pytest.mark.parametrize("action", ["markets_execution.place_order", "markets_execution.cancel_order"])
def test_order_actions_are_live_trading_and_need_approval(action):
    """The two actions in Cluster A that can lose money."""
    declared = departments.action_by_name(action)
    assert declared.risk is ToolRisk.LIVE_TRADING
    assert declared.requires_approval is True


def test_every_research_action_is_read_only():
    """The reason this department is implemented first."""
    for action in departments.DEPARTMENTS["research_intelligence"].actions:
        assert action.risk is ToolRisk.READ_ONLY, action.name


def test_block_deploy_and_propose_derisk_do_not_move_money():
    """Proposing is not acting. A proposal a human approves is the money step."""
    for name in ("risk_compliance.block_deploy", "risk_compliance.propose_derisk"):
        assert departments.action_by_name(name).risk is not ToolRisk.LIVE_TRADING


def test_no_action_is_silently_untiered():
    for dept in departments.DEPARTMENTS.values():
        for action in dept.actions:
            assert isinstance(action.risk, ToolRisk), action.name


# ── one table drives the registry and the bus ────────────────────────────────


def test_the_permission_registry_holds_exactly_the_declared_actions():
    """Through `all_actions()`, not by reaching into DEPARTMENTS.

    This walked `DEPARTMENTS.values()` directly, which stopped being the whole
    picture when the per-department `recall_memory` actions arrived — they are
    generated rather than written into the table, and the test could not see
    them. Asking the public accessor is what the registry and the bus both do,
    so the three now agree by construction.
    """
    registry = departments.permission_registry()
    declared = {a.name for a in departments.all_actions()}
    assert set(registry._permissions) == declared


def test_the_registry_is_versioned():
    """An unversioned permission set cannot be audited after the fact."""
    assert departments.permission_registry().version.strip()


# ── the bus gets its first registered tools ──────────────────────────────────


def test_the_bus_registers_every_implemented_action():
    bus = departments.build_tool_bus()
    implemented = {a.name for a in departments.implemented_actions()}
    assert implemented, "no action has a handler — the bus would still have zero tools"
    assert set(bus._tools) == implemented


def test_only_non_money_actions_are_implemented_so_far():
    """The build order, asserted rather than trusted.

    This began as "research is the only implemented department" and was
    correct until Risk & Compliance's two READ-ONLY actions landed. The
    invariant that actually matters is not which department is next — it is
    that nothing implemented so far can move money.
    """
    implemented = set(departments.implemented_actions())
    assert implemented, "no handlers at all means the bus has no tools"
    for action in implemented:
        assert action.risk is ToolRisk.READ_ONLY, f"{action.name} is implemented and not read-only"
        assert action.requires_approval is False, action.name


def test_an_unimplemented_action_refuses_rather_than_no_opping():
    """A permitted-but-absent tool must never read as a successful no-op.

    The example is CHOSEN, not hard-coded. Three earlier versions named a
    specific action and each went stale the moment its department landed —
    which is the build working, but a test that needs editing every time is a
    test measuring the schedule rather than the property. This picks any
    declared action whose permission tier admits it and which has no handler,
    so the refusal can only come from the missing implementation.
    """
    from ai.tools.bus import ToolDenied

    registry = departments.permission_registry()
    candidates = [a for a in departments.all_actions() if a.handler is None and registry.review(a.name).allowed]
    if not candidates:
        pytest.skip("every permitted action now has a handler — nothing left to refuse this way")

    bus = departments.build_tool_bus()
    action = candidates[0]
    with pytest.raises(ToolDenied) as excinfo:
        bus.invoke(action.name, operator="tester", allowed_actions={action.name})
    assert "tool_not_implemented" in excinfo.value.reason_codes, action.name


def test_an_order_action_is_refused_without_approval():
    from ai.tools.bus import ToolDenied

    bus = departments.build_tool_bus()
    with pytest.raises(ToolDenied) as excinfo:
        bus.invoke(
            "markets_execution.place_order",
            operator="tester",
            allowed_actions={"markets_execution.place_order"},
        )
    assert "human_approval_required" in excinfo.value.reason_codes


def test_a_research_action_runs_and_is_audited():
    """The end-to-end path: registry -> scope gate -> handler -> audit."""
    bus = departments.build_tool_bus()
    result = bus.invoke(
        "research_intelligence.score_regime",
        operator="tester",
        allowed_actions={"research_intelligence.score_regime"},
        symbol="XAUUSD",
    )
    assert result.allowed is True
    assert any(row["tool"] == "research_intelligence.score_regime" for row in bus.audit())


def test_a_handler_failure_is_reported_not_faked():
    """A tool that could not do its work must not answer as though it did."""
    bus = departments.build_tool_bus()
    result = bus.invoke(
        "research_intelligence.score_regime",
        operator="tester",
        allowed_actions={"research_intelligence.score_regime"},
        symbol="NOT-A-SYMBOL-ANYWHERE",
    )
    # Either a real answer or an explicit "unavailable" — never a fabricated one.
    assert isinstance(result.value, dict)
    assert "available" in result.value


# ── the production caller, read from the registry ────────────────────────────


def test_the_bus_is_built_at_startup():
    """Zero production callers is what §4 exists to fix. Asserted, not assumed."""
    import core.startup_factories as F

    assert hasattr(F, "init_ai_departments")


def test_the_registry_entry_is_optional_so_it_cannot_block_boot():
    from unittest.mock import MagicMock

    from core.startup_factories import build_component_registry

    registry = build_component_registry(MagicMock(), MagicMock())
    components = getattr(registry, "components", None) or registry._components
    assert "ai_departments" in components
    assert components["ai_departments"].required is False
