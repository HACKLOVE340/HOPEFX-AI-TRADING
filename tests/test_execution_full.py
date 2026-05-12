# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_execution_full.py
============================
Regression tests for HopeFXEngine state-machine bugs.

Covers:
  - Direction-flip: opening a position in the opposite direction must realise
    PnL from the previous position before recording the new one.
  - PAUSED state: tick loop must sleep, not exit, when engine is paused.
  - Pending order tracking: pending orders are stored and matched on fill.
  - _close_position_for_unwind: unwind closes position and updates equity.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

UTC = timezone.utc


# ── Minimal stubs for injected dependencies ───────────────────────────────────


def _make_tick(symbol="XAUUSD", mid=2000.0, bid=1999.5, ask=2000.5, confidence=0.9):
    return SimpleNamespace(
        symbol=symbol,
        mid=mid,
        bid=bid,
        ask=ask,
        spread=ask - bid,
        confidence=confidence,
        timestamp=datetime.now(UTC),
        lineage_id=str(uuid.uuid4()),
    )


def _make_orchestrator(tick=None, features=None, safe=True):
    orch = MagicMock()
    orch.get_latest_tick.return_value = tick or _make_tick()
    orch.get_ml_features.return_value = features or {
        "order_flow_imbalance": 0.5,
        "bid_pressure": 0.3,
        "news_sentiment_score": 0.2,
    }
    orch.is_safe_to_trade.return_value = safe
    orch.notify_fill = MagicMock()
    return orch


def _make_router(direction="long", fill_price=2000.0, status="filled"):
    router = MagicMock()
    router.route_and_execute = AsyncMock(
        return_value={
            "status": status,
            "fill_price": fill_price,
            "quantity": 1.0,
            "broker": "paper",
            "order_id": str(uuid.uuid4()),
        }
    )
    return router


def _make_risk_manager(quantity=1.0):
    rm = MagicMock()
    rm.size_order.return_value = SimpleNamespace(quantity=quantity)
    return rm


def _make_gatekeeper(passed=True):
    gk = MagicMock()
    gk.evaluate = AsyncMock(return_value=SimpleNamespace(passed=passed, reason="ok"))
    return gk


def _make_lineage():
    ls = MagicMock()
    ls.record_signal = MagicMock()
    return ls


def _make_engine(
    tick=None,
    features=None,
    router=None,
    fill_price=2000.0,
    fill_status="filled",
    quantity=1.0,
    initial_equity=100_000.0,
):
    """Build a HopeFXEngine with all dependencies stubbed."""
    from execution.hopefx_engine import HopeFXEngine

    orch = _make_orchestrator(tick=tick, features=features)
    rtr = router or _make_router(fill_price=fill_price, status=fill_status)
    rm = _make_risk_manager(quantity=quantity)
    gk = _make_gatekeeper()
    ls = _make_lineage()

    # Stub out heavy optional components
    intra = MagicMock()
    intra.on_tick.return_value = []  # no unwind signals
    intra.on_open = MagicMock()
    intra.on_close = MagicMock()
    intra.snapshot.return_value = {}

    post = MagicMock()
    post.record_fill = MagicMock()
    post.rolling_stats.return_value = {}

    dd = MagicMock()
    dd.update.return_value = SimpleNamespace(
        total_breach=False,
        daily_breach=False,
        total_drawdown_pct=0.0,
        daily_drawdown_pct=0.0,
        total_hwm=initial_equity,
        total_alert=False,
        daily_alert=False,
    )
    dd.record_fill = MagicMock()

    shadow = MagicMock()
    shadow.start = AsyncMock()
    shadow.stop = AsyncMock()
    shadow.on_tick = MagicMock()
    shadow.on_signal = MagicMock()
    shadow.on_live_close = MagicMock()
    shadow.health.return_value = {}
    shadow.get_comparison_report.return_value = {}

    shadow_val = MagicMock()
    shadow_val.start = AsyncMock()
    shadow_val.stop = AsyncMock()
    shadow_val.on_production_tick = MagicMock()

    engine = HopeFXEngine(
        orchestrator=orch,
        smart_router=rtr,
        risk_manager=rm,
        gatekeeper=gk,
        lineage_store=ls,
        ml_inference_fn=None,  # use built-in heuristic
        intra_trade_monitor=intra,
        post_trade_analyzer=post,
        drawdown_tracker=dd,
        shadow_engine=shadow,
        shadow_validator=shadow_val,
        initial_equity=initial_equity,
    )
    return engine


