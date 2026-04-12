# HOPEFX-AI-TRADING
# Tests for execution/ modules missing coverage:
# broker_circuit_breaker, market_impact, order_algorithms,
# position_tracker, spread_monitor, tca_recorder, throttler
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ===========================================================================
# broker_circuit_breaker
# ===========================================================================

from execution.broker_circuit_breaker import (
    BrokerCircuitBreaker,
    CircuitOpenError,
    CircuitState,
    _classify_error,
)


class TestCircuitBreakerBasic:
    def test_initial_state_closed(self):
        cb = BrokerCircuitBreaker("test", max_failures=3, reset_timeout=60)
        assert cb.state == CircuitState.CLOSED
        assert cb.is_open is False

    @pytest.mark.asyncio
    async def test_success_stays_closed(self):
        cb = BrokerCircuitBreaker("test", max_failures=3, reset_timeout=60)
        result = await cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failures_open_circuit(self):
        cb = BrokerCircuitBreaker("test", max_failures=3, reset_timeout=60, half_open_max=1)

        async def fail():
            raise ConnectionError("down")

        for _ in range(3):
            with pytest.raises(ConnectionError):
                await cb.call(fail)
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_open_raises_circuit_open_error(self):
        cb = BrokerCircuitBreaker("test", max_failures=2, reset_timeout=9999)

        async def fail():
            raise ConnectionError("down")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(fail)
        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(lambda: "ok")
        assert exc_info.value.broker_name == "test"

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        cb = BrokerCircuitBreaker("test", max_failures=2, reset_timeout=0.01, half_open_max=2)

        async def fail():
            raise ConnectionError("down")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(fail)
        await asyncio.sleep(0.02)
        result = await cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cb = BrokerCircuitBreaker("test", max_failures=2, reset_timeout=0.01, half_open_max=2)

        async def fail():
            raise ConnectionError("down")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(fail)
        await asyncio.sleep(0.02)
        with pytest.raises(ConnectionError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_record_success_resets_failure_count(self):
        cb = BrokerCircuitBreaker("test", max_failures=3, reset_timeout=60)
        await cb.record_failure("connection")
        await cb.record_success()
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_status_dict_keys(self):
        cb = BrokerCircuitBreaker("test", max_failures=3, reset_timeout=60)
        s = cb.status()
        for k in ("broker", "state", "failure_count", "total_calls", "config"):
            assert k in s

    @pytest.mark.asyncio
    async def test_async_callable_forwarded(self):
        cb = BrokerCircuitBreaker("test", max_failures=3, reset_timeout=60)

        async def async_fn():
            return 42

        result = await cb.call(async_fn)
        assert result == 42


class TestClassifyError:
    def test_timeout(self):
        assert _classify_error(TimeoutError("timed out")) == "timeout"

    def test_connection(self):
        assert _classify_error(ConnectionError("network unreachable")) == "connection"

    def test_auth(self):
        assert _classify_error(ValueError("unauthorized")) == "auth"

    def test_rejection(self):
        assert _classify_error(RuntimeError("rejected")) == "rejection"

    def test_unknown(self):
        assert _classify_error(RuntimeError("something else")) == "unknown"


# ===========================================================================
# market_impact
# ===========================================================================

from execution.market_impact import (
    AlmgrenChrissModel,
    FillSimulator,
    ImpactEstimate,
    SimulatedFill,
    get_fill_simulator,
)


class TestAlmgrenChrissModel:
    def test_estimate_returns_impact(self):
        model = AlmgrenChrissModel()
        est = model.estimate(order_size=100, adv=10_000, volatility_daily=0.012, spread_bps=3.0, price=2000.0)
        assert isinstance(est, ImpactEstimate)
        assert est.total_impact_bps > 0
        assert est.total_cost_usd > 0

    def test_zero_adv_spread_only(self):
        model = AlmgrenChrissModel()
        est = model.estimate(order_size=100, adv=0, volatility_daily=0.012, spread_bps=3.0, price=2000.0)
        assert est.temporary_impact_bps == 0.0
        assert est.permanent_impact_bps == 0.0
        assert est.spread_cost_bps > 0

    def test_fill_price_buy_higher(self):
        model = AlmgrenChrissModel()
        est = model.estimate(100, 10_000, 0.012, 3.0, 2000.0)
        assert est.fill_price("BUY") > 2000.0

    def test_fill_price_sell_lower(self):
        model = AlmgrenChrissModel()
        est = model.estimate(100, 10_000, 0.012, 3.0, 2000.0)
        assert est.fill_price("SELL") < 2000.0

    def test_participation_capped(self):
        model = AlmgrenChrissModel(max_participation=0.10)
        est = model.estimate(order_size=999_999, adv=1_000, volatility_daily=0.01, spread_bps=3.0, price=2000.0)
        assert est.participation_rate <= 0.10

    def test_slippage_alias(self):
        model = AlmgrenChrissModel()
        est = model.estimate(100, 10_000, 0.012, 3.0, 2000.0)
        assert est.slippage_bps == est.total_impact_bps


class TestFillSimulator:
    def test_full_fill_small_order(self):
        sim = FillSimulator()
        fill = sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=1.0,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=10_000.0,
            adv=100_000.0,
            volatility_daily=0.012,
        )
        assert isinstance(fill, SimulatedFill)
        assert fill.partial_fill is False
        assert fill.fill_quantity == pytest.approx(1.0)

    def test_partial_fill_large_order(self):
        sim = FillSimulator()
        fill = sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=999_999.0,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=100.0,
            adv=1_000.0,
            volatility_daily=0.012,
        )
        assert fill.partial_fill is True
        assert fill.fill_quantity < 999_999.0

    def test_buy_fill_clamped_to_bar_high(self):
        sim = FillSimulator()
        fill = sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=1.0,
            bar_high=2000.5,
            bar_low=1999.0,
            bar_volume=10_000.0,
            adv=100_000.0,
            volatility_daily=0.012,
        )
        assert fill.fill_price <= 2000.5

    def test_sell_fill_clamped_to_bar_low(self):
        sim = FillSimulator()
        fill = sim.simulate_fill(
            signal_price=2000.0,
            side="SELL",
            quantity=1.0,
            bar_high=2001.0,
            bar_low=1999.5,
            bar_volume=10_000.0,
            adv=100_000.0,
            volatility_daily=0.012,
        )
        assert fill.fill_price >= 1999.5

    def test_batch_simulate(self):
        sim = FillSimulator()
        signals = [
            {
                "signal_price": 2000.0,
                "side": "BUY",
                "quantity": 1.0,
                "bar_high": 2005.0,
                "bar_low": 1995.0,
                "bar_volume": 10_000.0,
            },
            {
                "signal_price": 2001.0,
                "side": "SELL",
                "quantity": 1.0,
                "bar_high": 2006.0,
                "bar_low": 1996.0,
                "bar_volume": 10_000.0,
            },
        ]
        fills = sim.simulate_fills_batch(signals, adv=100_000.0, volatility_daily=0.012)
        assert len(fills) == 2

    def test_singleton(self):
        s1 = get_fill_simulator()
        s2 = get_fill_simulator()
        assert s1 is s2


