# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§16: memory tiers, a knowledge graph, and the operator's control over both.

## Why this file leads with deletion

Four of §16's rows are about remembering. The fifth is "user review, correction
and deletion", and it is the one that can be got wrong in a way nobody notices:
a `forget()` that clears the in-process deque and leaves the durable rows
returns success, prints a reassuring count, and has deleted nothing that
survives a restart. The operator was told their data was gone.

`SqlMemoryBackend` had `write` and `read` and no `delete` at all, so that was
not a hypothetical — it was the only outcome available.

So the rule is: **a deletion that cannot reach every store reports what it could
not reach.** Never a bare success, never a count that includes rows still on
disk. `forget()` returns what it deleted AND what it could not, and a backend
that cannot delete makes `complete` false.

## The tiers differ by RETENTION, not by name

Working memory that survives the turn is not working memory, it is a leak with
a label. Each tier is asserted to actually forget on its own boundary.

## Long-term requires approval

The staged note on `memory.long_term` said "durable storage exists; approval
governance does not" — which means "long-term" was a synonym for "everything,
for ever". A fact reaches long-term when somebody approves it and not before.

These fail on the pre-fix tree: `ai.memory.tiers`, `ai.memory.graph` and
`ai.memory.governance` do not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    from ai.memory import governance, graph, store, tiers

    store.reset_for_testing()
    tiers.reset_for_testing()
    graph.reset_for_testing()
    governance.reset_for_testing()
    yield
    store.reset_for_testing()
    tiers.reset_for_testing()
    graph.reset_for_testing()
    governance.reset_for_testing()


# ── deletion, first ───────────────────────────────────────────────────────────


def test_forgetting_removes_the_fact_from_every_tier():
    from ai.memory import governance, tiers

    for tier in tiers.TIERS:
        tiers.remember(tier, operator="owner", kind="note", value=f"something in {tier}", source="test")

    result = governance.forget(operator="owner")
    assert result.complete is True
    for tier in tiers.TIERS:
        assert tiers.recall(tier, operator="owner") == [], f"{tier} still holds it"


def test_a_backend_that_cannot_delete_makes_the_result_incomplete():
    """The failure this file leads with. A `forget` that returns success while
    rows survive on disk has told the operator something untrue."""
    from ai.memory import governance, store, tiers

    class _WriteOnly:
        """The backend as it was: write and read, no delete."""

        def write(self, entry):
            return None

        def read(self, department, *, kind=None, limit=50):
            return []

    store.set_backend(_WriteOnly())
    tiers.remember("project", operator="owner", kind="note", value="x", source="test")

    result = governance.forget(operator="owner")
    assert result.complete is False
    assert any("delete" in reason.lower() for reason in result.unreachable)


def test_a_backend_that_can_delete_is_asked_to():
    from ai.memory import governance, store, tiers

    deleted: list[str] = []

    class _Deleting:
        def write(self, entry):
            return None

        def read(self, department, *, kind=None, limit=50):
            return []

        def delete(self, *, operator):
            deleted.append(operator)
            return 3

    store.set_backend(_Deleting())
    tiers.remember("project", operator="owner", kind="note", value="x", source="test")

    result = governance.forget(operator="owner")
    assert deleted == ["owner"]
    assert result.complete is True
    assert result.durable_rows == 3


def test_forgetting_one_operator_does_not_touch_another():
    """The most expensive way to get a deletion right and still be wrong."""
    from ai.memory import governance, tiers

    tiers.remember("session", operator="alice", kind="note", value="alice's", source="test")
    tiers.remember("session", operator="bob", kind="note", value="bob's", source="test")

    governance.forget(operator="alice")
    assert tiers.recall("session", operator="alice") == []
    assert len(tiers.recall("session", operator="bob")) == 1


def test_forgetting_reports_what_it_removed_rather_than_a_bare_success():
    """An operator exercising a deletion right is owed the count."""
    from ai.memory import governance, tiers

    for i in range(3):
        tiers.remember("episodic", operator="owner", kind="event", value=f"e{i}", source="test")
    result = governance.forget(operator="owner")
    assert result.removed == 3


def test_forgetting_nothing_is_not_an_error_and_says_so():
    from ai.memory import governance

    result = governance.forget(operator="nobody")
    assert result.complete is True
    assert result.removed == 0


# ── the tiers actually forget ─────────────────────────────────────────────────


def test_working_memory_does_not_survive_the_turn():
    """Working memory that survives the turn is not working memory, it is a
    leak with a label."""
    from ai.memory import tiers

    tiers.remember("working", operator="owner", kind="scratch", value="mid-thought", source="test")
    assert len(tiers.recall("working", operator="owner")) == 1

    tiers.end_turn("owner")
    assert tiers.recall("working", operator="owner") == []


