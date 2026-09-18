# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The support desk as one system, not nine well-tested parts.

Every seam has its own suite. Nothing drove a customer question through the
whole chain — triage → facts → gateway → ticket → broadcast → operator queue →
reply → resolve → back to the customer — in a single run, so a break *between*
two green modules had nowhere to show up.

## What is real here, and what is not

Real: `support.triage`, `support.facts` and the department handlers it calls,
`support.tickets` on a real SQLite file, `api/support.py`'s routers, and
FastAPI's own dispatch and dependency resolution.

Stood in for, and only these two:

* **the gateway** — the one network boundary, so the suite needs no model and
  no credential;
* **the queue broadcast** — wrapped, not replaced, so the real coroutine still
  runs and the frames are captured.

Marked `integration` rather than `e2e` on purpose. CI runs `-m "not slow and
not e2e"`, so an `e2e` mark would make this a test that never runs — which is
the defect class it exists to catch, applied to itself.

## Liveness before outcome

`hopefx-dead-controls` records F255: a code-analyzer test wrote its sample into
`tmp_path`, the analyzer skipped any path containing `/test`, and every "this
must still be flagged" case passed against a scanner that never executed.

> **A harness that never ran agrees with every assertion.**

An end-to-end test is where that bites hardest: if the chain short-circuits, the
assertions that matter here — no fabricated answer, no leaked internals, nothing
in the queue — all pass by doing nothing. So `TestTheHarnessIsLive` proves each
stage actually executed *before* anything asserts on what it produced, and every
journey below asserts a positive observation (a row, a call, a frame) alongside
each absence.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.integration]


class _Reply:
    """What the gateway returns. Shaped like `ModelResponse`, not a MagicMock:
    a bare mock agrees with every attribute access, including ones the real
    object does not have."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.provider = "test-provider"
        self.model = "test-model"
        self.latency_ms = 4.0


@pytest.fixture
def desk(tmp_path):
    """The whole desk, wired to a real database, with two seams observed."""
    import sqlalchemy as sa
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    import api.support as support_api
    from support import answering
    from api.auth import TokenPayload
    from database.models import SupportMessage, SupportTicket
    from support.tickets import TicketStore

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'desk.db'}")
    SupportTicket.__table__.create(engine)
    SupportMessage.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    store = TicketStore(factory)

    frames: list[dict[str, Any]] = []
    prompts: list[str] = []

    real_publish = support_api._publish_queue_event

    async def capture(event):
        frames.append(event)
        return await real_publish(event)

    def gateway(*, prompt: str, operator: str, timeout_s: float):
        prompts.append(prompt)
        return _Reply("Two-factor authentication lives in Settings, then Security.")

    app = FastAPI()
    app.include_router(support_api.router)
    http = TestClient(app)

    with (
        patch.object(support_api, "_store", lambda: store),
        patch.object(support_api, "_publish_queue_event", side_effect=capture),
        patch.object(answering, "_call_gateway", side_effect=gateway) as gw,
        patch.object(answering, "_gather", wraps=answering._gather) as gather,
    ):
        yield {
            "app": app,
            "http": http,
            "store": store,
            "mod": support_api,
            "frames": frames,
            "prompts": prompts,
            "gateway": gw,
            "gather": gather,
            "engine": engine,
            "TokenPayload": TokenPayload,
        }
    engine.dispose()


def as_customer(desk, user_id: str = "cust-1"):
    from fastapi import HTTPException

    payload = desk["TokenPayload"](sub=user_id, role="user")
    desk["app"].dependency_overrides[desk["mod"]._customer] = lambda: payload

    def refuse():
        raise HTTPException(status_code=403, detail="operator role required")

    desk["app"].dependency_overrides[desk["mod"]._operator] = refuse


def as_operator(desk, user_id: str = "ops-1"):
    payload = desk["TokenPayload"](sub=user_id, role="admin")
    desk["app"].dependency_overrides[desk["mod"]._customer] = lambda: payload
    desk["app"].dependency_overrides[desk["mod"]._operator] = lambda: payload


def open_ticket(desk, subject: str, body: str) -> dict[str, Any]:
    r = desk["http"].post("/api/support/tickets", json={"subject": subject, "body": body})
    assert r.status_code == 201, r.text
    return r.json()


# ── liveness ─────────────────────────────────────────────────────────────────


class TestTheHarnessIsLive:
    """Proven before anything asserts an absence. F255's lesson, applied here."""

    def test_the_support_routes_are_mounted(self, desk):
        from core.router_registry import iter_api_routes

        paths = {r.path for r in iter_api_routes(desk["app"].routes)}
        assert "/api/support/tickets" in paths
        assert "/api/support/queue" in paths

    def test_a_ticket_reaches_the_real_database(self, desk):
        from database.models import SupportTicket

        as_customer(desk)
        opened = open_ticket(desk, "2fa", "how do I enable two factor authentication")

        with desk["engine"].connect() as c:
            rows = c.execute(SupportTicket.__table__.select()).fetchall()
        assert len(rows) == 1, "the HTTP call returned 201 but no row was written"
        assert opened["id"]

    def test_the_gateway_seam_is_actually_reached(self, desk):
        """Otherwise 'the AI never fabricates' passes by never running."""
        as_customer(desk)
        open_ticket(desk, "2fa", "how do I enable two factor authentication")

        assert desk["gateway"].call_count == 1
        assert desk["prompts"], "no prompt was composed"

    def test_the_fact_gatherer_is_actually_reached(self, desk):
        as_customer(desk)
        open_ticket(desk, "order", "why was my order rejected by the broker")

        assert desk["gather"].call_count == 1

    def test_the_broadcast_seam_is_actually_reached(self, desk):
        as_customer(desk)
        open_ticket(desk, "refund", "I want a refund")

        assert desk["frames"], "an escalation was stored but nothing was broadcast"


