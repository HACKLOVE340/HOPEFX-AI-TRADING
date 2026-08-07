# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_broker_calls_are_awaited.py
===========================================
Round 3 audit (docs/HARDENING_BACKLOG.md S12-04, S12-04a).

Every method on ``BaseBroker`` is ``async def``. Calling one inside
``loop.run_in_executor(...)`` therefore does **not** perform the call — the
worker thread merely constructs a coroutine and hands it back. Awaiting the
executor future yields that coroutine object, not a result, and nothing ever
runs it.

The failure is quiet and it is *not* uniform, which is what made it survive:

* ``SLTPMonitor._close_position`` — coroutine is not ``None``, so the monitor
  declared the close a success and alerted "STOP_LOSS HIT: Closed ..." while
  the position stayed open at the broker (S12-04).
* ``ExecutionEngine._check_margin`` / ``_check_leverage`` — the ``account is
  None`` guard passes (a coroutine is not None), then ``getattr(account,
  "equity", ...)`` yields ``0.0``, so every order is blocked with the false
  reason "Account equity is zero or negative".
* ``ExecutionEngine._place_order_async`` — ``order.status`` raises
  ``AttributeError`` on a coroutine.

These tests use brokers whose methods are ``async def``, exactly like the real
ones, and assert on results rather than on calls being made.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class _AsyncBroker:
    """A broker with the same async surface as ``brokers.base.BaseBroker``."""

    def __init__(self, equity=100_000.0, margin_available=50_000.0):
        self._equity = equity
        self._margin_available = margin_available
        self.place_order_awaited = 0

    async def get_account_info(self):
        from brokers.base import AccountInfo

        return AccountInfo(
            account_id="acct-1",
            currency="USD",
            balance=self._equity,
            equity=self._equity,
            margin_used=0.0,
            margin_available=self._margin_available,
            unrealized_pnl=0.0,
            positions_count=0,
        )

    async def place_order(self, **kwargs):
        from brokers.base import Order, OrderSide, OrderStatus, OrderType

        self.place_order_awaited += 1
        return Order(
            id="ord-1",
            symbol=kwargs.get("symbol", "XAUUSD"),
            side=kwargs.get("side", OrderSide.BUY),
            type=kwargs.get("order_type", OrderType.MARKET),
            quantity=kwargs.get("quantity", 1.0),
            status=OrderStatus.FILLED,
            filled_quantity=kwargs.get("quantity", 1.0),
            average_price=2350.0,
        )


# ── the shared helper ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_broker_awaits_an_async_method():
    from execution.broker_call import call_broker

    broker = _AsyncBroker()
    account = await call_broker(broker.get_account_info)

    assert not asyncio.iscoroutine(account), "returned the coroutine instead of awaiting it"
    assert account.equity == pytest.approx(100_000.0)


@pytest.mark.asyncio
async def test_call_broker_still_handles_a_sync_method():
    """The paper broker is synchronous; it must keep working, off the loop."""
    from execution.broker_call import call_broker

    class SyncBroker:
        def get_account_info(self):
            return {"equity": 42.0}

    assert await call_broker(SyncBroker().get_account_info) == {"equity": 42.0}


@pytest.mark.asyncio
async def test_call_broker_passes_arguments_through():
    from execution.broker_call import call_broker

    broker = _AsyncBroker()
    order = await call_broker(broker.place_order, symbol="XAUUSD", quantity=2.0)
    assert order.symbol == "XAUUSD"
    assert order.quantity == pytest.approx(2.0)
    assert broker.place_order_awaited == 1


@pytest.mark.asyncio
async def test_call_broker_propagates_errors_rather_than_swallowing_them():
    from execution.broker_call import call_broker

    class Failing:
        async def place_order(self, **_):
            raise RuntimeError("broker rejected")

    with pytest.raises(RuntimeError, match="broker rejected"):
        await call_broker(Failing().place_order)


# ── ExecutionEngine: the gates must see the real account ──────────────────────


def _make_engine(broker):
    from unittest.mock import AsyncMock, MagicMock

    from execution.engine import ExecutionEngine

    rm = MagicMock()
    rm.validate_trade = AsyncMock(return_value=(True, "ok"))
    return ExecutionEngine(
        broker_manager=broker,
        risk_manager=rm,
        kill_switch=None,
        redis_client=None,
        tca_recorder=None,
    )


