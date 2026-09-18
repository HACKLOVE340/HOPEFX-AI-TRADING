# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""An opaque ticket id is not authorisation.

`support/` decides, records and drafts. Nothing HTTP-facing reached any of it,
so no customer could open a ticket and no operator could see one. This is that
surface, and the tests that matter are the ones about who may read what.

The finding this file is written against is S6-02's shape: `api/advanced_orders.py`
declared a router with no dependencies and three routes with no ownership check,
so `GET /{order_id}` allowed enumeration of every user's stop levels. A support
thread is the same kind of data — it contains what a customer said about their
account, their money and their losses.

So:

* **The router is gated at router level**, not per route, because a route added
  later without a dependency is a route added without authentication.
* **Every customer read checks ownership.** The id is 32 random hex characters,
  which makes enumeration hard and authorisation absent. Guessing being
  difficult is not a permission model.
* **A customer cannot reach an operator endpoint** — not the queue, not a claim,
  not a resolve — and the refusal is 403, not a 404 that leaks whether the
  ticket exists.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A real app router over a real SQLite database, with auth overridden.

    The auth dependency is overridden per test to a chosen identity; everything
    else — routing, the store, triage — is the production code path.
    """
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
    """Override the router's identity dependencies with a chosen caller."""
    from api.auth import TokenPayload

    payload = TokenPayload(sub=user_id, role=role)
    app.dependency_overrides[mod._customer] = lambda: payload
    app.dependency_overrides[mod._operator] = lambda: payload
    return payload


def _as_customer(app, mod, *, user_id: str = "cust-1"):
    from api.auth import TokenPayload

    from fastapi import HTTPException

    payload = TokenPayload(sub=user_id, role="user")
    app.dependency_overrides[mod._customer] = lambda: payload

    def _refuse():
        raise HTTPException(status_code=403, detail="operator role required")

    app.dependency_overrides[mod._operator] = _refuse
    return payload


@pytest.fixture
def ai_available(monkeypatch):
    """A support AI that answers.

    Without this the real `answer_question` runs, finds no reachable gateway in
    the test environment, and the router escalates the ticket — correct
    behaviour, and it silently turns every "the AI handled it" test into a test
    of the escalation path. Two tests below were written without it and asserted
    `needs_human is False` against a ticket that had, correctly, reached a
    person.
    """
    import api.support as mod
    from support.answering import Answer

    monkeypatch.setattr(
        mod,
        "answer_question",
        lambda *a, **k: Answer(available=True, text="Settings → Security.", department="platform_engineering"),
    )


class TestACustomerCannotReadAnotherCustomersTicket:
    def test_a_thread_is_refused_to_a_different_user(self, client):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"})
        assert ticket.status_code == 201, ticket.text
        ticket_id = ticket.json()["id"]

        _as_customer(app, mod, user_id="cust-2")
        stolen = http.get(f"/api/support/tickets/{ticket_id}")

        assert stolen.status_code == 404, "another customer read the thread — an opaque id is not authorisation"

    def test_a_different_user_cannot_post_into_the_thread(self, client):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as_customer(app, mod, user_id="cust-2")
        posted = http.post(f"/api/support/tickets/{ticket_id}/messages", json={"body": "hello"})

        assert posted.status_code == 404

    def test_the_owner_still_reads_their_own(self, client):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        mine = http.get(f"/api/support/tickets/{ticket_id}")

        assert mine.status_code == 200
        assert mine.json()["ticket"]["id"] == ticket_id
        assert len(mine.json()["messages"]) == 1

    def test_my_ticket_list_is_only_mine(self, client):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"})

        _as_customer(app, mod, user_id="cust-2")
        listed = http.get("/api/support/tickets")

        assert listed.status_code == 200
        assert listed.json()["tickets"] == []


class TestACustomerCannotActAsAnOperator:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/support/queue"),
            ("post", "/api/support/queue/abc/claim"),
            ("post", "/api/support/queue/abc/release"),
            ("post", "/api/support/queue/abc/resolve"),
            ("post", "/api/support/queue/abc/reply"),
        ],
    )
    def test_the_operator_surface_is_refused(self, client, method: str, path: str):
        app, mod, http = client
        _as_customer(app, mod)

        response = http.get(path) if method == "get" else getattr(http, method)(path, json={"body": "hi"})

        assert response.status_code == 403, (
            f"{method.upper()} {path} was reachable by a customer ({response.status_code})"
        )

    def test_a_customer_cannot_resolve_their_own_ticket_through_the_api(self, client):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        assert http.post(f"/api/support/queue/{ticket_id}/resolve").status_code == 403