# ── journey one: the AI answers, and the queue stays empty ───────────────────


class TestAQuestionTheAICanAnswer:
    def test_the_real_department_fact_reaches_the_real_prompt(self, desk):
        """The chain's whole point, in one assertion.

        `markets_execution.query_broker_status` is a real handler. Its answer
        travels through `support.facts`, into `_build_prompt`, and out to the
        gateway — and it reports `available: false` rather than inventing a
        broker state, so the model is told the gap exists.
        """
        as_customer(desk)
        open_ticket(desk, "order", "why was my order rejected by the broker")

        prompt = desk["prompts"][0]
        assert "query_broker_status" in prompt
        assert "Markets & Execution" in prompt, "the department brief did not reach the prompt"
        assert "State no figure" in prompt, "the no-invented-figures rule did not reach the prompt"

    def test_the_answer_is_stored_and_attributed_to_the_department(self, desk):
        as_customer(desk)
        opened = open_ticket(desk, "2fa", "how do I enable two factor authentication")

        thread = desk["http"].get(f"/api/support/tickets/{opened['id']}").json()
        ai = [m for m in thread["messages"] if m["author_kind"] == "ai"]
        assert len(ai) == 1
        assert ai[0]["author_id"] == "platform_engineering"
        assert "Settings" in ai[0]["body"]

    def test_it_does_not_reach_the_operator_queue(self, desk):
        as_customer(desk)
        open_ticket(desk, "2fa", "how do I enable two factor authentication")

        as_operator(desk)
        assert desk["http"].get("/api/support/queue").json()["tickets"] == []

    def test_and_nothing_was_broadcast_for_it(self, desk):
        """The queue channel carries the queue, not every ticket."""
        as_customer(desk)
        open_ticket(desk, "2fa", "how do I enable two factor authentication")

        assert desk["frames"] == []


# ── journey two: the floor escalates, and a person finishes it ───────────────


