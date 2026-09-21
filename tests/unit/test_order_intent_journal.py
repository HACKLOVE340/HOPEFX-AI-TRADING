# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_order_intent_journal.py
=======================================
Round 3 audit, Slice 7 (docs/HARDENING_BACKLOG.md S7-02, S7-05).

``TradeExecutor`` awaited ``broker.place_market_order(...)`` and recorded the
position ~36 lines later via ``position_tracker.add_position(...)``. Between
those two awaits the process can die — SIGKILL, OOM, pod eviction, deploy.

If it does, the broker holds a filled position that **nothing local ever knew
about**: no record was written before submission, and no client order id linked
the fill back to a local intent (S7-05). On restart ``restore_from_redis``
replays Redis, which has no trace of it. The position is invisible to SL/TP, to
risk exposure and to the dashboard, and stays open until a human reads the
broker statement.

The fix is a write-ahead intent journal: record the intent *before* the broker
call, clear it only after the position is tracked. Any intent still present at
boot is an order that may have filled while the process was down — a
reconciliation candidate, which is exactly what S7-03's broker diff consumes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeStore:
    """Minimal stand-in for execution.redis_state.AsyncRedisStateStore."""

    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.save_calls: list[dict] = []
        self.removed: list[str] = []

    async def save_order(self, order: dict) -> None:
        oid = str(order.get("id") or order.get("order_id"))
        self.orders[oid] = order
        self.save_calls.append(order)

    async def remove_order(self, order_id: str) -> None:
        self.orders.pop(str(order_id), None)
        self.removed.append(str(order_id))

    async def load_orders(self) -> list[dict]:
        return list(self.orders.values())


def _passing_risk_manager():
    """A risk manager whose every pre-trade check passes.

    Deliberately *not* a bare ``MagicMock``: `risk/pre_trade_gate.py` reads a
    dozen numeric attributes off the risk manager, and an auto-created Mock
    attribute is truthy and un-comparable, so it either trips a gate or raises
    ``TypeError`` inside one. Spelling the healthy values out keeps the fixture
    honest about what "all gates pass" means.
    """
    config = MagicMock()
    config.daily_loss_limit_pct = 0.05
    config.max_drawdown_pct = 0.10
    config.max_open_positions = 3
    config.max_position_size_pct = 0.05

    ks = MagicMock()
    ks.is_active = MagicMock(return_value=False)

    rm = MagicMock()
    rm.config = config
    rm._kill_switch = ks
    rm._trading_halted = False
    rm._halt_reason = ""
    rm._halt_until = None
    rm._streak_halted = False
    rm._streak_loss_count = 0
    rm._returns_history = []
    rm.current_drawdown = 0.0
    rm.daily_pnl = 0.0
    rm.daily_starting_equity = 100_000.0
    rm.open_positions = {}
    # RiskManager.validate_trade is sync (risk/manager.py:2199) and the gate
    # calls it without await — an AsyncMock here fails to unpack.
    rm.validate_trade = MagicMock(return_value=(True, "ok"))
    rm.notify_position_opened = MagicMock()
    rm.notify_position_closed = MagicMock()
    rm.get_account_equity = AsyncMock(return_value=100_000.0)
    rm.get_current_drawdown = MagicMock(return_value=0.0)
    rm.check_cvar_pre_trade = MagicMock(return_value=(True, "ok"))
    return rm


def _make_executor(store=None, *, fill_status="filled"):
    from execution.trade_executor import TradeExecutor

    order = MagicMock()
    order.id = "broker-order-1"
    order.status = MagicMock(value=fill_status)
    order.filled_quantity = 1.0
    order.average_fill_price = 2350.0
    order.commission = 2.0

    broker = MagicMock()
    broker.place_market_order = AsyncMock(return_value=order)

    rm = _passing_risk_manager()

    pt = MagicMock()
    pt.add_position = AsyncMock()
    pt.get_position = MagicMock(return_value=None)
    pt.get_all_positions = MagicMock(return_value={})
    pt.open_position_count = MagicMock(return_value=0)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("infrastructure.metrics.get_metrics_registry", MagicMock(return_value=MagicMock()))
        ex = TradeExecutor(broker, rm, pt, state_store=store)
    return ex, broker, pt


