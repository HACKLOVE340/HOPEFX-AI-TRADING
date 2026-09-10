# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""A ticket the AI cannot close, and a queue two operators cannot both claim.

`support/triage.py` decides who should answer. It decides and forgets: nothing
persisted the conversation, nothing collected the escalations for a person to
work, and nothing stopped the AI from marking its own escalation resolved.

This is that store. The two properties worth having tests are both refusals:

1. **An escalated ticket cannot be resolved by the AI.** The floor in triage is
   worth nothing if the thing it escalated to can be closed by the same AI a
   moment later. `resolve(actor=AI)` on a ticket that needs a human returns a
   refusal, not a log line.
2. **Two operators cannot claim the same ticket.** A claim that silently
   overwrites means two people work one customer while another queue item waits
   — and the second operator has no way to know. The second claim is refused
   and says who holds it.

Both are enforced as *returned refusals* on a state machine, in the shape
`invariants/` uses: the caller reads whether it was allowed. A transition that
logs and proceeds is the F176 shape — a control that exists and never stops
anything.

Rule 2 applies to the timestamps: `first_response_at` is `None` until something
actually responded. A store that stamps it on creation reports a support desk
answering every ticket instantly, which is exactly the kind of number nobody
checks.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def store():
    """A real session factory over an in-memory SQLite database.

    Not a fake: the refusals below depend on what the database does under a
    concurrent claim, and a stand-in that shares none of its code would agree
    with every assertion.
    """
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from database.models import SupportMessage, SupportTicket
    from support.tickets import TicketStore

    engine = sa.create_engine("sqlite://")
    SupportTicket.__table__.create(engine)
    SupportMessage.__table__.create(engine)
    yield TicketStore(sessionmaker(bind=engine))
    engine.dispose()


def _open(store, question="how do I enable two factor authentication"):
    return store.open_ticket(user_id="cust-1", subject="help", body=question)


class TestTheAICannotCloseWhatItEscalated:
    def test_an_escalated_ticket_refuses_an_ai_resolution(self, store):
        from support.tickets import Actor

        ticket = store.open_ticket(user_id="cust-1", subject="withdrawal", body="withdraw my balance to my bank")
        assert ticket.needs_human is True, "the floor should have caught this on open"

        outcome = store.resolve(ticket.id, actor=Actor.AI)

        assert outcome.allowed is False
        assert outcome.reason, "a refusal must say why"
        assert store.get(ticket.id).status != "resolved"

    def test_an_operator_can_resolve_the_same_ticket(self, store):
        from support.tickets import Actor

        ticket = store.open_ticket(user_id="cust-1", subject="withdrawal", body="withdraw my balance to my bank")
        store.claim(ticket.id, operator_id="ops-9")

        outcome = store.resolve(ticket.id, actor=Actor.OPERATOR, actor_id="ops-9")

        assert outcome.allowed is True
        assert store.get(ticket.id).status == "resolved"

    def test_the_ai_may_resolve_a_ticket_it_was_allowed_to_answer(self, store):
        """A desk where the AI can close nothing is a desk with no AI in it."""
        from support.tickets import Actor

        ticket = _open(store)
        assert ticket.needs_human is False

        assert store.resolve(ticket.id, actor=Actor.AI).allowed is True

    def test_escalating_later_takes_the_ai_resolution_away(self, store):
        """The floor is not only checked at open.

        A conversation that turns into a refund request mid-thread must move out
        of the AI's reach, not stay closable because its first message was a
        how-to.
        """
        from support.tickets import Actor

        ticket = _open(store)
        store.add_message(ticket.id, author_kind="customer", body="actually I want a refund")

        assert store.get(ticket.id).needs_human is True
        assert store.resolve(ticket.id, actor=Actor.AI).allowed is False


