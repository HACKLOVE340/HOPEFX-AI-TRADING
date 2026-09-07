# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§12: agents that talk to each other, and a graph that refuses a cycle.

## The rule this whole file exists to hold

**A message bus is not an execution path.** Publishing an event must not be
able to invoke a tool. Everything that acts still goes through
`ai/tools/bus.py`, where both gates run: the permission registry and the
sixteen constitutional invariants.

That is easy to write and easy to lose. The way it gets lost is convenience —
a subscriber is handed "just a little context" so it can do something useful,
and the thing it can now do is act without the gate that `ai/tools/bus.py`
exists to be. So it is asserted two ways: statically, that `ai/bus/` does not
import the tool bus at all, so the unsafe call is not expressible; and at
runtime, that a subscriber is handed one frozen data object with nothing
callable on it and no operator identity to act as.

## Why the graph refuses a cycle at `add()`, not at `run()`

A graph that detects a cycle when it schedules has already scheduled work.
`A -> B -> A` discovered at run time means A ran. Detection belongs at the
moment the edge is created, which is the last point where nothing has happened
yet.

## Empty is not unmeasured, again

`Delivery.fanout` always states what happened on the cross-worker leg. An
in-process bus that says nothing about the other workers reads, to the caller,
exactly like a bus that reached them.

These fail on the pre-fix tree: `ai.bus.agent_bus`, `ai.bus.lifecycle` and
`ai.bus.graph` do not exist there.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import json
import pathlib
import time

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _message(**over):
    from ai.hub.contracts import AgentMessage

    fields = {
        "task_id": "task-1",
        "sender": "research",
        "recipient": "risk",
        "confidence": 0.5,
        "evidence": ("audit:call-9",),
        "recommended_action": "size down",
    }
    fields.update(over)
    return AgentMessage(**fields)


@pytest.fixture()
def bus():
    from ai.bus.agent_bus import AgentBus

    return AgentBus()


# ── publishing is not execution ───────────────────────────────────────────────


def test_the_bus_package_does_not_import_the_tool_bus():
    """Not expressible beats not encouraged.

    `ai/awareness` has the same property for the same reason: a watcher raises
    a proposal and never acts, because it cannot reach the thing that acts.
    """
    modules = sorted((_ROOT / "ai" / "bus").glob("*.py"))
    assert len(modules) >= 4, "this guard passes vacuously on an empty package; it must see the real modules"

    # Parsed, not grepped: these modules *discuss* the tool bus at length, and a
    # substring search would flag the paragraph explaining why they never call it.
    offenders = []
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            else:
                continue
            if any(n.startswith("ai.tools") or n in {"ToolBus", "invoke"} for n in names):
                offenders.append(f"{path.name}: {names}")
    assert offenders == [], f"the event bus must not be able to reach the tool bus: {offenders}"


def test_a_subscriber_is_handed_one_frozen_message_and_nothing_callable(bus):
    seen: list = []
    bus.subscribe("risk", lambda *a, **k: seen.append((a, k)), operator="op-1", subscriber="risk-agent")
    bus.publish(_message(), operator="op-1")

    assert len(seen) == 1
    args, kwargs = seen[0]
    assert kwargs == {}, "the bus passes no keyword context — context is how authority leaks in"
    assert len(args) == 1
    message = args[0]

    callables = [n for n in dir(message) if not n.startswith("_") and callable(getattr(message, n))]
    # `is_expired` and `as_dict` are the message's own read-only helpers; nothing
    # a subscriber could act *through*.
    assert set(callables) <= {"is_expired", "as_dict", "from_dict"}, callables
    with pytest.raises(dataclasses.FrozenInstanceError):
        message.task_id = "other"


def test_the_message_carries_no_operator_identity_a_subscriber_could_act_as(bus):
    seen: list = []
    bus.subscribe("risk", seen.append, operator="op-1", subscriber="risk-agent")
    bus.publish(_message(), operator="op-1")

    payload = seen[0].as_dict()
    assert "operator" not in payload
    assert "op-1" not in json.dumps(payload), "the publishing operator must not travel inside the envelope"