def test_ending_a_turn_leaves_the_longer_tiers_alone():
    from ai.memory import tiers

    for tier in ("session", "episodic", "project"):
        tiers.remember(tier, operator="owner", kind="note", value="keep me", source="test")
    tiers.end_turn("owner")
    for tier in ("session", "episodic", "project"):
        assert len(tiers.recall(tier, operator="owner")) == 1, f"{tier} was cleared by a turn ending"


def test_session_memory_does_not_survive_the_session():
    from ai.memory import tiers

    tiers.remember("session", operator="owner", kind="note", value="this session", source="test")
    tiers.end_session("owner")
    assert tiers.recall("session", operator="owner") == []


def test_ending_a_session_ends_the_turn_inside_it():
    """A turn cannot outlive the session it happened in."""
    from ai.memory import tiers

    tiers.remember("working", operator="owner", kind="scratch", value="x", source="test")
    tiers.end_session("owner")
    assert tiers.recall("working", operator="owner") == []


def test_episodic_and_long_term_survive_a_session():
    from ai.memory import tiers

    tiers.remember("episodic", operator="owner", kind="event", value="the kill switch tripped", source="test")
    tiers.end_session("owner")
    assert len(tiers.recall("episodic", operator="owner")) == 1


def test_one_operators_turn_ending_does_not_clear_anothers():
    from ai.memory import tiers

    tiers.remember("working", operator="alice", kind="s", value="a", source="test")
    tiers.remember("working", operator="bob", kind="s", value="b", source="test")
    tiers.end_turn("alice")
    assert tiers.recall("working", operator="alice") == []
    assert len(tiers.recall("working", operator="bob")) == 1


def test_every_tier_is_bounded():
    """Memory that only grows is a cost and, for anything touching positions, a
    liability."""
    from ai.memory import tiers

    for tier in tiers.TIERS:
        for i in range(tiers.LIMITS[tier] + 25):
            tiers.remember(tier, operator="owner", kind="n", value=i, source="test")
        assert len(tiers.recall(tier, operator="owner", limit=10_000)) <= tiers.LIMITS[tier]


def test_an_unknown_tier_is_refused():
    """A typo must not open a memory nobody reads — the rule the department
    store already applies to department names."""
    from ai.memory import tiers

    with pytest.raises(ValueError, match="tier"):
        tiers.remember("permanent", operator="owner", kind="n", value=1, source="test")


# ── provenance ────────────────────────────────────────────────────────────────


def test_every_entry_records_where_it_came_from_and_when():
    from ai.memory import tiers

    entry = tiers.remember("episodic", operator="owner", kind="event", value="x", source="watcher:drawdown")
    assert entry["source"] == "watcher:drawdown"
    assert entry["at"]
    assert entry["operator"] == "owner"


def test_an_entry_with_no_source_is_refused():
    """An unattributable memory is one nobody can check, and it will be handed
    back to a model as though somebody had."""
    from ai.memory import tiers

    with pytest.raises(ValueError, match="source"):
        tiers.remember("episodic", operator="owner", kind="event", value="x", source="  ")


def test_a_credential_is_refused_at_every_tier():
    """Memory is durable: a secret written here outlives the conversation that
    leaked it, and the next recall hands it to a model again."""
    from ai.guardrails.output import GuardrailViolation, register_known_secret, reset_known_secrets
    from ai.memory import tiers

    register_known_secret("test-token", "sk-live-abcdef0123456789")
    try:
        for tier in tiers.TIERS:
            with pytest.raises(GuardrailViolation):
                tiers.remember(tier, operator="owner", kind="n", value="sk-live-abcdef0123456789", source="test")
    finally:
        reset_known_secrets()


# ── correction, which is not overwriting ──────────────────────────────────────


def test_correcting_a_fact_keeps_that_it_was_corrected():
    """Silently overwriting loses the fact that the AI once believed something
    else — which is exactly what somebody auditing a wrong decision needs."""
    from ai.memory import governance, tiers

    entry = tiers.remember("project", operator="owner", kind="fact", value="gold at 2400", source="test")
    corrected = governance.correct(entry["id"], operator="owner", value="gold at 2450", by="owner")

    assert corrected is not None
    assert corrected["value"] == "gold at 2450"
    assert corrected["corrected_from"] == "gold at 2400"
    assert corrected["corrected_by"] == "owner"


