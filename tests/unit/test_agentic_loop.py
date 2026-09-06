# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Spec §3 concept 1: "wire Think → Execute → Monitor → Improve explicitly".

The spec's own scorecard marked agentic loops "implicit only". Measured, they
were absent: grep the tree for think/execute/monitor/improve as a cycle and
nothing comes back. Departments could answer one question per request and had no
way to take a second step based on the first answer.

This is `agent/` — the last of spec §2's four anatomy parts, after actions/
(built), memory/ and awareness/ (the two previous commits).

**Three bounds, all of them hard.** A loop that can call itself is the ordinary
way an AI system runs away: it spends a monthly budget in minutes, or spins
forever on a condition it cannot resolve. Steps, wall-clock and tool calls are
each capped, and hitting any cap stops the loop with a named reason rather than
silently continuing.

**The planner may only choose read-only actions.** Not "should not" — the
allowlist is computed from the department's own registry and a choice outside it
is refused before it reaches the bus. The bus would refuse a write action anyway
(unimplemented, and gated on approval plus live mode), but a loop that can
attempt one is a loop one registry edit away from placing an order.

These tests fail on the pre-fix tree — `ai.agent` does not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    from ai.memory import store

    store.reset_for_testing()
    yield
    store.reset_for_testing()


def _bus():
    from ai.departments import build_tool_bus

    return build_tool_bus(live_mode=False)


def _run(planner, *, department="risk_compliance", **over):
    from ai.agent.loop import LoopBudget, run_loop

    kwargs = {
        "department": department,
        "goal": "check whether anything needs attention",
        "bus": _bus(),
        "operator": "owner",
        "planner": planner,
        "budget": LoopBudget(max_steps=6, max_tool_calls=4, max_seconds=5.0),
    }
    kwargs.update(over)
    return run_loop(**kwargs)


def _planner_calling(*tools):
    """A planner that requests each tool in turn, then stops."""
    queue = list(tools)

    def planner(_context):
        from ai.agent.loop import Plan

        if not queue:
            return Plan(action=None, rationale="nothing further to check")
        return Plan(action=queue.pop(0), rationale="next check")

    return planner


# ── the cycle ─────────────────────────────────────────────────────────────────


def test_the_loop_runs_a_full_cycle_and_reports_its_steps():
    run = _run(_planner_calling("risk_compliance.check_drawdown"))

    phases = [step.phase for step in run.steps]
    for phase in ("think", "execute", "monitor", "improve"):
        assert phase in phases, f"the {phase} phase never ran"


def test_a_planner_that_asks_for_nothing_stops_immediately():
    run = _run(_planner_calling())
    assert run.stopped_reason == "planner_finished"
    assert run.tool_calls == 0


def test_the_loop_takes_a_second_step_based_on_the_first():
    """The thing a single request could not do."""
    run = _run(
        _planner_calling(
            "risk_compliance.check_drawdown",
            "risk_compliance.validate_position_size",
        )
    )
    assert run.tool_calls == 2
    assert run.stopped_reason == "planner_finished"


def test_every_tool_result_is_available_to_the_next_think():
    """Otherwise it is two independent calls, not a loop."""
    seen = []

    def planner(context):
        from ai.agent.loop import Plan

        seen.append(len(context.observations))
        if len(context.observations) >= 2:
            return Plan(action=None, rationale="enough")
        return Plan(action="risk_compliance.check_drawdown", rationale="look")

    _run(planner)
    assert seen == [0, 1, 2], f"the planner did not see results accumulate: {seen}"


# ── the bounds ────────────────────────────────────────────────────────────────


def test_the_step_budget_stops_a_runaway():
    """A planner that never finishes must not run forever."""
    from ai.agent.loop import Plan

    run = _run(lambda _c: Plan(action="risk_compliance.check_drawdown", rationale="again"))
    assert run.stopped_reason in {"step_budget_exhausted", "tool_call_budget_exhausted"}


def test_the_tool_call_budget_is_enforced():
    from ai.agent.loop import LoopBudget, Plan

    run = _run(
        lambda _c: Plan(action="risk_compliance.check_drawdown", rationale="again"),
        budget=LoopBudget(max_steps=50, max_tool_calls=3, max_seconds=5.0),
    )
    assert run.tool_calls == 3
    assert run.stopped_reason == "tool_call_budget_exhausted"


def test_the_wall_clock_ceiling_is_enforced():
    from ai.agent.loop import LoopBudget, Plan

    run = _run(
        lambda _c: Plan(action="risk_compliance.check_drawdown", rationale="again"),
        budget=LoopBudget(max_steps=1000, max_tool_calls=1000, max_seconds=0.0),
    )
    assert run.stopped_reason == "time_budget_exhausted"


def test_a_stopped_loop_says_why_rather_than_looking_finished():
    from ai.agent.loop import LoopBudget, Plan

    run = _run(
        lambda _c: Plan(action="risk_compliance.check_drawdown", rationale="again"),
        budget=LoopBudget(max_steps=2, max_tool_calls=50, max_seconds=5.0),
    )
    assert run.completed is False, "an exhausted loop reported itself as completed"
    assert run.stopped_reason


