# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The operator queue, live — and a broadcast that cannot break the desk.

`GET /api/support/queue` was a poll. The owner asked to watch the queue in real
time and take over, which needs the queue to push.

Everything here is about the two ways a live channel goes wrong on a support
desk.

## A broadcast is never the operation

The ticket transition is the work. The push is a notification about it. If the
socket is down, the claim still happened, the reply is still saved, and the
customer is still answered — and the failure is logged at **ERROR**, because an
operator console that has silently stopped updating looks exactly like a quiet
queue. That is F248's shape: three alert call sites raised `TypeError` into a
handler that logged at DEBUG, so a tripped circuit breaker notified nobody for
as long as the code existed.

The reverse order matters too: the event is published **after** the store
commits, from what the store actually returned. Publishing first would announce
a claim that then failed — §E30's "success reported for work that did not
happen", one layer up.

## What travels, and what does not

The channel is operator-only (`_PRIVILEGED_CHANNELS`), so the payload may carry
what an operator needs to triage a row: id, status, department, category,
subject, who holds it. It carries **no message bodies**. An operator opens the
thread to read it; a broadcast that ships every customer message puts the whole
conversation into every connected console's memory, and into any log that
records frames.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sqlalchemy as sa
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from database.models import SupportMessage, SupportTicket

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'support.db'}")
    SupportTicket.__table__.create(engine)
    SupportMessage.__table__.create(engine)
    factory = sessionmaker(bind=engine)

    import api.support as mod
    from support.tickets import TicketStore

    monkeypatch.setattr(mod, "_store", lambda: TicketStore(factory))

    app = FastAPI()
    app.include_router(mod.router)
    yield app, mod, TestClient(app)
    engine.dispose()


def _as(app, mod, *, user_id: str, role: str):
    from api.auth import TokenPayload

    payload = TokenPayload(sub=user_id, role=role)
    app.dependency_overrides[mod._customer] = lambda: payload
    app.dependency_overrides[mod._operator] = lambda: payload
    return payload


def _as_customer(app, mod, *, user_id: str = "cust-1"):
    from fastapi import HTTPException

    from api.auth import TokenPayload

    payload = TokenPayload(sub=user_id, role="user")
    app.dependency_overrides[mod._customer] = lambda: payload

    def _refuse():
        raise HTTPException(status_code=403, detail="operator role required")

    app.dependency_overrides[mod._operator] = _refuse
    return payload


@pytest.fixture
def published():
    """Capture what reached the channel, without a socket."""
    sent: list[dict] = []

    async def _capture(event):
        sent.append(event)

    with patch("api.support._publish_queue_event", side_effect=_capture):
        yield sent


class TestTheQueuePushesWhenItChanges:
    def test_an_escalated_ticket_announces_itself(self, client, published):
        app, mod, http = client
        _as_customer(app, mod)

        http.post("/api/support/tickets", json={"subject": "refund please", "body": "I want a refund"})

        assert published, "a ticket reached the queue and nothing was pushed"
        assert published[-1]["needs_human"] is True
        assert published[-1]["event"] == "escalated"

    def test_a_ticket_the_ai_answers_does_not_announce(self, client, published, monkeypatch):
        """The queue channel carries the queue, not every ticket."""
        from support.answering import Answer

        app, mod, http = client
        _as_customer(app, mod)
        monkeypatch.setattr(
            mod, "answer_question", lambda *a, **k: Answer(available=True, text="Settings.", department="x")
        )

        http.post(
            "/api/support/tickets",
            json={"subject": "2fa", "body": "how do I enable two factor authentication"},
        )

        assert published == []

    @pytest.mark.parametrize(
        ("action", "event"),
        [("claim", "claimed"), ("release", "released"), ("resolve", "resolved")],
    )
    def test_each_operator_action_pushes(self, client, published, action: str, event: str):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        if action != "claim":
            http.post(f"/api/support/queue/{ticket_id}/claim")
        published.clear()

        assert http.post(f"/api/support/queue/{ticket_id}/{action}").status_code == 200
        assert [e["event"] for e in published] == [event]

    def test_a_customer_reply_on_a_queued_ticket_pushes(self, client, published):
        """The operator watching the row must see the customer answered."""
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]
        published.clear()

        http.post(f"/api/support/tickets/{ticket_id}/messages", json={"body": "any update?"})

        assert [e["event"] for e in published] == ["customer_replied"]

    def test_an_operator_reply_pushes_so_other_consoles_see_it(self, client, published):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        http.post(f"/api/support/queue/{ticket_id}/claim")
        published.clear()

        http.post(f"/api/support/queue/{ticket_id}/reply", json={"body": "looking now"})

        assert [e["event"] for e in published] == ["operator_replied"]


class TestThePayloadCarriesNoMessageBodies:
    def test_the_event_has_what_a_row_needs_and_no_more(self, client, published):
        app, mod, http = client
        _as_customer(app, mod)

        http.post(
            "/api/support/tickets",
            json={"subject": "refund please", "body": "I want a refund for order 12345"},
        )

        event = published[-1]
        assert event["subject"] == "refund please"
        assert {"ticket_id", "status", "needs_human", "department", "event"} <= set(event)
        assert "I want a refund" not in repr(event), (
            "a customer's message body travelled on the broadcast — an operator opens the thread to read it"
        )
        assert "body" not in event and "messages" not in event

    def test_an_operator_reply_body_does_not_travel_either(self, client, published):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        http.post(f"/api/support/queue/{ticket_id}/claim")
        published.clear()
        http.post(f"/api/support/queue/{ticket_id}/reply", json={"body": "secret internal note"})

        assert "secret internal note" not in repr(published)