# ── the envelope ──────────────────────────────────────────────────────────────


def test_publish_refuses_anything_that_is_not_an_agent_message(bus):
    """A dict is how a second, untyped envelope gets in beside the typed one."""
    with pytest.raises(TypeError):
        bus.publish({"task_id": "task-1", "sender": "a", "recipient": "b"}, operator="op-1")


def test_every_one_of_the_ten_fields_survives_the_trip(bus):
    seen: list = []
    bus.subscribe("risk", seen.append, operator="op-1", subscriber="risk-agent")
    sent = _message(
        priority="critical",
        status="running",
        confidence=0.81,
        evidence=("audit:call-9", "memory:note-4"),
        dependencies=("task-0",),
        expires_at=time.time() + 600,
        correlation_id="corr-7",
    )
    bus.publish(sent, operator="op-1")

    got = seen[0]
    for field in (
        "task_id",
        "correlation_id",
        "sender",
        "recipient",
        "priority",
        "status",
        "confidence",
        "evidence",
        "recommended_action",
        "dependencies",
        "expires_at",
    ):
        assert getattr(got, field) == getattr(sent, field), field


def test_an_expired_message_is_refused_and_the_refusal_says_why(bus):
    seen: list = []
    bus.subscribe("risk", seen.append, operator="op-1", subscriber="risk-agent")
    result = bus.publish(_message(expires_at=time.time() - 1), operator="op-1")

    assert seen == [], "stale evidence must not be delivered as if it were current"
    assert result.accepted is False
    assert "expired" in result.rejected
    assert result.fanout == "not attempted: the message was rejected", (
        "a rejected message must not report the fan-out state of a message that was sent"
    )


# ── operator scoping ──────────────────────────────────────────────────────────


def test_one_operators_message_never_reaches_anothers_subscriber(bus):
    """The precedent is a P0 in `ai/jobs/runner.py`: one operator's prompt and
    the model's answer on another operator's screen."""
    mine: list = []
    theirs: list = []
    bus.subscribe("risk", mine.append, operator="op-1", subscriber="risk-agent")
    bus.subscribe("risk", theirs.append, operator="op-2", subscriber="risk-agent")

    bus.publish(_message(), operator="op-1")

    assert len(mine) == 1
    assert theirs == []


def test_publishing_without_an_operator_is_refused(bus):
    with pytest.raises(ValueError):
        bus.publish(_message(), operator="  ")


def test_subscribing_without_an_operator_is_refused(bus):
    with pytest.raises(ValueError):
        bus.subscribe("risk", lambda m: None, operator="", subscriber="risk-agent")


# ── delivery behaviour ────────────────────────────────────────────────────────


def test_a_raising_subscriber_does_not_stop_the_others(bus):
    survived: list = []

    def explodes(_message):
        raise RuntimeError("subscriber is broken")

    bus.subscribe("risk", explodes, operator="op-1", subscriber="broken")
    bus.subscribe("risk", survived.append, operator="op-1", subscriber="fine")

    result = bus.publish(_message(), operator="op-1")

    assert len(survived) == 1
    assert result.delivered == 1
    assert result.failed == ("broken",), "a failed subscriber is named, not folded into the delivered count"


def test_a_wildcard_subscriber_sees_every_topic_for_its_own_operator(bus):
    seen: list = []
    bus.subscribe("*", seen.append, operator="op-1", subscriber="auditor")

    bus.publish(_message(recipient="risk"), operator="op-1")
    bus.publish(_message(recipient="news"), operator="op-1")
    bus.publish(_message(recipient="risk"), operator="op-2")

    assert [m.recipient for m in seen] == ["risk", "news"]


