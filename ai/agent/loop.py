# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Think → Execute → Monitor → Improve. Spec §3 concept 1, and §2's `agent/`.

The spec's scorecard marked agentic loops "implicit only"; measured, they were
absent. A department could answer one question per request and had no way to
take a second step based on the first answer — which is the difference between
a query surface and an agent.

This completes spec §2's four-part anatomy: actions/ was built, memory/ and
awareness/ landed in the two previous commits, and this is agent/.

## Three bounds, all hard

A loop that can call itself is the ordinary way an AI system runs away: it
spends a monthly budget in minutes, or spins on a condition it cannot resolve.
Steps, tool calls and wall-clock are each capped, and hitting any cap stops the
run with a named reason. `completed` stays False, so an exhausted loop cannot be
mistaken for a finished one — the distinction the budget module makes between
"a ceiling" and "a report", applied to time.

## The planner may only choose read-only actions

Not "should not". `permitted_actions()` computes the allowlist from the
department's own registry, filtered to `READ_ONLY`, and a choice outside it stops
the run before anything reaches the bus. The bus would refuse a write action
anyway — they are unimplemented, and gated on approval plus live mode — but a
loop that can *attempt* one is a loop one registry edit away from placing an
order. Defence in depth means the loop refuses first.

## Every call goes through the bus

Never around it. The bus is where the permission registry and
`enforce_agent_action` live; a loop with its own dispatch would be a second door
into the same room, which is the shape `ai/policy/roles.py` exists to prevent.

## The planner is pluggable

A deterministic planner is what the tests drive and what a scheduled health
sweep wants. A model-driven planner — the gateway choosing the next action from
the same allowlist, its choice validated by `validate_output` before it is
trusted — is the same interface, and is why the allowlist is computed rather
than passed in.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopBudget:
    """What one run may spend before it is stopped."""

    max_steps: int = 12
    max_tool_calls: int = 6
    max_seconds: float = 60.0


@dataclass(frozen=True)
class Plan:
    """What the planner decided to do next. `action=None` means it is done.

    `params` is what makes the loop useful for anything but zero-argument tools
    — `shadow_place_order` needs a symbol, a side and a quantity, and without
    this the loop could only call tools that take nothing.

    Adding it is also what surfaced the merge-order defect in `ToolBus.invoke`:
    caller context used to be able to overwrite the gate's own `approved_by`.
    The bus now refuses reserved keys outright, so a planner cannot smuggle
    authority through a parameter name.
    """

    action: str | None
    rationale: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    phase: str
    detail: str
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class LoopContext:
    """What the planner is given. Read-only in spirit; it decides, it does not act."""

    department: str
    goal: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    permitted: tuple[str, ...] = ()
    #: What the PLATFORM can do that relates to this goal, derived from the live
    #: route table (`ai/hub/app_surface.py`). Reference only — it is deliberately
    #: a different field from `permitted`, and the two must never be merged.
    #: `permitted` is what the planner may choose; this is what exists. A planner
    #: that treats a line here as callable gets the allowlist refusal below,
    #: which is the correct outcome and is asserted in the loop's tests.
    platform_context: str = ""


@dataclass
class LoopRun:
    department: str
    goal: str
    steps: list[Step] = field(default_factory=list)
    tool_calls: int = 0
    tools_called: list[str] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    completed: bool = False
    stopped_reason: str = ""

    def record(self, phase: str, detail: str) -> None:
        self.steps.append(Step(phase=phase, detail=detail))


def permitted_actions(department: str) -> tuple[str, ...]:
    """The read-only, implemented actions this department's agent may choose.

    Computed from the registry rather than listed here, so a new read action is
    available to the loop automatically and a new WRITE action is not — the
    direction that matters if the two are ever confused.
    """
    from ai.departments import DEPARTMENTS, implemented_actions
    from core.ai_tool_permissions import ToolRisk

    if department not in DEPARTMENTS:
        raise ValueError(f"unknown department {department!r}")
    prefix = f"{department}."
    return tuple(
        action.name
        for action in implemented_actions()
        if action.name.startswith(prefix) and action.risk == ToolRisk.READ_ONLY
    )


