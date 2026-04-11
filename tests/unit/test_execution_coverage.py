# HOPEFX-AI-TRADING
# Tests for execution/ — throttler, spread_monitor, position_tracker, tca
"""Real unit tests. No mocks/stubs/fake data."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest

UTC = timezone.utc


# ── execution/throttler ───────────────────────────────────────────────────────

class TestMessageThrottler:
    def setup_method(self):
        from execution.throttler import MessageThrottler
        self.throttler = MessageThrottler(
            max_messages_per_second=10,
            max_messages_per_minute=100,
            burst_allowance=2,
            cooldown_seconds=0.1,
        )

    def test_can_send_initially(self):
        assert self.throttler.can_send("order") is True

    def test_cancels_always_allowed(self):
        # FIA 3.4: cancellations must never be throttled
        for _ in range(200):
            assert self.throttler.can_send("cancel") is True

    def test_cancel_all_always_allowed(self):
        for _ in range(50):
            assert self.throttler.can_send("cancel_all") is True

    def test_modify_always_allowed(self):
        assert self.throttler.can_send("modify") is True

    def test_record_message_increments_window(self):
        self.throttler.record_message("order")
        assert len(self.throttler.second_window) == 1

    def test_cancel_not_counted(self):
        self.throttler.record_message("cancel")
        assert len(self.throttler.second_window) == 0

    def test_burst_blocks_after_limit(self):
        # Fill up to max_per_second + burst_allowance
        for _ in range(12):  # 10 + 2 burst
            self.throttler.record_message("order")
        # Next should be blocked
        assert self.throttler.can_send("order") is False

    def test_get_status_keys(self):
        status = self.throttler.get_status()
        assert "level" in status
        assert "messages_per_second" in status
        assert "messages_per_minute" in status
        assert "max_per_second" in status

    def test_throttle_level_normal_initially(self):
        from execution.throttler import ThrottleLevel
        status = self.throttler.get_status()
        assert status["level"] == ThrottleLevel.NORMAL.value

    def test_throttle_level_enum_values(self):
        from execution.throttler import ThrottleLevel
        assert ThrottleLevel.NORMAL.value == "normal"
        assert ThrottleLevel.WARNING.value == "warning"
        assert ThrottleLevel.THROTTLED.value == "throttled"
        assert ThrottleLevel.BLOCKED.value == "blocked"

    def test_throttle_state_dataclass(self):
        from execution.throttler import ThrottleState, ThrottleLevel
        state = ThrottleState(
            messages_in_window=5,
            window_start=time.time(),
            level=ThrottleLevel.NORMAL,
            cooldown_until=None,
        )
        assert state.messages_in_window == 5
        assert state.cooldown_until is None

    def test_minute_window_limit(self):
        throttler = __import__("execution.throttler", fromlist=["MessageThrottler"]).MessageThrottler(
            max_messages_per_second=1000,
            max_messages_per_minute=5,
            burst_allowance=0,
            cooldown_seconds=0.1,
        )
        for _ in range(5):
            throttler.record_message("order")
        assert throttler.can_send("order") is False

    def test_cooldown_state_set(self):
        from execution.throttler import MessageThrottler, ThrottleLevel
        throttler = MessageThrottler(
            max_messages_per_second=2,
            max_messages_per_minute=100,
            burst_allowance=0,
            cooldown_seconds=60.0,  # long cooldown so it stays blocked
        )
        for _ in range(3):
            throttler.record_message("order")
        # Should be blocked and in cooldown
        assert throttler.can_send("order") is False
        assert throttler.state.cooldown_until is not None


# ── execution/spread_monitor ──────────────────────────────────────────────────

class TestSpreadMonitor:
    def setup_method(self):
        from execution.spread_monitor import SpreadMonitor
        self.monitor = SpreadMonitor(
            spike_multiplier=3.0,
            baseline_window=10,
            min_ticks=5,
            abs_limit_usd=5.0,
        )

    def test_on_tick_returns_snapshot(self):
        snap = self.monitor.on_tick("XAUUSD", 1900.0, 1901.0)
        assert snap is not None
        assert snap.symbol == "XAUUSD"

    def test_snapshot_spread_correct(self):
        snap = self.monitor.on_tick("XAUUSD", 1900.0, 1901.0)
        assert snap.current_spread == pytest.approx(1.0)

    def test_tick_count_increments(self):
        for i in range(5):
            snap = self.monitor.on_tick("XAUUSD", 1900.0, 1901.0)
        assert snap.tick_count == 5

    def test_no_spike_on_normal_spread(self):
        for _ in range(10):
            self.monitor.on_tick("XAUUSD", 1900.0, 1901.0)
        assert self.monitor.is_spread_spiking("XAUUSD") is False

    def test_spike_detected_on_wide_spread(self):
        # Build baseline with tight spread
        for _ in range(10):
            self.monitor.on_tick("XAUUSD", 1900.0, 1900.5)
        # Now send a very wide spread
        self.monitor.on_tick("XAUUSD", 1900.0, 1910.0)
        assert self.monitor.is_spread_spiking("XAUUSD") is True

    def test_get_snapshot_returns_latest(self):
        self.monitor.on_tick("XAUUSD", 1900.0, 1901.0)
        snap = self.monitor.get_snapshot("XAUUSD")
        assert snap.symbol == "XAUUSD"
        assert snap.current_spread == pytest.approx(1.0)

    def test_get_all_snapshots(self):
        self.monitor.on_tick("XAUUSD", 1900.0, 1901.0)
        self.monitor.on_tick("EURUSD", 1.0800, 1.0801)
        all_snaps = self.monitor.get_all_snapshots()
        assert "XAUUSD" in all_snaps
        assert "EURUSD" in all_snaps

    def test_multiple_symbols_independent(self):
        for _ in range(10):
            self.monitor.on_tick("XAUUSD", 1900.0, 1900.5)
        for _ in range(10):
            self.monitor.on_tick("EURUSD", 1.0800, 1.0801)
        assert not self.monitor.is_spread_spiking("XAUUSD")
        assert not self.monitor.is_spread_spiking("EURUSD")

    def test_spread_snapshot_namedtuple(self):
        from execution.spread_monitor import SpreadSnapshot
        snap = SpreadSnapshot(
            symbol="XAUUSD",
            current_spread=1.0,
            baseline_spread=0.8,
            ratio=1.25,
            is_spiking=False,
            tick_count=10,
        )
        assert snap.symbol == "XAUUSD"
        assert snap.is_spiking is False

    def test_singleton(self):
        from execution.spread_monitor import get_spread_monitor
        m1 = get_spread_monitor()
        m2 = get_spread_monitor()
        assert m1 is m2

    def test_abs_limit_triggers_spike(self):
        monitor = __import__("execution.spread_monitor", fromlist=["SpreadMonitor"]).SpreadMonitor(
            spike_multiplier=100.0,  # very high multiplier — won't trigger ratio spike
            baseline_window=5,
            min_ticks=3,
            abs_limit_usd=2.0,  # but abs limit is $2
        )
        for _ in range(5):
            monitor.on_tick("XAUUSD", 1900.0, 1900.5)
        # Spread of $10 exceeds abs_limit_usd=2.0
        monitor.on_tick("XAUUSD", 1900.0, 1910.0)
        assert monitor.is_spread_spiking("XAUUSD") is True


# ── execution/position_tracker ────────────────────────────────────────────────

def _make_pos(pid="p1", symbol="XAUUSD", side="buy", qty=1.0, entry=1900.0):
    from execution.position_tracker import Position
    return Position(id=pid, symbol=symbol, side=side,
                    quantity=qty, entry_price=entry, current_price=entry)


class TestPositionTracker:
    def setup_method(self):
        from execution.position_tracker import PositionTracker
        self.tracker = PositionTracker()

    @pytest.mark.asyncio
    async def test_add_position(self):
        result = await self.tracker.add_position(_make_pos())
        assert result is True

    @pytest.mark.asyncio
    async def test_get_position(self):
        await self.tracker.add_position(_make_pos("p1"))
        retrieved = self.tracker.get_position("p1")
        assert retrieved is not None
        assert retrieved.id == "p1"

    def test_get_position_missing_returns_none(self):
        assert self.tracker.get_position("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_all_positions(self):
        await self.tracker.add_position(_make_pos("p1"))
        await self.tracker.add_position(_make_pos("p2", symbol="EURUSD"))
        all_pos = self.tracker.get_all_positions()
        assert len(all_pos) == 2

    @pytest.mark.asyncio
    async def test_get_positions_by_symbol(self):
        await self.tracker.add_position(_make_pos("p1", symbol="XAUUSD"))
        await self.tracker.add_position(_make_pos("p2", symbol="XAUUSD"))
        await self.tracker.add_position(_make_pos("p3", symbol="EURUSD"))
        xau_pos = self.tracker.get_positions_by_symbol("XAUUSD")
        assert len(xau_pos) == 2

    @pytest.mark.asyncio
    async def test_update_position(self):
        await self.tracker.add_position(_make_pos("p1", entry=1900.0))
        result = await self.tracker.update_position("p1", current_price=1910.0)
        assert result is True
        updated = self.tracker.get_position("p1")
        assert updated.current_price == pytest.approx(1910.0)

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_false(self):
        result = await self.tracker.update_position("ghost", current_price=1900.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_close_position(self):
        await self.tracker.add_position(_make_pos("p1", entry=1900.0))
        closed = await self.tracker.close_position("p1", exit_price=1910.0)
        assert closed is not None
        assert self.tracker.get_position("p1") is None

    @pytest.mark.asyncio
    async def test_close_nonexistent_returns_none(self):
        result = await self.tracker.close_position("ghost", exit_price=1900.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_total_pnl(self):
        await self.tracker.add_position(_make_pos("p1", entry=1900.0))
        pnl = self.tracker.get_total_pnl()
        assert isinstance(pnl, dict)

    @pytest.mark.asyncio
    async def test_get_exposure(self):
        await self.tracker.add_position(_make_pos("p1", qty=2.0, entry=1900.0))
        exposure = self.tracker.get_exposure()
        assert isinstance(exposure, dict)

    @pytest.mark.asyncio
    async def test_update_prices(self):
        await self.tracker.add_position(_make_pos("p1", symbol="XAUUSD", entry=1900.0))
        await self.tracker.update_prices("XAUUSD", 1920.0)
        updated = self.tracker.get_position("p1")
        assert updated.current_price == pytest.approx(1920.0)

    @pytest.mark.asyncio
    async def test_add_multiple_positions(self):
        # add_position always succeeds; duplicate IDs overwrite
        pos1 = _make_pos("p1", entry=1900.0)
        pos2 = _make_pos("p1", entry=1910.0)  # same id, different price
        await self.tracker.add_position(pos1)
        await self.tracker.add_position(pos2)
        # Latest entry wins
        p = self.tracker.get_position("p1")
        assert p is not None


# ── execution/tca ─────────────────────────────────────────────────────────────

class TestTCAEngine:
    def setup_method(self):
        from execution.tca import TCAEngine
        self.engine = TCAEngine(window_size=100)

    def _make_fill(self, order_id="ord1", symbol="XAUUSD", side=None,
                   qty="1.0", price="1900.0"):
        from execution.tca import Fill, Side
        from core.types import OrderId, Symbol, Venue
        if side is None:
            side = Side.BUY
        return Fill(
            order_id=OrderId(order_id),
            fill_id="fill1",
            symbol=Symbol(symbol),
            side=side,
            quantity=Decimal(qty),
            price=Decimal(price),
            timestamp=datetime.now(UTC),
            venue=Venue("OANDA"),
        )

    def test_start_order(self):
        from execution.tca import Side, BenchmarkType
        self.engine.start_order(
            order_id="ord1",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1.0"),
            arrival_price=Decimal("1900.0"),
        )
        # No exception = pass

    def test_record_fill(self):
        from execution.tca import Side, BenchmarkType
        self.engine.start_order(
            order_id="ord1", symbol="XAUUSD", side=Side.BUY,
            quantity=Decimal("1.0"), arrival_price=Decimal("1900.0"),
        )
        fill = self._make_fill()
        self.engine.record_fill("ord1", fill)

    def test_complete_order_returns_metrics(self):
        from execution.tca import Side
        self.engine.start_order(
            order_id="ord1", symbol="XAUUSD", side=Side.BUY,
            quantity=Decimal("1.0"), arrival_price=Decimal("1900.0"),
        )
        fill = self._make_fill()
        self.engine.record_fill("ord1", fill)
        metrics = self.engine.complete_order("ord1")
        assert metrics is not None

    def test_get_stats_empty(self):
        stats = self.engine.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats_after_order(self):
        from execution.tca import Side
        self.engine.start_order(
            order_id="ord2", symbol="XAUUSD", side=Side.SELL,
            quantity=Decimal("1.0"), arrival_price=Decimal("1900.0"),
        )
        fill = self._make_fill("ord2", side=__import__("execution.tca", fromlist=["Side"]).Side.SELL,
                               price="1899.0")
        self.engine.record_fill("ord2", fill)
        self.engine.complete_order("ord2")
        stats = self.engine.get_stats()
        assert isinstance(stats, dict)