def test_the_topic_defaults_to_the_recipient_so_addressing_needs_no_convention(bus):
    seen: list = []
    bus.subscribe("news", seen.append, operator="op-1", subscriber="news-agent")
    bus.publish(_message(recipient="news"), operator="op-1")
    assert len(seen) == 1


def test_unsubscribe_stops_delivery(bus):
    seen: list = []
    sub = bus.subscribe("risk", seen.append, operator="op-1", subscriber="risk-agent")
    bus.unsubscribe(sub)
    bus.publish(_message(), operator="op-1")
    assert seen == []


def test_no_subscriber_is_reported_as_zero_delivered_and_not_as_a_failure(bus):
    result = bus.publish(_message(), operator="op-1")
    assert result.accepted is True
    assert result.delivered == 0
    assert result.failed == ()


# ── the honest report on the cross-worker leg ─────────────────────────────────


def test_fanout_states_what_happened_on_the_other_workers(bus):
    """`API_WORKERS > 1` means an in-process bus reaches one worker of several.

    Saying nothing about the rest reads, to the caller, as having reached them.
    """
    result = bus.publish(_message(), operator="op-1")
    assert result.fanout, "the cross-worker leg always reports; silence reads as success"
    assert "in-process" in result.fanout


# ── task lifecycle ────────────────────────────────────────────────────────────


@pytest.fixture()
def lifecycle(bus):
    from ai.bus.lifecycle import TaskLifecycle

    return TaskLifecycle(bus, operator="op-1", task_id="task-1", sender="orchestrator", recipient="workbench")


def test_each_transition_is_published_as_a_message(bus, lifecycle):
    seen: list = []
    bus.subscribe("*", seen.append, operator="op-1", subscriber="watcher")

    lifecycle.started()
    lifecycle.succeeded()

    assert [m.status for m in seen] == ["running", "succeeded"]
    assert {m.task_id for m in seen} == {"task-1"}


def test_an_illegal_transition_is_refused(lifecycle):
    lifecycle.started()
    lifecycle.succeeded()
    with pytest.raises(ValueError):
        lifecycle.started()


def test_a_task_that_never_ran_cannot_have_succeeded(lifecycle):
    """The same rule the graph holds: an outcome for work that never ran is
    invented, not observed. Cancelling a queued task is different, and allowed —
    it never started, and that is exactly what `cancelled` means."""
    with pytest.raises(ValueError):
        lifecycle.succeeded()
    lifecycle.cancelled()
    assert lifecycle.status == "cancelled"


def test_a_terminal_status_is_terminal(bus, lifecycle):
    seen: list = []
    bus.subscribe("*", seen.append, operator="op-1", subscriber="watcher")
    lifecycle.cancelled()
    with pytest.raises(ValueError):
        lifecycle.partial({"text": "more"})
    assert [m.status for m in seen] == ["cancelled"]


def test_partials_carry_an_increasing_sequence_so_a_gap_is_visible(bus, lifecycle):
    seen: list = []
    bus.subscribe("*", seen.append, operator="op-1", subscriber="watcher")

    lifecycle.started()
    lifecycle.partial({"text": "gold is "})
    lifecycle.partial({"text": "holding "})
    lifecycle.partial({"text": "3400"})

    partials = [m for m in seen if m.status == "partial"]
    assert [p.body["sequence"] for p in partials] == [1, 2, 3]
    assert [p.body["text"] for p in partials] == ["gold is ", "holding ", "3400"]


def test_a_partial_after_the_terminal_status_is_refused(lifecycle):
    lifecycle.started()
    lifecycle.succeeded()
    with pytest.raises(ValueError):
        lifecycle.partial({"text": "late"})


def test_a_timeout_is_distinct_from_a_failure(bus, lifecycle):
    seen: list = []
    bus.subscribe("*", seen.append, operator="op-1", subscriber="watcher")
    lifecycle.started()
    lifecycle.timed_out()
    assert seen[-1].status == "timed_out"


# ── the task graph ────────────────────────────────────────────────────────────