# ── the safety boundary ───────────────────────────────────────────────────────


def test_the_planner_cannot_choose_a_write_action():
    """The allowlist is computed, not trusted."""
    from ai.agent.loop import Plan

    run = _run(
        lambda _c: Plan(action="markets_execution.place_order", rationale="I want to trade"),
        department="markets_execution",
    )
    assert run.tool_calls == 0, "a write action reached the bus"
    assert run.stopped_reason == "planner_chose_a_forbidden_action"


def test_the_planner_cannot_reach_another_departments_tools():
    from ai.agent.loop import Plan

    run = _run(
        lambda _c: Plan(action="platform_engineering.scan_secrets", rationale="curious"),
        department="risk_compliance",
    )
    assert run.tool_calls == 0
    assert run.stopped_reason == "planner_chose_a_forbidden_action"


def test_an_unknown_action_is_refused_not_attempted():
    from ai.agent.loop import Plan

    run = _run(lambda _c: Plan(action="risk_compliance.launch_missiles", rationale="no"))
    assert run.tool_calls == 0
    assert run.stopped_reason == "planner_chose_a_forbidden_action"


def test_the_allowlist_contains_only_read_only_actions():
    from ai.agent.loop import permitted_actions
    from ai.departments import action_by_name
    from core.ai_tool_permissions import ToolRisk

    for department in ("markets_execution", "risk_compliance"):
        for name in permitted_actions(department):
            assert action_by_name(name).risk == ToolRisk.READ_ONLY, f"{name} is not read-only"


def test_every_call_goes_through_the_bus():
    """Not around it. The bus is where the two gates live."""
    calls = []

    class _SpyBus:
        def invoke(self, tool, **kwargs):
            calls.append(tool)
            from ai.tools.bus import ToolResult

            return ToolResult(tool=tool, allowed=True, value={"ok": True})

    _run(_planner_calling("risk_compliance.check_drawdown"), bus=_SpyBus())
    assert calls == ["risk_compliance.check_drawdown"]


def test_a_refused_tool_stops_the_loop_rather_than_being_retried():
    """A refusal is an answer. Looping on it would hammer a closed gate."""
    from ai.tools.bus import ToolDenied

    class _RefusingBus:
        def invoke(self, tool, **kwargs):
            raise ToolDenied(("agent_action_refused",), f"{tool}: refused")

    run = _run(_planner_calling("risk_compliance.check_drawdown"), bus=_RefusingBus())
    assert run.stopped_reason == "tool_refused"
    assert run.completed is False


# ── the record ────────────────────────────────────────────────────────────────


def test_the_run_is_written_to_department_memory():
    """A loop nobody can inspect afterwards is a black box."""
    from ai.memory.store import recall

    _run(_planner_calling("risk_compliance.check_drawdown"))

    runs = recall("risk_compliance", kind="loop_run")
    assert len(runs) == 1
    assert runs[0]["value"]["goal"]


def test_the_recorded_run_names_every_tool_it_called():
    from ai.memory.store import recall

    _run(_planner_calling("risk_compliance.check_drawdown", "risk_compliance.validate_position_size"))
    recorded = recall("risk_compliance", kind="loop_run")[0]["value"]
    assert "risk_compliance.check_drawdown" in recorded["tools_called"]


def test_a_forbidden_choice_is_recorded_too():
    """Refusing quietly would hide a planner repeatedly trying to trade."""
    from ai.agent.loop import Plan
    from ai.memory.store import recall

    _run(
        lambda _c: Plan(action="markets_execution.place_order", rationale="trade"),
        department="markets_execution",
    )
    recorded = recall("markets_execution", kind="loop_run")[0]["value"]
    assert recorded["stopped_reason"] == "planner_chose_a_forbidden_action"


# ── parameters ────────────────────────────────────────────────────────────────
# Without these the loop can only call zero-argument tools, which excludes the
# one execution decision it most needs to make.


def test_a_plan_can_carry_tool_parameters():
    from ai.agent.loop import Plan
    from ai.memory.store import recall

    run = _run(
        lambda c: (
            Plan(action=None, rationale="done")
            if c.observations
            else Plan(
                action="markets_execution.shadow_place_order",
                rationale="size a position",
                params={"symbol": "XAUUSD", "side": "buy", "quantity": 0.5},
            )
        ),
        department="markets_execution",
    )
    assert run.tool_calls == 1
    assert run.completed is True

    shadow = recall("markets_execution", kind="shadow_order")
    assert shadow[0]["value"]["would_have"]["symbol"] == "XAUUSD"


def test_a_planner_cannot_smuggle_authority_through_a_parameter_name():
    """The defect adding params surfaced, asserted at the loop boundary."""
    from ai.agent.loop import Plan

    run = _run(
        lambda _c: Plan(
            action="risk_compliance.check_drawdown",
            rationale="escalate",
            params={"approved_by": "superadmin"},
        )
    )
    assert run.tool_calls == 0
    assert run.stopped_reason == "tool_refused"
