# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""No order the brain originates reaches a broker without the risk gate.

This is the property I listed as unasserted and then found violated. It was not
a missing check — it was a check that could never run, which is this audit's
signature defect placed directly on the money path:

    brain/brain.py:858
    if self.risk_manager and hasattr(self.risk_manager, "filter_signals"):
        signals = await self.risk_manager.filter_signals(signals, self.state)

`filter_signals` is defined nowhere in this repository. `RiskManager` exposes
`validate_trade`, `check_risk_limits`, `check_kill_switch`, `check_drawdown`,
`check_position_size` and seven more — but not that one. So `hasattr` is always
False, the branch never executes, and every generated signal fell through to
`_execute_signal`, which called `broker.place_market_order()` after checking
only that the fields were present and the size was above zero.

The path is live and unflagged: `core/startup_factories.py:1794`
(`init_hopefx_brain`) constructs `brain.brain.HOPEFXBrain`, injects the real
broker and the real risk manager, and launches `dominate()`. It is registered as
`brain` with no feature flag.

Two properties, and the second matters as much as the first:

* a trade the risk manager refuses must not reach the broker, and
* a trade it permits must still reach the broker — a gate that blocks
  everything is not a fix, it is an outage with better branding.

Fail-closed: no risk manager means no order. The old code treated an absent risk
manager as "nothing to filter with, carry on", which is the most dangerous
reading available.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from brain.brain import HOPEFXBrain
from risk.manager import RiskConfig, RiskManager

pytestmark = pytest.mark.unit


def a_brain(*, risk_manager, broker):
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


def a_broker():
    broker = MagicMock()
    order = MagicMock()
    order.id = "ord-1"
    order.average_fill_price = 2000.0
    order.status.value = "filled"
    broker.place_market_order = AsyncMock(return_value=order)
    broker.close_position = AsyncMock(return_value=True)
    return broker


BUY = {"action": "buy", "symbol": "XAUUSD", "size": 1.0}


# ── the method the old gate looked for does not exist ────────────────────────


def test_risk_manager_has_no_filter_signals_method():
    """The fact the old guard depended on, asserted so it cannot be assumed back."""
    assert not hasattr(RiskManager(config=RiskConfig()), "filter_signals")


def test_the_brain_no_longer_gates_on_a_method_that_does_not_exist():
    """Read as code, not as prose.

    The first version of this test grepped the source text and failed against
    the fix, because the comment explaining the removal quotes the line it
    removed. That is F255 exactly — `security/code_analyzer.py` scanned
    docstrings as source, and the script written to verify that fix then flagged
    four correct files for quoting the defect they fixed. A comment describing a
    dead gate is not a dead gate. So this walks the AST.
    """
    import ast

    tree = ast.parse(inspect.getsource(HOPEFXBrain))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "hasattr"):
            continue
        probed = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        assert "filter_signals" not in probed, (
            "the risk gate is a hasattr for a method no class in this repository defines, so it can never run"
        )


# ── refused trades must not reach the broker ─────────────────────────────────


@pytest.mark.asyncio
async def test_a_halted_risk_manager_stops_the_order():
    risk = RiskManager(config=RiskConfig())
    risk.halt_trading("test halt") if hasattr(risk, "halt_trading") else setattr(risk, "_halt", True)
    broker = a_broker()

    await a_brain(risk_manager=risk, broker=broker)._execute_signal(dict(BUY))

    broker.place_market_order.assert_not_called()


@pytest.mark.asyncio
async def test_an_oversized_order_is_refused():
    """The size limit is a risk gate; the brain must be behind it."""
    risk = RiskManager(config=RiskConfig())
    broker = a_broker()

    await a_brain(risk_manager=risk, broker=broker)._execute_signal(
        {"action": "buy", "symbol": "XAUUSD", "size": 1_000_000_000.0}
    )

    broker.place_market_order.assert_not_called()


@pytest.mark.asyncio
async def test_no_risk_manager_means_no_order():
    """Fail closed. "Nothing to filter with, carry on" is the dangerous reading."""
    broker = a_broker()

    await a_brain(risk_manager=None, broker=broker)._execute_signal(dict(BUY))

    broker.place_market_order.assert_not_called()


@pytest.mark.asyncio
async def test_a_risk_manager_that_raises_refuses_rather_than_permits():
    """A gate that errors must not become a gate that waves the trade through."""
    risk = MagicMock()
    risk.validate_trade.side_effect = RuntimeError("risk subsystem down")
    broker = a_broker()

    await a_brain(risk_manager=risk, broker=broker)._execute_signal(dict(BUY))

    broker.place_market_order.assert_not_called()


# ── permitted trades must still get through ──────────────────────────────────


@pytest.mark.asyncio
async def test_a_permitted_trade_still_reaches_the_broker():
    """A gate that blocks everything is an outage, not a fix."""
    risk = MagicMock()
    risk.validate_trade.return_value = (True, "")
    broker = a_broker()

    await a_brain(risk_manager=risk, broker=broker)._execute_signal(dict(BUY))

    broker.place_market_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_risk_manager_is_asked_about_the_actual_order():
    """Asking about the wrong symbol or size is the same as not asking."""
    risk = MagicMock()
    risk.validate_trade.return_value = (True, "")
    broker = a_broker()

    await a_brain(risk_manager=risk, broker=broker)._execute_signal({"action": "sell", "symbol": "XAUUSD", "size": 2.5})

    kwargs = risk.validate_trade.call_args.kwargs
    args = risk.validate_trade.call_args.args
    assert "XAUUSD" in (list(args) + list(kwargs.values()))
    assert 2.5 in (list(args) + list(kwargs.values()))


@pytest.mark.asyncio
async def test_closing_a_position_is_still_allowed_when_trading_is_halted():
    """Reducing exposure must not be blocked by the gate that stops opening it.

    A halt that also prevents closing turns a risk control into a trap: the
    account is frozen holding exactly the positions the halt was called over.
    """
    risk = RiskManager(config=RiskConfig())
    risk._halt = True
    broker = a_broker()

    await a_brain(risk_manager=risk, broker=broker)._execute_signal(
        {"action": "close", "symbol": "XAUUSD", "size": 1.0, "position_id": "pos-1"}
    )

    broker.close_position.assert_awaited_once_with("pos-1")