@pytest.mark.asyncio
async def test_margin_gate_still_blocks_an_undermargined_order():
    """The margin gate must actually fire — it was silently inert.

    Reading a coroutine gives ``equity = 0.0``, and the buffer test is guarded
    by ``if projected_used > 0 and equity > 0``. With equity 0 that guard is
    False, so the check was **skipped entirely** and the gate never blocked
    anything. This is fail-*open*, despite the docstring promising fail-closed.
    """
    from execution.engine import ExecutionRequest

    # $100 of free margin against a $23,500 order — far under the 2.0x buffer.
    engine = _make_engine(_AsyncBroker(equity=100_000.0, margin_available=100.0))
    req = ExecutionRequest(
        symbol="XAUUSD",
        side="BUY",
        quantity=10.0,
        order_type="LIMIT",
        price=2350.0,
        strategy_id="t",
    )

    blocked = await engine._check_margin(req, 0.0)
    assert blocked is not None, (
        "margin gate passed an order with a 0.004x margin buffer — it read a "
        "coroutine instead of an AccountInfo, so equity was 0 and the buffer "
        "check was skipped"
    )
    assert "MARGIN_INSUFFICIENT" in (blocked.message or "")


@pytest.mark.asyncio
async def test_leverage_gate_does_not_block_a_funded_account():
    """A $2,350 order against $100k equity is 0.02x leverage — must pass.

    With a coroutine the gate read equity 0 and blocked *every* order with the
    false reason "Account equity is zero or negative".
    """
    from execution.engine import ExecutionRequest

    engine = _make_engine(_AsyncBroker())
    req = ExecutionRequest(
        symbol="XAUUSD",
        side="BUY",
        quantity=1.0,
        order_type="LIMIT",
        price=2350.0,
        strategy_id="t",
    )

    blocked = await engine._check_leverage(req, 0.0)
    assert blocked is None, (
        f"leverage gate blocked a funded account: {getattr(blocked, 'message', blocked)}"
    )


@pytest.mark.asyncio
async def test_leverage_gate_still_blocks_excessive_leverage():
    """...and the gate must remain able to block. Guards against over-fixing."""
    from execution.engine import ExecutionRequest

    engine = _make_engine(_AsyncBroker(equity=1_000.0))
    req = ExecutionRequest(
        symbol="XAUUSD",
        side="BUY",
        quantity=100.0,
        order_type="LIMIT",
        price=2350.0,
        strategy_id="t",
    )

    blocked = await engine._check_leverage(req, 0.0)
    assert blocked is not None, "235x leverage was not blocked"
    assert "LEVERAGE_EXCEEDED" in (blocked.message or "")


# ── structural guard ──────────────────────────────────────────────────────────

#: Files on the money path where an un-awaited broker call moves (or fails to
#: move) real positions.
MONEY_PATH = (
    "execution/engine.py",
    "execution/sl_tp_monitor.py",
    "execution/trade_executor.py",
    "api/health.py",
)

#: Broker methods declared `async def` on brokers/base.py.
ASYNC_BROKER_METHODS = frozenset(
    {
        "place_order",
        "get_account_info",
        "get_positions",
        "get_orders",
        "close_position",
        "cancel_order",
        "modify_order",
        "connect",
        "disconnect",
    }
)


@pytest.mark.parametrize("rel_path", MONEY_PATH)
def test_no_unawaited_broker_call_in_an_executor(rel_path: str):
    """`run_in_executor` must never be handed a bare async broker method.

    This is the structural form of the bug: it catches a reintroduction at any
    of these call sites, including ones no behavioural test covers.
    """
    path = REPO_ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} not present")

    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run_in_executor"
            and len(node.args) >= 2
        ):
            continue
        target = node.args[1]
        for sub in ast.walk(target):
            if isinstance(sub, ast.Attribute) and sub.attr in ASYNC_BROKER_METHODS:
                offenders.append((node.lineno, sub.attr))

    assert not offenders, (
        f"{rel_path} calls async broker method(s) inside run_in_executor at "
        f"{offenders}. The worker thread only builds a coroutine; nothing awaits "
        f"it, so the broker is never actually called. Use "
        f"execution.broker_call.call_broker instead."
    )