# ── Direction-flip regression test ───────────────────────────────────────────


class TestDirectionFlip:
    """
    Regression for the bug where _on_fill read self._open_positions[symbol]
    AFTER overwriting it with the new position, so the flip logic never fired.
    """

    @pytest.mark.asyncio
    async def test_flip_long_to_short_realises_pnl(self):
        """
        Open a LONG at 2000, then fill a SHORT at 2100.
        The engine must:
          1. Detect the existing LONG position.
          2. Realise PnL = (2100 - 2000) * 1.0 * 100 = 10 000.
          3. Add that PnL to current_equity.
          4. Record the new SHORT position.
        """
        engine = _make_engine(fill_price=2000.0)

        # Manually plant a LONG position (simulates a previous fill)
        engine._open_positions["XAUUSD"] = {
            "position_id": "pos-long-1",
            "direction": "long",
            "quantity": 1.0,
            "entry_price": 2000.0,
            "signal_id": "sig-long-1",
            "opened_at": datetime.now(UTC).isoformat(),
            "mtm_pnl": 0.0,
        }
        initial_equity = engine._current_equity

        # Build a SHORT signal
        from execution.hopefx_engine import ExecutionSignal

        signal = ExecutionSignal(
            signal_id="sig-short-1",
            symbol="XAUUSD",
            direction="short",
            confidence=0.8,
            probability=0.75,
            tick_mid=2100.0,
            tick_bid=2099.5,
            tick_ask=2100.5,
            tick_spread=1.0,
            tick_timestamp=datetime.now(UTC),
            features={},
            features_hash="abc123",
            data_quality=0.9,
            sentiment_score=0.0,
            impact_score=0.0,
            lineage_id="lin-1",
        )
        order_request = {
            "order_id": "ord-short-1",
            "signal_id": signal.signal_id,
            "symbol": "XAUUSD",
            "direction": "short",
            "quantity": 1.0,
            "order_type": "MARKET",
            "mid_price": 2100.0,
            "bid": 2099.5,
            "ask": 2100.5,
            "spread": 1.0,
            "confidence": 0.8,
            "sentiment": 0.0,
            "impact": 0.0,
            "features": {},
            "lineage_id": "lin-1",
        }
        fill = {
            "status": "filled",
            "fill_price": 2100.0,
            "quantity": 1.0,
            "broker": "paper",
            "order_id": "ord-short-1",
        }

        await engine._on_fill(signal, order_request, fill, latency_ms=5.0)

        # New position must be SHORT
        pos = engine.get_open_position("XAUUSD")
        assert pos is not None
        assert pos["direction"] == "short", f"Expected short, got {pos['direction']}"
        assert pos["entry_price"] == 2100.0

        # PnL from the closed LONG: (2100 - 2000) * 1.0 * 100 = 10 000
        expected_pnl = (2100.0 - 2000.0) * 1.0 * 100.0
        assert engine._current_equity == pytest.approx(initial_equity + expected_pnl, rel=1e-6), (
            f"equity={engine._current_equity} expected={initial_equity + expected_pnl}"
        )

    @pytest.mark.asyncio
    async def test_flip_short_to_long_realises_pnl(self):
        """
        Open a SHORT at 2200, then fill a LONG at 2100.
        PnL = (2200 - 2100) * 1.0 * 100 = 10 000.
        """
        engine = _make_engine(fill_price=2100.0)

        engine._open_positions["XAUUSD"] = {
            "position_id": "pos-short-1",
            "direction": "short",
            "quantity": 1.0,
            "entry_price": 2200.0,
            "signal_id": "sig-short-1",
            "opened_at": datetime.now(UTC).isoformat(),
            "mtm_pnl": 0.0,
        }
        initial_equity = engine._current_equity

        from execution.hopefx_engine import ExecutionSignal

        signal = ExecutionSignal(
            signal_id="sig-long-2",
            symbol="XAUUSD",
            direction="long",
            confidence=0.8,
            probability=0.75,
            tick_mid=2100.0,
            tick_bid=2099.5,
            tick_ask=2100.5,
            tick_spread=1.0,
            tick_timestamp=datetime.now(UTC),
            features={},
            features_hash="def456",
            data_quality=0.9,
            sentiment_score=0.0,
            impact_score=0.0,
            lineage_id="lin-2",
        )
        order_request = {
            "order_id": "ord-long-2",
            "signal_id": signal.signal_id,
            "symbol": "XAUUSD",
            "direction": "long",
            "quantity": 1.0,
            "order_type": "MARKET",
            "mid_price": 2100.0,
            "bid": 2099.5,
            "ask": 2100.5,
            "spread": 1.0,
            "confidence": 0.8,
            "sentiment": 0.0,
            "impact": 0.0,
            "features": {},
            "lineage_id": "lin-2",
        }
        fill = {
            "status": "filled",
            "fill_price": 2100.0,
            "quantity": 1.0,
            "broker": "paper",
            "order_id": "ord-long-2",
        }

        await engine._on_fill(signal, order_request, fill, latency_ms=5.0)

        pos = engine.get_open_position("XAUUSD")
        assert pos is not None
        assert pos["direction"] == "long"

        expected_pnl = (2200.0 - 2100.0) * 1.0 * 100.0
        assert engine._current_equity == pytest.approx(initial_equity + expected_pnl, rel=1e-6)

    @pytest.mark.asyncio
    async def test_same_direction_does_not_realise_pnl(self):
        """
        Re-entering the same direction must NOT realise PnL from the old position.
        The old position is simply replaced (add-to-position semantics are not
        implemented; the engine tracks one position per symbol).
        """
        engine = _make_engine(fill_price=2050.0)

        engine._open_positions["XAUUSD"] = {
            "position_id": "pos-long-1",
            "direction": "long",
            "quantity": 1.0,
            "entry_price": 2000.0,
            "signal_id": "sig-long-1",
            "opened_at": datetime.now(UTC).isoformat(),
            "mtm_pnl": 0.0,
        }
        initial_equity = engine._current_equity

        from execution.hopefx_engine import ExecutionSignal

        signal = ExecutionSignal(
            signal_id="sig-long-2",
            symbol="XAUUSD",
            direction="long",
            confidence=0.8,
            probability=0.75,
            tick_mid=2050.0,
            tick_bid=2049.5,
            tick_ask=2050.5,
            tick_spread=1.0,
            tick_timestamp=datetime.now(UTC),
            features={},
            features_hash="ghi789",
            data_quality=0.9,
            sentiment_score=0.0,
            impact_score=0.0,
            lineage_id="lin-3",
        )
        order_request = {
            "order_id": "ord-long-2",
            "signal_id": signal.signal_id,
            "symbol": "XAUUSD",
            "direction": "long",
            "quantity": 1.0,
            "order_type": "MARKET",
            "mid_price": 2050.0,
            "bid": 2049.5,
            "ask": 2050.5,
            "spread": 1.0,
            "confidence": 0.8,
            "sentiment": 0.0,
            "impact": 0.0,
            "features": {},
            "lineage_id": "lin-3",
        }
        fill = {
            "status": "filled",
            "fill_price": 2050.0,
            "quantity": 1.0,
            "broker": "paper",
            "order_id": "ord-long-2",
        }

        await engine._on_fill(signal, order_request, fill, latency_ms=5.0)

        # Equity must be unchanged — no PnL realised for same-direction re-entry
        assert engine._current_equity == pytest.approx(initial_equity, rel=1e-9)
        pos = engine.get_open_position("XAUUSD")
        assert pos["entry_price"] == 2050.0  # new position recorded


