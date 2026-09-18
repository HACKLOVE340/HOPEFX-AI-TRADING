# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Nothing noticed anything on its own.

`awareness` was the last of spec §2's four parts still typed
`tuple[str, ...]` — "broker disconnect detection", "live exposure vs rules",
"strategy drift vs trained regime". Labels. Grep for a watcher, a trigger or a
subscription and nothing came back.

Until now every department was purely reactive: it could answer a question an
operator asked and could not tell anyone that something had changed. Awareness
is what makes it a monitor rather than a query surface.

**The rule that governs the whole layer: an observation raises a PROPOSAL and
never acts.** Spec §2 is explicit — every department can recommend, and nothing
places a trade, deploys code, rotates a credential or changes a setting without
passing the superadmin approval queue. A watcher that could act would be the
single most dangerous thing in this codebase, so `ai/awareness` does not import
the tool bus at all and these tests assert that it stays that way.

These tests fail on the pre-fix tree — `ai.awareness` does not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    from ai.awareness import watchers
    from ai.memory import store

    store.reset_for_testing()
    watchers.reset_for_testing()
    yield
    store.reset_for_testing()
    watchers.reset_for_testing()


def _observation(**over):
    from ai.awareness.watchers import Observation

    kwargs = {
        "department": "risk_compliance",
        "trigger": "drawdown_near_limit",
        "severity": "warning",
        "summary": "Drawdown is 4.6% against a 5% limit.",
        "detail": {"pct": 4.6, "limit": 5.0},
    }
    kwargs.update(over)
    return Observation(**kwargs)


# ── the safety boundary ───────────────────────────────────────────────────────


def test_the_awareness_package_cannot_reach_the_tool_bus():
    """Structural, not a convention.

    A watcher that could invoke a tool is the most dangerous thing this
    codebase could contain: it would act on its own opinion with no human in
    the loop. The module does not import the bus, so it cannot.
    """
    import pathlib

    import ai.awareness.watchers as w

    src = pathlib.Path(w.__file__).read_text(encoding="utf-8")
    assert "ai.tools.bus" not in src, "the awareness layer can reach the tool bus"
    assert "ToolBus" not in src, "the awareness layer references the tool bus"


def test_an_observation_has_no_way_to_express_an_action():
    """The dataclass itself refuses the concept."""
    from ai.awareness.watchers import Observation

    fields = set(Observation.__dataclass_fields__)
    for forbidden in ("action", "tool", "execute", "order", "command"):
        assert forbidden not in fields, f"Observation carries an {forbidden!r} field"


# ── observing ─────────────────────────────────────────────────────────────────


def test_a_watcher_that_sees_nothing_raises_nothing():
    from ai.awareness.watchers import register, run_all

    register("risk_compliance", "quiet", lambda: None)
    assert run_all() == []


def test_an_observation_is_recorded_in_that_departments_memory():
    from ai.awareness.watchers import register, run_all
    from ai.memory.store import recall

    register("risk_compliance", "drawdown_near_limit", lambda: _observation())
    run_all()

    remembered = recall("risk_compliance", kind="observation")
    assert len(remembered) == 1
    assert remembered[0]["value"]["trigger"] == "drawdown_near_limit"


def test_an_observation_raises_a_proposal():
    from ai.awareness.watchers import register, run_all

    raised: list[dict] = []
    from ai.awareness import watchers

    watchers.set_proposal_sink(raised.append)

    register("risk_compliance", "drawdown_near_limit", lambda: _observation())
    run_all()

    assert len(raised) == 1
    assert raised[0]["status"] == "pending", "a raised proposal must wait for a human"
    assert raised[0]["kind"] == "observation"


def test_a_raised_proposal_is_attributed_to_the_department_not_a_person():
    from ai.awareness import watchers
    from ai.awareness.watchers import register, run_all

    raised: list[dict] = []
    watchers.set_proposal_sink(raised.append)
    register("risk_compliance", "drawdown_near_limit", lambda: _observation())
    run_all()

    assert "risk_compliance" in raised[0]["created_by"]