# ===========================================================================
# order_algorithms
# ===========================================================================

from execution.order_algorithms import (
    PartialFillAggregator,
    TWAPExecutor,
    VWAPExecutor,
)


class TestPartialFillAggregator:
    def test_register_and_record(self):
        agg = PartialFillAggregator()
        agg.register("p1", "XAUUSD", "BUY", target_lots=0.01)
        state = agg.record_fill("p1", lots=0.005, price=2000.0)
        assert state is not None
        assert state.filled_lots == pytest.approx(0.005)

    def test_complete_fires_callback(self):
        fired = []
        agg = PartialFillAggregator()
        agg.on_complete(lambda s: fired.append(s))
        agg.register("p1", "XAUUSD", "BUY", target_lots=0.01)
        agg.record_fill("p1", lots=0.005, price=2000.0)
        agg.record_fill("p1", lots=0.005, price=2001.0)
        assert len(fired) == 1
        assert fired[0].is_complete

    def test_unknown_parent_returns_none(self):
        agg = PartialFillAggregator()
        result = agg.record_fill("nonexistent", lots=0.01, price=2000.0)
        assert result is None

    def test_pending_count(self):
        agg = PartialFillAggregator()
        agg.register("p1", "XAUUSD", "BUY", 0.01)
        agg.register("p2", "XAUUSD", "SELL", 0.01)
        assert agg.pending_count() == 2

    def test_avg_price_weighted(self):
        agg = PartialFillAggregator()
        agg.register("p1", "XAUUSD", "BUY", 0.02)
        agg.record_fill("p1", lots=0.01, price=2000.0)
        state = agg.record_fill("p1", lots=0.01, price=2002.0)
        assert state.avg_price == pytest.approx(2001.0)

    def test_fill_pct(self):
        agg = PartialFillAggregator()
        agg.register("p1", "XAUUSD", "BUY", 0.02)
        state = agg.record_fill("p1", lots=0.01, price=2000.0)
        assert state.fill_pct == pytest.approx(0.5)


