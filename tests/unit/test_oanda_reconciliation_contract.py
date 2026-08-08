# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_oanda_reconciliation_contract.py
=================================================
G-01 — startup reconciliation could not read live OANDA positions.

Raised by automated review on PR #265 (thirteen threads, one finding) and
verified against the code before acting on it. Both halves are real:

**1. The method does not exist.**
``core/startup_factories.py:1151`` wires ``AsyncOANDAConnector``, which is an
alias for ``brokers.oanda.OANDABroker`` (``oanda.py:632``). That class implements
``get_open_positions()`` and **not** ``get_positions()``, which
``PositionManager._reconcile_with_broker`` awaits. The call raises
``AttributeError``, the handler catches it, logs "restored state is UNVERIFIED",
and returns the persisted Redis snapshot untouched.

The sync ``OANDAConnector`` further down the same module *does* have
``get_positions()`` — returning ``_Position`` objects — which is presumably why
nobody noticed. It is not the class production wires, and it is not async.

**2. Even reachable, the records are the wrong shape.**
``get_open_positions()`` returns ``list[dict]``. The reconciler does
``getattr(p, "symbol", None)``, and a dict has no ``.symbol`` attribute, so
``live_by_symbol`` stays empty. That is the more dangerous of the two: an empty
broker view means *every persisted position is treated as closed and dropped*,
and no broker-only position is ever adopted.

(One correction to the report: ``get_open_positions()`` already maps
``instrument`` onto a ``symbol`` key, so the key name is not the problem — the
attribute-vs-mapping access is.)

**Why it matters.** Reconciliation exists to catch exactly the divergence a
restart creates: positions closed, opened or resized while the process was down.
With it inert, live OANDA exposure sits outside position limits, stop
monitoring, risk tracking and the dashboard, and the operator is told the
restore succeeded.

This is the same family as S1-01 (a second ``AccountInfo``), S13-03 (BUY
submitted as SELL) and S12-04 (never-awaited broker coroutines): the money path
and the broker disagreeing about a contract, and failing upward.

