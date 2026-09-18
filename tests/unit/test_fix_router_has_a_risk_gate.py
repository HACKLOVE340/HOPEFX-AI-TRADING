# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The order path that is actually running must consult a risk gate.

``run.py:372-380`` routes ``PAPER_TRADING=true`` to ``PaperRunner``, whose tick
loop publishes to ``CH_ORDER`` and lands in ``FIXRouter._route``. That method had
one gate — ``if self._halted`` — and then went straight to the broker, with size
taken from the constant ``PAPER_ORDER_UNITS`` (F142).

These tests are about the router's behaviour, not the gate's: that it asks, that
it obeys a refusal, that it uses the size it is given, and that adding a gate did
not displace the kill switch.
"""

from __future__ import annotations

import pytest

from execution.order_gate import AlwaysAllowGate, GateDecision

pytestmark = pytest.mark.unit


class _Gate:
    def __init__(self, decision):
        self.decision = decision
        self.calls: list[dict] = []

    async def check(self, order_request):
        self.calls.append(order_request)
        return self.decision


@pytest.mark.asyncio
async def test_a_refused_order_never_reaches_the_broker(monkeypatch):
    from execution.fix_router import FIXRouter

    gate = _Gate(GateDecision(False, "daily_dd:6.10%"))
    router = FIXRouter(gate=gate)
    sent = []

    async def _never(*args, **kwargs):
        sent.append(args)
        return {"status": "filled"}

    monkeypatch.setattr(router, "_send_paper", _never)
    router._paper_broker = object()

    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0})

    assert gate.calls, "the router did not consult the gate at all"
    assert sent == [], "a risk-refused order was sent to the broker"


@pytest.mark.asyncio
async def test_the_gates_size_replaces_the_fixed_constant(monkeypatch):
    from execution.fix_router import FIXRouter

    router = FIXRouter(gate=_Gate(GateDecision(True, "ok", quantity=37.5)))
    seen: dict = {}

    async def _capture(symbol, direction, units, req):
        seen["units"] = units
        seen["request_units"] = req.get("units")
        return {"status": "filled"}

    async def _noop(fill):
        return None

    monkeypatch.setattr(router, "_send_paper", _capture)
    monkeypatch.setattr(router, "_on_fill", _noop)
    monkeypatch.setattr("execution.fix_router._PAPER_MODE", True)
    router._paper_broker = object()

    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0})

    assert seen["units"] == 37.5, "PAPER_ORDER_UNITS was used instead of the risk-manager size"
    assert seen["request_units"] == 37.5, "the order_request still carried the unsized constant downstream"


@pytest.mark.asyncio
async def test_the_original_request_is_not_mutated(monkeypatch):
    """The caller's dict is shared with the event bus; resizing must not reach
    back into whatever else is holding it."""
    from execution.fix_router import FIXRouter

    router = FIXRouter(gate=_Gate(GateDecision(True, "ok", quantity=37.5)))

    async def _capture(symbol, direction, units, req):
        return {"status": "filled"}

    async def _noop(fill):
        return None

    monkeypatch.setattr(router, "_send_paper", _capture)
    monkeypatch.setattr(router, "_on_fill", _noop)
    monkeypatch.setattr("execution.fix_router._PAPER_MODE", True)
    router._paper_broker = object()

    original = {"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0}
    await router._route(original)

    assert original["units"] == 1000.0, "the router mutated the caller's order_request"


@pytest.mark.asyncio
async def test_the_halt_gate_still_wins():
    """Regression guard: adding a risk gate must not displace the kill switch."""
    from execution.fix_router import FIXRouter

    gate = _Gate(GateDecision(True, "ok", quantity=1.0))
    router = FIXRouter(gate=gate)
    router._halted = True

    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1.0})

    assert gate.calls == [], "the router consulted the gate while halted"


@pytest.mark.asyncio
async def test_a_refusal_is_counted():
    """A refusal nobody can count is invisible in production."""
    from execution.fix_router import FIXRouter

    router = FIXRouter(gate=_Gate(GateDecision(False, "daily_dd")))
    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1.0})
    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1.0})

    assert router._gate_refused_count == 2
    # Distinct from _reject_count, which counts broker rejections — these never
    # reached a broker at all.
    assert router._reject_count == 0
    assert router.metrics()["gate_refused_count"] == 2


def test_a_router_built_with_no_gate_gets_the_loud_one():
    """Defaulting to no gate silently would be F142 again, in the fix."""
    from execution.fix_router import FIXRouter

    assert isinstance(FIXRouter()._gate, AlwaysAllowGate)