class TestTheOperatorQueue:
    def test_an_escalated_ticket_is_in_the_queue(self, store):
        store.open_ticket(user_id="cust-1", subject="x", body="I want a refund")

        queue = store.operator_queue()

        assert len(queue) == 1
        assert queue[0].needs_human is True

    def test_a_ticket_the_ai_can_answer_is_not_in_the_queue(self, store):
        _open(store)
        assert store.operator_queue() == []

    def test_a_second_claim_is_refused_and_names_the_holder(self, store):
        ticket = store.open_ticket(user_id="cust-1", subject="x", body="I want a refund")
        assert store.claim(ticket.id, operator_id="ops-1").allowed is True

        outcome = store.claim(ticket.id, operator_id="ops-2")

        assert outcome.allowed is False
        assert "ops-1" in (outcome.reason or ""), "the second operator must be told who holds it"
        assert store.get(ticket.id).assigned_operator_id == "ops-1"

    def test_reclaiming_your_own_ticket_is_not_an_error(self, store):
        """A refreshed page must not look like a conflict."""
        ticket = store.open_ticket(user_id="cust-1", subject="x", body="I want a refund")
        store.claim(ticket.id, operator_id="ops-1")

        assert store.claim(ticket.id, operator_id="ops-1").allowed is True

    def test_a_claimed_ticket_leaves_the_unassigned_queue(self, store):
        ticket = store.open_ticket(user_id="cust-1", subject="x", body="I want a refund")
        store.claim(ticket.id, operator_id="ops-1")

        assert store.operator_queue(unassigned_only=True) == []
        assert len(store.operator_queue()) == 1

    def test_releasing_a_ticket_puts_it_back(self, store):
        ticket = store.open_ticket(user_id="cust-1", subject="x", body="I want a refund")
        store.claim(ticket.id, operator_id="ops-1")

        assert store.release(ticket.id, operator_id="ops-1").allowed is True
        assert len(store.operator_queue(unassigned_only=True)) == 1

    def test_an_operator_cannot_release_someone_elses_ticket(self, store):
        ticket = store.open_ticket(user_id="cust-1", subject="x", body="I want a refund")
        store.claim(ticket.id, operator_id="ops-1")

        outcome = store.release(ticket.id, operator_id="ops-2")

        assert outcome.allowed is False
        assert store.get(ticket.id).assigned_operator_id == "ops-1"

    def test_the_queue_is_oldest_first(self, store):
        """A support queue ordered newest-first starves the person waiting longest."""
        a = store.open_ticket(user_id="c1", subject="x", body="I want a refund")
        b = store.open_ticket(user_id="c2", subject="y", body="I want a refund")

        assert [t.id for t in store.operator_queue()] == [a.id, b.id]


class TestAnUnmeasuredTimestampIsAbsent:
    def test_first_response_is_none_until_something_responds(self, store):
        ticket = _open(store)
        assert ticket.first_response_at is None

    def test_a_customer_message_is_not_a_response(self, store):
        ticket = _open(store)
        store.add_message(ticket.id, author_kind="customer", body="anyone there?")
        assert store.get(ticket.id).first_response_at is None

    @pytest.mark.parametrize("who", ["ai", "operator"])
    def test_an_answer_records_when_it_arrived(self, store, who: str):
        ticket = _open(store)
        store.add_message(ticket.id, author_kind=who, body="here is how")
        assert store.get(ticket.id).first_response_at is not None

    def test_the_first_response_is_the_first_one(self, store):
        """Later replies must not overwrite the measurement."""
        ticket = _open(store)
        store.add_message(ticket.id, author_kind="ai", body="one")
        first = store.get(ticket.id).first_response_at
        store.add_message(ticket.id, author_kind="operator", body="two")

        assert store.get(ticket.id).first_response_at == first


class TestTheTicketRecordsWhyItWasRouted:
    def test_it_keeps_the_triage_decision(self, store):
        ticket = store.open_ticket(user_id="c1", subject="x", body="why was my order rejected")

        assert ticket.category == "orders_or_execution"
        assert ticket.department == "markets_execution"

    def test_an_escalation_keeps_its_reason_and_evidence(self, store):
        ticket = store.open_ticket(user_id="c1", subject="x", body="I want a refund")

        assert ticket.escalation_reason
        assert ticket.matched_on, "an operator taking over must see why it landed here"

    def test_messages_round_trip_in_order(self, store):
        ticket = _open(store)
        store.add_message(ticket.id, author_kind="ai", body="first")
        store.add_message(ticket.id, author_kind="customer", body="second")

        bodies = [m.body for m in store.messages(ticket.id)]
        assert bodies == [
            "how do I enable two factor authentication",
            "first",
            "second",
        ]


class TestTheStateMachineRefusesRatherThanLogs:
    def test_an_unknown_ticket_is_a_refusal_not_a_crash(self, store):
        from support.tickets import Actor

        outcome = store.resolve("no-such-ticket", actor=Actor.OPERATOR, actor_id="ops-1")
        assert outcome.allowed is False
        assert "not found" in (outcome.reason or "").lower()

    def test_a_resolved_ticket_cannot_be_claimed(self, store):
        from support.tickets import Actor

        ticket = _open(store)
        store.resolve(ticket.id, actor=Actor.AI)

        assert store.claim(ticket.id, operator_id="ops-1").allowed is False

    def test_reopening_a_resolved_ticket_is_allowed(self, store):
        """A customer replying after a close must not need a new ticket."""
        from support.tickets import Actor

        ticket = _open(store)
        store.resolve(ticket.id, actor=Actor.AI)
        store.add_message(ticket.id, author_kind="customer", body="that did not work")

        assert store.get(ticket.id).status == "open"