def _signal():
    return {
        "symbol": "XAUUSD",
        "action": "buy",
        "size": 1.0,
        "risk_approval_token": "tok-issued-by-risk-manager",
        "stop_loss": 2300.0,
        "take_profit": 2400.0,
    }


# ── S7-05: the fill must be correlatable back to a local intent ───────────────


@pytest.mark.asyncio
async def test_broker_call_carries_a_client_order_id():
    """Without one, a broker fill cannot be matched to a local order."""
    ex, broker, _ = _make_executor(_FakeStore())
    await ex.execute_signal(_signal())

    kwargs = broker.place_market_order.await_args.kwargs
    assert kwargs.get("client_order_id"), (
        "place_market_order was called with no client_order_id — a fill found at "
        "the broker after a crash cannot be correlated back to a local intent "
        "(S7-05)"
    )


@pytest.mark.asyncio
async def test_client_order_id_is_unique_per_order():
    ex, broker, _ = _make_executor(_FakeStore())
    await ex.execute_signal(_signal())
    await ex.execute_signal(_signal())

    ids = [c.kwargs.get("client_order_id") for c in broker.place_market_order.await_args_list]
    assert len(set(ids)) == 2, f"client_order_id was reused across orders: {ids}"


# ── S7-02: the write-ahead intent ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intent_is_journalled_before_the_broker_is_called():
    """The record must exist *before* submission, or the crash window is open."""
    store = _FakeStore()
    ex, broker, _ = _make_executor(store)

    saved_before_call: list[bool] = []

    original = broker.place_market_order

    async def _spy(**kwargs):
        # At the moment the broker is called, the intent must already be down.
        saved_before_call.append(bool(store.orders))
        return await original(**kwargs)

    broker.place_market_order = AsyncMock(side_effect=_spy)
    await ex.execute_signal(_signal())

    assert saved_before_call and saved_before_call[0], (
        "the intent was not journalled before place_market_order — a crash "
        "between submission and add_position leaves an untracked live position "
        "(S7-02)"
    )


@pytest.mark.asyncio
async def test_intent_records_what_reconciliation_needs():
    store = _FakeStore()
    ex, _, _ = _make_executor(store)
    await ex.execute_signal(_signal())

    assert store.save_calls, "nothing was journalled"
    intent = store.save_calls[0]
    assert intent.get("symbol") == "XAUUSD"
    assert intent.get("quantity") == pytest.approx(1.0)
    assert str(intent.get("side", "")).lower() in ("buy", "long")
    assert intent.get("status") == "intent"


@pytest.mark.asyncio
async def test_intent_is_cleared_once_the_position_is_tracked():
    """A completed order must not look like an orphan at the next boot."""
    store = _FakeStore()
    ex, _, pt = _make_executor(store)
    await ex.execute_signal(_signal())

    pt.add_position.assert_awaited_once()
    assert store.orders == {}, (
        f"intent left behind after the position was tracked: {store.orders} — "
        f"every clean restart would flag it as an unreconciled fill"
    )


@pytest.mark.asyncio
async def test_intent_survives_when_the_position_is_never_tracked():
    """The whole point: if add_position never runs, the intent must remain."""
    store = _FakeStore()
    ex, _, pt = _make_executor(store)
    # Stand-in for the process dying between the broker ack and add_position.
    pt.add_position = AsyncMock(side_effect=RuntimeError("process died here"))

    # execute_signal catches RuntimeError and reports it rather than raising.
    result = await ex.execute_signal(_signal())
    assert not result.success

    assert store.orders, (
        "the intent was cleared even though the position was never tracked — "
        "boot reconciliation would have nothing to find"
    )
    intent = next(iter(store.orders.values()))
    assert intent["status"] == "intent"
    assert intent["symbol"] == "XAUUSD"