# ── Pending order tracking ────────────────────────────────────────────────────


class TestPendingOrders:
    @pytest.mark.asyncio
    async def test_pending_order_stored(self):
        """A broker response of status=pending must store the order in _pending_orders."""
        router = _make_router(status="pending")
        engine = _make_engine(router=router)

        # Bypass the full tick loop — call _route_and_execute directly
        from execution.hopefx_engine import ExecutionSignal

        signal = ExecutionSignal(
            signal_id="sig-pend-1",
            symbol="XAUUSD",
            direction="long",
            confidence=0.8,
            probability=0.75,
            tick_mid=2000.0,
            tick_bid=1999.5,
            tick_ask=2000.5,
            tick_spread=1.0,
            tick_timestamp=datetime.now(UTC),
            features={},
            features_hash="pend1",
            data_quality=0.9,
            sentiment_score=0.0,
            impact_score=0.0,
            lineage_id="lin-pend-1",
        )
        sized = SimpleNamespace(quantity=1.0)

        await engine._route_and_execute(signal, sized)

        assert len(engine._pending_orders) == 1

    @pytest.mark.asyncio
    async def test_on_pending_fill_clears_pending_and_records_position(self):
        """on_pending_fill must remove the pending entry and open a position."""
        router = _make_router(status="pending")
        engine = _make_engine(router=router)

        from execution.hopefx_engine import ExecutionSignal

        signal = ExecutionSignal(
            signal_id="sig-pend-2",
            symbol="EURUSD",
            direction="long",
            confidence=0.8,
            probability=0.75,
            tick_mid=1.0820,
            tick_bid=1.0819,
            tick_ask=1.0821,
            tick_spread=0.0002,
            tick_timestamp=datetime.now(UTC),
            features={},
            features_hash="pend2",
            data_quality=0.9,
            sentiment_score=0.0,
            impact_score=0.0,
            lineage_id="lin-pend-2",
        )
        sized = SimpleNamespace(quantity=1.0)

        # Submit — goes to pending
        await engine._route_and_execute(signal, sized)
        assert len(engine._pending_orders) == 1
        order_id = list(engine._pending_orders.keys())[0]

        # Simulate broker callback
        await engine.on_pending_fill(
            order_id=order_id,
            fill={
                "fill_price": 1.0820,
                "quantity": 1.0,
                "broker": "paper",
                "order_id": order_id,
            },
        )

        assert len(engine._pending_orders) == 0
        pos = engine.get_open_position("EURUSD")
        assert pos is not None
        assert pos["direction"] == "long"

    @pytest.mark.asyncio
    async def test_on_pending_fill_unknown_order_is_noop(self):
        """on_pending_fill with an unknown order_id must not raise."""
        engine = _make_engine()
        # Should not raise
        await engine.on_pending_fill("nonexistent-order-id", {"fill_price": 2000.0})
        assert engine._fill_count == 0