def test_a_cycle_is_refused_when_the_edge_is_added_not_when_it_runs():
    """Detecting `A -> B -> A` at schedule time means A has already run."""
    from ai.bus.graph import CycleRefused, TaskGraph

    graph = TaskGraph()
    graph.add("a", depends_on=("b",))
    with pytest.raises(CycleRefused) as exc:
        graph.add("b", depends_on=("a",))
    assert "a" in str(exc.value) and "b" in str(exc.value), "the refusal names the cycle it found"


def test_a_longer_cycle_is_refused_too():
    from ai.bus.graph import CycleRefused, TaskGraph

    graph = TaskGraph()
    graph.add("a", depends_on=("b",))
    graph.add("b", depends_on=("c",))
    with pytest.raises(CycleRefused):
        graph.add("c", depends_on=("a",))


def test_a_dependency_that_was_never_added_is_named_not_ignored():
    from ai.bus.graph import TaskGraph

    graph = TaskGraph()
    graph.add("a", depends_on=("never-added",))
    assert graph.unknown_dependencies() == ("never-added",)
    assert graph.ready() == (), "a graph with a dangling edge must not offer work"


def test_ready_returns_only_tasks_whose_dependencies_succeeded():
    from ai.bus.graph import TaskGraph

    graph = TaskGraph()
    graph.add("fetch")
    graph.add("analyse", depends_on=("fetch",))

    assert graph.ready() == ("fetch",)
    graph.started("fetch")
    assert graph.ready() == (), "a running task is not offered a second time"
    graph.completed("fetch", "succeeded")
    assert graph.ready() == ("analyse",)


def test_the_graph_is_not_a_queue():
    """A diamond offers both branches at once. A sequential queue offers one."""
    from ai.bus.graph import TaskGraph

    graph = TaskGraph()
    graph.add("fetch")
    graph.add("technicals", depends_on=("fetch",))
    graph.add("sentiment", depends_on=("fetch",))
    graph.add("synthesis", depends_on=("technicals", "sentiment"))

    graph.started("fetch")
    graph.completed("fetch", "succeeded")
    assert sorted(graph.ready()) == ["sentiment", "technicals"]


def test_a_failed_dependency_blocks_its_dependents_rather_than_skipping_them():
    from ai.bus.graph import TaskGraph

    graph = TaskGraph()
    graph.add("fetch")
    graph.add("analyse", depends_on=("fetch",))
    graph.started("fetch")
    graph.completed("fetch", "failed")

    assert graph.ready() == ()
    assert graph.status("analyse") == "blocked"
    assert graph.blocked() == (("analyse", "fetch"),), "the blocked task names what blocked it"


def test_a_cancelled_dependency_blocks_too_and_the_reason_is_kept():
    from ai.bus.graph import TaskGraph

    graph = TaskGraph()
    graph.add("fetch")
    graph.add("analyse", depends_on=("fetch",))
    graph.started("fetch")
    graph.completed("fetch", "cancelled")
    assert graph.status("analyse") == "blocked"


def test_completing_a_task_that_never_started_is_refused():
    from ai.bus.graph import TaskGraph

    graph = TaskGraph()
    graph.add("fetch")
    with pytest.raises(ValueError):
        graph.completed("fetch", "succeeded")


def test_a_duplicate_task_id_is_refused():
    from ai.bus.graph import TaskGraph

    graph = TaskGraph()
    graph.add("fetch")
    with pytest.raises(ValueError):
        graph.add("fetch")


def test_the_graph_reports_progress_without_pretending_the_unstarted_are_done():
    from ai.bus.graph import TaskGraph

    graph = TaskGraph()
    graph.add("fetch")
    graph.add("analyse", depends_on=("fetch",))
    graph.started("fetch")
    graph.completed("fetch", "succeeded")

    report = graph.report()
    assert report["succeeded"] == 1
    assert report["pending"] == 1
    assert report["complete"] is False


# ── the registry ──────────────────────────────────────────────────────────────


