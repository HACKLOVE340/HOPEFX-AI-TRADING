# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§14 task orchestration, and §11's orchestrator: priority that cannot starve.

## The rule this file is named for

**A priority queue must not starve.** A low-priority job that never runs
because higher-priority work keeps arriving is a job that silently never
happens, and the operator watching it sees `queued` for ever — which looks
identical to a job that is about to start. Every priority scheme without
ageing has this defect; the only question is whether anyone has hit it yet.

So the rank a waiting item is compared on is not its priority. It is its
priority *minus how long it has waited*, and after enough waiting a background
item outranks a critical one that has just arrived. That is provable rather
than hoped for, and the test below proves it.

## Priority only engages under contention

`JobRunner` submits straight to a `ThreadPoolExecutor`, which is strictly FIFO.
Rather than replace that — it is the live path for every concurrent AI job on
the AI Core screen — the queue sits in front of it and is consulted only when
the pool is saturated. Uncontended behaviour is unchanged, which is what the
existing tests exercise; priority appears exactly where it can matter.

## A trigger enqueues; it never executes

Phase A's rule was that a message bus is not an execution path. A trigger that
ran its task inside the subscriber callback would make it one. So a trigger
puts work on the queue and returns, and `ai/bus/triggers.py` cannot reach the
tool bus — the same AST assertion `ai/bus` and `ai/improve` carry.

A task that publishes the event that triggers it is a loop. Every triggered
message carries a depth, and a trigger refuses to fire past its ceiling.

## The orchestrator executes a graph; it does not re-implement ordering

`ai/bus/graph.py` already decides what may run. A second scheduler beside it is
how the graph stops being the thing that decides. And two agents reaching
opposite conclusions is not averaged into a number nobody argued for — it goes
to `ai/debate/session.py`, which is allowed to answer UNRESOLVED.

These fail on the pre-fix tree: `ai.jobs.priority`, `ai.bus.triggers` and
`ai.agent.orchestrator` do not exist there.
"""

from __future__ import annotations

import ast
import pathlib
import threading
import time

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── the ageing priority queue ─────────────────────────────────────────────────


def test_higher_priority_runs_first_when_everything_arrived_together():
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    queue.push("bg", priority="background", operator="op-1", now=0.0)
    queue.push("crit", priority="critical", operator="op-1", now=0.0)
    queue.push("sec", priority="secondary", operator="op-1", now=0.0)

    assert [queue.pop(now=0.0).id for _ in range(3)] == ["crit", "sec", "bg"]


def test_equal_rank_is_broken_by_arrival_order():
    """Otherwise the order depends on dict iteration, which is not an order."""
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    for n in range(4):
        queue.push(f"j{n}", priority="secondary", operator="op-1", now=float(n))

    assert [queue.pop(now=10.0).id for _ in range(4)] == ["j0", "j1", "j2", "j3"]


def test_a_background_job_is_not_starved_by_a_stream_of_critical_ones():
    """The defect this whole component exists to prevent.

    A queue without ageing answers "critical" for ever here, and the background
    job shows `queued` on the operator's screen indefinitely — indistinguishable
    from one that is about to start.
    """
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue(ageing_s=10.0)
    queue.push("bg", priority="background", operator="op-1", now=0.0)

    popped = []
    now = 0.0
    for n in range(60):
        now += 1.0
        queue.push(f"crit{n}", priority="critical", operator="op-1", now=now)
        item = queue.pop(now=now)
        popped.append(item.id)
        if item.id == "bg":
            break

    assert "bg" in popped, "the background job never ran under sustained critical load"
    waited = popped.index("bg")
    assert waited <= 40, f"it waited {waited} rounds; ageing is not biting"


def test_the_wait_needed_to_overtake_is_exactly_the_tier_gap():
    """Stated, not incidental: `background` is three tiers below `critical`,
    so it takes three ageing periods of waiting to draw level."""
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue(ageing_s=10.0)
    old = queue.push("bg", priority="background", operator="op-1", now=0.0)

    # "Just arrived" means enqueued at the moment of comparison. A critical item
    # that has itself been waiting is ageing too, so the gap it must be overcome
    # across is measured against a zero-wait one.
    just_arrived_at_29 = queue.push("crit29", priority="critical", operator="op-1", now=29.0)
    assert queue.rank(old, now=29.0) > queue.rank(just_arrived_at_29, now=29.0)

    just_arrived_at_31 = queue.push("crit31", priority="critical", operator="op-1", now=31.0)
    assert queue.rank(old, now=31.0) < queue.rank(just_arrived_at_31, now=31.0)


def test_an_unknown_priority_is_refused_rather_than_guessed():
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    with pytest.raises(ValueError):
        queue.push("x", priority="urgent-ish", operator="op-1")


def test_the_queue_has_a_ceiling():
    from ai.jobs.priority import AgeingPriorityQueue
    from ai.jobs.runner import QueueFull

    queue = AgeingPriorityQueue(max_queued=2)
    queue.push("a", priority="secondary", operator="op-1")
    queue.push("b", priority="secondary", operator="op-1")
    with pytest.raises(QueueFull):
        queue.push("c", priority="secondary", operator="op-1")


def test_popping_an_empty_queue_returns_none_rather_than_raising():
    from ai.jobs.priority import AgeingPriorityQueue

    assert AgeingPriorityQueue().pop() is None


def test_the_snapshot_reports_the_longest_wait_not_only_the_depth():
    """Depth alone hides starvation: three items could be three seconds old or
    three hours old, and only one of those is a problem."""
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    queue.push("old", priority="background", operator="op-1", now=0.0)
    queue.push("new", priority="critical", operator="op-1", now=90.0)

    snap = queue.snapshot(now=100.0)
    assert snap["waiting"] == 2
    assert snap["by_priority"]["background"] == 1
    assert snap["longest_wait_s"] == pytest.approx(100.0)


# ── the runner uses it, under contention only ─────────────────────────────────


def test_an_uncontended_job_still_starts_immediately():
    """The live path for every AI Core panel. Priority must not add a hop."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    try:
        job_id = runner.submit(prompt="p", work=lambda _r: "ok", operator="owner")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and runner.get(job_id).state != "succeeded":
            time.sleep(0.01)
        assert runner.get(job_id).state == "succeeded"
    finally:
        runner.shutdown()