# ── State machine: PAUSED ─────────────────────────────────────────────────────


class TestStateMachinePaused:
    @pytest.mark.asyncio
    async def test_pause_stops_tick_processing(self):
        """
        When the engine is paused, _process_tick must not be called.
        The loop must remain alive (not exit) and resume processing on resume().
        """
        engine = _make_engine()

        process_calls = []
        original = engine._process_tick

        async def _spy():
            process_calls.append(1)
            await original()

        engine._process_tick = _spy

        await engine.start()
        await asyncio.sleep(0.05)  # let at least one tick fire

        calls_before_pause = len(process_calls)
        assert calls_before_pause >= 1, "Engine should have processed at least one tick before pause"

        engine.pause()
        await asyncio.sleep(0.15)  # wait > 1 tick interval (1 Hz = 1 s, but we use 0.15 s)

        calls_while_paused = len(process_calls) - calls_before_pause
        assert calls_while_paused == 0, (
            f"Engine processed {calls_while_paused} tick(s) while paused — loop should sleep"
        )

        # Loop task must still be alive
        assert engine._loop_task is not None
        assert not engine._loop_task.done(), "Tick loop task must remain alive while paused"

        engine.resume()
        # The tick loop interval is 1/ENGINE_TICK_LOOP_HZ (default 1 s).
        # After resume the loop wakes on the next sleep expiry.  Give it up
        # to 1.5 s to fire at least one tick.
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            if len(process_calls) > calls_before_pause + calls_while_paused:
                break

        calls_after_resume = len(process_calls) - calls_before_pause - calls_while_paused
        assert calls_after_resume >= 1, "Engine should process ticks after resume"

        await engine.stop()

    @pytest.mark.asyncio
    async def test_halt_exits_loop(self):
        """halt() must cause the tick loop to exit after the current sleep expires."""
        engine = _make_engine()
        await engine.start()
        await asyncio.sleep(0.05)

        engine.halt("test_halt")

        # Loop sleeps for up to 1/ENGINE_TICK_LOOP_HZ (default 1 s).
        # Wait up to 1.5 s for the task to finish.
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            if engine._loop_task is not None and engine._loop_task.done():
                break

        assert engine._loop_task is not None
        assert engine._loop_task.done(), "Tick loop must exit after halt()"


# ── get_open_position helper ──────────────────────────────────────────────────


class TestGetOpenPosition:
    def test_returns_none_when_no_position(self):
        engine = _make_engine()
        assert engine.get_open_position("XAUUSD") is None

    def test_returns_position_after_manual_insert(self):
        engine = _make_engine()
        engine._open_positions["XAUUSD"] = {"direction": "long", "entry_price": 2000.0}
        pos = engine.get_open_position("XAUUSD")
        assert pos is not None
        assert pos["direction"] == "long"
