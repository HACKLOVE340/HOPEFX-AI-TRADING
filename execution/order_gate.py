# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/order_gate.py
=======================
The pre-trade gate the order routers call.

``FIXRouter._route`` had exactly one gate — ``if self._halted`` — and then went
straight to the broker (F142). No ``RiskManager``, no position sizing, no
stop-loss, no drawdown, exposure or correlation check; size was the constant
``PAPER_ORDER_UNITS``. That is the path ``run.py`` takes when
``PAPER_TRADING=true``, which ``CLAUDE.md`` describes as the platform's current
status — so it is the path with no risk layer that is actually running.

Risk policy does not belong in a router. The router takes an object with one
method: production injects :class:`RiskManagerGate`, tests inject a stub, and
neither has to know about the other. ``fix_router.py`` stays free of risk logic
and the gate stays independently testable.

**Everything here fails closed.** A gate that cannot reach its risk manager
refuses the order, and an approval carrying no size is refused too — an unsized
order is precisely the defect this module exists to stop, so passing one through
on the caller's constant would reinstate F142 one layer down.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateDecision:
    """The gate's answer about one order.

    Frozen: a decision a caller can edit after the fact is not a gate.
    """

    allowed: bool
    reason: str
    #: The size the gate authorises, in units. Always set when ``allowed`` is
    #: True — an approval without one is refused rather than returned.
    quantity: float | None = None


@runtime_checkable
class OrderGate(Protocol):
    """One method, so a router can hold a gate without importing risk policy."""

    async def check(self, order_request: dict[str, Any]) -> GateDecision: ...


class RiskManagerGate:
    """Routes an order_request through ``RiskManager.assess()``.

    ``assess()`` returns a ``RiskAssessment`` carrying ``approved``, ``reason``
    and an optional ``sizing`` with a ``quantity``. This adapts that to the one
    question a router needs answered, and refuses anything it cannot read as a
    clear approval with a usable size.
    """

    def __init__(self, risk_manager: Any) -> None:
        self._rm = risk_manager

    async def check(self, order_request: dict[str, Any]) -> GateDecision:
        symbol = order_request.get("symbol")
        try:
            assessment = self._rm.assess(order_request)
        except Exception:
            # Fail closed. An unsized trade is not a smaller problem than a
            # blocked one, and a risk manager that raises is telling you it
            # cannot vouch for this order.
            logger.exception("Pre-trade risk assessment failed for %s — REFUSING order (fail closed)", symbol)
            return GateDecision(False, "risk_assessment_error")

        if not getattr(assessment, "approved", False):
            reason = getattr(assessment, "reason", "rejected")
            logger.warning("Pre-trade gate REFUSED %s: %s", symbol, reason)
            return GateDecision(False, reason)

        sizing = getattr(assessment, "sizing", None)
        quantity = getattr(sizing, "quantity", None) if sizing is not None else None

        if quantity is None:
            logger.error(
                "Pre-trade gate REFUSED %s: approved but unsized. Falling back to a "
                "fixed order size is what F142 was; the risk manager owns sizing.",
                symbol,
            )
            return GateDecision(False, "approved_but_unsized")

        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            logger.error("Pre-trade gate REFUSED %s: unreadable size %r", symbol, quantity)
            return GateDecision(False, "approved_but_unsized")

        if not quantity > 0:
            # Zero or negative is not a small trade; it is a broken one.
            logger.error("Pre-trade gate REFUSED %s: non-positive size %s", symbol, quantity)
            return GateDecision(False, f"non_positive_size:{quantity}")

        return GateDecision(True, str(getattr(assessment, "reason", "ok")), quantity)


class AlwaysAllowGate:
    """No risk layer at all — explicit, named, and loud.

    Used only when nothing injected a real gate. It warns on **every** order
    rather than passing silently, because a deployment trading with no risk
    layer and saying nothing is the exact shape of F142. A quiet default here
    would recreate the defect while looking like a fix.
    """

    async def check(self, order_request: dict[str, Any]) -> GateDecision:
        logger.warning(
            "ORDER PLACED WITH NO RISK GATE: symbol=%s. No sizing, drawdown or "
            "exposure check was applied. Wire a RiskManager (see "
            "execution/order_gate.RiskManagerGate).",
            order_request.get("symbol"),
        )
        return GateDecision(True, "no_gate_configured")
