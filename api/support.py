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
from starlette.concurrency import run_in_threadpool

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


#: The live channel the operator console watches. Privileged AND private in
#: `LiveConnectionManager`: a customer cannot subscribe to it, and it is never
#: delivered through the implicit "empty subscription = all channels" firehose.
QUEUE_CHANNEL = "support_queue"


def _queue_event(event: str, ticket: Any) -> dict[str, Any]:
    """What an operator needs to render a queue row — and nothing else.

    No message bodies. An operator opens the thread to read it; a broadcast
    that ships every customer message puts the whole conversation into every
    connected console's memory, and into any log that records frames.
    """
    return {
        "event": event,
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "needs_human": ticket.needs_human,
        "department": ticket.department,
        "category": ticket.category,
        "assigned_operator_id": ticket.assigned_operator_id,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "first_response_at": (ticket.first_response_at.isoformat() if ticket.first_response_at else None),
    }


async def _publish_queue_event(event: dict[str, Any]) -> None:
    """Push one queue change to the operator channel."""
    from api.ws_live import get_live_manager

    await get_live_manager().broadcast(QUEUE_CHANNEL, {"type": QUEUE_CHANNEL, "data": event})


async def _announce(event: str, ticket: Any) -> None:
    """Publish, and never let the socket decide whether the work happened.

    The ticket transition is the work; this is a notification about it. If the
    socket is down the claim still happened, the reply is still saved, and the
    customer is still answered.

    Logged at ERROR, not DEBUG: an operator console that has silently stopped
    updating looks exactly like a quiet queue. That is F248's shape — three
    alert call sites raised `TypeError` into a DEBUG handler, so a tripped
    circuit breaker notified nobody for as long as the code existed.

    Called only AFTER the store commits, from what the store returned.
    Publishing first would announce a claim that then failed.
    """
    if ticket is None:
        return
    try:
        await _publish_queue_event(_queue_event(event, ticket))
    except Exception as exc:
        logger.error("support: queue broadcast failed for %s (%s): %s", ticket.id, event, exc)


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
async def open_ticket(payload: OpenTicket, user: TokenPayload = Depends(_customer)) -> dict[str, Any]:
    """Raise a ticket, and answer it now if the AI is allowed and able to.

    Async so the queue broadcast can be awaited after the store commits. The
    store and the model call both block, so they go to the threadpool rather
    than holding the event loop for the length of an inference.
    """
    body = _reject_blank(payload.body)
    store = _store()
    ticket = await run_in_threadpool(store.open_ticket, user_id=user.sub, subject=payload.subject.strip(), body=body)

    ai_reply: str | None = None
    if not ticket.needs_human:
        answer = await run_in_threadpool(answer_question, body)
        if answer.available and answer.text:
            await run_in_threadpool(
                store.add_message,
                ticket.id,
                author_kind="ai",
                author_id=answer.department,
                body=answer.text,
            )
            ai_reply = answer.text
        else:
            # The AI could not answer. That is a ticket for a person, not a
            # ticket that quietly sits unanswered — the whole point of
            # `answering`'s refusal is that something else picks it up.
            await run_in_threadpool(
                store.escalate,
                ticket.id,
                reason=answer.unavailable_reason or "The support AI could not answer this.",
            )

    fresh = await run_in_threadpool(store.get, ticket.id) or ticket
    if fresh.needs_human:
        # Published from the COMMITTED state, not from the intent, and only for
        # the queue's own changes — a ticket the AI answered is not a queue item.
        await _announce("escalated", fresh)
    return {
        "id": fresh.id,
        "status": fresh.status,
        "needs_human": fresh.needs_human,
        "department": fresh.department,
        "escalation_reason": fresh.escalation_reason,
        "ai_reply": ai_reply,
    }


@_customer_routes.get("", summary="My support tickets")
async def my_tickets(user: TokenPayload = Depends(_customer)) -> dict[str, Any]:
    tickets = await run_in_threadpool(_store().tickets_for, user.sub)
    # Customer projection — see `TicketView.as_customer_dict`.
    return {"tickets": [t.as_customer_dict() for t in tickets]}


@_customer_routes.get("/{ticket_id}", summary="One of my tickets, with its thread")
def my_ticket(ticket_id: str, user: TokenPayload = Depends(_customer)) -> dict[str, Any]:
    store = _store()
    ticket = _owned(store, ticket_id, user)
    return {
        # Customer projection: the triage internals do not cross this line.
        "ticket": ticket.as_customer_dict(),
        "messages": [m.as_dict() for m in store.messages(ticket_id)],
    }


@_customer_routes.post("/{ticket_id}/messages", summary="Reply on my own ticket")
async def post_message(ticket_id: str, payload: PostMessage, user: TokenPayload = Depends(_customer)) -> dict[str, Any]:
    body = _reject_blank(payload.body)
    store = _store()
    _owned(store, ticket_id, user)

    outcome = await run_in_threadpool(
        store.add_message, ticket_id, author_kind="customer", author_id=user.sub, body=body
    )
    if not outcome.allowed:
        raise HTTPException(status_code=409, detail=outcome.reason or "Message refused.")

    fresh = await run_in_threadpool(store.get, ticket_id)
    if fresh and fresh.needs_human:
        # An operator watching the row must see that the customer answered —
        # and that a mid-thread message just escalated it.
        await _announce("customer_replied", fresh)
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


async def _transition(ticket_id: str, event: str, work) -> dict[str, Any]:
    """Run one operator action, then announce what the store committed.

    The order is the point. `_apply` raises on a refusal, so a claim that lost
    a race never reaches `_announce` — announcing first would put a row on
    every console showing an operator who does not hold the ticket.
    """
    store = _store()
    result = _apply(await run_in_threadpool(work, store), ticket_id)
    await _announce(event, await run_in_threadpool(store.get, ticket_id))
    return result


@_operator_routes.post("/{ticket_id}/claim", summary="Take a ticket")
async def claim(ticket_id: str, user: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    return await _transition(ticket_id, "claimed", lambda store: store.claim(ticket_id, operator_id=user.sub))


@_operator_routes.post("/{ticket_id}/release", summary="Put a ticket back")
async def release(ticket_id: str, user: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    return await _transition(ticket_id, "released", lambda store: store.release(ticket_id, operator_id=user.sub))


@_operator_routes.post("/{ticket_id}/reply", summary="Reply to the customer")
async def reply(ticket_id: str, payload: PostMessage, user: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    body = _reject_blank(payload.body)
    return await _transition(
        ticket_id,
        "operator_replied",
        lambda store: store.add_message(ticket_id, author_kind="operator", author_id=user.sub, body=body),
    )


@_operator_routes.post("/{ticket_id}/resolve", summary="Close a ticket")
async def resolve(ticket_id: str, user: TokenPayload = Depends(_operator)) -> dict[str, Any]:
    return await _transition(
        ticket_id,
        "resolved",
        lambda store: store.resolve(ticket_id, actor=Actor.OPERATOR, actor_id=user.sub),
    )


router.include_router(_customer_routes)
router.include_router(_operator_routes)