def test_correcting_something_that_is_not_yours_is_refused():
    from ai.memory import governance, tiers

    entry = tiers.remember("project", operator="alice", kind="fact", value="x", source="test")
    assert governance.correct(entry["id"], operator="bob", value="y", by="bob") is None


def test_reviewing_returns_everything_remembered_about_one_operator():
    """ "Review" that shows a subset is not review."""
    from ai.memory import governance, tiers

    for tier in tiers.TIERS:
        tiers.remember(tier, operator="owner", kind="n", value=tier, source="test")
    review = governance.review(operator="owner")
    assert set(review["tiers"]) == set(tiers.TIERS)
    assert review["total"] == len(tiers.TIERS)


def test_reviewing_shows_nothing_of_another_operators():
    from ai.memory import governance, tiers

    tiers.remember("project", operator="alice", kind="n", value="alice's", source="test")
    assert governance.review(operator="bob")["total"] == 0


# ── long-term needs approval ──────────────────────────────────────────────────


def test_a_fact_does_not_reach_long_term_without_approval():
    """Otherwise "long-term" is a synonym for "everything, for ever"."""
    from ai.memory import governance, tiers

    governance.propose_long_term(operator="owner", kind="fact", value="XAUUSD is the only symbol traded", source="test")
    assert tiers.recall("long_term", operator="owner") == []


def test_an_approved_fact_reaches_long_term_and_says_who_approved_it():
    from ai.memory import governance, tiers

    proposal = governance.propose_long_term(
        operator="owner", kind="fact", value="XAUUSD is the only symbol traded", source="test"
    )
    assert governance.approve_long_term(proposal["id"], by="owner") is True

    stored = tiers.recall("long_term", operator="owner")
    assert len(stored) == 1
    assert stored[0]["approved_by"] == "owner"


def test_approving_something_twice_does_not_store_it_twice():
    from ai.memory import governance, tiers

    proposal = governance.propose_long_term(operator="owner", kind="fact", value="x", source="test")
    assert governance.approve_long_term(proposal["id"], by="owner") is True
    assert governance.approve_long_term(proposal["id"], by="owner") is False
    assert len(tiers.recall("long_term", operator="owner")) == 1


def test_pending_proposals_are_listed_for_review():
    from ai.memory import governance

    governance.propose_long_term(operator="owner", kind="fact", value="x", source="test")
    assert len(governance.pending_long_term(operator="owner")) == 1


# ── the knowledge graph ───────────────────────────────────────────────────────


def test_a_relation_must_be_one_the_graph_declares():
    """An invented relation is a claim the reader cannot check — the rule the
    surface-relationship table already follows."""
    from ai.memory import graph

    with pytest.raises(ValueError, match="relation"):
        graph.link("XAUUSD", "vibes with", "the moon", operator="owner")


def test_a_declared_relation_links_two_entities():
    from ai.memory import graph

    graph.link("job:42", "produced", "report:7", operator="owner")
    assert [n.entity for n in graph.neighbours("job:42", operator="owner")] == ["report:7"]


def test_the_graph_is_per_operator():
    from ai.memory import graph

    graph.link("a", "relates_to", "b", operator="alice")
    assert graph.neighbours("a", operator="bob") == []


def test_a_relation_carries_provenance():
    from ai.memory import graph

    graph.link("a", "relates_to", "b", operator="owner", source="synthesis")
    edge = graph.neighbours("a", operator="owner")[0]
    assert edge.source == "synthesis"
    assert edge.at


def test_forgetting_an_operator_clears_their_graph_too():
    """A deletion that left the relations behind would leave the shape of what
    was deleted — who worked on what, and when."""
    from ai.memory import governance, graph

    graph.link("a", "relates_to", "b", operator="owner")
    governance.forget(operator="owner")
    assert graph.neighbours("a", operator="owner") == []


def test_the_graph_is_bounded():
    from ai.memory import graph

    for i in range(graph.MAX_EDGES + 50):
        graph.link(f"n{i}", "relates_to", "hub", operator="owner")
    assert graph.edge_count("owner") <= graph.MAX_EDGES


def test_the_real_backend_deliberately_offers_no_operator_delete():
    """Pinning a decision, not describing a gap.

    `ai_department_memory` is keyed by department and has no operator column, so
    an operator-scoped delete is not expressible against it without a migration.
    A `delete(operator=...)` that quietly matched nothing and returned 0 would
    make `forget()` report complete while deleting nothing — worse than having
    none, which is why there is none. If somebody adds one, it must actually
    delete, and this test is where they find out that is the contract.
    """
    from ai.memory.sql_backend import SqlMemoryBackend

    assert not hasattr(SqlMemoryBackend, "delete"), (
        "SqlMemoryBackend grew a `delete` — it must be operator-scoped and real, "
        "or `forget()` will report a complete deletion that is not one"
    )