def _platform_context(goal: str, limit: int = 12) -> str:
    """What the platform can do about this goal, for the planner to read.

    Without this the catalogue in `ai/hub/app_surface.py` is a control nobody
    runs: derived correctly, exposed on an endpoint, and never reaching the one
    place a decision is made. That is the shape of defect F176 in this
    repository — a check that exists, reads correctly, and never executes.

    Failure here is not allowed to stop a run. An agent that cannot describe the
    platform is less informed; an agent that crashes because it could not is
    worse, and this is context, not a gate.
    """
    try:
        from ai.hub.app_surface import describe_app

        return describe_app().as_prompt(goal, limit=limit)
    except Exception:
        logger.warning("ai.agent: platform context unavailable for this run", exc_info=True)
        return ""


def run_loop(
    *,
    department: str,
    goal: str,
    bus: Any,
    operator: str,
    planner: Callable[[LoopContext], Plan],
    budget: LoopBudget | None = None,
) -> LoopRun:
    """Run one bounded Think → Execute → Monitor → Improve cycle."""
    budget = budget or LoopBudget()
    permitted = permitted_actions(department)
    run = LoopRun(department=department, goal=goal)
    context = LoopContext(
        department=department,
        goal=goal,
        permitted=permitted,
        platform_context=_platform_context(goal),
    )
    started = time.monotonic()

    for _ in range(budget.max_steps):
        # Time is checked at the top of every step rather than only at the end:
        # a ceiling that can only be noticed after the work is a report.
        if time.monotonic() - started >= budget.max_seconds:
            run.stopped_reason = "time_budget_exhausted"
            break

        # ── Think ────────────────────────────────────────────────────────────
        try:
            plan = planner(context)
        except Exception as exc:
            logger.exception("ai.agent: planner failed for %s", department)
            run.record("think", f"planner failed: {exc}")
            run.stopped_reason = "planner_failed"
            break
        run.record("think", plan.rationale or "(no rationale given)")

        if plan.action is None:
            run.completed = True
            run.stopped_reason = "planner_finished"
            break

        # The allowlist check, before anything reaches the bus.
        if plan.action not in permitted:
            run.record("think", f"refused: {plan.action} is not permitted for {department}")
            run.stopped_reason = "planner_chose_a_forbidden_action"
            break

        if run.tool_calls >= budget.max_tool_calls:
            run.stopped_reason = "tool_call_budget_exhausted"
            break

        # ── Execute ──────────────────────────────────────────────────────────
        try:
            result = bus.invoke(
                plan.action,
                operator=operator,
                allowed_actions={plan.action},
                **plan.params,
            )
        except Exception as exc:
            # A refusal is an ANSWER. Retrying it would hammer a closed gate,
            # and the same rule the gateway follows for guardrail rejections
            # applies here: do not loop on a decision.
            run.record("execute", f"{plan.action} was refused: {exc}")
            run.stopped_reason = "tool_refused"
            break

        run.tool_calls += 1
        run.tools_called.append(plan.action)
        run.record("execute", f"called {plan.action}")

        # ── Monitor ──────────────────────────────────────────────────────────
        observation = {"tool": plan.action, "value": getattr(result, "value", None)}
        run.observations.append(observation)
        context.observations.append(observation)
        run.record("monitor", f"observed {plan.action}")

        # ── Improve ──────────────────────────────────────────────────────────
        # The next Think sees every observation so far, which is what makes this
        # a loop rather than a sequence of independent calls.
        run.record("improve", f"{len(context.observations)} observation(s) available to the next step")
    else:
        run.stopped_reason = run.stopped_reason or "step_budget_exhausted"

    _remember(run)
    return run


def _remember(run: LoopRun) -> None:
    """Persist the run, so a loop is auditable rather than a black box.

    Recorded whatever the outcome, including a refused or forbidden one: a
    planner repeatedly trying to place an order is exactly the thing that must
    not be discoverable only from a log nobody reads.
    """
    try:
        from ai.memory.store import remember

        remember(
            run.department,
            "loop_run",
            {
                "goal": run.goal,
                "completed": run.completed,
                "stopped_reason": run.stopped_reason,
                "tool_calls": run.tool_calls,
                "tools_called": list(run.tools_called),
                "steps": [asdict(step) for step in run.steps],
            },
        )
    except Exception:
        logger.exception("ai.agent: could not record the loop run for %s", run.department)


__all__ = ["LoopBudget", "LoopContext", "LoopRun", "Plan", "Step", "permitted_actions", "run_loop"]
