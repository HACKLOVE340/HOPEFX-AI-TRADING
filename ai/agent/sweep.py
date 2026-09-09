# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The scheduled health sweep — `ai/agent/loop.py`'s production caller.

`loop.py` built Think → Execute → Monitor → Improve, and `ai/hub/capabilities.py`
cites `ai.agent.loop` as the evidence that `arch.layer_b.intelligence` is
**live**. It was not: nothing outside `ai/agent/` and its own tests imported it.
`verify()` resolved the row anyway, because the module imports and the symbol
exists — which is not the same question as whether anything runs it. That is
defect F176's shape exactly, and the registry cannot see it, because "the
evidence resolves" and "a caller exists" are different claims.

The loop's docstring names the caller it was designed for:

    "A deterministic planner is what the tests drive and what a scheduled
     health sweep wants."

This is that sweep, and it is deliberately the smallest real caller that makes
the claim true. A model-driven planner is the same interface and can replace
this one later; doing the deterministic one first means the wiring is proven
before a language model is anywhere near the tool bus.

## Why the planner is not "any action that needs no arguments"

That was the first design, and it is wrong in a way worth recording. Measured
against the live registry, **every** READ_ONLY handler defaults all of its
parameters — so "callable with no arguments" admits
`markets_execution.shadow_place_order`, `platform_engineering.run_tests`,
`research_intelligence.run_backtest` and `walk_forward_validate`. A sweep on a
timer would then place shadow orders into the audit trail every interval, and
run the test suite and a backtest on the same box that is executing trades.

So the sweep names the *health checks* it wants, by the action's suffix, and
**intersects that with `context.permitted`** — the allowlist the loop computed
from the department's own registry. The intersection is what makes the named
set safe: it can only ever narrow what the loop already allowed, never widen
it. If a check is renamed in the registry, this sweep calls one thing fewer,
which is the direction an error here must fail in.

## What this must never become

The loop refuses anything outside `permitted_actions(department)` before it
reaches the bus, and the bus consults the permission registry and
`enforce_agent_action` again. This module adds a third narrowing on top of
those two. It must never be the place that widens any of them — no action name
is dispatched from here that did not come out of `context.permitted`.
"""

from __future__ import annotations

import logging
from typing import Any

from ai.agent.loop import LoopBudget, LoopContext, LoopRun, Plan, run_loop

logger = logging.getLogger(__name__)

#: Action suffixes this sweep is willing to call, intersected with whatever the
#: loop permits for the department. Deliberately a *statement of intent* rather
#: than a derived set — see the module docstring for why "needs no arguments"
#: is not a usable filter here. Adding a name to this set can never grant an
#: action the registry does not already class READ_ONLY and permit.
HEALTH_CHECKS: frozenset[str] = frozenset(
    {
        "service_health",
        "host_resources",
        "recent_failures",
        "feed_health",
        "stale_sources",
        "memory_health",
        "describe_retention",
        "check_drawdown",
        "pending_notifications",
        "describe_policy",
        "vision_status",
        "query_broker_status",
    }
)


def sweepable_actions(permitted: tuple[str, ...]) -> tuple[str, ...]:
    """The health checks available to this run, in a stable order.

    `permitted` is the loop's own allowlist. Everything returned came out of
    it; nothing is added.
    """
    return tuple(action for action in permitted if action.split(".", 1)[-1] in HEALTH_CHECKS)


def health_sweep_planner(context: LoopContext) -> Plan:
    """Choose the next health check that has not been run yet, then stop.

    Deterministic on purpose: the same platform state produces the same sweep,
    so a difference between two runs is a difference in the platform rather
    than in the planner.
    """
    already_called = {observation.get("tool") for observation in context.observations}
    for action in sweepable_actions(context.permitted):
        if action not in already_called:
            return Plan(
                action=action,
                rationale=f"health sweep: {action} has not been checked in this run",
            )
    return Plan(action=None, rationale="health sweep: every available check has been run")


def run_health_sweep(
    *,
    bus: Any,
    operator: str = "system",
    department: str = "system_ops",
    budget: LoopBudget | None = None,
) -> LoopRun:
    """Run one bounded health sweep for `department` and return its record.

    The bounds are the loop's, not this module's — passing the budget through
    rather than enforcing anything here keeps one place responsible for
    stopping a runaway loop.
    """
    return run_loop(
        department=department,
        goal=f"sweep {department} for anything needing attention",
        bus=bus,
        operator=operator,
        planner=health_sweep_planner,
        budget=budget,
    )


__all__ = ["HEALTH_CHECKS", "health_sweep_planner", "run_health_sweep", "sweepable_actions"]
