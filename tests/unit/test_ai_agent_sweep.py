# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The agent loop's production caller.

`ai/agent/loop.py` implements Think → Execute → Monitor → Improve, and is the
evidence `ai/hub/capabilities.py` cites for `arch.layer_b.intelligence` being
**live**. It had no caller: not from `api/`, not from `core/`, not from
anywhere else in `ai/` — only its own tests. `verify()` resolves that row
because the module imports and the symbol exists, which is a different question
from whether anything ever runs it. That gap is the shape this repository keeps
finding (F176): a component that is built, correct, and invoked by nothing.

The loop's own docstring names the caller it was designed for:

    "A deterministic planner is what the tests drive and what a scheduled
     health sweep wants."

This is that sweep. It is deliberately the *smallest* real caller that makes
the claim true, rather than a model-driven planner — the loop already supports
one through the same interface, and choosing the deterministic planner first
means the wiring is proven before an LLM is anywhere near it.

## What must not weaken

The loop refuses any action outside `permitted_actions(department)`, which it
computes from the department's own registry filtered to `READ_ONLY`. The
planner here chooses from `context.permitted` — the allowlist the loop handed
it — and never from a list written in this module, which could drift away from
the registry and start naming actions the registry no longer considers
read-only. The tests below pin that: the planner's choices are asserted against
the live registry, not against a copy.
"""

from __future__ import annotations

import contextlib

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


def _read_only_actions(department: str) -> tuple[str, ...]:
    from ai.agent.loop import permitted_actions

    return permitted_actions(department)


# ── the planner ───────────────────────────────────────────────────────────────


class TestThePlannerStaysInsideTheAllowlist:
    def test_it_only_ever_chooses_actions_the_loop_permitted(self) -> None:
        from ai.agent.loop import LoopContext
        from ai.agent.sweep import health_sweep_planner

        permitted = _read_only_actions("system_ops")
        context = LoopContext(
            department="system_ops",
            goal="health sweep",
            permitted=permitted,
        )

        chosen = []
        for _ in range(20):
            plan = health_sweep_planner(context)
            if plan.action is None:
                break
            assert plan.action in permitted, f"planner chose {plan.action!r}, which the loop did not permit"
            chosen.append(plan.action)
            context.observations.append({"tool": plan.action, "value": None})

        assert chosen, "the planner chose nothing at all — it would prove no wiring"

    def test_it_chooses_from_the_context_not_from_a_hardcoded_list(self) -> None:
        # The allowlist is the loop's, computed from the registry. A planner
        # holding its own copy is one registry edit away from naming an action
        # that is no longer read-only, so it must not have one: given a context
        # permitting exactly one action, that is the only thing it may pick.
        from ai.agent.loop import LoopContext
        from ai.agent.sweep import health_sweep_planner

        only = _read_only_actions("system_ops")[:1]
        context = LoopContext(department="system_ops", goal="health sweep", permitted=only)

        plan = health_sweep_planner(context)
        assert plan.action in (only[0], None)

    def test_it_finishes_rather_than_looping_forever(self) -> None:
        from ai.agent.loop import LoopContext
        from ai.agent.sweep import health_sweep_planner

        permitted = _read_only_actions("system_ops")
        context = LoopContext(department="system_ops", goal="health sweep", permitted=permitted)

        for _ in range(50):
            plan = health_sweep_planner(context)
            if plan.action is None:
                break
            context.observations.append({"tool": plan.action, "value": None})
        else:
            pytest.fail("the planner never returned action=None — the sweep would only stop on a budget")

    def test_it_stops_when_nothing_is_permitted(self) -> None:
        # A department with no read-only actions must end the run cleanly
        # rather than raising or choosing something outside the empty allowlist.
        from ai.agent.loop import LoopContext
        from ai.agent.sweep import health_sweep_planner

        context = LoopContext(department="system_ops", goal="health sweep", permitted=())
        assert health_sweep_planner(context).action is None

    def test_it_gives_a_rationale(self) -> None:
        # The loop records the rationale into the run's steps; an empty one
        # makes the audit trail say "(no rationale given)".
        from ai.agent.loop import LoopContext
        from ai.agent.sweep import health_sweep_planner

        context = LoopContext(
            department="system_ops",
            goal="health sweep",
            permitted=_read_only_actions("system_ops"),
        )
        assert health_sweep_planner(context).rationale.strip()


# ── the sweep, driven through the real loop and the real bus ──────────────────


class TestTheSweepActuallyRuns:
    def test_it_calls_real_read_only_tools(self) -> None:
        from ai.agent.sweep import run_health_sweep

        run = run_health_sweep(bus=_bus(), operator="owner", department="system_ops")

        assert run.tools_called, "the sweep called no tools — the loop is still not wired to anything"
        permitted = set(_read_only_actions("system_ops"))
        for tool in run.tools_called:
            assert tool in permitted, f"{tool} is not a read-only action of system_ops"

    def test_it_completes_rather_than_exhausting_a_budget(self) -> None:
        from ai.agent.sweep import run_health_sweep

        run = run_health_sweep(bus=_bus(), operator="owner", department="system_ops")

        assert run.completed is True, f"sweep did not complete: {run.stopped_reason}"
        assert run.stopped_reason == "planner_finished"

    def test_it_records_observations_the_next_step_can_see(self) -> None:
        from ai.agent.sweep import run_health_sweep

        run = run_health_sweep(bus=_bus(), operator="owner", department="system_ops")
        assert len(run.observations) == len(run.tools_called)

    def test_the_run_is_written_to_memory_for_audit(self) -> None:
        from ai.agent.sweep import run_health_sweep
        from ai.memory import store

        run_health_sweep(bus=_bus(), operator="owner", department="system_ops")

        recorded = store.recall("system_ops", kind="loop_run")
        assert recorded, "the sweep ran but left no auditable record"

    def test_it_respects_a_tighter_budget(self) -> None:
        # The bounds are the loop's, not the sweep's — proving the sweep passes
        # a budget through rather than quietly running unbounded.
        from ai.agent.loop import LoopBudget
        from ai.agent.sweep import run_health_sweep

        run = run_health_sweep(
            bus=_bus(),
            operator="owner",
            department="system_ops",
            budget=LoopBudget(max_steps=2, max_tool_calls=1, max_seconds=5.0),
        )
        assert run.tool_calls <= 1

    def test_it_never_calls_order_shaped_or_expensive_tools(self) -> None:
        # The filter cannot be "a handler that needs no arguments": measured,
        # EVERY read-only handler in the registry defaults all of its
        # parameters, so that rule admits shadow_place_order, run_tests,
        # run_backtest and walk_forward_validate. A sweep on a timer must not
        # place shadow orders into the audit trail, and must not run a backtest
        # or the test suite on the box that is executing trades.
        from ai.agent.sweep import run_health_sweep
        from ai.departments import DEPARTMENTS

        never = {
            "shadow_place_order",
            "shadow_cancel_order",
            "run_tests",
            "run_backtest",
            "walk_forward_validate",
            "describe_image",
            "sync_positions",
        }
        for department in sorted(DEPARTMENTS):
            run = run_health_sweep(bus=_bus(), operator="owner", department=department)
            for tool in run.tools_called:
                assert tool.split(".", 1)[-1] not in never, f"the sweep called {tool}"

    def test_every_department_can_be_swept_without_raising(self) -> None:
        # The sweep must not assume system_ops' particular action names.
        from ai.agent.sweep import run_health_sweep
        from ai.departments import DEPARTMENTS

        for department in sorted(DEPARTMENTS):
            run = run_health_sweep(bus=_bus(), operator="owner", department=department)
            assert run.stopped_reason, f"{department} produced a run with no outcome recorded"


# ── the wiring itself ─────────────────────────────────────────────────────────


class TestItIsRegisteredAsAStartupFactory:
    """A sweep nobody schedules is the same defect one layer up."""

    def test_the_factory_exists_and_is_registered(self) -> None:
        import pathlib

        import core.startup_factories as F

        assert hasattr(F, "init_ai_agent_sweep"), "no startup factory for the agent sweep"
        src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
        assert "F.init_ai_agent_sweep" in src, "the factory is defined but never registered"

    async def test_calling_the_factory_actually_schedules_a_sweep(self) -> None:
        # Registration is not execution. This drives the factory itself, so the
        # wiring is proven by running it rather than by reading the register
        # call — the distinction this repository keeps paying for.
        import asyncio
        import types

        from core.startup_factories import init_ai_agent_sweep

        state = types.SimpleNamespace(ai_tool_bus=_bus(), background_tasks=[])
        task = await init_ai_agent_sweep(state)
        try:
            assert task is not None, "the factory scheduled nothing"
            assert state.background_tasks, "the task was not registered for shutdown"
            # Give the scheduled loop a moment to run its first pass.
            await asyncio.sleep(0.1)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def test_the_factory_refuses_to_report_a_sweep_it_could_not_run(self) -> None:
        # No bus means the departments factory did not build one. A sweep
        # against nothing must not schedule and quietly look healthy.
        import types

        from core.startup_factories import init_ai_agent_sweep

        state = types.SimpleNamespace(ai_tool_bus=None, background_tasks=[])
        assert await init_ai_agent_sweep(state) is None
        assert not state.background_tasks

    def test_the_capability_registry_row_now_has_a_real_caller(self) -> None:
        # ai/hub/capabilities.py cites ai.agent.loop as evidence that
        # arch.layer_b.intelligence is live. Prove the citation is now true of
        # production code, not just of the tests: something outside ai/agent/
        # and outside tests/ IMPORTS the ai.agent package.
        #
        # Parsed with ast, not grepped. The first version of this test searched
        # for the substring "run_loop" and passed before anything was wired,
        # because hopefx_engine.py and nuclear/nuclear_agent.py both define an
        # unrelated `_run_loop`/`run_loop` of their own. A text match tests how
        # code is written; this asks what it imports.
        import ast
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[2]
        callers = []
        for path in repo.rglob("*.py"):
            rel = path.relative_to(repo).as_posix()
            if rel.startswith(("tests/", "ai/agent/", ".venv/")) or "__pycache__" in rel:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ai.agent"):
                    callers.append(rel)
                    break
                if isinstance(node, ast.Import) and any(a.name.startswith("ai.agent") for a in node.names):
                    callers.append(rel)
                    break

        assert callers, "nothing outside ai/agent/ and tests/ imports ai.agent — the registry claim is still false"
