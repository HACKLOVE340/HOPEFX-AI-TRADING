# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A hedge that was not placed must not be reported as placed.

`RiskOrchestrator.activate_hedge_mode` sets the state before it does the work:

    self._hedge_active = True          # :318 — before any broker call
    ...
    result = await broker.place_order(...)   # :325
    except Exception as exc:
        logger.error("Hedge order failed: %s", exc)   # :334 — swallowed
    pos = HedgePosition(..., order_id=order_id)       # :343 — appended anyway
    self._hedge_positions.append(pos)

So a failed hedge order leaves the process, the persisted state file, the
Prometheus gauge, `/nuclear/hedge/activate`'s `status: "ok"` and every dashboard
reading "hedged" while the account carries no hedge at all — during the exact
event the hedge exists for. And because `_hedge_active` is already True, the
guard at :314 returns early on every retry, so recovery is impossible without a
restart (F81).

The same is true with no broker configured: :341 logs "Manual hedge required"
and then records the HedgePosition regardless.

These tests assert the state against what the broker actually did.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def orchestrator(tmp_path):
    """An orchestrator with an isolated state file (the default is shared)."""
    from risk.orchestrator import RiskOrchestrator

    return RiskOrchestrator(state_file=tmp_path / "risk_state.json")


class _Broker:
    """A broker that records orders and can be told to fail."""

    def __init__(self, fail: bool = False, result=None):
        self.fail = fail
        self.result = result if result is not None else {"id": "ORD-1"}
        self.orders: list[dict] = []

    async def place_order(self, **kwargs):
        self.orders.append(kwargs)
        if self.fail:
            raise RuntimeError("venue rejected the order")
        return self.result


# ── The failure path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_failed_hedge_order_does_not_leave_the_system_believing_it_is_hedged(orchestrator):
    orchestrator._broker = _Broker(fail=True)

    await orchestrator.activate_hedge_mode("XAU_USD")

    assert orchestrator._hedge_active is False, (
        "the account is unhedged but the orchestrator reports hedge_active — this is F81"
    )
    assert orchestrator._hedge_positions == [], "a hedge position was recorded for an order that never filled"


@pytest.mark.asyncio
async def test_a_failed_hedge_can_be_retried(orchestrator):
    """`if self._hedge_active: return` latched on the failure, so the retry that
    would have saved the position was never attempted."""
    broker = _Broker(fail=True)
    orchestrator._broker = broker

    await orchestrator.activate_hedge_mode("XAU_USD")
    broker.fail = False
    await orchestrator.activate_hedge_mode("XAU_USD")

    assert len(broker.orders) == 2, "the retry was skipped because the failed attempt latched the flag"
    assert orchestrator._hedge_active is True
    assert len(orchestrator._hedge_positions) == 1


@pytest.mark.asyncio
async def test_no_broker_records_no_hedge(orchestrator):
    orchestrator._broker = None

    await orchestrator.activate_hedge_mode("XAU_USD")

    assert orchestrator._hedge_active is False
    assert orchestrator._hedge_positions == [], "'Manual hedge required' was logged and a hedge recorded anyway"


@pytest.mark.asyncio
async def test_a_broker_returning_no_order_id_is_a_failure(orchestrator):
    """An empty response is not a fill. Recording a HedgePosition with
    `order_id=None` is how an unplaced hedge became a tracked one."""
    orchestrator._broker = _Broker(result={})

    await orchestrator.activate_hedge_mode("XAU_USD")

    assert orchestrator._hedge_active is False
    assert orchestrator._hedge_positions == []


@pytest.mark.asyncio
async def test_the_failure_is_reported_not_only_logged(orchestrator):
    """A hedge that did not open is an operator event."""
    orchestrator._broker = _Broker(fail=True)

    await orchestrator.activate_hedge_mode("XAU_USD")

    kinds = [e.get("event") or e.get("type") or e.get("kind") for e in orchestrator._history]
    assert any(k and "fail" in str(k) for k in kinds), f"no failure event was recorded; history holds {kinds}"