class TestAFollowUpIsCheckedAgainstTheFloorAndNothingElse:
    """Found by a failing test, not by reasoning about it.

    `test_reopening_a_resolved_ticket_is_allowed` failed with
    `awaiting_operator` where it expected `open`: re-running the whole of
    `triage` on *"that did not work"* categorised nothing, hit the
    unroutable-goes-to-a-human branch, and escalated. Every conversation would
    have escalated on its second turn, and the operator queue would have filled
    with people saying "thanks".

    Routing is decided once per thread. The floor applies to every message.
    """

    @pytest.mark.parametrize(
        "reply",
        ["that did not work", "ok thanks", "still broken", "?", "any update"],
    )
    def test_a_conversational_follow_up_does_not_escalate(self, store, reply: str):
        ticket = _open(store)
        store.add_message(ticket.id, author_kind="customer", body=reply)

        assert store.get(ticket.id).needs_human is False, (
            f"{reply!r} escalated — the follow-up path is running the router, not the floor"
        )

    @pytest.mark.parametrize(
        "reply",
        [
            "actually I want a refund",
            "should I buy gold instead",
            "someone else logged into my account",
            "I am taking legal action",
        ],
    )
    def test_the_floor_still_applies_on_every_message(self, store, reply: str):
        ticket = _open(store)
        store.add_message(ticket.id, author_kind="customer", body=reply)

        assert store.get(ticket.id).needs_human is True


class TestNeedsHumanIsSticky:
    def test_a_later_harmless_message_does_not_clear_it(self, store):
        """A customer who mentions a withdrawal and then changes the subject
        has not made the ticket safe for an AI to close."""
        from support.tickets import Actor

        ticket = store.open_ticket(user_id="c1", subject="x", body="I want to withdraw my balance")
        store.add_message(ticket.id, author_kind="customer", body="never mind, how do I enable 2fa")

        assert store.get(ticket.id).needs_human is True
        assert store.resolve(ticket.id, actor=Actor.AI).allowed is False

    def test_the_escalation_reason_is_not_overwritten_by_a_later_one(self, store):
        """The first reason is the one that took it out of the AI's hands."""
        ticket = store.open_ticket(user_id="c1", subject="x", body="I want to withdraw my balance")
        first = store.get(ticket.id).escalation_reason

        store.add_message(ticket.id, author_kind="customer", body="also I am reporting you")

        assert store.get(ticket.id).escalation_reason == first


class TestWhoMayResolve:
    def test_a_customer_cannot_resolve_their_own_ticket_here(self, store):
        """Not a judgement about customers — this store has no authenticated
        customer identity, so accepting it would be accepting an unchecked claim."""
        from support.tickets import Actor

        ticket = _open(store)
        assert store.resolve(ticket.id, actor=Actor.CUSTOMER).allowed is False

    def test_an_operator_resolving_records_who(self, store):
        from support.tickets import Actor

        ticket = store.open_ticket(user_id="c1", subject="x", body="I want a refund")
        store.resolve(ticket.id, actor=Actor.OPERATOR, actor_id="ops-7")

        assert store.get(ticket.id).assigned_operator_id == "ops-7"
        assert store.get(ticket.id).resolved_at is not None

    def test_an_unknown_ticket_refuses_every_transition(self, store):
        from support.tickets import Actor

        assert store.claim("nope", operator_id="ops-1").allowed is False
        assert store.release("nope", operator_id="ops-1").allowed is False
        assert store.resolve("nope", actor=Actor.OPERATOR).allowed is False
        assert store.add_message("nope", author_kind="ai", body="hello").allowed is False
        assert store.get("nope") is None
        assert store.messages("nope") == []


class TestTheViewsAreSerialisable:
    def test_a_ticket_renders_without_a_live_session(self, store):
        ticket = store.open_ticket(user_id="c1", subject="x", body="I want a refund")
        payload = store.get(ticket.id).as_dict()

        assert payload["needs_human"] is True
        assert payload["first_response_at"] is None
        assert isinstance(payload["created_at"], str)

    def test_a_message_renders(self, store):
        ticket = _open(store)
        payload = store.messages(ticket.id)[0].as_dict()

        assert payload["author_kind"] == "customer"
        assert isinstance(payload["created_at"], str)


class TestEscalationDoesNotDisturbAnOperatorAlreadyOnTheTicket:
    def test_a_claimed_ticket_stays_with_its_operator(self, store):
        """Bouncing it back to the queue would take it off the desk of the
        person mid-conversation with the customer."""
        ticket = _open(store)
        store.claim(ticket.id, operator_id="ops-3")

        store.add_message(ticket.id, author_kind="customer", body="and I want a refund")

        after = store.get(ticket.id)
        assert after.needs_human is True
        assert after.status == "with_operator"
        assert after.assigned_operator_id == "ops-3"

    def test_a_reopened_escalated_ticket_returns_to_the_queue(self, store):
        """Reopening puts it back in front of a person, not back with the AI."""
        from support.tickets import Actor

        ticket = store.open_ticket(user_id="c1", subject="x", body="I want a refund")
        store.claim(ticket.id, operator_id="ops-3")
        store.resolve(ticket.id, actor=Actor.OPERATOR, actor_id="ops-3")
        assert store.get(ticket.id).status == "resolved"

        # A conversational reply — nothing on the floor matches it. The ticket
        # still needs a person, because `needs_human` never clears.
        store.add_message(ticket.id, author_kind="customer", body="that is still not sorted")

        after = store.get(ticket.id)
        assert after.status == "awaiting_operator", (
            "a reopened escalated ticket landed in a state the operator queue does not show"
        )
        assert len(store.operator_queue()) == 1