class TestTWAPExecutor:
    @pytest.mark.asyncio
    async def test_no_router_returns_pending(self):
        exec_ = TWAPExecutor(router=None)
        result = await exec_.execute(
            parent_id="t1",
            symbol="XAUUSD",
            side="long",
            total_lots=0.01,
            duration_s=0.01,
            slices=2,
        )
        assert result["algo"] == "twap"
        assert result["target_lots"] == pytest.approx(0.01)

    @pytest.mark.asyncio
    async def test_with_router_filled(self):
        router = MagicMock()
        router.route = AsyncMock(return_value={"status": "filled", "fill_price": 2000.0})
        exec_ = TWAPExecutor(router=router)
        result = await exec_.execute(
            parent_id="t1",
            symbol="XAUUSD",
            side="long",
            total_lots=0.002,
            duration_s=0.01,
            slices=2,
            mid_price=2000.0,
        )
        assert result["status"] == "filled"
        assert result["filled_lots"] > 0

    @pytest.mark.asyncio
    async def test_router_failure_counted(self):
        router = MagicMock()
        router.route = AsyncMock(side_effect=RuntimeError("broker down"))
        exec_ = TWAPExecutor(router=router)
        result = await exec_.execute(
            parent_id="t1",
            symbol="XAUUSD",
            side="long",
            total_lots=0.002,
            duration_s=0.01,
            slices=2,
            mid_price=2000.0,
        )
        assert result["failed_slices"] == 2


class TestVWAPExecutor:
    @pytest.mark.asyncio
    async def test_no_router_returns_result(self):
        exec_ = VWAPExecutor(router=None)
        result = await exec_.execute(
            parent_id="v1",
            symbol="XAUUSD",
            side="long",
            total_lots=0.01,
            duration_s=0.01,
            slices=3,
        )
        assert result["algo"] == "vwap"

    def test_slice_weights_sum_to_one(self):
        exec_ = VWAPExecutor()
        weights = exec_._compute_slice_weights(start_hour_utc=8, n_slices=6)
        assert sum(weights) == pytest.approx(1.0)


# ===========================================================================
# position_tracker
# ===========================================================================

from execution.position_tracker import Position, PositionTracker


