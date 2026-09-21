# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/tenancy.py — who is allowed to see which trading rows.

**The problem this exists to solve.** ``app_state.broker`` is one process-wide
engine with one account. Every logged-in user trades against it, so
``broker.get_positions()`` and ``broker.get_orders()`` return *everybody's*
rows, and ``broker.get_account_info()`` returns one shared balance. Isolation
was deferred when the platform was single-account, and the filters added
afterwards landed on some endpoints and not others:
``GET /api/trading/positions`` filtered, ``GET /api/trading/orders`` did not,
``/balance`` did not, ``api/portfolio.py`` did not, and the WebSocket account
broadcaster pushed one account's equity to every subscriber.

Scattering the filter across each endpoint is how the gaps appeared in the
first place. Ownership is resolved here, once, and every read surface goes
through it.

**Fail closed.** When ownership cannot be established — no database, a failed
query — these return *nothing* rather than everything. Showing an empty book to
a user whose rows we cannot identify is a bug they will report. Showing them
another trader's positions is one nobody reports and everybody sees.

**Operators are not exempt.** ``admin`` and ``superadmin`` used to bypass the
position filter entirely, on the reasoning that operators "see the whole book".
On the ordinary trading endpoints they no longer do: an admin placing a trade is
a trader like any other and sees their own account. Whole-book visibility lives
on explicit operator routes that say so and are audited — see
``is_operator`` and its callers under ``api/superadmin/``.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, TypeVar

logger = logging.getLogger(__name__)

__all__ = [
    "OPERATOR_ROLES",
    "acting_user_id",
    "is_operator",
    "owned_order_ids",
    "owned_position_ids",
    "scope_rows",
]

T = TypeVar("T")

# Roles permitted to use the operator endpoints. Membership grants access to
# /api/superadmin/* views of the whole book — it does NOT widen what the
# ordinary trading endpoints return.
OPERATOR_ROLES = frozenset({"admin", "superadmin"})


def is_operator(user: Any) -> bool:
    """True when *user* may call the operator (whole-book) endpoints."""
    return getattr(user, "role", None) in OPERATOR_ROLES


def acting_user_id(user: Any) -> str:
    """The account a request acts on.

    Always the authenticated subject, for every role. An operator wanting a
    different account uses the operator endpoints and names it explicitly, so
    that access is deliberate and auditable rather than an implicit consequence
    of holding a role.
    """
    return str(getattr(user, "sub", "") or "")


def _session_factory():
    try:
        from core.app_state import app_state

        return getattr(app_state, "db_session_factory", None)
    except Exception:  # pragma: no cover - defensive
        return None


def _owned_ids(model_attr: str, user_id: str, what: str) -> set[str]:
    """Ids of *what* rows owned by *user_id*; empty set on any failure."""
    if not user_id:
        logger.warning("Ownership lookup with no user id — returning an empty %s book.", what)
        return set()

    factory = _session_factory()
    if factory is None:
        # No database means no way to tell one user's rows from another's. The
        # shared engine's book is not a safe default.
        logger.warning(
            "Ownership for %s cannot be established (no DB session factory) — "
            "returning an empty book for user=%s rather than leaking the shared engine.",
            what,
            user_id,
        )
        return set()

    try:
        from database import models

        model = getattr(models, model_attr)
        with factory() as db:
            rows = db.query(model.id).filter(model.user_id == user_id).all()
        return {str(r[0]) for r in rows}
    except Exception as exc:
        logger.warning(
            "Ownership lookup for %s failed for user=%s (%s) — returning an empty book.",
            what,
            user_id,
            exc,
        )
        return set()


def owned_position_ids(user_id: str) -> set[str]:
    """Ids of the positions belonging to *user_id*. Empty on failure."""
    return _owned_ids("Position", user_id, "positions")


def owned_order_ids(user_id: str) -> set[str]:
    """Ids of the orders belonging to *user_id*. Empty on failure.

    ``Order`` grew a ``user_id`` column for this; it previously had none, which
    is why ``GET /api/trading/orders`` had nothing to filter on and returned the
    shared book to every caller.
    """
    return _owned_ids("Order", user_id, "orders")


def scope_rows(rows: Iterable[T], owned: set[str], *, id_attrs: tuple[str, ...] = ("id",)) -> list[T]:
    """Keep only the rows whose identifier is in *owned*.

    Broker objects are not uniform — a position may expose ``id`` while an order
    exposes ``order_id`` — so the identifier is looked up across *id_attrs* and
    the first non-empty one decides. A row with no recognisable identifier is
    dropped, not kept: an unidentifiable row cannot be shown to have come from
    this user's account.
    """
    kept: list[T] = []
    dropped_unidentified = 0
    for row in rows or []:
        ident = ""
        for attr in id_attrs:
            value = getattr(row, attr, None)
            if value is None and isinstance(row, dict):
                value = row.get(attr)
            if value not in (None, ""):
                ident = str(value)
                break
        if not ident:
            dropped_unidentified += 1
            continue
        if ident in owned:
            kept.append(row)
    if dropped_unidentified:
        logger.debug(
            "scope_rows dropped %d row(s) with no identifier — cannot attribute them to an owner",
            dropped_unidentified,
        )
    return kept
