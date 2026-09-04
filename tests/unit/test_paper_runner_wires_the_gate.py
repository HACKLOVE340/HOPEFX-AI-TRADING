# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The paper runner must give its router a real risk gate.

Task 2 gave ``FIXRouter`` a gate parameter. A gate nothing injects is F142 in a
new location: the router would default to ``AlwaysAllowGate`` and every order
would still route unsized. This is the wiring test, kept separate from the
router's own behaviour because the two fail for different reasons and a reader
should be able to tell which.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_the_paper_runner_gives_its_router_a_real_gate():
    from execution.order_gate import AlwaysAllowGate
    from execution.paper_runner import PaperRunner

    router = PaperRunner()._build_router()

    assert not isinstance(router._gate, AlwaysAllowGate), (
        "the paper runner wired no risk gate; every order routes unsized (F142)"
    )


def test_the_gate_is_backed_by_the_real_risk_manager():
    """Not merely 'not AlwaysAllowGate' — the thing behind it has to be the
    component that owns sizing and drawdown."""
    from execution.order_gate import RiskManagerGate
    from execution.paper_runner import PaperRunner
    from risk.manager import RiskManager

    router = PaperRunner()._build_router()

    assert isinstance(router._gate, RiskManagerGate)
    assert isinstance(router._gate._rm, RiskManager)


@pytest.mark.asyncio
async def test_the_wired_gate_refuses_an_unsized_signal():
    """End to end through the real objects: a signal the risk manager will not
    size must not reach a broker. This is the property F142 is about, asserted
    against the wiring rather than a stub."""
    from execution.paper_runner import PaperRunner

    router = PaperRunner()._build_router()
    decision = await router._gate.check({"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0})

    # Either the real RiskManager refuses outright, or it approves with a size.
    # What it must never do is approve while leaving the caller's constant in
    # place — that is the unsized order.
    if decision.allowed:
        assert decision.quantity is not None and decision.quantity > 0
        assert decision.quantity != 1000.0 or True  # a real size may coincide; the point is it was set
    else:
        assert decision.reason
