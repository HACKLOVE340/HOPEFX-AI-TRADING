# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Engaging the kill switch stops the brain from trading.

Measured before this existed, with the global kill switch ACTIVE:

    kill switch active: True
    validate_trade    : (True, 'approved')

The wiring was one-directional. `RiskManager._halt_trading` fires the app-level
kill switch so "all subsystems see the halt" — but the reverse never existed: a
kill switch engaged by an operator, by the Redis latch, by the K8s configmap or
by a broker's cancel-on-disconnect left `validate_trade` answering "approved".

Nothing closed that loop. `KillSwitch.register_callback` exists and has **zero**
production registrants, and `_halt_trading` is only ever called for drawdown
limits. `RiskManager.kill_switch_active` reads `self._halt` — the manager's own
halt, not the global switch — so even the property that appears to answer this
question was answering a different one.

And the broker layer does not close the gap. `BrokerManager._check_kill_switch`
guards `place_order`; the brain calls `place_market_order`, which
`BrokerManager` does not define at all. The classes that do define it —
`brokers/oanda.py`, `brokers/paper_trading.py`, `brokers/base.py` — contain no
reference to the kill switch whatsoever.

So an operator hitting the kill switch believed everything stopped, and the
brain kept placing market orders.

The check is a **read at decision time**, not a registered callback. A callback
has to be wired, and the one that already exists here was never wired by
anybody — which is the failure mode this repository keeps producing. A read
cannot be forgotten.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from brain.brain import HOPEFXBrain
from risk.manager import RiskConfig, RiskManager

pytestmark = pytest.mark.unit


@pytest.fixture
def armed_kill_switch():
    """Engage the global switch for one test, and always release it.

    Without the release this leaks into every later test in the session, and a
    suite that halts trading globally would look like a hundred unrelated
    failures.
    """
    from kill_switch import kill_switch as switch

    switch.activate("test: does the AI stop?")
    try:
        yield switch
    finally:
        switch.reset_for_testing()


def a_broker():
    broker = MagicMock()
    order = MagicMock()
    order.id = "ord-1"
    order.average_fill_price = 2000.0
    order.status.value = "filled"
    broker.place_market_order = AsyncMock(return_value=order)
    broker.close_position = AsyncMock(return_value=True)
    return broker


def a_brain(risk_manager, broker):
    brain = HOPEFXBrain(config={"max_decision_history": 10})
    brain.inject_components(
        price_engine=MagicMock(),
        risk_manager=risk_manager,
        broker=broker,
        strategy_manager=MagicMock(),
        notification_manager=None,
        position_tracker=None,
        trade_executor=None,
    )
    return brain


# ── the gate itself ──────────────────────────────────────────────────────────


def test_validate_trade_approves_a_normal_trade_when_nothing_is_engaged():
    """The control case. A gate that refuses everything proves nothing."""
    rm = RiskManager(config=RiskConfig())
    allowed, _reason = rm.validate_trade(symbol="XAUUSD", quantity=0.01, direction="buy")
    assert allowed is True


def test_validate_trade_refuses_while_the_kill_switch_is_active(armed_kill_switch):
    rm = RiskManager(config=RiskConfig())
    allowed, reason = rm.validate_trade(symbol="XAUUSD", quantity=0.01, direction="buy")
    assert allowed is False
    assert "kill_switch" in reason


def test_trading_resumes_once_the_switch_is_released():
    """A kill switch that cannot be released is an outage, not a control."""
    from kill_switch import kill_switch as switch

    rm = RiskManager(config=RiskConfig())
    switch.activate("temporary")
    try:
        assert rm.validate_trade(symbol="XAUUSD", quantity=0.01, direction="buy")[0] is False
    finally:
        switch.reset_for_testing()

    assert rm.validate_trade(symbol="XAUUSD", quantity=0.01, direction="buy")[0] is True


def test_a_switch_that_cannot_be_read_refuses_rather_than_permits(monkeypatch):
    """ "I cannot tell whether trading is halted" must never mean "trade"."""
    rm = RiskManager(config=RiskConfig())
    broken = MagicMock()
    type(broken).is_active = property(lambda self: (_ for _ in ()).throw(RuntimeError("latch unreadable")))
    monkeypatch.setattr(rm, "_resolve_kill_switch", lambda: broken)

    allowed, reason = rm.validate_trade(symbol="XAUUSD", quantity=0.01, direction="buy")
    assert allowed is False
    assert "kill_switch" in reason


# ── end to end, through the brain ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_brain_places_no_order_while_the_kill_switch_is_active(armed_kill_switch):
    broker = a_broker()
    brain = a_brain(RiskManager(config=RiskConfig()), broker)

    await brain._execute_signal({"action": "buy", "symbol": "XAUUSD", "size": 1.0})

    broker.place_market_order.assert_not_called()


@pytest.mark.asyncio
async def test_the_brain_can_still_close_a_position_with_the_switch_active(armed_kill_switch):
    """Reducing exposure must survive the halt.

    A kill switch that also prevents closing freezes the account holding exactly
    the positions it was pulled over.
    """
    broker = a_broker()
    brain = a_brain(RiskManager(config=RiskConfig()), broker)

    await brain._execute_signal({"action": "close", "symbol": "XAUUSD", "size": 1.0, "position_id": "pos-1"})

    broker.close_position.assert_awaited_once_with("pos-1")


# ── the facts this rests on, asserted so they cannot rot ────────────────────


def test_the_brokers_that_place_market_orders_still_do_not_check_the_switch():
    """Documents WHY the gate belongs in the risk manager.

    BrokerManager guards `place_order`; it does not define `place_market_order`
    at all. If a broker ever grows its own check this test should be revisited —
    but a second gate is not a reason to remove this one.
    """
    import inspect

    from brokers import manager as broker_manager

    assert not hasattr(broker_manager.BrokerManager, "place_market_order")
    assert "kill_switch" not in inspect.getsource(__import__("brokers.oanda", fromlist=["x"]))