def test_a_saturated_pool_dispatches_the_highest_priority_waiter_first():
    from ai.jobs.runner import JobRunner

    release = threading.Event()
    started: list[str] = []

    def _blocker(_report):
        release.wait(timeout=5)
        return "done"

    def _named(name):
        def _work(_report):
            started.append(name)
            return name

        return _work

    runner = JobRunner(max_concurrent=1)
    try:
        runner.submit(prompt="blocker", work=_blocker, operator="owner")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and runner.snapshot()["running"] < 1:
            time.sleep(0.01)

        runner.submit(prompt="bg", work=_named("bg"), operator="owner", priority="background")
        runner.submit(prompt="crit", work=_named("crit"), operator="owner", priority="critical")
        assert runner.snapshot()["waiting"] == 2

        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(started) < 2:
            time.sleep(0.01)

        assert started == ["crit", "bg"], f"dispatched {started}"
    finally:
        release.set()
        runner.shutdown()


def test_the_snapshot_says_how_many_are_waiting():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)
    try:
        snap = runner.snapshot()
        assert "waiting" in snap
    finally:
        runner.shutdown()


# ── event-triggered tasks ─────────────────────────────────────────────────────


def test_triggers_cannot_reach_the_tool_bus():
    tree = ast.parse((_ROOT / "ai" / "bus" / "triggers.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        elif isinstance(node, ast.Name | ast.Attribute):
            names = [node.id if isinstance(node, ast.Name) else node.attr]
        assert not any(n.startswith("ai.tools") or n in {"ToolBus", "invoke"} for n in names), (
            f"line {node.lineno}: a trigger must enqueue, never execute"
        )


def test_a_matching_message_enqueues_a_task_and_does_not_run_it():
    from ai.bus.agent_bus import AgentBus
    from ai.bus.triggers import Trigger, TriggerRegistry
    from ai.hub.contracts import AgentMessage
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    bus = AgentBus()
    registry = TriggerRegistry(bus, queue)
    ran: list[str] = []

    registry.register(
        Trigger(
            name="drawdown",
            topic="risk",
            when=lambda m: m.body.get("kind") == "drawdown",
            task="review-exposure",
            priority="critical",
        ),
        operator="op-1",
    )

    bus.publish(
        AgentMessage(task_id="t1", sender="risk", recipient="risk", body={"kind": "drawdown"}),
        operator="op-1",
    )

    assert ran == [], "a trigger ran work inside a subscriber callback"
    item = queue.pop()
    assert item is not None
    assert item.payload["task"] == "review-exposure"
    assert item.priority == "critical"


def test_a_non_matching_message_enqueues_nothing():
    from ai.bus.agent_bus import AgentBus
    from ai.bus.triggers import Trigger, TriggerRegistry
    from ai.hub.contracts import AgentMessage
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    bus = AgentBus()
    TriggerRegistry(bus, queue).register(
        Trigger(name="d", topic="risk", when=lambda m: False, task="never"),
        operator="op-1",
    )
    bus.publish(AgentMessage(task_id="t1", sender="a", recipient="risk"), operator="op-1")
    assert queue.pop() is None


def test_a_trigger_refuses_to_fire_past_its_depth_ceiling():
    """A task that publishes the event that triggers it is a loop."""
    from ai.bus.agent_bus import AgentBus
    from ai.bus.triggers import DEPTH_KEY, Trigger, TriggerRegistry
    from ai.hub.contracts import AgentMessage
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    bus = AgentBus()
    registry = TriggerRegistry(bus, queue)
    registry.register(
        Trigger(name="loop", topic="risk", when=lambda _m: True, task="again", max_depth=2),
        operator="op-1",
    )

    for depth in (0, 1, 2, 3):
        bus.publish(
            AgentMessage(task_id=f"t{depth}", sender="a", recipient="risk", body={DEPTH_KEY: depth}),
            operator="op-1",
        )

    fired = []
    while (item := queue.pop()) is not None:
        fired.append(item.payload[DEPTH_KEY])
    assert fired == [1, 2], f"fired at depths {fired}"


def test_the_enqueued_task_carries_an_incremented_depth():
    from ai.bus.agent_bus import AgentBus
    from ai.bus.triggers import DEPTH_KEY, Trigger, TriggerRegistry
    from ai.hub.contracts import AgentMessage
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    bus = AgentBus()
    TriggerRegistry(bus, queue).register(
        Trigger(name="t", topic="risk", when=lambda _m: True, task="x"), operator="op-1"
    )
    bus.publish(AgentMessage(task_id="t1", sender="a", recipient="risk"), operator="op-1")
    assert queue.pop().payload[DEPTH_KEY] == 1


def test_a_predicate_that_raises_is_recorded_and_fires_nothing():
    from ai.bus.agent_bus import AgentBus
    from ai.bus.triggers import Trigger, TriggerRegistry
    from ai.hub.contracts import AgentMessage
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    bus = AgentBus()
    registry = TriggerRegistry(bus, queue)

    def _explodes(_m):
        raise RuntimeError("bad predicate")

    registry.register(Trigger(name="bad", topic="risk", when=_explodes, task="x"), operator="op-1")
    bus.publish(AgentMessage(task_id="t1", sender="a", recipient="risk"), operator="op-1")

    assert queue.pop() is None
    assert registry.failures()[0][0] == "bad"


def test_a_full_queue_does_not_break_the_bus_and_is_recorded():
    from ai.bus.agent_bus import AgentBus
    from ai.bus.triggers import Trigger, TriggerRegistry
    from ai.hub.contracts import AgentMessage
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue(max_queued=1)
    bus = AgentBus()
    registry = TriggerRegistry(bus, queue)
    registry.register(Trigger(name="t", topic="risk", when=lambda _m: True, task="x"), operator="op-1")

    for n in range(3):
        result = bus.publish(AgentMessage(task_id=f"t{n}", sender="a", recipient="risk"), operator="op-1")
        assert result.failed == (), "a full queue was reported as a broken subscriber"

    assert any("full" in why.lower() for _n, why in registry.failures())


def test_one_operators_event_never_fires_another_operators_trigger():
    from ai.bus.agent_bus import AgentBus
    from ai.bus.triggers import Trigger, TriggerRegistry
    from ai.hub.contracts import AgentMessage
    from ai.jobs.priority import AgeingPriorityQueue

    queue = AgeingPriorityQueue()
    bus = AgentBus()
    TriggerRegistry(bus, queue).register(
        Trigger(name="t", topic="risk", when=lambda _m: True, task="x"), operator="op-1"
    )
    bus.publish(AgentMessage(task_id="t1", sender="a", recipient="risk"), operator="op-2")
    assert queue.pop() is None


# ── the orchestrator ──────────────────────────────────────────────────────────


def _steps():
    from ai.agent.orchestrator import Step

    return [
        Step(task_id="fetch", department="markets_execution", action="sync_positions"),
        Step(
            task_id="technicals",
            department="markets_execution",
            action="query_broker_status",
            depends_on=("fetch",),
        ),
        Step(
            task_id="sentiment",
            department="news_intelligence",
            action="fetch_headlines",
            depends_on=("fetch",),
        ),
        Step(
            task_id="synthesis",
            department="news_intelligence",
            action="score_geopolitical_risk",
            depends_on=("technicals", "sentiment"),
        ),
    ]


def test_decompose_builds_a_graph_and_the_graph_decides_the_order():
    from ai.agent import orchestrator

    plan = orchestrator.decompose("what is gold doing", _steps())
    assert plan.graph.ready() == ("fetch",)

    plan.graph.started("fetch")
    plan.graph.completed("fetch", "succeeded")
    assert sorted(plan.graph.ready()) == ["sentiment", "technicals"], "the diamond was serialised"


def test_the_orchestrator_does_not_keep_its_own_ordering():
    """A second scheduler beside the graph is how the graph stops deciding."""
    import inspect

    from ai.agent import orchestrator

    source = inspect.getsource(orchestrator)
    for smell in ("sorted(steps", "topological", "def _order", "self._order"):
        assert smell not in source, f"the orchestrator re-implements ordering: {smell}"
    assert "TaskGraph" in source


def test_a_cycle_in_the_declared_plan_is_refused_at_decompose():
    from ai.agent import orchestrator
    from ai.agent.orchestrator import Step
    from ai.bus.graph import CycleRefused

    with pytest.raises(CycleRefused):
        orchestrator.decompose(
            "loop",
            [
                Step(task_id="a", department="markets_execution", action="sync_positions", depends_on=("b",)),
                Step(task_id="b", department="markets_execution", action="sync_positions", depends_on=("a",)),
            ],
        )


def test_allocation_names_what_it_could_not_assign():
    """A step dropped from the plan reads, in the report, as a step that ran."""
    from ai.agent import orchestrator
    from ai.agent.orchestrator import Step

    plan = orchestrator.decompose(
        "mixed",
        [
            Step(task_id="ok", department="markets_execution", action="sync_positions"),
            Step(task_id="nope", department="markets_execution", action="not_a_real_action"),
            Step(task_id="alien", department="no_such_department", action="sync_positions"),
        ],
    )

    assigned = {a.task_id for a in plan.assignments}
    assert assigned == {"ok"}
    unassignable = dict(plan.unassignable)
    assert set(unassignable) == {"nope", "alien"}
    assert all(reason for reason in unassignable.values())


def test_a_write_action_is_never_allocated_to_an_autonomous_step(monkeypatch):
    """The orchestrator plans; acting stays behind the tool bus and its gates.

    Every currently implemented action happens to be READ_ONLY, so an
    implemented higher-risk action is injected rather than asserting against
    whichever one exists today: the guard has to hold for the next one added,
    not only for the ones present when it was written.
    """
    from ai.agent import orchestrator
    from ai.agent.orchestrator import Step
    from ai.departments import implemented_actions
    from core.ai_tool_permissions import ToolRisk

    class _Risky:
        name = "markets_execution.derisk"
        risk = ToolRisk.PAPER_TRADING

    monkeypatch.setattr(
        "ai.departments.implemented_actions",
        lambda: (*implemented_actions(), _Risky()),
    )

    plan = orchestrator.decompose(
        "act",
        [Step(task_id="trade", department="markets_execution", action="derisk")],
    )
    assert plan.assignments == ()
    assert "read-only" in dict(plan.unassignable)["trade"].lower()


def test_an_action_that_does_not_exist_is_refused_before_its_risk_is_considered():
    from ai.agent import orchestrator
    from ai.agent.orchestrator import Step

    plan = orchestrator.decompose(
        "act",
        [Step(task_id="trade", department="markets_execution", action="place_order")],
    )
    assert plan.assignments == ()
    assert "not an implemented action" in dict(plan.unassignable)["trade"]


def test_tracking_publishes_a_lifecycle_message_per_task():
    from ai.agent import orchestrator
    from ai.bus.agent_bus import AgentBus

    bus = AgentBus()
    seen: list = []
    bus.subscribe("*", seen.append, operator="op-1", subscriber="watcher")

    plan = orchestrator.decompose("q", _steps())
    orchestrator.track(plan, "fetch", "running", bus=bus, operator="op-1")
    orchestrator.track(plan, "fetch", "succeeded", bus=bus, operator="op-1")

    assert [m.status for m in seen] == ["running", "succeeded"]
    assert {m.task_id for m in seen} == {"fetch"}


def test_merge_keeps_the_tasks_that_produced_nothing():
    from ai.agent import orchestrator

    plan = orchestrator.decompose("q", _steps())
    merged = orchestrator.merge(plan, {"fetch": {"price": 3400}, "technicals": {"trend": "up"}})

    assert merged["results"]["fetch"] == {"price": 3400}
    assert set(merged["missing"]) == {"sentiment", "synthesis"}
    assert merged["complete"] is False


def test_merge_is_complete_only_when_every_task_answered():
    from ai.agent import orchestrator

    plan = orchestrator.decompose("q", _steps())
    merged = orchestrator.merge(plan, {t: {"x": 1} for t in ("fetch", "technicals", "sentiment", "synthesis")})
    assert merged["complete"] is True
    assert merged["missing"] == ()


def test_a_conflict_goes_to_a_debate_and_is_never_averaged():
    from ai.agent import orchestrator
    from ai.debate.session import Position

    result = orchestrator.resolve(
        subject="direction",
        positions=[
            Position(agent="technicals", stance="long", argument="higher lows since Monday"),
            Position(agent="sentiment", stance="short", argument="two hawkish speakers"),
        ],
    )
    assert result.outcome in {"resolved", "unresolved"}
    assert result.subject == "direction"


def test_a_single_stance_comes_back_unresolved_and_says_why():
    """Not an exception, and deliberately not a resolution.

    `debate` answers UNRESOLVED and names the missing opposition, which is the
    outcome an average cannot express: dressing one position as a debate implies
    an opposing view was sought and found wanting.
    """
    from ai.agent import orchestrator
    from ai.debate.session import Position

    result = orchestrator.resolve(
        subject="direction",
        positions=[Position(agent="technicals", stance="long", argument="higher lows")],
    )
    assert result.outcome == "unresolved"
    assert result.leading is None
    assert "one stance" in result.unresolved_reason.lower()


def test_resolving_with_no_positions_at_all_is_refused():
    from ai.agent import orchestrator

    with pytest.raises(ValueError):
        orchestrator.resolve(subject="direction", positions=[])


# ── the registry ──────────────────────────────────────────────────────────────


def test_the_phase_b_rows_are_live_and_their_evidence_resolves():
    from ai.hub import capabilities

    assert capabilities.verify().discrepancies == ()
    rows = {c.id: c for c in capabilities.REGISTRY}
    for row in ("parallel.priority_queues", "parallel.event_triggered", "agents.orchestrator"):
        assert rows[row].state == "live", f"{row} is {rows[row].state}"