def test_forget_is_complete_when_there_is_no_durable_backend():
    """Nothing durable to reach is not the same as failing to reach it."""
    from ai.memory import governance, store, tiers

    store.set_backend(None)
    tiers.remember("session", operator="owner", kind="n", value="x", source="test")
    result = governance.forget(operator="owner")
    assert result.complete is True
    assert result.unreachable == ()


def test_a_result_cannot_report_complete_beside_something_unreachable():
    """`complete` is derived, not stored, so the two cannot disagree — and a
    caller reading only the flag cannot be told a clean deletion happened."""
    from ai.memory.governance import ForgetResult

    assert ForgetResult(operator="o", unreachable=("something",)).complete is False
    assert ForgetResult(operator="o").complete is True


# ── it has to run, and it has to be reachable ─────────────────────────────────


def test_a_critical_notification_becomes_an_episodic_memory():
    """`ai/memory/tiers.py` could be perfect and never be written to. A tripped
    kill switch is the definition of a significant event."""
    from ai.memory import tiers
    from ai.notify import Notification, Severity, service

    service.reset_for_testing()
    service.submit(
        Notification(key="kill", severity=Severity.CRITICAL, title="Kill switch tripped", body="b", operator="owner")
    )
    remembered = tiers.recall("episodic", operator="owner")
    assert len(remembered) == 1
    assert remembered[0]["value"]["title"] == "Kill switch tripped"
    service.reset_for_testing()


def test_routine_chatter_does_not_become_an_episodic_memory():
    """An episodic memory of every informational notice is a log with a grander
    name."""
    from ai.memory import tiers
    from ai.notify import Notification, Severity, service

    service.reset_for_testing()
    service.submit(Notification(key="fyi", severity=Severity.INFORMATIONAL, title="t", body="b", operator="owner"))
    assert tiers.recall("episodic", operator="owner") == []
    service.reset_for_testing()


def test_a_broken_memory_store_cannot_stop_a_critical_alert():
    """Remembering an event is worth less than delivering it."""
    import ai.memory.tiers as tiers_module
    from ai.notify import Notification, Severity, service

    service.reset_for_testing()
    original = tiers_module.remember
    tiers_module.remember = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("memory is down"))
    try:
        decision = service.submit(
            Notification(key="kill", severity=Severity.CRITICAL, title="t", body="b", operator="owner")
        )
        assert decision.action == "deliver"
        assert len(service.inbox_for("owner")) == 1
    finally:
        tiers_module.remember = original
        service.reset_for_testing()


@pytest.mark.asyncio
async def test_the_review_endpoint_shows_only_the_callers_memory():
    from ai.memory import tiers
    from api.ai_memory import memory_review
    from api.auth import TokenPayload

    tiers.remember("project", operator="alice", kind="n", value="alice's", source="test")
    body = await memory_review(TokenPayload(sub="bob", role="superadmin"))
    assert body["total"] == 0
    assert body["operator"] == "bob"


@pytest.mark.asyncio
async def test_correcting_someone_elses_entry_is_a_404_not_a_403():
    """Separating "not yours" from "no such entry" turns an id into an oracle
    for what the AI remembers about other people."""
    from fastapi import HTTPException

    from ai.memory import tiers
    from api.ai_memory import memory_correct
    from api.auth import TokenPayload

    entry = tiers.remember("project", operator="alice", kind="n", value="x", source="test")
    with pytest.raises(HTTPException) as caught:
        await memory_correct(entry["id"], {"value": "y"}, TokenPayload(sub="bob", role="superadmin"))
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_the_forget_endpoint_reports_completeness_rather_than_a_bare_ok():
    from ai.memory import tiers
    from api.ai_memory import memory_forget
    from api.auth import TokenPayload

    tiers.remember("session", operator="owner", kind="n", value="x", source="test")
    body = await memory_forget(TokenPayload(sub="owner", role="superadmin"))
    assert body["removed"] == 1
    assert body["complete"] is True
    assert "unreachable" in body


@pytest.mark.asyncio
async def test_the_tiers_endpoint_states_the_retention_of_each():
    """An operator deciding what to let the AI keep needs to know how long each
    tier keeps it."""
    from api.ai_memory import memory_tiers
    from api.auth import TokenPayload

    body = await memory_tiers(TokenPayload(sub="owner", role="superadmin"))
    assert set(body["retention"]) == set(body["tiers"])
    assert "cleared when the turn ends" in body["retention"]["working"]