class TestNoRouteIsReachableWithoutAnIdentity:
    """Asserted by calling every route, not by reading the router's structure.

    The first version of this class checked `router.dependencies` — and could
    not: Starlette records each inclusion as an opaque `_IncludedRouter`, so
    `router.routes` holds wrappers with no `dependencies` attribute at all.
    That is the trap `core/router_registry.py` documents at length, and a
    structural assertion would have been reading the wrong object even if it
    had one.

    Calling each route with no identity is the property that matters anyway: a
    route added later without a dependency fails here whatever the wiring looks
    like (S6-01).
    """

    def test_every_route_refuses_an_anonymous_caller(self, client):
        from core.router_registry import iter_api_routes

        app, mod, http = client
        app.dependency_overrides.clear()

        routes = list(iter_api_routes(app.routes))
        assert routes, "no routes were discovered — the sweep would pass vacuously"

        for route in routes:
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                path = route.path.replace("{ticket_id}", "abc")
                response = http.request(method, path, json={"body": "x", "subject": "x"})
                assert response.status_code in (401, 403), (
                    f"{method} {path} answered {response.status_code} to an anonymous caller"
                )


class TestTheOperatorFlow:
    def test_an_escalated_ticket_appears_in_the_queue(self, client):
        app, mod, http = client
        _as_customer(app, mod)
        http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"})

        _as(app, mod, user_id="ops-1", role="admin")
        queue = http.get("/api/support/queue")

        assert queue.status_code == 200
        assert len(queue.json()["tickets"]) == 1
        assert queue.json()["tickets"][0]["needs_human"] is True

    def test_a_second_operator_claiming_gets_a_conflict_naming_the_holder(self, client):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        assert http.post(f"/api/support/queue/{ticket_id}/claim").status_code == 200

        _as(app, mod, user_id="ops-2", role="admin")
        second = http.post(f"/api/support/queue/{ticket_id}/claim")

        assert second.status_code == 409
        assert "ops-1" in second.json()["detail"]

    def test_an_operator_reply_reaches_the_customer_thread(self, client):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        http.post(f"/api/support/queue/{ticket_id}/claim")
        assert http.post(f"/api/support/queue/{ticket_id}/reply", json={"body": "on it"}).status_code == 200

        _as_customer(app, mod, user_id="cust-1")
        thread = http.get(f"/api/support/tickets/{ticket_id}").json()

        assert [m["body"] for m in thread["messages"]][-1] == "on it"
        assert thread["ticket"]["first_response_at"] is not None

    def test_an_operator_can_resolve_what_the_ai_could_not(self, client):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        _as(app, mod, user_id="ops-1", role="admin")
        http.post(f"/api/support/queue/{ticket_id}/claim")

        assert http.post(f"/api/support/queue/{ticket_id}/resolve").status_code == 200
        assert http.get("/api/support/queue").json()["tickets"] == []


class TestOpeningATicketReportsWhatHappened:
    def test_an_escalated_ticket_says_a_person_will_answer(self, client):
        app, mod, http = client
        _as_customer(app, mod)

        body = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()

        assert body["needs_human"] is True
        assert body["escalation_reason"]
        assert body["ai_reply"] is None, "an escalated ticket must not carry a draft reply"

    def test_an_answerable_ticket_carries_the_ai_reply_when_there_is_one(self, client, monkeypatch):
        from support.answering import Answer

        app, mod, http = client
        _as_customer(app, mod)
        monkeypatch.setattr(
            mod,
            "answer_question",
            lambda *a, **k: Answer(available=True, text="Settings → Security.", department="platform_engineering"),
        )

        body = http.post(
            "/api/support/tickets",
            json={"subject": "x", "body": "how do I enable two factor authentication"},
        ).json()

        assert body["ai_reply"] == "Settings → Security."

    def test_an_unavailable_ai_does_not_invent_a_reply(self, client, monkeypatch):
        """The desk stays honest end to end, not only inside `answering`."""
        from support.answering import Answer

        app, mod, http = client
        _as_customer(app, mod)
        monkeypatch.setattr(
            mod,
            "answer_question",
            lambda *a, **k: Answer(
                available=False, needs_human=True, unavailable_reason="The support AI is unavailable."
            ),
        )

        body = http.post(
            "/api/support/tickets",
            json={"subject": "x", "body": "how do I enable two factor authentication"},
        ).json()

        assert body["ai_reply"] is None
        assert body["needs_human"] is True

        _as(app, mod, user_id="ops-1", role="admin")
        assert len(http.get("/api/support/queue").json()["tickets"]) == 1, (
            "a ticket the AI could not answer never reached a person"
        )