class TestPositionTracker:
    @pytest.mark.asyncio
    async def test_add_and_get(self):
        tracker = PositionTracker()
        pos = Position(id="p1", symbol="XAUUSD", side="long", quantity=1.0, entry_price=2000.0, current_price=2000.0)
        await tracker.add_position(pos)
        assert tracker.get_position("p1") is pos

    @pytest.mark.asyncio
    async def test_update_position(self):
        tracker = PositionTracker()
        pos = Position(id="p1", symbol="XAUUSD", side="long", quantity=1.0, entry_price=2000.0, current_price=2000.0)
        await tracker.add_position(pos)
        result = await tracker.update_position("p1", quantity=2.0)
        assert result is True
        assert tracker.get_position("p1").quantity == 2.0

    @pytest.mark.asyncio
    async def test_update_missing_returns_false(self):
        tracker = PositionTracker()
        result = await tracker.update_position("nonexistent", quantity=1.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_close_position_long(self):
        tracker = PositionTracker()
        pos = Position(id="p1", symbol="XAUUSD", side="long", quantity=1.0, entry_price=2000.0, current_price=2000.0)
        await tracker.add_position(pos)
        closed = await tracker.close_position("p1", exit_price=2010.0, commission=1.0)
        assert closed is not None
        assert closed.realized_pnl == pytest.approx(10.0)
        assert tracker.get_position("p1") is None

    @pytest.mark.asyncio
    async def test_close_position_short(self):
        tracker = PositionTracker()
        pos = Position(id="p1", symbol="XAUUSD", side="short", quantity=1.0, entry_price=2000.0, current_price=2000.0)
        await tracker.add_position(pos)
        closed = await tracker.close_position("p1", exit_price=1990.0)
        assert closed.realized_pnl == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_close_missing_returns_none(self):
        tracker = PositionTracker()
        result = await tracker.close_position("nonexistent", exit_price=2000.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_prices(self):
        tracker = PositionTracker()
        pos = Position(id="p1", symbol="XAUUSD", side="long", quantity=1.0, entry_price=2000.0, current_price=2000.0)
        await tracker.add_position(pos)
        await tracker.update_prices("XAUUSD", 2010.0)
        assert tracker.get_position("p1").current_price == pytest.approx(2010.0)

    @pytest.mark.asyncio
    async def test_get_exposure(self):
        tracker = PositionTracker()
        await tracker.add_position(
            Position(id="p1", symbol="XAUUSD", side="long", quantity=2.0, entry_price=2000.0, current_price=2000.0)
        )
        await tracker.add_position(
            Position(id="p2", symbol="XAUUSD", side="short", quantity=1.0, entry_price=2000.0, current_price=2000.0)
        )
        exp = tracker.get_exposure("XAUUSD")
        assert exp["long"] == pytest.approx(2.0)
        assert exp["short"] == pytest.approx(1.0)
        assert exp["net"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_get_total_pnl(self):
        tracker = PositionTracker()
        pos = Position(
            id="p1",
            symbol="XAUUSD",
            side="long",
            quantity=1.0,
            entry_price=2000.0,
            current_price=2010.0,
            unrealized_pnl=10.0,
        )
        await tracker.add_position(pos)
        pnl = tracker.get_total_pnl()
        assert pnl["unrealized"] == pytest.approx(10.0)

    def test_position_update_price_long(self):
        pos = Position(id="p1", symbol="XAUUSD", side="long", quantity=2.0, entry_price=2000.0, current_price=2000.0)
        pos.update_price(2010.0)
        assert pos.unrealized_pnl == pytest.approx(20.0)

    def test_position_market_value(self):
        pos = Position(id="p1", symbol="XAUUSD", side="long", quantity=2.0, entry_price=2000.0, current_price=2005.0)
        assert pos.market_value == pytest.approx(4010.0)


# ===========================================================================
# spread_monitor
# ===========================================================================

from execution.spread_monitor import SpreadMonitor, SpreadSnapshot, get_spread_monitor


class TestSpreadMonitor:
    def test_on_tick_returns_snapshot(self):
        mon = SpreadMonitor(min_ticks=1)
        snap = mon.on_tick("XAUUSD", bid=2000.0, ask=2000.3)
        assert isinstance(snap, SpreadSnapshot)
        assert snap.current_spread == pytest.approx(0.3)

    def test_invalid_tick_skipped(self):
        mon = SpreadMonitor()
        snap = mon.on_tick("XAUUSD", bid=0.0, ask=0.0)
        assert snap.current_spread == 0.0
        assert snap.is_spiking is False

    def test_crossed_market_skipped(self):
        mon = SpreadMonitor()
        snap = mon.on_tick("XAUUSD", bid=2001.0, ask=2000.0)
        assert snap.current_spread == 0.0

    def test_spike_detected_absolute(self):
        mon = SpreadMonitor(abs_limit_usd=1.0, min_ticks=1)
        snap = mon.on_tick("XAUUSD", bid=2000.0, ask=2010.0)  # spread=10 > abs_limit=1
        assert snap.is_spiking is True

    def test_no_spike_below_threshold(self):
        mon = SpreadMonitor(spike_multiplier=3.0, min_ticks=5, abs_limit_usd=100.0)
        for _ in range(10):
            mon.on_tick("XAUUSD", bid=2000.0, ask=2000.3)
        snap = mon.on_tick("XAUUSD", bid=2000.0, ask=2000.3)
        assert snap.is_spiking is False

    def test_is_spread_spiking_insufficient_ticks(self):
        mon = SpreadMonitor(min_ticks=20)
        mon.on_tick("XAUUSD", bid=2000.0, ask=2010.0)
        assert mon.is_spread_spiking("XAUUSD") is False

    def test_get_snapshot(self):
        mon = SpreadMonitor(min_ticks=1)
        mon.on_tick("XAUUSD", bid=2000.0, ask=2000.5)
        snap = mon.get_snapshot("XAUUSD")
        assert snap.symbol == "XAUUSD"

    def test_get_all_snapshots(self):
        mon = SpreadMonitor(min_ticks=1)
        mon.on_tick("XAUUSD", bid=2000.0, ask=2000.3)
        mon.on_tick("EURUSD", bid=1.1000, ask=1.1002)
        snaps = mon.get_all_snapshots()
        assert "XAUUSD" in snaps
        assert "EURUSD" in snaps

    def test_on_tick_obj_with_bid_ask(self):
        mon = SpreadMonitor(min_ticks=1)
        tick = MagicMock()
        tick.bid = 2000.0
        tick.ask = 2000.3
        snap = mon.on_tick_obj("XAUUSD", tick)
        assert snap.current_spread == pytest.approx(0.3)

    def test_on_tick_obj_mid_fallback(self):
        mon = SpreadMonitor(min_ticks=1)
        tick = MagicMock(spec=["mid"])
        tick.mid = 2000.0
        snap = mon.on_tick_obj("XAUUSD", tick)
        assert snap.current_spread > 0

    def test_singleton(self):
        s1 = get_spread_monitor()
        s2 = get_spread_monitor()
        assert s1 is s2


# ===========================================================================
# tca_recorder
# ===========================================================================

from execution.tca_recorder import TCARecorder, get_tca_recorder


class TestTCARecorder:
    def _make_recorder(self):
        rec = TCARecorder()
        return rec

    def test_record_signal_and_fill(self):
        rec = self._make_recorder()
        rec.record_signal("req1", "XAUUSD", "BUY", signal_price=2000.0, quantity=1.0)
        record = rec.record_fill("req1", fill_price=2001.0, filled_quantity=1.0, broker="oanda", latency_ms=42.0)
        assert record is not None
        assert record.slippage_bps > 0

    def test_fill_without_signal_returns_none(self):
        rec = self._make_recorder()
        result = rec.record_fill("unknown_req", fill_price=2001.0, filled_quantity=1.0, broker="oanda")
        assert result is None

    def test_slippage_bps_buy_adverse(self):
        rec = self._make_recorder()
        rec.record_signal("r1", "XAUUSD", "BUY", 2000.0, 1.0)
        record = rec.record_fill("r1", fill_price=2002.0, filled_quantity=1.0, broker="b")
        assert record.slippage_bps > 0  # paid more than expected

    def test_slippage_bps_sell_adverse(self):
        rec = self._make_recorder()
        rec.record_signal("r1", "XAUUSD", "SELL", 2000.0, 1.0)
        record = rec.record_fill("r1", fill_price=1998.0, filled_quantity=1.0, broker="b")
        assert record.slippage_bps > 0  # received less than expected

    def test_get_report(self):
        rec = self._make_recorder()
        for i in range(5):
            rec.record_signal(f"r{i}", "XAUUSD", "BUY", 2000.0, 1.0)
            rec.record_fill(f"r{i}", fill_price=2001.0, filled_quantity=1.0, broker="oanda")
        report = rec.get_report(broker="oanda", last_n=100)
        assert report.n_trades == 5
        assert report.mean_slippage_bps > 0

    def test_get_recent_records(self):
        rec = self._make_recorder()
        rec.record_signal("r1", "XAUUSD", "BUY", 2000.0, 1.0)
        rec.record_fill("r1", fill_price=2001.0, filled_quantity=1.0, broker="oanda")
        records = rec.get_recent_records(n=10)
        assert len(records) == 1
        assert "slippage_bps" in records[0]

    def test_is_fill_quality_degraded_false_initially(self):
        rec = self._make_recorder()
        assert rec.is_fill_quality_degraded("oanda") is False

    def test_to_dict_keys(self):
        rec = self._make_recorder()
        rec.record_signal("r1", "XAUUSD", "BUY", 2000.0, 1.0)
        record = rec.record_fill("r1", fill_price=2001.0, filled_quantity=1.0, broker="oanda")
        d = record.to_dict()
        for k in ("request_id", "symbol", "slippage_bps", "broker", "latency_ms"):
            assert k in d

    def test_singleton(self):
        r1 = get_tca_recorder()
        r2 = get_tca_recorder()
        assert r1 is r2


# ===========================================================================
# throttler
# ===========================================================================

from execution.throttler import MessageThrottler, ThrottleLevel


class TestThrottler:
    def test_can_send_initially(self):
        t = MessageThrottler(max_messages_per_second=10, max_messages_per_minute=100)
        assert t.can_send() is True

    def test_record_and_status(self):
        t = MessageThrottler(max_messages_per_second=10, max_messages_per_minute=100)
        t.record_message()
        status = t.get_status()
        assert "level" in status
        assert "messages_per_second" in status

    def test_exceeds_per_second_throttles(self):
        # burst_allowance=0 so limit is strict
        t = MessageThrottler(max_messages_per_second=2, max_messages_per_minute=1000, burst_allowance=0)
        t.record_message()
        t.record_message()
        assert t.can_send() is False

    def test_throttle_level_normal(self):
        t = MessageThrottler(max_messages_per_second=100, max_messages_per_minute=10000)
        assert t._calculate_level() == ThrottleLevel.NORMAL

    def test_status_keys(self):
        t = MessageThrottler(max_messages_per_second=10, max_messages_per_minute=100)
        s = t.get_status()
        for k in ("level", "messages_per_second", "messages_per_minute", "max_per_second", "max_per_minute"):
            assert k in s
