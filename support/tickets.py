# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The ticket the AI cannot close, and the queue two operators cannot both claim.

`support.triage` decides who should answer a question and whether a human must.
It decides and forgets. This module is the part that carries the decision
forward — and the part that stops the AI undoing it.

## Two refusals, and why they are refusals

**An escalated ticket cannot be resolved by the AI.** The floor in triage is
worth nothing if the thing it escalated to can be marked resolved a moment later
by the same AI it escalated away from. `resolve(actor=Actor.AI)` on a ticket
whose `needs_human` is set returns `Outcome(allowed=False, reason=...)`. The
caller reads whether it was allowed, in the shape `invariants/enforcement.py`
uses — a transition that logs and proceeds is the F176 shape, a control that
exists and never stops anything.

**Two operators cannot claim the same ticket.** A claim that silently overwrites
means two people work one customer while another queue item waits, and the
second operator has no way to find out. The second claim is refused and names
the holder, because "someone else has it" without saying who is not actionable
at 3am.

## `needs_human` is sticky, and re-checked on every customer message

The floor is not only evaluated when a ticket opens. A conversation that starts
as *"how do I enable 2FA"* and becomes *"actually I want a refund"* moves out of
the AI's reach on that second message. And once set, it never clears: a customer
who mentions a withdrawal and then changes the subject has not made the ticket
safe for an AI to close.

## Rule 2 for the clock

`first_response_at` stays `None` until an AI or an operator actually replies. A
customer chasing their own ticket is not a response, which is why the store
checks the author kind rather than merely that a row was added. A column
defaulted to the creation time would report a desk answering every ticket
instantly — an unmeasured value presented as a best case.

This module does not send anything, and it holds no broker or payment path. It
records what happened and refuses what must not.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from support.triage import check_floor, triage

logger = logging.getLogger(__name__)

__all__ = [
    "Actor",
    "MessageView",
    "Outcome",
    "STATUS_AWAITING_OPERATOR",
    "STATUS_OPEN",
    "STATUS_RESOLVED",
    "STATUS_WITH_OPERATOR",
    "TicketStore",
    "TicketView",
]

STATUS_OPEN = "open"
STATUS_AWAITING_OPERATOR = "awaiting_operator"
STATUS_WITH_OPERATOR = "with_operator"
STATUS_RESOLVED = "resolved"

#: Author kinds whose message counts as a *response* to the customer.
_RESPONDERS = frozenset({"ai", "operator"})


class Actor(str, Enum):
    """Who is asking for a transition. The AI is deliberately not a person."""

    AI = "ai"
    OPERATOR = "operator"
    CUSTOMER = "customer"
    SYSTEM = "system"


@dataclass(frozen=True)
class Outcome:
    """Whether a transition happened, and why not when it did not.

    Same shape as `invariants.enforcement.EnforcementResult`: the caller reads
    `allowed`. There is no variant that means "refused but applied anyway".
    """

    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class TicketView:
    """A detached snapshot — safe to return after the session closes."""

    id: str
    user_id: str
    subject: str
    status: str
    category: str | None
    department: str | None
    needs_human: bool
    escalation_reason: str | None
    matched_on: str | None
    assigned_operator_id: str | None
    created_at: datetime | None
    updated_at: datetime | None
    first_response_at: datetime | None
    resolved_at: datetime | None

    def as_dict(self) -> dict[str, Any]:
        def _iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "id": self.id,
            "user_id": self.user_id,
            "subject": self.subject,
            "status": self.status,
            "category": self.category,
            "department": self.department,
            "needs_human": self.needs_human,
            "escalation_reason": self.escalation_reason,
            "matched_on": self.matched_on,
            "assigned_operator_id": self.assigned_operator_id,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "first_response_at": _iso(self.first_response_at),
            "resolved_at": _iso(self.resolved_at),
        }


@dataclass(frozen=True)
class MessageView:
    author_kind: str
    author_id: str | None
    body: str
    created_at: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "author_kind": self.author_kind,
            "author_id": self.author_id,
            "body": self.body,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _view(row: Any) -> TicketView:
    return TicketView(
        id=row.ticket_id,
        user_id=row.user_id,
        subject=row.subject,
        status=row.status,
        category=row.category,
        department=row.department,
        needs_human=bool(row.needs_human),
        escalation_reason=row.escalation_reason,
        matched_on=row.matched_on,
        assigned_operator_id=row.assigned_operator_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        first_response_at=row.first_response_at,
        resolved_at=row.resolved_at,
    )


