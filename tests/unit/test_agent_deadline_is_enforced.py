# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""A run that overran its budget did not complete, whatever it managed to do.

`run_loop` checked the clock at the TOP of each step and nowhere else. So the
budget bounded when work was allowed to START, not when it had to be finished,
and anything that overran inside a step was never noticed. Reproduced on the
audited revision with a planner that consumed 2s against a 1s budget:

    completed      : True
    stopped_reason : planner_finished

That is worse than a late answer. `completed=True` is what a caller reads to
decide whether to act on the run, and `_remember()` writes it to memory, so a
run that blew its deadline became a successful precedent for the next one.

The fix is one absolute deadline computed once, rechecked after every operation
AND before accepting a completion, with the remaining time given to the planner
so it can choose to do less rather than be cut off.

What this deliberately does NOT claim: that an overrunning synchronous planner
or tool is cancelled. Python cannot interrupt arbitrary synchronous code, and a
thread timeout abandons the waiter while the work continues to run — and on this
platform tool handlers touch brokers and the database, so abandoning one
mid-flight is worse than waiting for it. The loop therefore bounds what it
ACCEPTS and what it STARTS, and says so.

Nor does it hand the deadline to a tool HANDLER. `ToolBus.invoke` forwards
`**context` straight to `handler(**context)`, so an extra keyword would raise
TypeError in every handler that does not declare it — which is every tool on the
platform. That needs an opt-in on the registration the way `wants_operator`
already works, and is a change to the tool contract, not to this loop. The
planner is told, and the planner is what chooses to start a tool.
"""

from __future__ import annotations

import types

import pytest

import ai.agent.loop as loop_mod
from ai.agent.loop import LoopBudget, Plan, run_loop


DEPARTMENT = "research_intelligence"


@pytest.fixture
def clock(monkeypatch):
    """A clock the test moves, so no test sleeps and none is timing-flaky."""
    now = {"t": 0.0}
    monkeypatch.setattr(loop_mod, "time", types.SimpleNamespace(monotonic=lambda: now["t"]))
    return now


class _NoBus:
    def invoke(self, *_a, **_k):
        raise AssertionError("no tool should have been started")


def _run(planner, *, bus=None, **budget_kw):
    return run_loop(
        department=DEPARTMENT,
        goal="a goal",
        bus=bus or _NoBus(),
        operator="operator",
        planner=planner,
        budget=LoopBudget(**budget_kw),
    )


def test_a_planner_that_overran_cannot_report_completion(clock):
    """The reported reproduction, as a regression test."""

    def slow(_ctx):
        clock["t"] += 2.0
        return Plan(action=None, rationale="done")

    run = _run(slow, max_seconds=1.0)
    assert run.completed is False
    assert run.stopped_reason == "time_budget_exhausted"


def test_a_planner_that_finished_in_time_still_completes(clock):
    """The fix must not turn every run into a timeout."""

    def quick(_ctx):
        clock["t"] += 0.1
        return Plan(action=None, rationale="done")

    run = _run(quick, max_seconds=1.0)
    assert run.completed is True
    assert run.stopped_reason == "planner_finished"


def test_no_tool_starts_once_the_deadline_has_passed(clock):
    """A step whose planning overran must not then go on to call a tool."""
    started: list[str] = []

    class _Bus:
        def invoke(self, tool, **_k):
            started.append(tool)
            return types.SimpleNamespace(value=None)

    permitted = loop_mod.permitted_actions(DEPARTMENT)
    assert permitted, "this test needs at least one permitted read-only action"

    def slow(_ctx):
        clock["t"] += 5.0
        return Plan(action=permitted[0], rationale="go", params={})

    run = _run(slow, bus=_Bus(), max_seconds=1.0)
    assert started == [], f"a tool was started after the deadline: {started}"
    assert run.completed is False
    assert run.stopped_reason == "time_budget_exhausted"


def test_a_tool_that_overran_does_not_produce_a_completed_run(clock):
    """The deadline is rechecked AFTER the tool call, not only before it."""
    permitted = loop_mod.permitted_actions(DEPARTMENT)

    class _SlowBus:
        def invoke(self, _tool, **_k):
            clock["t"] += 5.0
            return types.SimpleNamespace(value=42)

    calls = {"n": 0}

    def planner(_ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            return Plan(action=permitted[0], rationale="go", params={})
        return Plan(action=None, rationale="done")

    run = _run(planner, bus=_SlowBus(), max_seconds=1.0)
    assert run.completed is False
    assert run.stopped_reason == "time_budget_exhausted"
    assert calls["n"] == 1, "the loop planned another step after the deadline"


def test_the_planner_is_told_how_long_it_has_left(clock):
    """A planner that is not told the budget cannot respect it. The loop can
    only refuse an overrun after the fact; this is how it can be avoided."""
    seen: list[float | None] = []

    def planner(ctx):
        seen.append(getattr(ctx, "remaining_seconds", None))
        clock["t"] += 0.25
        return Plan(action=None, rationale="done")

    _run(planner, max_seconds=1.0)
    assert seen == [pytest.approx(1.0)], f"planner saw {seen}"


def test_remaining_time_shrinks_across_steps(clock):
    permitted = loop_mod.permitted_actions(DEPARTMENT)
    seen: list[float] = []

    class _Bus:
        def invoke(self, _tool, **_k):
            clock["t"] += 0.3
            return types.SimpleNamespace(value=1)

    calls = {"n": 0}

    def planner(ctx):
        seen.append(ctx.remaining_seconds)
        calls["n"] += 1
        if calls["n"] <= 2:
            return Plan(action=permitted[0], rationale="go", params={})
        return Plan(action=None, rationale="done")

    _run(planner, bus=_Bus(), max_seconds=10.0)
    assert seen == sorted(seen, reverse=True), f"remaining time did not fall: {seen}"
    assert seen[0] == pytest.approx(10.0)
    assert seen[1] == pytest.approx(9.7)


def test_an_exhausted_run_is_recorded_as_not_completed(clock, monkeypatch):
    """`_remember` writes `completed` into memory, so a run that overran must
    not become a successful precedent."""
    written: list[dict] = []
    monkeypatch.setattr(
        loop_mod,
        "_remember",
        lambda run: written.append({"completed": run.completed, "stopped_reason": run.stopped_reason}),
    )

    def slow(_ctx):
        clock["t"] += 9.0
        return Plan(action=None, rationale="done")

    _run(slow, max_seconds=1.0)
    assert written == [{"completed": False, "stopped_reason": "time_budget_exhausted"}]


def test_the_deadline_is_absolute_not_re_derived_per_step(clock):
    """Three steps of 0.4s against a 1.0s budget: the third must not run, even
    though no single step exceeds the budget on its own."""
    permitted = loop_mod.permitted_actions(DEPARTMENT)
    steps = {"n": 0}

    class _Bus:
        def invoke(self, _tool, **_k):
            clock["t"] += 0.4
            return types.SimpleNamespace(value=1)

    def planner(_ctx):
        steps["n"] += 1
        return Plan(action=permitted[0], rationale="go", params={})

    run = _run(planner, bus=_Bus(), max_seconds=1.0, max_steps=10)
    assert steps["n"] <= 3, f"ran {steps['n']} steps inside a 1.0s budget"
    assert run.stopped_reason == "time_budget_exhausted"
    assert run.completed is False


def test_an_overrunning_tool_is_recorded_as_having_returned_late(clock):
    """The recheck after the tool call must earn its place.

    Removing it left all the other tests here green, because the next
    iteration's top-of-loop check produces the same `completed` and the same
    `stopped_reason`. A branch no test distinguishes is the shape this
    repository calls a dead control, so either it is observable or it should not
    exist. What it changes is the RECORD, and `_remember` writes the record:
    without it the run logs "N observation(s) available to the next step" when
    there is no next step, and never says the tool came back late — so a reader
    of the memory sees a step that looks ordinary followed by an unexplained
    timeout.
    """
    permitted = loop_mod.permitted_actions(DEPARTMENT)

    class _SlowBus:
        def invoke(self, _tool, **_k):
            clock["t"] += 5.0
            return types.SimpleNamespace(value=42)

    def planner(_ctx):
        return Plan(action=permitted[0], rationale="go", params={})

    run = _run(planner, bus=_SlowBus(), max_seconds=1.0)

    notes = [s.detail for s in run.steps]
    assert any("after the run's deadline" in n for n in notes), f"the late return was not recorded: {notes}"
    assert not any("available to the next step" in n for n in notes), (
        f"the run promised a next step it had no budget for: {notes}"
    )
    # and the observation is still kept — the work happened
    assert run.observations and run.observations[-1]["value"] == 42