def test_a_watcher_that_throws_does_not_stop_the_others():
    """One broken watcher must not blind the whole platform."""
    from ai.awareness.watchers import register, run_all

    def explode():
        raise RuntimeError("data feed is gone")

    register("markets_execution", "broken", explode)
    register("risk_compliance", "working", lambda: _observation())

    observed = run_all()
    assert len(observed) == 1, "a throwing watcher suppressed a healthy one"


def test_a_throwing_watcher_is_reported_at_error(caplog):
    """A watcher that silently stopped watching is a dead control."""
    import logging

    from ai.awareness.watchers import register, run_all

    def explode():
        raise RuntimeError("data feed is gone")

    register("markets_execution", "broken", explode)
    with caplog.at_level(logging.ERROR):
        run_all()

    assert any(r.levelno >= logging.ERROR for r in caplog.records)


# ── suppression ───────────────────────────────────────────────────────────────


def test_the_same_condition_does_not_flood_the_queue():
    """A watcher on a 60-second loop would raise 1,440 proposals a day."""
    from ai.awareness import watchers
    from ai.awareness.watchers import register, run_all

    raised: list[dict] = []
    watchers.set_proposal_sink(raised.append)
    register("risk_compliance", "drawdown_near_limit", lambda: _observation())

    for _ in range(10):
        run_all()

    assert len(raised) == 1, f"the same open condition raised {len(raised)} proposals"


def test_a_condition_clearing_and_returning_raises_again():
    """Suppression must not become permanent blindness."""
    from ai.awareness import watchers
    from ai.awareness.watchers import register, run_all

    raised: list[dict] = []
    watchers.set_proposal_sink(raised.append)

    state = {"firing": True}
    register("risk_compliance", "drawdown_near_limit", lambda: _observation() if state["firing"] else None)

    run_all()
    state["firing"] = False
    run_all()  # clears
    state["firing"] = True
    run_all()  # fires again

    assert len(raised) == 2, "a condition that cleared and returned was suppressed"


def test_a_different_trigger_is_not_suppressed():
    from ai.awareness import watchers
    from ai.awareness.watchers import register, run_all

    raised: list[dict] = []
    watchers.set_proposal_sink(raised.append)
    register("risk_compliance", "a", lambda: _observation(trigger="a"))
    register("risk_compliance", "b", lambda: _observation(trigger="b"))
    run_all()

    assert len(raised) == 2


def test_a_severity_change_on_an_open_condition_raises_again():
    """warning -> critical is new information, not a repeat."""
    from ai.awareness import watchers
    from ai.awareness.watchers import register, run_all

    raised: list[dict] = []
    watchers.set_proposal_sink(raised.append)

    level = {"s": "warning"}
    register("risk_compliance", "drawdown", lambda: _observation(trigger="drawdown", severity=level["s"]))

    run_all()
    level["s"] = "critical"
    run_all()

    assert len(raised) == 2, "an escalation was suppressed as a duplicate"


# ── the real watchers ─────────────────────────────────────────────────────────


def test_every_department_has_at_least_one_watcher():
    from ai.awareness.watchers import install_default_watchers, registered
    from ai.departments import DEPARTMENTS

    install_default_watchers()
    covered = {department for department, _name in registered()}
    for key in DEPARTMENTS:
        assert key in covered, f"{key} has no watcher, so it notices nothing"


#: Departments whose `awareness` entries are PROSE rather than watcher names.
#:
#: Found by the test below when it was written, not designed. Cluster A
#: declares things like "broker disconnect detection"; Clusters B and C declare
#: "feed_stale" — the same field means two things, and `as_dict()` puts both on
#: the wire, so normalising Cluster A would change text an operator reads.
#:
#: Recorded here rather than quietly excluded, and asserted to be exactly these
#: four: closing the inconsistency means shrinking this list, and leaving it
#: stale fails.
PROSE_AWARENESS = {
    "markets_execution",
    "risk_compliance",
    "research_intelligence",
    "platform_engineering",
}