Fixed on both sides — a normalised async ``get_positions()`` on ``OANDABroker``,
and a reconciler that reads mappings as well as objects.
"""

from __future__ import annotations

import pytest

from brokers.base import OrderSide

pytestmark = pytest.mark.unit


# ── 1. The broker provides the awaited contract ──────────────────────────────


@pytest.mark.asyncio
async def test_production_oanda_broker_exposes_get_positions():
    from brokers.oanda import AsyncOANDAConnector, OANDABroker

    assert AsyncOANDAConnector is OANDABroker, "startup wires the alias; keep them the same class"
    assert hasattr(OANDABroker, "get_positions"), (
        "PositionManager._reconcile_with_broker awaits broker.get_positions(); "
        "without it the AttributeError is caught and the restart keeps an "
        "unverified snapshot (G-01)"
    )


def _broker_with(records):
    """An OANDABroker whose raw open-position call returns *records*."""
    from brokers.oanda import OANDABroker

    b = OANDABroker.__new__(OANDABroker)

    async def _fake():
        return records

    b.get_open_positions = _fake  # type: ignore[method-assign]
    return b


@pytest.mark.asyncio
async def test_a_long_leg_normalises_to_a_signed_buy():
    b = _broker_with([{"symbol": "EUR_USD", "long_units": 1000, "short_units": 0, "unrealized_pnl": 12.5}])
    (pos,) = await b.get_positions()
    assert pos.symbol == "EUR_USD"
    assert pos.side == OrderSide.BUY
    assert pos.quantity == 1000
    assert pos.unrealized_pnl == 12.5


@pytest.mark.asyncio
async def test_a_short_leg_normalises_to_a_sell_with_positive_quantity():
    # OANDA reports short units negative. Quantity is a magnitude; direction
    # lives in `side`. Leaking the sign into quantity is how a short gets sized
    # as a negative position downstream.
    b = _broker_with([{"symbol": "EUR_USD", "long_units": 0, "short_units": -800, "unrealized_pnl": -3.0}])
    (pos,) = await b.get_positions()
    assert pos.side == OrderSide.SELL
    assert pos.quantity == 800


@pytest.mark.asyncio
async def test_a_hedged_account_nets_the_two_legs():
    """OANDA hedging accounts can hold both legs at once. The reconciler's model
    is one position per symbol, so the policy is explicit: net them."""
    b = _broker_with([{"symbol": "EUR_USD", "long_units": 1000, "short_units": -300, "unrealized_pnl": 0.0}])
    (pos,) = await b.get_positions()
    assert pos.side == OrderSide.BUY
    assert pos.quantity == 700


@pytest.mark.asyncio
async def test_a_net_flat_hedge_is_not_reported_as_a_position():
    b = _broker_with([{"symbol": "EUR_USD", "long_units": 500, "short_units": -500, "unrealized_pnl": 0.0}])
    assert await b.get_positions() == []


@pytest.mark.asyncio
async def test_a_malformed_record_does_not_take_down_the_restore():
    b = _broker_with(
        [
            {"symbol": None, "long_units": 1, "short_units": 0},
            {"symbol": "EUR_USD", "long_units": 100, "short_units": 0, "unrealized_pnl": 0.0},
        ]
    )
    out = await b.get_positions()
    assert [p.symbol for p in out] == ["EUR_USD"]


# ── 2. The reconciler reads mappings as well as objects ──────────────────────


class _Broker:
    def __init__(self, live):
        self._live = live

    async def get_positions(self):
        return self._live


def _pm():
    from execution.position_manager import PositionManager

    return PositionManager.__new__(PositionManager)


def _persisted(symbol, qty=1.0, side="long"):
    from execution.position_manager import Position

    return Position(
        position_id=f"p-{symbol}",
        symbol=symbol,
        side=side,
        quantity=qty,
        entry_price=1.10,
        strategy_id="test",
    )


@pytest.mark.asyncio
async def test_a_mapping_position_is_matched_not_dropped():
    """The executed reproduction in the report: a live EUR_USD record alongside a
    persisted EUR_USD position returned no positions at all."""
    pm = _pm()
    parsed = {"EUR_USD": _persisted("EUR_USD", qty=1000)}
    live = [{"symbol": "EUR_USD", "quantity": 1000, "side": "long", "entry_price": 1.10}]

    out = await pm._reconcile_with_broker(parsed, _Broker(live))

    assert "EUR_USD" in out, (
        "a persisted position that the broker still holds was dropped as closed "
        "because the live record is a mapping and the loop read attributes (G-01)"
    )


@pytest.mark.asyncio
async def test_a_broker_only_mapping_position_is_adopted():
    pm = _pm()
    live = [{"symbol": "GBP_USD", "quantity": 500, "side": "short", "entry_price": 1.27}]

    out = await pm._reconcile_with_broker({}, _Broker(live))

    assert "GBP_USD" in out, "a broker-only position was not adopted from a mapping record"
    assert out["GBP_USD"].side == "short"
    assert out["GBP_USD"].quantity == 500


@pytest.mark.asyncio
async def test_a_quantity_mismatch_in_a_mapping_takes_the_brokers_number():
    pm = _pm()
    parsed = {"EUR_USD": _persisted("EUR_USD", qty=1000)}
    live = [{"symbol": "EUR_USD", "quantity": 600, "side": "long"}]

    out = await pm._reconcile_with_broker(parsed, _Broker(live))
    assert out["EUR_USD"].quantity == 600


@pytest.mark.asyncio
async def test_object_records_still_work():
    """The existing contract must not regress while mappings are added."""

    class _P:
        symbol = "EUR_USD"
        quantity = 1000
        side = "long"
        entry_price = 1.10

    pm = _pm()
    out = await pm._reconcile_with_broker({"EUR_USD": _persisted("EUR_USD", qty=1000)}, _Broker([_P()]))
    assert "EUR_USD" in out


@pytest.mark.asyncio
async def test_a_broker_that_still_cannot_be_read_keeps_the_persisted_view():
    """Unchanged behaviour, restated: when the broker genuinely cannot be
    queried, keeping the snapshot beats losing it — the log says UNVERIFIED."""

    class _Broken:
        async def get_positions(self):
            raise RuntimeError("no session")

    pm = _pm()
    parsed = {"EUR_USD": _persisted("EUR_USD")}
    out = await pm._reconcile_with_broker(parsed, _Broken())
    assert out == parsed