class TestInputIsBounded:
    def test_an_empty_body_is_rejected(self, client):
        app, mod, http = client
        _as_customer(app, mod)

        assert http.post("/api/support/tickets", json={"subject": "x", "body": "  "}).status_code == 422

    def test_an_enormous_body_is_rejected(self, client):
        """Unbounded text is a storage and a prompt-cost problem at once."""
        app, mod, http = client
        _as_customer(app, mod)

        response = http.post("/api/support/tickets", json={"subject": "x", "body": "a" * 50_000})
        assert response.status_code == 422


class TestTheRestOfTheOperatorSurface:
    def _escalated(self, http):
        return http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

    def test_an_operator_reads_a_queued_thread(self, client):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = self._escalated(http)

        _as(app, mod, user_id="ops-1", role="admin")
        thread = http.get(f"/api/support/queue/{ticket_id}")

        assert thread.status_code == 200
        assert thread.json()["ticket"]["needs_human"] is True
        assert len(thread.json()["messages"]) == 1

    def test_an_unknown_ticket_is_404_on_the_operator_surface_too(self, client):
        app, mod, http = client
        _as(app, mod, user_id="ops-1", role="admin")

        assert http.get("/api/support/queue/nope").status_code == 404
        assert http.post("/api/support/queue/nope/claim").status_code == 404
        assert http.post("/api/support/queue/nope/release").status_code == 404
        assert http.post("/api/support/queue/nope/reply", json={"body": "x"}).status_code == 404

    def test_releasing_returns_the_ticket_to_the_unassigned_queue(self, client):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = self._escalated(http)

        _as(app, mod, user_id="ops-1", role="admin")
        http.post(f"/api/support/queue/{ticket_id}/claim")
        assert http.get("/api/support/queue?unassigned_only=true").json()["tickets"] == []

        assert http.post(f"/api/support/queue/{ticket_id}/release").status_code == 200
        assert len(http.get("/api/support/queue?unassigned_only=true").json()["tickets"]) == 1

    def test_releasing_someone_elses_ticket_is_a_conflict(self, client):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = self._escalated(http)

        _as(app, mod, user_id="ops-1", role="admin")
        http.post(f"/api/support/queue/{ticket_id}/claim")

        _as(app, mod, user_id="ops-2", role="admin")
        assert http.post(f"/api/support/queue/{ticket_id}/release").status_code == 409


class TestTheCustomerCanContinueTheirOwnThread:
    def test_a_reply_lands_and_reports_the_new_state(self, client, ai_available):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = http.post(
            "/api/support/tickets",
            json={"subject": "x", "body": "how do I enable two factor authentication"},
        ).json()["id"]

        posted = http.post(f"/api/support/tickets/{ticket_id}/messages", json={"body": "thanks"})

        assert posted.status_code == 200
        assert posted.json()["needs_human"] is False

    def test_a_reply_that_hits_the_floor_escalates_the_thread(self, client, ai_available):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = http.post(
            "/api/support/tickets",
            json={"subject": "x", "body": "how do I enable two factor authentication"},
        ).json()["id"]

        posted = http.post(f"/api/support/tickets/{ticket_id}/messages", json={"body": "actually I want a refund"})

        assert posted.json()["needs_human"] is True

        _as(app, mod, user_id="ops-1", role="admin")
        assert len(http.get("/api/support/queue").json()["tickets"]) == 1

    def test_a_blank_reply_is_rejected(self, client):
        app, mod, http = client
        _as_customer(app, mod)
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        assert http.post(f"/api/support/tickets/{ticket_id}/messages", json={"body": "   "}).status_code == 422

    def test_my_ticket_list_shows_my_own(self, client):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"})

        listed = http.get("/api/support/tickets")

        assert len(listed.json()["tickets"]) == 1
        assert listed.json()["tickets"][0]["user_id"] == "cust-1"


