# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Let the agent decide, and let nothing happen.

`place_order` and `cancel_order` are the only two actions in Cluster A that can
lose money, and they are deliberately unimplemented: the build order put them
last, after the permission tiers, the scope gate and the audit trail had been
exercised by departments that cannot.

That left a gap. Nobody can tell whether the agent's *decisions* are any good
until the handlers exist, and by then the first evidence arrives attached to a
real order. Shadow mode closes it — the agent proposes exactly what it would do,
against live market conditions, and nothing is sent. When the real handlers are
eventually written, they are written against a decision record somebody has
already read.

## Shadow is a different tool, not a mode on the real one

A `dry_run=True` parameter is one config edit, one changed default, or one
forgotten argument away from a live order. `shadow_place_order` is its own
action with its own handler, and **this module does not import a broker, the
OMS, or anything that can send** — so "shadow accidentally went live" is not a
failure mode that exists. Same reasoning as `ai/awareness` not importing the
tool bus: make the unsafe thing inexpressible rather than discouraged.

## The verdict matters more than the intent

Recording "the agent wanted to buy 0.5 lots" says nothing about whether that was
sane. Every shadow order is put through the same risk gate a real one would
face, and the verdict is recorded next to the intent. The question worth
answering is not what the agent wanted but whether the platform would have let
it.

## No order id, ever

An id is what downstream code keys a real position on. A shadow result carries
`sent: False`, a `note` saying so in words, and nothing that could be mistaken
for a ticket.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

SIDES = ("buy", "sell")


def _validate(symbol: str, side: str, quantity: float) -> None:
    """Refuse an impossible order rather than recording it.

    A shadow trail full of orders that could never have been placed is worthless
    as evidence — the whole value is that every entry is something the agent
    genuinely would have sent.
    """
    if not symbol or not symbol.strip():
        raise ValueError("a shadow order needs a symbol")
    if side not in SIDES:
        raise ValueError(f"side {side!r} is not one of {SIDES}")
    if quantity is None or float(quantity) <= 0:
        raise ValueError("a shadow order needs a positive quantity")


def _risk_verdict(symbol: str, side: str, quantity: float) -> dict[str, Any]:
    """What the risk gate would have said.

    Best-effort: on a box with no risk manager this reports that it could not be
    evaluated, which is honest. It never invents an approval — an unavailable
    gate must not read as a passed one, which is the failure `hopefx-dead-controls`
    exists to catch.
    """
    try:
        from ai.departments import risk_compliance

        verdict = risk_compliance.validate_position_size(
            trade={"symbol": symbol, "side": side, "quantity": float(quantity)},
        )
    except Exception as exc:
        logger.warning("shadow: risk gate could not be consulted (%s)", exc)
        return {"allowed": None, "reason": "risk_gate_unavailable"}

    if not verdict.get("available"):
        return {"allowed": None, "reason": verdict.get("reason", "risk_gate_unavailable")}
    return {"allowed": bool(verdict.get("passed", False)), "reason": verdict.get("reason", "")}


def _record(kind: str, payload: dict[str, Any]) -> None:
    try:
        from ai.memory.store import remember

        remember("markets_execution", kind, payload)
    except Exception:
        # The trail is the product here, so losing an entry is worth an ERROR —
        # but it must not fail the caller, because nothing was at stake anyway.
        logger.exception("shadow: could not record a %s", kind)


def shadow_place_order(
    *,
    symbol: str = "",
    side: str = "",
    quantity: float = 0.0,
    order_type: str = "market",
    price: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    """What `place_order` would have done. Sends nothing."""
    _validate(symbol, side, quantity)

    would_have = {
        "symbol": symbol,
        "side": side,
        "quantity": float(quantity),
        "order_type": order_type,
        "price": price,
    }
    result = {
        "shadow": True,
        "sent": False,
        "would_have": would_have,
        "risk_verdict": _risk_verdict(symbol, side, float(quantity)),
        "at": datetime.now(UTC).isoformat(),
        "note": "Shadow mode — no order was sent to any broker and no position changed.",
    }
    _record("shadow_order", result)
    return result


def shadow_cancel_order(*, order_id: str = "", **_: Any) -> dict[str, Any]:
    """What `cancel_order` would have done. Sends nothing."""
    if not order_id or not str(order_id).strip():
        raise ValueError("a shadow cancel needs an order_id")

    result = {
        "shadow": True,
        "sent": False,
        "would_have": {"order_id": str(order_id)},
        "at": datetime.now(UTC).isoformat(),
        "note": "Shadow mode — no cancellation was sent to any broker.",
    }
    _record("shadow_cancel", result)
    return result


__all__ = ["SIDES", "shadow_cancel_order", "shadow_place_order"]