class TicketStore:
    """Persistence and the state machine, over an injected session factory."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    # ── reads ───────────────────────────────────────────────────────────────

    def get(self, ticket_id: str) -> TicketView | None:
        from database.models import SupportTicket

        with self._session_factory() as session:
            row = session.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).one_or_none()
            return _view(row) if row is not None else None

    def messages(self, ticket_id: str, *, limit: int = 500) -> list[MessageView]:
        from database.models import SupportMessage

        with self._session_factory() as session:
            rows = (
                session.query(SupportMessage)
                .filter(SupportMessage.ticket_id == ticket_id)
                .order_by(SupportMessage.created_at.asc(), SupportMessage.id.asc())
                .limit(max(0, limit))
                .all()
            )
            return [
                MessageView(
                    author_kind=r.author_kind,
                    author_id=r.author_id,
                    body=r.body,
                    created_at=r.created_at,
                )
                for r in rows
            ]

    def tickets_for(self, user_id: str, *, limit: int = 100) -> list[TicketView]:
        """One customer's own tickets, newest first.

        Filtered in the query rather than after the fetch: a read that pulls
        every ticket and then discards other people's is one forgotten filter
        away from returning them.
        """
        from database.models import SupportTicket

        with self._session_factory() as session:
            rows = (
                session.query(SupportTicket)
                .filter(SupportTicket.user_id == user_id)
                .order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc())
                .limit(max(0, limit))
                .all()
            )
            return [_view(r) for r in rows]

    def operator_queue(self, *, unassigned_only: bool = False, limit: int = 200) -> list[TicketView]:
        """Tickets waiting on a person, oldest first.

        Oldest first on purpose: a queue ordered newest-first starves whoever
        has been waiting longest, which is the customer most likely to escalate
        somewhere the platform cannot answer.
        """
        from database.models import SupportTicket

        with self._session_factory() as session:
            query = session.query(SupportTicket).filter(
                SupportTicket.needs_human.is_(True),
                SupportTicket.status != STATUS_RESOLVED,
            )
            if unassigned_only:
                query = query.filter(SupportTicket.assigned_operator_id.is_(None))
            rows = query.order_by(SupportTicket.created_at.asc(), SupportTicket.id.asc()).limit(max(0, limit)).all()
            return [_view(r) for r in rows]

    # ── writes ──────────────────────────────────────────────────────────────

    def open_ticket(self, *, user_id: str, subject: str, body: str) -> TicketView:
        """Create a ticket, triaging the first message as it lands."""
        from database.models import SupportMessage, SupportTicket

        decision = triage(body)
        ticket_id = uuid.uuid4().hex[:32]

        with self._session_factory() as session:
            row = SupportTicket(
                ticket_id=ticket_id,
                user_id=user_id,
                subject=subject,
                status=STATUS_AWAITING_OPERATOR if decision.needs_human else STATUS_OPEN,
                category=decision.category,
                department=decision.department,
                needs_human=decision.needs_human,
                escalation_reason=decision.escalation_reason,
                matched_on=decision.matched_on,
            )
            session.add(row)
            session.add(SupportMessage(ticket_id=ticket_id, author_kind="customer", author_id=user_id, body=body))
            session.commit()
            session.refresh(row)
            view = _view(row)

        if decision.needs_human:
            logger.info("support: ticket %s opened and escalated (%s)", ticket_id, decision.category)
        return view

    def add_message(
        self,
        ticket_id: str,
        *,
        author_kind: str,
        body: str,
        author_id: str | None = None,
    ) -> Outcome:
        """Append a turn, and re-evaluate the floor when the customer speaks."""
        from database.models import SupportMessage, SupportTicket

        with self._session_factory() as session:
            row = session.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).one_or_none()
            if row is None:
                return Outcome(False, f"Ticket {ticket_id!r} not found.")

            session.add(SupportMessage(ticket_id=ticket_id, author_kind=author_kind, author_id=author_id, body=body))

            if author_kind in _RESPONDERS and row.first_response_at is None:
                # The FIRST response. Later replies must not overwrite it, or
                # the measurement becomes "time to most recent reply".
                row.first_response_at = datetime.utcnow()

            if author_kind == "customer":
                if row.status == STATUS_RESOLVED:
                    # A reply after a close reopens rather than needing a new
                    # ticket — the customer should not have to restate the
                    # problem because the desk decided it was over.
                    row.status = STATUS_OPEN
                    row.resolved_at = None
                # The FLOOR only, not the whole of triage: routing is already
                # decided for this thread, and re-categorising a one-line
                # follow-up in isolation escalates every conversation on its
                # second turn. See `support.triage.check_floor`.
                decision = check_floor(body)
                if decision is not None and not row.needs_human:
                    # Sticky: set here, never cleared. A customer who mentions a
                    # withdrawal and then changes the subject has not made the
                    # ticket safe for an AI to close.
                    row.needs_human = True
                    row.escalation_reason = decision.escalation_reason
                    row.matched_on = decision.matched_on
                    row.category = decision.category or row.category
                    if row.status != STATUS_WITH_OPERATOR:
                        row.status = STATUS_AWAITING_OPERATOR
                    logger.info("support: ticket %s escalated mid-thread (%s)", ticket_id, decision.category)
                elif row.status == STATUS_OPEN and row.needs_human:
                    row.status = STATUS_AWAITING_OPERATOR

            session.commit()
        return Outcome(True)

    def escalate(self, ticket_id: str, *, reason: str) -> Outcome:
        """Send a ticket to a person for a reason the floor did not raise.

        The floor is not the only way a ticket needs a human. An AI that could
        not answer — no reachable model, a budget refusal, an empty completion —
        leaves a ticket nobody is working, and a ticket nobody is working looks
        identical to one that was answered. This is how `answering`'s refusal
        becomes somebody's queue item.

        Sticky like the floor: it sets `needs_human` and never clears it.
        """
        from database.models import SupportTicket

        with self._session_factory() as session:
            row = session.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).one_or_none()
            if row is None:
                return Outcome(False, f"Ticket {ticket_id!r} not found.")
            if not row.needs_human:
                row.needs_human = True
                row.escalation_reason = reason
                if row.status != STATUS_WITH_OPERATOR:
                    row.status = STATUS_AWAITING_OPERATOR
                logger.info("support: ticket %s escalated (%s)", ticket_id, reason)
            session.commit()
        return Outcome(True)

    def claim(self, ticket_id: str, *, operator_id: str) -> Outcome:
        """Take a ticket. Refused if someone else already holds it."""
        from database.models import SupportTicket

        with self._session_factory() as session:
            row = session.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).one_or_none()
            if row is None:
                return Outcome(False, f"Ticket {ticket_id!r} not found.")
            if row.status == STATUS_RESOLVED:
                return Outcome(False, f"Ticket {ticket_id!r} is resolved; reopen it before claiming.")

            held_by = row.assigned_operator_id
            if held_by and held_by != operator_id:
                # Naming the holder is the point: "someone else has it" is not
                # something the second operator can act on.
                return Outcome(False, f"Ticket {ticket_id!r} is already held by {held_by!r}.")

            row.assigned_operator_id = operator_id
            row.status = STATUS_WITH_OPERATOR
            session.commit()
        return Outcome(True)

    def release(self, ticket_id: str, *, operator_id: str) -> Outcome:
        """Put a ticket back in the queue. Only its holder may."""
        from database.models import SupportTicket

        with self._session_factory() as session:
            row = session.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).one_or_none()
            if row is None:
                return Outcome(False, f"Ticket {ticket_id!r} not found.")
            held_by = row.assigned_operator_id
            if held_by != operator_id:
                return Outcome(
                    False,
                    f"Ticket {ticket_id!r} is held by {held_by!r}, not {operator_id!r}.",
                )
            row.assigned_operator_id = None
            row.status = STATUS_AWAITING_OPERATOR if row.needs_human else STATUS_OPEN
            session.commit()
        return Outcome(True)

    def resolve(self, ticket_id: str, *, actor: Actor, actor_id: str | None = None) -> Outcome:
        """Close a ticket. **The AI may not close what the floor escalated.**"""
        from database.models import SupportTicket

        with self._session_factory() as session:
            row = session.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).one_or_none()
            if row is None:
                return Outcome(False, f"Ticket {ticket_id!r} not found.")

            if actor is Actor.AI and row.needs_human:
                # The whole point of the floor. Refused, not logged-and-applied.
                logger.info("support: refused AI resolution of escalated ticket %s", ticket_id)
                return Outcome(
                    False,
                    "This ticket was escalated to a person and cannot be resolved by the AI: "
                    + (row.escalation_reason or "it needs a human."),
                )
            if actor is Actor.CUSTOMER:
                return Outcome(False, "A customer cannot resolve their own ticket from here.")

            row.status = STATUS_RESOLVED
            row.resolved_at = datetime.utcnow()
            if actor is Actor.OPERATOR and actor_id:
                row.assigned_operator_id = actor_id
            session.commit()
        return Outcome(True)