@pytest.mark.asyncio
async def test_a_missing_state_store_does_not_break_execution():
    """Paper/dev runs have no Redis; trading must still work (loudly)."""
    ex, broker, pt = _make_executor(None)
    result = await ex.execute_signal(_signal())

    assert result.success
    pt.add_position.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failing_journal_does_not_lose_an_executed_order():
    """Redis being down must not make us disown a position the broker filled."""
    store = _FakeStore()
    store.remove_order = AsyncMock(side_effect=OSError("redis down"))
    ex, _, pt = _make_executor(store)

    result = await ex.execute_signal(_signal())

    assert result.success
    pt.add_position.assert_awaited_once()


# ── the journal must be read, not just written ────────────────────────────────


@pytest.mark.asyncio
async def test_orphaned_intents_are_surfaced_at_boot(caplog):
    """A write-ahead record nothing reads is not a recovery mechanism.

    This is the other half of S7-02: an intent left behind means the process
    died after submitting an order. Boot has to say so, loudly, or the record
    is state nothing consumes — the exact defect class this audit keeps finding.
    """
    import logging

    from execution.position_manager import PositionManager

    store = _FakeStore()
    await store.save_order(
        {
            "id": "hopefx-abc123",
            "client_order_id": "hopefx-abc123",
            "symbol": "XAUUSD",
            "side": "buy",
            "quantity": 1.0,
            "status": "intent",
        }
    )

    pm = PositionManager()
    pm._redis_store = store

    with caplog.at_level(logging.CRITICAL, logger="execution.position_manager"):
        orphans = await pm.audit_order_intents(restored={})

    assert len(orphans) == 1
    assert orphans[0]["client_order_id"] == "hopefx-abc123"
    assert any("UNRECONCILED ORDER INTENT" in r.message for r in caplog.records), (
        "an unfinished order intent was not reported at boot"
    )


@pytest.mark.asyncio
async def test_completed_orders_are_not_reported_as_orphans():
    """Guards against alert fatigue — a cleared intent must stay silent."""
    from execution.position_manager import PositionManager

    pm = PositionManager()
    pm._redis_store = _FakeStore()  # nothing journalled

    assert await pm.audit_order_intents(restored={}) == []


# ── the journal must not depend on startup ordering ───────────────────────────


@pytest.mark.asyncio
async def test_store_is_resolved_lazily_when_not_injected():
    """Ordering must not silently disable the journal.

    `init_trade_executor` reads the PositionManager's Redis store, but
    `trade_executor` cannot declare `position_manager` as a dependency: the
    registry is a topological sort in which a *failed* dependency causes the
    dependent to be **skipped**, so a Redis outage would stop trading entirely
    rather than merely stop journalling. Ordering is therefore not guaranteed,
    and an executor built before the position manager must still pick the store
    up later instead of journalling nothing forever.
    """
    from unittest.mock import patch

    store = _FakeStore()
    ex, _, _ = _make_executor(None)  # constructed with no store, as if built first
    assert ex.state_store is None

    pm = MagicMock()
    pm._redis_store = store
    with patch.dict("sys.modules", {"execution.position_manager": MagicMock(position_manager=pm)}):
        await ex.execute_signal(_signal())

    assert store.save_calls, (
        "the executor never picked up the store that became available after "
        "construction — the journal is silently dependent on startup ordering"
    )


@pytest.mark.asyncio
async def test_lazy_resolution_failure_is_not_fatal():
    """If no store can be found, trade anyway (loudly) — never block on it."""
    from unittest.mock import patch

    ex, _, pt = _make_executor(None)
    broken = MagicMock()
    type(broken)._redis_store = property(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

    with patch.dict("sys.modules", {"execution.position_manager": MagicMock(position_manager=broken)}):
        result = await ex.execute_signal(_signal())

    assert result.success
    pt.add_position.assert_awaited_once()
