# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The pre-trade gate the order routers call.

``FIXRouter._route`` had exactly one gate — ``if self._halted`` — and then went
straight to the broker: no risk assessment, no sizing, no drawdown or exposure
check, and a fixed ``PAPER_ORDER_UNITS`` size (F142). That is the path
``run.py`` takes when ``PAPER_TRADING=true``, which ``CLAUDE.md`` describes as
the platform's current status.

Risk policy does not belong in a router, so the router takes an object with one
method instead. These tests pin the gate's own behaviour; wiring it into the
router is tested separately.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from execution.order_gate import AlwaysAllowGate, GateDecision, RiskManagerGate

pytestmark = pytest.mark.unit


class _Assessment:
    def __init__(self, approved, reason="", quantity=None):
        self.approved = approved
        self.reason = reason
        self.sizing = type("S", (), {"quantity": quantity})() if quantity else None


@pytest.mark.asyncio
async def test_a_rejected_assessment_blocks_the_order():
    class RM:
        def assess(self, signal):
            return _Assessment(False, reason="daily_dd:6.10%")

    decision = await RiskManagerGate(RM()).check({"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0})
    assert decision.allowed is False
    assert "daily_dd" in decision.reason


@pytest.mark.asyncio
async def test_an_approved_assessment_returns_the_risk_managers_size():
    class RM:
        def assess(self, signal):
            return _Assessment(True, reason="ok", quantity=37.5)

    decision = await RiskManagerGate(RM()).check({"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0})
    assert decision.allowed is True
    assert decision.quantity == 37.5, "the fixed PAPER_ORDER_UNITS constant survived the gate"


@pytest.mark.asyncio
async def test_an_approval_with_no_sizing_is_refused():
    """The plan's default. An approved signal the risk manager did not size is
    exactly the unsized order F142 is about; passing it through with the
    caller's constant would reinstate the defect one layer down."""

    class RM:
        def assess(self, signal):
            return _Assessment(True, reason="ok", quantity=None)

    decision = await RiskManagerGate(RM()).check({"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0})
    assert decision.allowed is False
    assert "unsized" in decision.reason


@pytest.mark.asyncio
async def test_a_non_positive_size_is_refused():
    """A zero or negative quantity is not a small trade; it is a broken one."""
    for bad in (0.0, -1.0):

        class RM:
            def assess(self, signal, _q=bad):
                return _Assessment(True, reason="ok", quantity=_q)

        decision = await RiskManagerGate(RM()).check({"symbol": "XAUUSD", "direction": "BUY"})
        assert decision.allowed is False, f"a quantity of {bad} was allowed through"


@pytest.mark.asyncio
async def test_a_raising_risk_manager_fails_closed():
    class RM:
        def assess(self, signal):
            raise RuntimeError("feature store down")

    decision = await RiskManagerGate(RM()).check({"symbol": "XAUUSD", "direction": "BUY"})
    assert decision.allowed is False, "a broken risk manager let an unsized order through"
    assert "error" in decision.reason


@pytest.mark.asyncio
async def test_the_always_allow_gate_says_so_loudly(caplog):
    with caplog.at_level("WARNING"):
        decision = await AlwaysAllowGate().check({"symbol": "XAUUSD"})
    assert decision.allowed is True
    assert any("no risk gate" in r.message.lower() for r in caplog.records), (
        "an unconfigured deployment trades with no risk layer and says nothing"
    )


def test_a_gate_decision_is_immutable():
    """A decision that a caller can edit after the fact is not a gate."""
    decision = GateDecision(False, "daily_dd")
    with pytest.raises(FrozenInstanceError):
        decision.allowed = True  # type: ignore[misc]