class TestTheProductionStoreIsRealWiring:
    def test_the_store_resolves_the_application_session_factory(self):
        """The seam every other test replaces, exercised once against the real
        construction — otherwise nothing proves a route ever reaches a database."""
        from unittest.mock import patch

        import api.support as mod

        with patch("database.connection.SessionLocal") as session_local:
            store = mod._store()

        assert store._session_factory is session_local


class TestTheRefusalPathOnACustomerReply:
    """Another guard today's code cannot open, proven able to fire.

    `_owned` has already established the ticket exists, so `add_message` can
    only refuse for a reason that does not arise on this path — coverage showed
    the 409 never executing. It is kept rather than deleted: without it a future
    refusal from the store (a closed-thread rule, a rate limit) would be
    discarded and the endpoint would report success for a message it did not
    save, which is the "success reported for work that did not happen" shape.
    """

    def test_a_store_refusal_becomes_a_409_rather_than_a_silent_success(self, client):
        from unittest.mock import patch

        from support.tickets import Outcome

        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

        with patch.object(mod.TicketStore, "add_message", return_value=Outcome(False, "thread locked")):
            response = http.post(f"/api/support/tickets/{ticket_id}/messages", json={"body": "hi"})

        assert response.status_code == 409
        assert response.json()["detail"] == "thread locked"


class TestTheCustomerSurfaceDoesNotLeakTheTriageInternals:
    """The same ticket, two audiences, two projections.

    `my_ticket` and `my_tickets` returned `TicketView.as_dict()` — the operator's
    projection — to the customer who raised the ticket. Three fields do not
    belong there:

    * **`matched_on`** is the exact phrase that tripped the floor ("withdraw",
      "is … going up"). Handing it back is a classifier oracle: probe a few
      phrasings, learn which words reach a person and which reach the AI, then
      phrase around the floor. The floor is the platform's regulatory guard, so
      that is not a curiosity.
    * **`escalation_reason`** is internal wording written for an operator —
      *"This platform is not licensed to give financial advice"* reads as a
      lecture to the person who asked, and explains the classifier's reasoning
      to someone who has no need for it.
    * **`assigned_operator_id`** names the staff member handling them.

    The customer is still told everything they need: that a person is involved,
    and what state their ticket is in. What is removed is *why the machine
    decided that*, which is the operator's business.
    """

    def _open(self, http):
        return http.post("/api/support/tickets", json={"subject": "x", "body": "I want a refund"}).json()["id"]

    @pytest.mark.parametrize("field", ["matched_on", "escalation_reason", "assigned_operator_id"])
    def test_the_thread_read_omits_it(self, client, field: str):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = self._open(http)

        ticket = http.get(f"/api/support/tickets/{ticket_id}").json()["ticket"]

        assert field not in ticket, f"the customer surface returned {field!r}"

    @pytest.mark.parametrize("field", ["matched_on", "escalation_reason", "assigned_operator_id"])
    def test_the_list_read_omits_it(self, client, field: str):
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        self._open(http)

        rows = http.get("/api/support/tickets").json()["tickets"]

        assert rows and field not in rows[0], f"the customer list returned {field!r}"

    def test_the_matched_phrase_is_nowhere_in_the_payload(self, client):
        """Asserted against the whole response, not a key list.

        A field removed from `as_customer_dict` but echoed somewhere else — a
        message body, a status string — is the same leak with a different name.
        """
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = self._open(http)

        body = http.get(f"/api/support/tickets/{ticket_id}").text

        assert "escalated on match" not in body.lower()
        assert "not licensed" not in body.lower()

    def test_the_customer_still_learns_a_person_is_involved(self, client):
        """Removing the reasoning must not remove the fact."""
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = self._open(http)

        ticket = http.get(f"/api/support/tickets/{ticket_id}").json()["ticket"]

        assert ticket["needs_human"] is True
        assert ticket["status"] == "awaiting_operator"
        assert ticket["subject"] and ticket["id"] == ticket_id

    def test_the_operator_surface_still_carries_all_of_it(self, client):
        """The operator needs exactly what the customer must not have."""
        app, mod, http = client
        _as_customer(app, mod, user_id="cust-1")
        ticket_id = self._open(http)

        _as(app, mod, user_id="ops-1", role="admin")
        ticket = http.get(f"/api/support/queue/{ticket_id}").json()["ticket"]

        assert ticket["matched_on"]
        assert ticket["escalation_reason"]
        assert "assigned_operator_id" in ticket