class TestABroadcastFailureIsNeverTheOperation:
    def test_the_claim_still_happens_when_the_socket_is_down(self, client):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        with patch("api.support._publish_queue_event", side_effect=RuntimeError("socket gone")):
            response = http.post(f"/api/support/queue/{ticket_id}/claim")

        assert response.status_code == 200, "a dead socket refused a claim"
        assert http.get(f"/api/support/queue/{ticket_id}").json()["ticket"]["assigned_operator_id"] == "ops-1"

    def test_a_customer_can_still_open_a_ticket_when_the_socket_is_down(self, client):
        app, mod, http = client
        _as_customer(app, mod)

        with patch("api.support._publish_queue_event", side_effect=RuntimeError("socket gone")):
            response = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"})

        assert response.status_code == 201

    def test_the_failure_is_logged_at_error_not_debug(self, client, caplog):
        """An operator console that stopped updating looks like a quiet queue.

        F248: three alert call sites raised into a handler that logged at DEBUG,
        so a tripped circuit breaker notified nobody for as long as the code
        existed.
        """
        import logging

        app, mod, http = client
        _as_customer(app, mod)

        with caplog.at_level(logging.DEBUG, logger="api.support"):
            with patch("api.support._publish_queue_event", side_effect=RuntimeError("socket gone")):
                http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"})

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "the broadcast failed silently"
        assert "socket gone" in errors[0].getMessage()


class TestThePublishReachesTheRealChannel:
    @pytest.mark.asyncio
    async def test_it_broadcasts_on_the_operator_only_channel(self):
        """The seam every other test patches, exercised once for real.

        `support_queue` is privileged AND private — a customer cannot subscribe
        to it, and it is never delivered through the implicit-all firehose.
        `tests/unit/test_ws_privileged_channels.py` holds those two properties;
        this asserts the publisher actually uses that channel.
        """
        from api.support import _publish_queue_event

        with patch("api.ws_live.get_live_manager") as get_manager:
            manager = get_manager.return_value

            async def _noop(channel, msg):
                return None

            manager.broadcast.side_effect = _noop
            await _publish_queue_event({"event": "escalated", "ticket_id": "t1"})

        channel, msg = manager.broadcast.call_args.args
        assert channel == "support_queue"
        assert msg["type"] == "support_queue"
        assert msg["data"]["ticket_id"] == "t1"

    def test_the_channel_is_operator_only(self):
        from api.ws_live import LiveConnectionManager

        assert "support_queue" in LiveConnectionManager._PRIVILEGED_CHANNELS
        assert "support_queue" in LiveConnectionManager._PRIVATE_CHANNELS


class TestNothingIsAnnouncedForATicketThatIsNotThere:
    @pytest.mark.asyncio
    async def test_announce_on_a_missing_ticket_is_a_no_op(self):
        """A guard, proven rather than assumed.

        `_transition` re-reads the ticket after the store commits. A `None`
        there means the row vanished between the write and the read — a
        concurrent delete, or a store that returned success for work that did
        not happen. Broadcasting a row built from `None` would raise inside the
        publisher and take the whole notification path down with it.
        """
        from api.support import _announce

        with patch("api.support._publish_queue_event") as publish:
            await _announce("claimed", None)

        assert publish.call_count == 0


class TestNothingIsAnnouncedForATransitionThatDidNotHappen:
    """The ordering rule, and the counterfactual that exposed it as unproven.

    Moving `_announce` above the store call left all fifteen tests green: the
    event *names* were still right, only the payload was the pre-transition
    state, and a refused claim's broadcast was covered by nothing.

    That is §E30's shape one layer up — "success reported for work that did not
    happen". A losing claim would have put a row on every console showing an
    operator who does not hold the ticket, and the operator who does hold it
    watching their row get taken.
    """

    def test_a_losing_claim_announces_nothing(self, client, published):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        http.post(f"/api/support/queue/{ticket_id}/claim")
        published.clear()

        _as(app, mod, user_id="ops-2", role="admin")
        assert http.post(f"/api/support/queue/{ticket_id}/claim").status_code == 409

        assert published == [], (
            "a claim that lost the race was broadcast — every console now shows "
            "an operator who does not hold this ticket"
        )

    def test_a_refused_reply_announces_nothing(self, client, published):
        from support.tickets import Outcome

        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        published.clear()

        with patch.object(mod.TicketStore, "add_message", return_value=Outcome(False, "thread locked")):
            assert http.post(f"/api/support/queue/{ticket_id}/reply", json={"body": "hello"}).status_code == 409

        assert published == []

    def test_the_payload_is_the_state_after_the_transition(self, client, published):
        """Not before it. A row announced from the pre-transition read shows
        the console the world as it was a moment ago, which is worse than not
        updating: it looks current."""
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        published.clear()
        http.post(f"/api/support/queue/{ticket_id}/claim")

        assert published[-1]["assigned_operator_id"] == "ops-1", (
            "the claim was announced from the state before it happened"
        )
        assert published[-1]["status"] == "with_operator"

    def test_a_resolve_announces_the_resolved_state(self, client, published):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        http.post(f"/api/support/queue/{ticket_id}/claim")
        published.clear()
        http.post(f"/api/support/queue/{ticket_id}/resolve")

        assert published[-1]["status"] == "resolved"