@pytest.mark.asyncio
async def test_the_persisted_state_does_not_claim_a_hedge_that_failed(orchestrator, tmp_path):
    """The state file is read on the next boot to decide which hedges are
    already open. A false entry there survives the restart."""
    import json

    orchestrator._broker = _Broker(fail=True)
    await orchestrator.activate_hedge_mode("XAU_USD")

    state_file = tmp_path / "risk_state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        assert state.get("hedge_active") is not True
        assert state.get("hedge_positions") == []


# ── The success path must still work ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_placed_hedge_is_recorded(orchestrator):
    broker = _Broker(result={"id": "ORD-42"})
    orchestrator._broker = broker

    await orchestrator.activate_hedge_mode("XAU_USD")

    assert orchestrator._hedge_active is True
    assert len(orchestrator._hedge_positions) == 1
    assert orchestrator._hedge_positions[0].order_id == "ORD-42"
    assert orchestrator._hedge_positions[0].direction == "short"
    assert broker.orders[0]["units"] == -orchestrator._hedge_units, "the hedge must be a short"


@pytest.mark.asyncio
async def test_an_already_open_hedge_is_not_duplicated(orchestrator):
    broker = _Broker()
    orchestrator._broker = broker

    await orchestrator.activate_hedge_mode("XAU_USD")
    await orchestrator.activate_hedge_mode("XAU_USD")

    assert len(broker.orders) == 1, "a second activation opened a second hedge"


@pytest.mark.asyncio
async def test_activate_reports_whether_the_hedge_is_open(orchestrator):
    orchestrator._broker = _Broker(fail=True)
    assert await orchestrator.activate_hedge_mode("XAU_USD") is False

    orchestrator._broker = _Broker()
    assert await orchestrator.activate_hedge_mode("XAU_USD") is True


# ── The endpoint must not report ok for a hedge that failed ──────────────────


@pytest.mark.asyncio
async def test_the_endpoint_does_not_report_ok_for_a_failed_hedge(orchestrator, monkeypatch):
    from api import nuclear

    orchestrator._broker = _Broker(fail=True)
    monkeypatch.setattr(nuclear, "_get_orchestrator", lambda: orchestrator)

    class _Req:
        symbol = "XAU_USD"

    response = await nuclear.activate_hedge(_Req(), _user=None)

    assert response["hedge_active"] is False
    assert response["status"] != "ok", f"the endpoint reported {response['status']!r} for a hedge that never opened"


# ── The mirror defect: a hedge that could not be closed must stay tracked ─────


@pytest.mark.asyncio
async def test_a_hedge_that_could_not_be_closed_is_not_forgotten(orchestrator):
    """`deactivate_hedge_mode` cleared `_hedge_positions` unconditionally, so a
    rejected close dropped the position from tracking while the short stayed
    open at the venue: a live, unhedged, *untracked* short. This is worse than
    F81 — there, you believe you are hedged when you are not; here, nothing in
    the system knows a real position exists."""
    broker = _Broker()
    orchestrator._broker = broker
    await orchestrator.activate_hedge_mode("XAU_USD")

    broker.fail = True
    closed = await orchestrator.deactivate_hedge_mode()

    assert closed is False
    assert len(orchestrator._hedge_positions) == 1, "the open short was dropped from tracking"
    assert orchestrator._hedge_active is True, "hedge mode was cleared while a hedge was still open"


@pytest.mark.asyncio
async def test_a_failed_close_can_be_retried(orchestrator):
    broker = _Broker()
    orchestrator._broker = broker
    await orchestrator.activate_hedge_mode("XAU_USD")

    broker.fail = True
    await orchestrator.deactivate_hedge_mode()
    broker.fail = False
    assert await orchestrator.deactivate_hedge_mode() is True
    assert orchestrator._hedge_positions == []
    assert orchestrator._hedge_active is False


@pytest.mark.asyncio
async def test_closing_with_no_broker_keeps_the_position(orchestrator):
    orchestrator._broker = _Broker()
    await orchestrator.activate_hedge_mode("XAU_USD")

    orchestrator._broker = None
    assert await orchestrator.deactivate_hedge_mode() is False
    assert len(orchestrator._hedge_positions) == 1