class TestAQuestionTheFloorTakesAway:
    def test_no_model_is_called_and_no_facts_are_gathered(self, desk):
        """Measured, not assumed: the floor returns before either seam."""
        as_customer(desk)
        opened = open_ticket(desk, "withdrawal", "withdraw my balance to my bank account")

        assert opened["needs_human"] is True
        assert desk["gateway"].call_count == 0
        assert desk["gather"].call_count == 0
        assert opened["ai_reply"] is None

    def test_it_is_announced_on_the_queue_channel(self, desk):
        as_customer(desk)
        open_ticket(desk, "withdrawal", "withdraw my balance to my bank account")

        assert [f["event"] for f in desk["frames"]] == ["escalated"]
        assert desk["frames"][0]["needs_human"] is True

    def test_the_operator_sees_it_with_the_reason(self, desk):
        as_customer(desk)
        open_ticket(desk, "withdrawal", "withdraw my balance to my bank account")

        as_operator(desk)
        queued = desk["http"].get("/api/support/queue").json()["tickets"]
        assert len(queued) == 1
        assert "moves money" in queued[0]["escalation_reason"]
        assert queued[0]["matched_on"] == "withdraw"

    def test_the_customer_never_sees_the_triage_internals(self, desk):
        as_customer(desk)
        opened = open_ticket(desk, "withdrawal", "withdraw my balance to my bank account")

        raw = desk["http"].get(f"/api/support/tickets/{opened['id']}").text
        assert "matched_on" not in raw
        assert "escalation_reason" not in raw
        # And still learns the fact, which is the half that must survive.
        assert desk["http"].get(f"/api/support/tickets/{opened['id']}").json()["ticket"]["needs_human"] is True

    def test_the_full_handoff_completes_and_the_customer_sees_it(self, desk):
        """Claim → reply → resolve, then read it back as the customer."""
        as_customer(desk)
        opened = open_ticket(desk, "withdrawal", "withdraw my balance to my bank account")
        tid = opened["id"]

        as_operator(desk, "ops-1")
        assert desk["http"].post(f"/api/support/queue/{tid}/claim").status_code == 200
        assert (
            desk["http"]
            .post(f"/api/support/queue/{tid}/reply", json={"body": "Checking with payments now."})
            .status_code
            == 200
        )
        assert desk["http"].post(f"/api/support/queue/{tid}/resolve").status_code == 200
        assert desk["http"].get("/api/support/queue").json()["tickets"] == []

        assert [f["event"] for f in desk["frames"]] == [
            "escalated",
            "claimed",
            "operator_replied",
            "resolved",
        ]

        as_customer(desk)
        thread = desk["http"].get(f"/api/support/tickets/{tid}").json()
        assert thread["ticket"]["status"] == "resolved"
        operator_msgs = [m for m in thread["messages"] if m["author_kind"] == "operator"]
        assert len(operator_msgs) == 1
        assert operator_msgs[0]["body"] == "Checking with payments now."

    def test_a_customer_reply_reopens_it_and_puts_it_back(self, desk):
        as_customer(desk)
        tid = open_ticket(desk, "withdrawal", "withdraw my balance to my bank account")["id"]
        as_operator(desk)
        desk["http"].post(f"/api/support/queue/{tid}/claim")
        desk["http"].post(f"/api/support/queue/{tid}/resolve")

        as_customer(desk)
        assert (
            desk["http"].post(f"/api/support/tickets/{tid}/messages", json={"body": "still not sorted"}).status_code
            == 200
        )

        as_operator(desk)
        assert len(desk["http"].get("/api/support/queue").json()["tickets"]) == 1


# ── journey three: the AI cannot answer, so a person must ────────────────────


class TestWhenTheModelIsUnreachable:
    def test_the_ticket_reaches_a_person_rather_than_sitting_unanswered(self, desk):
        """`answering` refuses to invent a reply. This proves the refusal is
        picked up by something rather than leaving a silent ticket."""
        from support import answering

        as_customer(desk)
        with patch.object(answering, "_call_gateway", side_effect=RuntimeError("no provider")):
            opened = open_ticket(desk, "2fa", "how do I enable two factor authentication")

        assert opened["ai_reply"] is None
        assert opened["needs_human"] is True

        as_operator(desk)
        queued = desk["http"].get("/api/support/queue").json()["tickets"]
        assert len(queued) == 1
        assert "unavailable" in queued[0]["escalation_reason"].lower()

    def test_an_empty_completion_is_treated_the_same_way(self, desk):
        """A blank reply is a failure that looks like a success."""
        from support import answering

        as_customer(desk)
        with patch.object(answering, "_call_gateway", return_value=_Reply("   ")):
            opened = open_ticket(desk, "2fa", "how do I enable two factor authentication")

        assert opened["ai_reply"] is None
        assert opened["needs_human"] is True


# ── the property that spans every journey ────────────────────────────────────


class TestTheAICannotCloseWhatTheFloorEscalated:
    def test_end_to_end(self, desk):
        """Held at the store, and never offered by the API — two refusals.

        The floor is worth nothing if the thing it escalated to can be closed
        by the same AI a moment later.
        """
        from support.tickets import Actor

        as_customer(desk)
        tid = open_ticket(desk, "withdrawal", "withdraw my balance to my bank account")["id"]

        outcome = desk["store"].resolve(tid, actor=Actor.AI)
        assert outcome.allowed is False
        assert desk["store"].get(tid).status != "resolved"

        # And the customer surface offers no route that could ask for it.
        assert desk["http"].post(f"/api/support/queue/{tid}/resolve").status_code == 403
