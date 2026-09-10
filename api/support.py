# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The support desk, over HTTP. An opaque ticket id is not authorisation.

`support/` decides who answers (`triage`), records the conversation and refuses
what the AI must not do to it (`tickets`), and drafts a reply or says it cannot
(`answering`). None of it was reachable: no customer could open a ticket and no
operator could see one. This is that surface.

## Who may read what

The finding this module is written against is S6-02's shape.
`api/advanced_orders.py` declared a router with no dependencies and three routes
with no ownership check, so `GET /{order_id}` enumerated every user's stop
levels. A support thread is the same class of data — it holds what a customer
said about their account, their money and their losses.

So the ownership rule here is explicit and tested: **every customer read and
write checks that the ticket belongs to the caller.** The id is 32 random hex
characters, which makes guessing hard and authorises nothing. A hard-to-guess
identifier is not a permission model.

A ticket that exists but belongs to someone else answers **404, not 403**: a 403
confirms the id is real, which is a free oracle for anyone enumerating.

## Two surfaces, two roles

`/api/support/tickets/*` is the customer's own thread. `/api/support/queue/*` is
the operator's, and requires `admin`. They are separate routers with separate
dependencies rather than one router with per-route checks, because a route added
later inherits the gate instead of needing to remember it (S6-01).

## What the customer surface cannot do

Resolve, claim, release, or read anyone else's anything. `TicketStore` refuses an
AI resolution of an escalated ticket and this router never offers the customer
one at all — two independent refusals, so neither is the only thing standing
there.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role
from support.answering import answer_question
from support.tickets import Actor, TicketStore

logger = logging.getLogger(__name__)

#: The operator queue starts at admin. A trader has no reason to read another
#: customer's support thread, and support is not a trading permission.
_OPERATOR_ROLE = "admin"

#: The customer surface. Every authenticated tier may raise a ticket — a
#: starter-tier customer with a billing problem is exactly who needs one.
_CUSTOMER_ROLE = "starter"

#: Bounded on the way in. Unbounded text is a storage problem and a prompt-cost
#: problem at once, and the second one is billed.
_MAX_BODY = 8_000
_MAX_SUBJECT = 200


def _customer(user: TokenPayload = Depends(require_role(_CUSTOMER_ROLE))) -> TokenPayload:
    return user


def _operator(user: TokenPayload = Depends(require_role(_OPERATOR_ROLE))) -> TokenPayload:
    return user


router = APIRouter(prefix="/api/support", tags=["Support"])

#: Router-level dependencies, not per-route. A route added to either of these
#: later carries the gate without anyone remembering to add it.
_customer_routes = APIRouter(prefix="/tickets", dependencies=[Depends(_customer)])
_operator_routes = APIRouter(prefix="/queue", dependencies=[Depends(_operator)])


def _store() -> TicketStore:
    """The production session factory, resolved per call.

    A module-level store would bind a session factory at import time, before
    `database.connection` has configured one.
    """
    from database.connection import SessionLocal

    return TicketStore(SessionLocal)


class OpenTicket(BaseModel):
    subject: str = Field(min_length=1, max_length=_MAX_SUBJECT)
    body: str = Field(min_length=1, max_length=_MAX_BODY)


class PostMessage(BaseModel):
    body: str = Field(min_length=1, max_length=_MAX_BODY)