def test_the_rows_this_phase_closes_are_live_and_their_evidence_resolves():
    from ai.hub import capabilities

    result = capabilities.verify()
    assert result.discrepancies == ()

    by_id = {c.id: c for c in capabilities.REGISTRY}
    for row in (
        "bus.pubsub",
        "bus.message_envelope",
        "bus.lifecycle_events",
        "bus.streaming_partials",
        "bus.task_graph",
        "stack.event_bus",
    ):
        assert by_id[row].state == "live", f"{row} is {by_id[row].state}"


# ── the wiring, because registered is not run ─────────────────────────────────


def test_a_startup_factory_exists_and_is_registered():
    import core.startup_factories as F

    assert hasattr(F, "init_ai_agent_bus"), "no startup factory for the agent bus"
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    assert "F.init_ai_agent_bus" in src, "the factory is defined but never registered"


@pytest.mark.asyncio
async def test_the_startup_factory_installs_the_fanout_when_called():
    """`hasattr` and "is registered" are not execution.

    The precedent is `init_ai_job_progress`, whose first draft imported a name
    that does not exist: it passed both assertions above and would have raised
    ImportError on the first startup. This one is called.
    """
    from types import SimpleNamespace

    import core.startup_factories as F
    from ai.bus import agent_bus

    agent_bus.reset_for_testing()
    bus = agent_bus.get_agent_bus()
    before = bus.publish(_message(), operator="op-1").fanout
    assert "not installed" in before

    try:
        await F.init_ai_agent_bus(SimpleNamespace())
        after = bus.publish(_message(), operator="op-1").fanout
        assert after != before, "the factory ran and the fan-out is still not installed"
        assert "core.event_bus" in after
    finally:
        agent_bus.reset_for_testing()


def test_the_fanout_report_admits_that_nothing_reads_the_channel_yet():
    """Publishing to a channel no worker subscribes to is not delivery.

    `AgentBus.consume` exists and no factory starts one, so cross-worker
    RECEIVE is not live. The label says so, in the words a reader of a
    `Delivery` will see — the alternative is a caller inferring reach from a
    line that mentions Redis.
    """
    from ai.bus import agent_bus

    agent_bus.reset_for_testing()
    bus = agent_bus.get_agent_bus()
    try:
        loop = asyncio.new_event_loop()
        try:
            label = agent_bus.install_redis_fanout(bus, loop)
            assert "only where AgentBus.consume is running" in label
        finally:
            loop.close()
    finally:
        agent_bus.reset_for_testing()


def test_a_message_from_another_worker_is_rebuilt_through_the_typed_envelope(bus):
    """A remote payload that is not a valid message must fail at the boundary,
    not reach a subscriber as a half-formed object."""
    from ai.hub.contracts import AgentMessage

    seen: list = []
    bus.subscribe("risk", seen.append, operator="op-1", subscriber="risk-agent")

    sent = _message(confidence=0.7)
    result = bus.deliver_remote({"type": "agent_message", **sent.as_dict()}, operator="op-1")

    assert result.delivered == 1
    assert isinstance(seen[0], AgentMessage)
    assert seen[0].confidence == 0.7
    assert seen[0].task_id == sent.task_id

    with pytest.raises(ValueError):
        bus.deliver_remote({"type": "agent_message", **sent.as_dict(), "confidence": 4.0}, operator="op-1")


def test_a_remote_message_is_not_published_back_out(bus):
    """Otherwise every worker rebroadcasts what it received, forever."""
    published: list = []
    bus.enable_fanout(lambda channel, payload: published.append(channel), label="test transport")
    bus.subscribe("risk", lambda m: None, operator="op-1", subscriber="risk-agent")

    bus.deliver_remote({"type": "agent_message", **_message().as_dict()}, operator="op-1")
    assert published == [], "a received message must not be re-published"

    bus.publish(_message(), operator="op-1")
    assert published == ["hopefx:ai:agent:op-1"], "a locally published message fans out on the operator's own channel"