def test_every_declared_trigger_has_a_watcher():
    """A department's `awareness` tuple is a claim about what it notices.

    The existing test above counts departments: one watcher each is enough to
    pass it. That let `system_ops` ship declaring `breaker_open` with nothing
    watching for it — a trigger named in the directory, put on the wire by
    `as_dict()`, and unreachable. This asserts the claim itself, for every
    department that states it as a trigger name.
    """
    from ai.awareness.watchers import install_default_watchers, registered
    from ai.departments import DEPARTMENTS

    install_default_watchers()
    watched: dict[str, set[str]] = {}
    for department, name in registered():
        watched.setdefault(department, set()).add(name)

    for key, department in DEPARTMENTS.items():
        if key in PROSE_AWARENESS:
            continue
        for trigger in department.awareness:
            assert trigger in watched.get(key, set()), (
                f"{key} declares awareness of {trigger!r} and no watcher registers it, "
                f"so nothing ever notices — registered for {key}: {sorted(watched.get(key, set()))}"
            )


def test_the_prose_exemption_is_exactly_the_departments_that_need_it():
    """The exemption above must shrink when the inconsistency is fixed.

    An exemption list nobody re-checks becomes a permanent hole. This one
    fails if a department is added to it without needing it, and fails if one
    stops needing it and stays.
    """
    from ai.departments import DEPARTMENTS

    still_prose = {
        key
        for key, department in DEPARTMENTS.items()
        # A trigger name is an identifier. Prose has spaces in it.
        if any(" " in trigger for trigger in department.awareness)
    }
    assert still_prose == PROSE_AWARENESS, (
        f"PROSE_AWARENESS is stale: departments whose awareness is still prose are {sorted(still_prose)}"
    )


def test_the_default_watchers_survive_a_run_with_no_live_services():
    """CI has no broker, no feed, no positions. Nothing may throw."""
    from ai.awareness.watchers import install_default_watchers, run_all

    install_default_watchers()
    run_all()  # must not raise


# ── the wiring ────────────────────────────────────────────────────────────────


def test_a_startup_factory_exists_and_is_registered():
    import pathlib

    import core.startup_factories as F

    assert hasattr(F, "init_ai_awareness"), "no startup factory for awareness"
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    assert "F.init_ai_awareness" in src, "the factory is defined but never registered"


# ── the proposal actually lands in the real queue ─────────────────────────────
# The factory test above proves registration. This proves the sink it installs
# reaches the queue an operator actually reads — the seam where an "alerts list
# nobody looks at" would otherwise appear.


def test_a_queued_observation_lands_in_the_real_proposal_queue():
    import api.safe_agent_platform as sp

    before = len(sp._PROPOSALS)
    sp.queue_observation_proposal(
        {
            "id": "observation-test-1",
            "title": "[critical] risk_compliance: drawdown_limit_breached",
            "kind": "observation",
            "status": "pending",
            "created_by": "awareness:risk_compliance",
        }
    )
    try:
        assert len(sp._PROPOSALS) == before + 1
        assert sp._PROPOSALS[-1]["status"] == "pending"
    finally:
        sp._PROPOSALS[:] = sp._PROPOSALS[:before]


def test_an_observation_proposal_never_asks_for_two_approvers():
    """`repair` and `upgrade` carry a superadmin quorum. An observation is
    neither — it proposes nothing, so inheriting that quorum would make a
    notification harder to dismiss than a real change is to approve."""
    from ai.policy.roles import QUORUM_NEEDS_SUPERADMIN_KINDS

    assert "observation" not in QUORUM_NEEDS_SUPERADMIN_KINDS


def test_the_awareness_sink_the_factory_installs_reaches_that_queue():
    """Ties the two halves together, so neither can drift alone."""
    import pathlib

    import core.startup_factories as F

    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    assert "queue_observation_proposal" in src, "the factory does not queue anything"