def _reject_blank(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        # Pydantic's min_length counts whitespace, so "   " passes it.
        raise HTTPException(status_code=422, detail="Message body cannot be empty.")
    return stripped


def _owned(store: TicketStore, ticket_id: str, user: TokenPayload) -> Any:
    """The ticket, if it belongs to this caller. 404 otherwise.

    404 rather than 403 on purpose: a 403 confirms the id exists, which hands an
    enumerator a free oracle. The caller who owns nothing learns nothing.
    """
    ticket = store.get(ticket_id)
    if ticket is None or ticket.user_id != user.sub:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return ticket


# ── Customer surface ────────────────────────────────────────────────────────


@_customer_routes.post("", status_code=201, summary="Open a support ticket")
def open_ticket(payload: OpenTicket, user: TokenPayload = Depends(_customer)) -> dict[str, Any]:
    """Raise a ticket, and answer it now if the AI is allowed and able to."""
    body = _reject_blank(payload.body)
    store = _store()
    ticket = store.open_ticket(user_id=user.sub, subject=payload.subject.strip(), body=body)

    ai_reply: str | None = None
    if not ticket.needs_human:
        answer = answer_question(body)
        if answer.available and answer.text:
            store.add_message(ticket.id, author_kind="ai", author_id=answer.department, body=answer.text)
            ai_reply = answer.text
        else:
            # The AI could not answer. That is a ticket for a person, not a
            # ticket that quietly sits unanswered — the whole point of
            # `answering`'s refusal is that something else picks it up.
            store.escalate(
                ticket.id,
                reason=answer.unavailable_reason or "The support AI could not answer this.",
            )

    fresh = store.get(ticket.id) or ticket
    return {
        "id": fresh.id,
        "status": fresh.status,
        "needs_human": fresh.needs_human,
        "department": fresh.department,
        "escalation_reason": fresh.escalation_reason,
        "ai_reply": ai_reply,
    }


@_customer_routes.get("", summary="My support tickets")
def my_tickets(user: TokenPayload = Depends(_customer)) -> dict[str, Any]:
    return {"tickets": [t.as_dict() for t in _store().tickets_for(user.sub)]}


@_customer_routes.get("/{ticket_id}", summary="One of my tickets, with its thread")
def my_ticket(ticket_id: str, user: TokenPayload = Depends(_customer)) -> dict[str, Any]:
    store = _store()
    ticket = _owned(store, ticket_id, user)
    return {
        "ticket": ticket.as_dict(),
        "messages": [m.as_dict() for m in store.messages(ticket_id)],
    }


@_customer_routes.post("/{ticket_id}/messages", summary="Reply on my own ticket")
def post_message(ticket_id: str, payload: PostMessage, user: TokenPayload = Depends(_customer)) -> dict[str, Any]:
    body = _reject_blank(payload.body)
    store = _store()
    _owned(store, ticket_id, user)

    outcome = store.add_message(ticket_id, author_kind="customer", author_id=user.sub, body=body)
    if not outcome.allowed:
        raise HTTPException(status_code=409, detail=outcome.reason or "Message refused.")

    fresh = store.get(ticket_id)
    return {"status": fresh.status if fresh else None, "needs_human": bool(fresh and fresh.needs_human)}


# ── Operator surface ────────────────────────────────────────────────────────


@_operator_routes.get("", summary="Tickets waiting on a person")
def queue(unassigned_only: bool = False, _: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    tickets = _store().operator_queue(unassigned_only=unassigned_only)
    return {"tickets": [t.as_dict() for t in tickets], "count": len(tickets)}


@_operator_routes.get("/{ticket_id}", summary="One queued ticket, with its thread")
def queued_ticket(ticket_id: str, _: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    store = _store()
    ticket = store.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return {
        "ticket": ticket.as_dict(),
        "messages": [m.as_dict() for m in store.messages(ticket_id)],
    }


def _apply(outcome: Any, ticket_id: str) -> dict[str, Any]:
    """Turn a store refusal into the status code it deserves.

    409 for a conflict with another operator, 404 for a ticket that is not
    there. The reason travels with it — "someone else has it" is not something
    the second operator can act on.
    """
    if outcome.allowed:
        return {"ok": True, "ticket_id": ticket_id}
    reason = outcome.reason or "Refused."
    raise HTTPException(status_code=404 if "not found" in reason.lower() else 409, detail=reason)


@_operator_routes.post("/{ticket_id}/claim", summary="Take a ticket")
def claim(ticket_id: str, user: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    return _apply(_store().claim(ticket_id, operator_id=user.sub), ticket_id)


@_operator_routes.post("/{ticket_id}/release", summary="Put a ticket back")
def release(ticket_id: str, user: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    return _apply(_store().release(ticket_id, operator_id=user.sub), ticket_id)


@_operator_routes.post("/{ticket_id}/reply", summary="Reply to the customer")
def reply(ticket_id: str, payload: PostMessage, user: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    body = _reject_blank(payload.body)
    return _apply(
        _store().add_message(ticket_id, author_kind="operator", author_id=user.sub, body=body),
        ticket_id,
    )


@_operator_routes.post("/{ticket_id}/resolve", summary="Close a ticket")
def resolve(ticket_id: str, user: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    return _apply(
        _store().resolve(ticket_id, actor=Actor.OPERATOR, actor_id=user.sub),
        ticket_id,
    )


router.include_router(_customer_routes)
router.include_router(_operator_routes)
