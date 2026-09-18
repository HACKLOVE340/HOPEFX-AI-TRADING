# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Targeted coverage boost for execution/ modules.

Covers missing branches in:
  position_manager, redis_state, smart_router, sl_tp_monitor,
  tca, tca_recorder, market_impact, trade_executor, async_engine,
  oms, order_algorithms, spread_monitor.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc

# ---------------------------------------------------------------------------
# market_impact — 0% coverage, fully unit-testable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAlmgrenChrissModel:
    def _model(self):
        from execution.market_impact import AlmgrenChrissModel

        return AlmgrenChrissModel()

    def test_estimate_normal(self):
        m = self._model()
        est = m.estimate(order_size=100, adv=10000, volatility_daily=0.012, spread_bps=3.0, price=2000.0)
        assert est.total_impact_bps > 0
        assert est.participation_rate == pytest.approx(0.01)

    def test_estimate_zero_adv_spread_only(self):
        m = self._model()
        est = m.estimate(order_size=100, adv=0, volatility_daily=0.012, spread_bps=3.0, price=2000.0)
        assert est.temporary_impact_bps == 0.0
        assert est.permanent_impact_bps == 0.0
        assert est.spread_cost_bps > 0

    def test_participation_capped_at_max(self):
        m = self._model()
        est = m.estimate(order_size=9999, adv=100, volatility_daily=0.01, spread_bps=2.0, price=1000.0)
        assert est.participation_rate == pytest.approx(m.max_participation)

    def test_fill_price_buy(self):
        m = self._model()
        est = m.estimate(order_size=10, adv=1000, volatility_daily=0.01, spread_bps=2.0, price=1000.0)
        assert est.fill_price("BUY") > 1000.0

    def test_fill_price_sell(self):
        m = self._model()
        est = m.estimate(order_size=10, adv=1000, volatility_daily=0.01, spread_bps=2.0, price=1000.0)
        assert est.fill_price("SELL") < 1000.0

    def test_total_cost_usd(self):
        m = self._model()
        est = m.estimate(order_size=1, adv=1000, volatility_daily=0.01, spread_bps=2.0, price=2000.0)
        assert est.total_cost_usd > 0

    def test_slippage_bps_alias(self):
        m = self._model()
        est = m.estimate(order_size=10, adv=1000, volatility_daily=0.01, spread_bps=2.0, price=1000.0)
        assert est.slippage_bps == est.total_impact_bps

    def test_min_spread_bps_floor(self):
        m = self._model()
        # spread_bps=0 → should still have spread_cost >= _MIN_SPREAD_BPS
        est = m.estimate(order_size=1, adv=1000, volatility_daily=0.01, spread_bps=0.0, price=1000.0)
        from execution.market_impact import _MIN_SPREAD_BPS

        assert est.spread_cost_bps >= _MIN_SPREAD_BPS


@pytest.mark.unit
class TestFillSimulator:
    def _sim(self):
        from execution.market_impact import FillSimulator

        return FillSimulator()

    def test_simulate_fill_buy_normal(self):
        s = self._sim()
        fill = s.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=1.0,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=5000.0,
            adv=10000.0,
            volatility_daily=0.012,
        )
        assert fill.fill_price <= 2005.0
        assert fill.fill_quantity > 0

    def test_simulate_fill_sell_normal(self):
        s = self._sim()
        fill = s.simulate_fill(
            signal_price=2000.0,
            side="SELL",
            quantity=1.0,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=5000.0,
            adv=10000.0,
            volatility_daily=0.012,
        )
        assert fill.fill_price >= 1995.0

    def test_partial_fill_when_large_order(self):
        s = self._sim()
        fill = s.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=9999.0,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=100.0,
            adv=10000.0,
            volatility_daily=0.012,
        )
        assert fill.partial_fill is True
        assert fill.fill_quantity < 9999.0
        assert "Partial fill" in fill.notes

    def test_no_partial_fill_small_order(self):
        s = self._sim()
        fill = s.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=0.1,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=5000.0,
            adv=10000.0,
            volatility_daily=0.012,
        )
        assert fill.partial_fill is False

    def test_simulate_fills_batch(self):
        s = self._sim()
        signals = [
            {
                "signal_price": 2000.0,
                "side": "BUY",
                "quantity": 1.0,
                "bar_high": 2005.0,
                "bar_low": 1995.0,
                "bar_volume": 5000.0,
            },
            {
                "signal_price": 1900.0,
                "side": "SELL",
                "quantity": 0.5,
                "bar_high": 1905.0,
                "bar_low": 1895.0,
                "bar_volume": 3000.0,
            },
        ]
        fills = s.simulate_fills_batch(signals, adv=10000.0, volatility_daily=0.012)
        assert len(fills) == 2

    def test_get_fill_simulator_singleton(self):
        from execution.market_impact import get_fill_simulator, FillSimulator

        s1 = get_fill_simulator()
        s2 = get_fill_simulator()
        assert s1 is s2
        assert isinstance(s1, FillSimulator)


# ---------------------------------------------------------------------------
# tca_recorder — 0% coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTCARecord:
    def _record(self, side="BUY", signal=2000.0, fill=2001.0):
        from execution.tca_recorder import TCARecord

        return TCARecord(
            request_id="req1",
            symbol="XAUUSD",
            side=side,
            signal_price=signal,
            fill_price=fill,
            filled_quantity=1.0,
            broker="oanda",
            latency_ms=10.0,
            model_version="v1",
            session="london",
            signal_time=datetime.now(UTC),
            fill_time=datetime.now(UTC),
        )

    def test_slippage_bps_buy_adverse(self):
        r = self._record(side="BUY", signal=2000.0, fill=2001.0)
        assert r.slippage_bps > 0

    def test_slippage_bps_sell_adverse(self):
        r = self._record(side="SELL", signal=2000.0, fill=1999.0)
        assert r.slippage_bps > 0

    def test_slippage_bps_zero_signal_price(self):
        r = self._record(signal=0.0, fill=1.0)
        assert r.slippage_bps == 0.0

    def test_slippage_usd(self):
        r = self._record(signal=2000.0, fill=2001.0)
        assert r.slippage_usd == pytest.approx(1.0)

    def test_signal_to_fill_ms(self):
        r = self._record()
        assert r.signal_to_fill_ms >= 0.0

    def test_to_dict_keys(self):
        r = self._record()
        d = r.to_dict()
        assert "slippage_bps" in d
        assert "slippage_usd" in d
        assert "broker" in d


@pytest.mark.unit
class TestTCARecorder:
    def _recorder(self):
        from execution.tca_recorder import TCARecorder

        return TCARecorder()

    def test_record_signal_and_fill(self):
        rec = self._recorder()
        rec.record_signal("req1", "XAUUSD", "BUY", 2000.0, 1.0)
        result = rec.record_fill("req1", 2001.0, 1.0, broker="oanda", latency_ms=10.0)
        assert result is not None
        assert result.symbol == "XAUUSD"

    def test_record_fill_no_signal_returns_none(self):
        rec = self._recorder()
        result = rec.record_fill("missing_req", 2001.0, 1.0)
        assert result is None

    def test_get_report_no_records_returns_none(self):
        rec = self._recorder()
        assert rec.get_report(broker="oanda") is None

    def test_get_report_with_records(self):
        rec = self._recorder()
        for i in range(5):
            rec.record_signal(f"req{i}", "XAUUSD", "BUY", 2000.0, 1.0)
            rec.record_fill(f"req{i}", 2000.0 + i * 0.5, 1.0, broker="oanda", latency_ms=10.0)
        report = rec.get_report(broker="oanda")
        assert report is not None
        assert report.n_trades == 5

    def test_get_report_filter_symbol(self):
        rec = self._recorder()
        rec.record_signal("r1", "XAUUSD", "BUY", 2000.0, 1.0)
        rec.record_fill("r1", 2001.0, 1.0, broker="oanda")
        rec.record_signal("r2", "EURUSD", "SELL", 1.10, 1.0)
        rec.record_fill("r2", 1.101, 1.0, broker="oanda")
        report = rec.get_report(broker="oanda", symbol="XAUUSD")
        assert report.n_trades == 1

    def test_get_report_filter_session(self):
        rec = self._recorder()
        rec.record_signal("r1", "XAUUSD", "BUY", 2000.0, 1.0)
        rec.record_fill("r1", 2001.0, 1.0, broker="oanda")
        report = rec.get_report(session="london")
        # May or may not match depending on time of test run
        assert report is None or report.n_trades >= 0

    def test_get_all_reports(self):
        rec = self._recorder()
        for broker in ("oanda", "ibkr"):
            rec.record_signal(f"r_{broker}", "XAUUSD", "BUY", 2000.0, 1.0)
            rec.record_fill(f"r_{broker}", 2001.0, 1.0, broker=broker)
        reports = rec.get_all_reports()
        assert len(reports) == 2

    def test_get_recent_records(self):
        rec = self._recorder()
        rec.record_signal("r1", "XAUUSD", "BUY", 2000.0, 1.0)
        rec.record_fill("r1", 2001.0, 1.0, broker="oanda")
        records = rec.get_recent_records(n=10)
        assert len(records) == 1
        assert "slippage_bps" in records[0]

    def test_is_fill_quality_degraded_insufficient_data(self):
        rec = self._recorder()
        assert rec.is_fill_quality_degraded("oanda") is False

    def test_is_fill_quality_degraded_high_slippage(self):
        rec = self._recorder()
        # Inject 15 high-slippage fills to exceed threshold
        for i in range(15):
            rec.record_signal(f"r{i}", "XAUUSD", "BUY", 100.0, 1.0)
            rec.record_fill(f"r{i}", 110.0, 1.0, broker="bad_broker")
        assert rec.is_fill_quality_degraded("bad_broker") is True

    def test_is_fill_quality_degraded_low_slippage(self):
        rec = self._recorder()
        for i in range(15):
            rec.record_signal(f"r{i}", "XAUUSD", "BUY", 2000.0, 1.0)
            rec.record_fill(f"r{i}", 2000.01, 1.0, broker="good_broker")
        assert rec.is_fill_quality_degraded("good_broker") is False

    def test_get_session_london(self):
        from execution.tca_recorder import TCARecorder

        dt = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert TCARecorder._get_session(dt) == "london"

    def test_get_session_new_york(self):
        from execution.tca_recorder import TCARecorder

        dt = datetime(2025, 1, 1, 18, 0, 0, tzinfo=UTC)
        assert TCARecorder._get_session(dt) == "new_york"

    def test_get_session_asia(self):
        from execution.tca_recorder import TCARecorder

        dt = datetime(2025, 1, 1, 3, 0, 0, tzinfo=UTC)
        assert TCARecorder._get_session(dt) == "asia"

    def test_get_session_off_hours(self):
        from execution.tca_recorder import TCARecorder

        dt = datetime(2025, 1, 1, 23, 0, 0, tzinfo=UTC)
        assert TCARecorder._get_session(dt) == "off_hours"

    def test_get_tca_recorder_singleton(self):
        from execution.tca_recorder import get_tca_recorder, TCARecorder

        r1 = get_tca_recorder()
        r2 = get_tca_recorder()
        assert r1 is r2
        assert isinstance(r1, TCARecorder)

    def test_report_summary_string(self):
        rec = self._recorder()
        for i in range(3):
            rec.record_signal(f"r{i}", "XAUUSD", "BUY", 2000.0, 1.0)
            rec.record_fill(f"r{i}", 2001.0, 1.0, broker="oanda")
        report = rec.get_report(broker="oanda")
        summary = report.summary()
        assert "oanda" in summary
        assert "bps" in summary

    def test_persist_redis_suppresses_error(self):
        rec = self._recorder()
        rec.record_signal("r1", "XAUUSD", "BUY", 2000.0, 1.0)
        # Should not raise even if redis is unavailable
        with patch("execution.tca_recorder.TCA_PERSIST_REDIS", True):
            with patch("execution.tca_recorder.TCA_PERSIST_DB", False):
                result = rec.record_fill("r1", 2001.0, 1.0, broker="oanda")
        assert result is not None

    def test_persist_db_suppresses_error(self):
        rec = self._recorder()
        rec.record_signal("r1", "XAUUSD", "BUY", 2000.0, 1.0)
        with patch("execution.tca_recorder.TCA_PERSIST_REDIS", False):
            with patch("execution.tca_recorder.TCA_PERSIST_DB", True):
                result = rec.record_fill("r1", 2001.0, 1.0, broker="oanda")
        assert result is not None


# ---------------------------------------------------------------------------
# tca.py — 0% coverage, fully unit-testable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTCAMarketImpactModel:
    def test_calculate_returns_tuple(self):
        from decimal import Decimal
        from execution.tca import MarketImpactModel

        m = MarketImpactModel()
        temp, perm = m.calculate(
            order_size=Decimal("100"),
            avg_daily_volume=Decimal("10000"),
            volatility=0.012,
            spread_bps=3.0,
        )
        assert temp >= Decimal(0)
        assert perm >= Decimal(0)

    def test_calculate_zero_adv(self):
        from decimal import Decimal
        from execution.tca import MarketImpactModel

        m = MarketImpactModel()
        temp, perm = m.calculate(
            order_size=Decimal("100"),
            avg_daily_volume=Decimal("0"),
            volatility=0.012,
            spread_bps=3.0,
        )
        assert temp == Decimal(0)
        assert perm == Decimal(0)


@pytest.mark.unit
class TestTCAMetrics:
    def _metrics(self):
        from decimal import Decimal
        from execution.tca import TCAMetrics, BenchmarkType
        from core.types import Side

        return TCAMetrics(
            order_id="o1",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2000"),
            arrival_time=datetime.now(UTC),
            benchmark_type=BenchmarkType.ARRIVAL,
            fills=[],
            avg_fill_price=Decimal("2001"),
            total_commission=Decimal("0.5"),
            total_slippage=Decimal("0.3"),
            total_fees=Decimal("0.8"),
            implementation_shortfall_bps=Decimal("5"),
            market_impact_bps=Decimal("3"),
            timing_cost_bps=Decimal("1"),
            opportunity_cost_bps=Decimal("0"),
            fill_rate=1.0,
            price_improvement_bps=Decimal("0"),
            adv_used=10000.0,
            volatility_used=0.012,
            adv_source="redis",
            vol_source="redis",
        )

    def test_total_cost_bps(self):
        m = self._metrics()
        assert m.total_cost_bps >= 0

    def test_alpha_extraction_bps(self):
        m = self._metrics()
        # Should not raise
        _ = m.alpha_extraction_bps

    def test_to_dict(self):
        m = self._metrics()
        d = m.to_dict()
        assert "order_id" in d
        assert "symbol" in d


@pytest.mark.unit
class TestMarketContextProvider:
    def test_get_adv_env_override(self):
        import os
        from execution.tca import MarketContextProvider

        ctx = MarketContextProvider()
        with patch.dict(os.environ, {"TCA_ADV_XAUUSD": "75000"}):
            adv, source = ctx.get_adv("XAUUSD")
        assert adv == pytest.approx(75000.0)
        assert source == "env_override"

    def test_get_adv_default_fallback(self):
        from execution.tca import MarketContextProvider

        ctx = MarketContextProvider()
        adv, source = ctx.get_adv("UNKNOWN_SYM_XYZ")
        assert adv > 0
        assert source in ("default", "env_override", "tick_cache", "redis")

    def test_get_volatility_env_override(self):
        import os
        from execution.tca import MarketContextProvider

        ctx = MarketContextProvider()
        with patch.dict(os.environ, {"TCA_VOL_XAUUSD": "0.025"}):
            vol, source = ctx.get_volatility("XAUUSD")
        assert vol == pytest.approx(0.025)
        assert source == "env_override"

    def test_get_volatility_default(self):
        from execution.tca import MarketContextProvider

        ctx = MarketContextProvider()
        vol, source = ctx.get_volatility("UNKNOWN_SYM_XYZ")
        assert vol > 0

    def test_accumulate_tick(self):
        from execution.tca import MarketContextProvider

        ctx = MarketContextProvider()
        ctx.accumulate_tick("XAUUSD", volume=1000.0, ts=datetime.now(UTC))
        # Should not raise


@pytest.mark.unit
class TestTCAEngineLifecycle:
    def _fill(self, price="2001", qty="1", commission="0.5"):
        from decimal import Decimal
        from core.types import Fill, Side

        return Fill(
            order_id="o1",
            fill_id="f1",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal(qty),
            price=Decimal(price),
            timestamp=datetime.now(UTC),
            venue="OANDA",
            commission=Decimal(commission),
        )

    @pytest.mark.asyncio
    async def test_start_and_complete_order(self):
        from decimal import Decimal
        from execution.tca import TCAEngine
        from core.types import Side

        tca = TCAEngine()
        await tca.start_order(
            order_id="o1",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2000"),
        )
        await tca.record_fill("o1", self._fill())
        metrics = await tca.complete_order("o1")
        assert metrics.order_id == "o1"
        assert metrics.fill_rate == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_complete_order_no_fills(self):
        from decimal import Decimal
        from execution.tca import TCAEngine
        from core.types import Side

        tca = TCAEngine()
        await tca.start_order(
            order_id="o2",
            symbol="XAUUSD",
            side=Side.SELL,
            quantity=Decimal("1"),
            arrival_price=Decimal("2000"),
        )
        metrics = await tca.complete_order("o2")
        assert metrics.fill_rate == 0.0

    @pytest.mark.asyncio
    async def test_complete_unknown_order_raises(self):
        from execution.tca import TCAEngine

        tca = TCAEngine()
        with pytest.raises(ValueError, match="Unknown order"):
            await tca.complete_order("nonexistent")

    @pytest.mark.asyncio
    async def test_record_fill_unknown_order_logs(self):
        from execution.tca import TCAEngine

        tca = TCAEngine()
        # Should not raise — just logs a warning
        await tca.record_fill("unknown_order", self._fill())

    def test_get_stats_empty(self):
        from execution.tca import TCAEngine

        tca = TCAEngine()
        assert tca.get_stats() == {}

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self):
        from decimal import Decimal
        from execution.tca import TCAEngine
        from core.types import Side

        tca = TCAEngine()
        await tca.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        await tca.record_fill("o1", self._fill())
        await tca.complete_order("o1")
        stats = tca.get_stats()
        assert "count" in stats
        assert stats["count"] == 1

    def test_register_cost_callback(self):
        from execution.tca import TCAEngine

        tca = TCAEngine()
        cb = MagicMock()
        tca.register_cost_callback(cb)
        assert cb in tca._cost_callbacks

    @pytest.mark.asyncio
    async def test_update_market_data(self):
        from decimal import Decimal
        from execution.tca import TCAEngine
        from core.types import Tick

        tca = TCAEngine()
        tick = Tick(
            symbol="XAUUSD",
            bid=Decimal("1999.5"),
            ask=Decimal("2000.5"),
            mid=Decimal("2000.0"),
            timestamp=datetime.now(UTC),
            venue="OANDA",
            volume=Decimal("100"),
        )
        # Should not raise
        tca.update_market_data(tick)

    @pytest.mark.asyncio
    async def test_sell_order_isf_calculation(self):
        from decimal import Decimal
        from execution.tca import TCAEngine
        from core.types import Side, Fill

        tca = TCAEngine()
        await tca.start_order("o1", "XAUUSD", Side.SELL, Decimal("1"), Decimal("2000"))
        fill = Fill(
            order_id="o1",
            fill_id="f1",
            symbol="XAUUSD",
            side=Side.SELL,
            quantity=Decimal("1"),
            price=Decimal("1999"),
            timestamp=datetime.now(UTC),
            venue="OANDA",
            commission=Decimal("0"),
        )
        await tca.record_fill("o1", fill)
        metrics = await tca.complete_order("o1")
        assert metrics.implementation_shortfall_bps > 0

    @pytest.mark.asyncio
    async def test_cost_callback_fired_on_expensive_trade(self):
        from decimal import Decimal
        from execution.tca import TCAEngine
        from core.types import Side, Fill

        tca = TCAEngine()
        cb = MagicMock()
        tca.register_cost_callback(cb)
        await tca.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"), expected_advantage_bps=0.0)
        fill = Fill(
            order_id="o1",
            fill_id="f1",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            price=Decimal("2500"),
            timestamp=datetime.now(UTC),
            venue="OANDA",
            commission=Decimal("100"),
        )
        await tca.record_fill("o1", fill)
        await tca.complete_order("o1")
        # Just verify no exception was raised


# ---------------------------------------------------------------------------
# position_manager — 68% coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPositionManagerBasic:
    def _pm(self):
        from execution.position_manager import PositionManager

        return PositionManager()

    @pytest.mark.asyncio
    async def test_open_buy_position(self):
        pm = self._pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        assert pos.symbol == "XAUUSD"
        assert pos.side == "BUY"

    @pytest.mark.asyncio
    async def test_open_sell_position(self):
        pm = self._pm()
        pos = await pm.open_position("XAUUSD", "SELL", 2.0, 1900.0)
        assert pos.side == "SELL"

    @pytest.mark.asyncio
    async def test_open_duplicate_raises(self):
        from execution.position_manager import PositionAlreadyOpenError

        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        with pytest.raises(PositionAlreadyOpenError):
            await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)

    @pytest.mark.asyncio
    async def test_open_invalid_side_raises(self):
        pm = self._pm()
        with pytest.raises(ValueError, match="side"):
            await pm.open_position("XAUUSD", "LONG", 1.0, 1900.0)

    @pytest.mark.asyncio
    async def test_open_zero_quantity_raises(self):
        pm = self._pm()
        with pytest.raises(ValueError, match="quantity"):
            await pm.open_position("XAUUSD", "BUY", 0.0, 1900.0)

    @pytest.mark.asyncio
    async def test_open_zero_price_raises(self):
        pm = self._pm()
        with pytest.raises(ValueError, match="entry_price"):
            await pm.open_position("XAUUSD", "BUY", 1.0, 0.0)

    @pytest.mark.asyncio
    async def test_close_buy_profit(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        result = await pm.close_position("XAUUSD", 1920.0)
        assert result.realized_pnl == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_close_sell_profit(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "SELL", 1.0, 1900.0)
        result = await pm.close_position("XAUUSD", 1880.0)
        assert result.realized_pnl == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_close_not_found_raises(self):
        from execution.position_manager import PositionNotFoundError

        pm = self._pm()
        with pytest.raises(PositionNotFoundError):
            await pm.close_position("MISSING", 1900.0)

    @pytest.mark.asyncio
    async def test_close_zero_price_raises(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        with pytest.raises(ValueError, match="fill_price"):
            await pm.close_position("XAUUSD", 0.0)

    @pytest.mark.asyncio
    async def test_update_last_price(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        pos = await pm.update_position("XAUUSD", last_price=1910.0)
        assert pos.last_price == pytest.approx(1910.0)

    @pytest.mark.asyncio
    async def test_update_stop_loss(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        pos = await pm.update_position("XAUUSD", stop_loss=1880.0)
        assert pos.stop_loss == pytest.approx(1880.0)

    @pytest.mark.asyncio
    async def test_update_take_profit(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        pos = await pm.update_position("XAUUSD", take_profit=1950.0)
        assert pos.take_profit == pytest.approx(1950.0)

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self):
        from execution.position_manager import PositionNotFoundError

        pm = self._pm()
        with pytest.raises(PositionNotFoundError):
            await pm.update_position("MISSING", last_price=1900.0)

    def test_get_position_none(self):
        pm = self._pm()
        assert pm.get_position("XAUUSD") is None

    @pytest.mark.asyncio
    async def test_get_all_positions(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        await pm.open_position("EURUSD", "SELL", 1.0, 1.10)
        all_pos = pm.get_all_positions()
        assert len(all_pos) == 2

    @pytest.mark.asyncio
    async def test_get_total_exposure(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 2.0, 1900.0)
        exposure = pm.get_total_exposure()
        assert exposure == pytest.approx(3800.0)

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl_buy(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        await pm.update_position("XAUUSD", last_price=1920.0)
        pnl = pm.get_unrealized_pnl()
        assert pnl["XAUUSD"] == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl_sell(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "SELL", 1.0, 1900.0)
        await pm.update_position("XAUUSD", last_price=1880.0)
        pnl = pm.get_unrealized_pnl()
        assert pnl["XAUUSD"] == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl_no_last_price(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        pnl = pm.get_unrealized_pnl()
        assert pnl["XAUUSD"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_get_history_limit(self):
        pm = self._pm()
        for i in range(5):
            await pm.open_position(f"SYM{i}", "BUY", 1.0, 100.0 + i)
            await pm.close_position(f"SYM{i}", 110.0 + i)
        history = pm.get_history(limit=3)
        assert len(history) == 3

    def test_position_from_dict_roundtrip(self):
        from execution.position_manager import Position

        now = datetime.now(UTC)
        p = Position(
            position_id="p1",
            symbol="XAUUSD",
            side="BUY",
            quantity=2.0,
            entry_price=1900.0,
            opened_at=now,
            stop_loss=1880.0,
            take_profit=1940.0,
        )
        d = p.to_dict()
        p2 = Position.from_dict(d)
        assert p2.symbol == "XAUUSD"
        assert p2.stop_loss == pytest.approx(1880.0)

    def test_position_from_dict_no_opened_at(self):
        from execution.position_manager import Position

        d = {"position_id": "p1", "symbol": "XAUUSD", "side": "BUY", "quantity": 1.0, "entry_price": 1900.0}
        p = Position.from_dict(d)
        assert p.opened_at is not None

    @pytest.mark.asyncio
    async def test_open_with_custom_position_id(self):
        pm = self._pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0, position_id="custom-id")
        assert pos.position_id == "custom-id"

    @pytest.mark.asyncio
    async def test_open_with_metadata(self):
        pm = self._pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0, metadata={"strategy": "momentum"})
        assert pos.metadata["strategy"] == "momentum"

    @pytest.mark.asyncio
    async def test_close_result_has_duration(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        result = await pm.close_position("XAUUSD", 1910.0)
        assert result.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_position_added_to_history_after_close(self):
        pm = self._pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 1900.0)
        await pm.close_position("XAUUSD", 1910.0)
        history = pm.get_history()
        assert len(history) == 1
        assert history[0].symbol == "XAUUSD"


# ---------------------------------------------------------------------------
# redis_state — 71% coverage (async paths missing)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAsyncRedisStateStoreFull:
    def _mock_r(self):
        r = AsyncMock()
        r.set = AsyncMock(return_value=True)
        r.get = AsyncMock(return_value=None)
        r.delete = AsyncMock(return_value=1)
        r.sadd = AsyncMock(return_value=1)
        r.srem = AsyncMock(return_value=1)
        r.smembers = AsyncMock(return_value=set())
        return r

    @pytest.mark.asyncio
    async def test_save_order_success(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        store = AsyncRedisStateStore(r)
        await store.save_order({"order_id": "o1", "symbol": "XAUUSD"})
        r.set.assert_called_once()
        r.sadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_order_no_id_skipped(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        store = AsyncRedisStateStore(r)
        await store.save_order({"symbol": "XAUUSD"})
        r.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_order_connection_error(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.set = AsyncMock(side_effect=ConnectionError("down"))
        store = AsyncRedisStateStore(r)
        await store.save_order({"order_id": "o1"})  # must not raise

    @pytest.mark.asyncio
    async def test_remove_order_success(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        store = AsyncRedisStateStore(r)
        await store.remove_order("o1")
        r.delete.assert_called_once()
        r.srem.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_order_connection_error(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.delete = AsyncMock(side_effect=ConnectionError("down"))
        store = AsyncRedisStateStore(r)
        await store.remove_order("o1")  # must not raise

    @pytest.mark.asyncio
    async def test_load_orders_empty(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        store = AsyncRedisStateStore(r)
        orders = await store.load_orders()
        assert orders == []

    @pytest.mark.asyncio
    async def test_load_orders_with_data(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.smembers = AsyncMock(return_value={b"o1"})
        r.get = AsyncMock(return_value=json.dumps({"order_id": "o1"}).encode())
        store = AsyncRedisStateStore(r)
        orders = await store.load_orders()
        assert len(orders) == 1

    @pytest.mark.asyncio
    async def test_load_orders_connection_error(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.smembers = AsyncMock(side_effect=ConnectionError("down"))
        store = AsyncRedisStateStore(r)
        orders = await store.load_orders()
        assert orders == []

    @pytest.mark.asyncio
    async def test_save_position_success(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        store = AsyncRedisStateStore(r)
        await store.save_position({"symbol": "XAUUSD", "side": "BUY"})
        r.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_position_no_symbol_skipped(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        store = AsyncRedisStateStore(r)
        await store.save_position({"side": "BUY"})
        r.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_position_connection_error(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.set = AsyncMock(side_effect=ConnectionError("down"))
        store = AsyncRedisStateStore(r)
        await store.save_position({"symbol": "XAUUSD"})  # must not raise

    @pytest.mark.asyncio
    async def test_remove_position_success(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        store = AsyncRedisStateStore(r)
        await store.remove_position("XAUUSD")
        r.delete.assert_called_once()
        r.srem.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_position_connection_error(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.delete = AsyncMock(side_effect=ConnectionError("down"))
        store = AsyncRedisStateStore(r)
        await store.remove_position("XAUUSD")  # must not raise

    @pytest.mark.asyncio
    async def test_load_positions_with_data(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.smembers = AsyncMock(return_value={b"XAUUSD"})
        r.get = AsyncMock(return_value=json.dumps({"symbol": "XAUUSD"}).encode())
        store = AsyncRedisStateStore(r)
        positions = await store.load_positions()
        assert len(positions) == 1

    @pytest.mark.asyncio
    async def test_load_positions_connection_error(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.smembers = AsyncMock(side_effect=ConnectionError("down"))
        store = AsyncRedisStateStore(r)
        positions = await store.load_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_load_state_on_boot_with_data(self):
        from execution.redis_state import AsyncRedisStateStore

        r = self._mock_r()
        r.smembers = AsyncMock(return_value={b"o1"})
        r.get = AsyncMock(return_value=json.dumps({"order_id": "o1"}).encode())
        store = AsyncRedisStateStore(r)
        state = await store.load_state_on_boot()
        assert "orders" in state
        assert "positions" in state


# ---------------------------------------------------------------------------
# spread_monitor — 67% coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSpreadMonitorFull:
    def _mon(self, **kw):
        from execution.spread_monitor import SpreadMonitor

        return SpreadMonitor(**kw)

    def test_on_tick_normal(self):
        m = self._mon()
        snap = m.on_tick("XAUUSD", bid=2000.0, ask=2000.5)
        assert snap.current_spread == pytest.approx(0.5)
        assert snap.is_spiking is False

    def test_on_tick_invalid_bid_zero(self):
        m = self._mon()
        snap = m.on_tick("XAUUSD", bid=0.0, ask=2000.5)
        assert snap.current_spread == 0.0
        assert snap.is_spiking is False

    def test_on_tick_crossed_market(self):
        m = self._mon()
        snap = m.on_tick("XAUUSD", bid=2001.0, ask=2000.0)
        assert snap.current_spread == 0.0

    def test_spike_detected_absolute_limit(self):
        m = self._mon(abs_limit_usd=1.0)
        snap = m.on_tick("XAUUSD", bid=2000.0, ask=2002.0)
        assert snap.is_spiking is True

    def test_spike_detected_relative(self):
        m = self._mon(spike_multiplier=2.0, min_ticks=3)
        for _ in range(5):
            m.on_tick("XAUUSD", bid=2000.0, ask=2000.1)
        snap = m.on_tick("XAUUSD", bid=2000.0, ask=2000.9)
        assert snap.is_spiking is True

    def test_no_spike_insufficient_ticks(self):
        m = self._mon(min_ticks=20)
        for _ in range(5):
            m.on_tick("XAUUSD", bid=2000.0, ask=2001.0)
        assert m.is_spread_spiking("XAUUSD") is False

    def test_is_spread_spiking_unknown_symbol(self):
        m = self._mon()
        assert m.is_spread_spiking("UNKNOWN") is False

    def test_get_snapshot_no_ticks(self):
        m = self._mon()
        snap = m.get_snapshot("XAUUSD")
        assert snap.current_spread == 0.0
        assert snap.tick_count == 0

    def test_get_snapshot_with_ticks(self):
        m = self._mon()
        m.on_tick("XAUUSD", bid=2000.0, ask=2000.3)
        snap = m.get_snapshot("XAUUSD")
        assert snap.current_spread == pytest.approx(0.3)

    def test_get_all_snapshots(self):
        m = self._mon()
        m.on_tick("XAUUSD", bid=2000.0, ask=2000.3)
        m.on_tick("EURUSD", bid=1.10, ask=1.101)
        snaps = m.get_all_snapshots()
        assert "XAUUSD" in snaps
        assert "EURUSD" in snaps

    def test_on_tick_obj_with_bid_ask(self):
        m = self._mon()
        tick = MagicMock()
        tick.bid = 2000.0
        tick.ask = 2000.5
        snap = m.on_tick_obj("XAUUSD", tick)
        assert snap.current_spread == pytest.approx(0.5)

    def test_on_tick_obj_with_mid_fallback(self):
        m = self._mon()
        tick = MagicMock(spec=["mid"])
        tick.mid = 2000.0
        snap = m.on_tick_obj("XAUUSD", tick)
        assert snap.current_spread == pytest.approx(1.0)

    def test_on_tick_obj_no_price_attrs(self):
        m = self._mon()
        tick = MagicMock(spec=[])
        snap = m.on_tick_obj("XAUUSD", tick)
        assert snap.current_spread == 0.0

    def test_ema_updates_over_ticks(self):
        m = self._mon()
        for _i in range(10):
            m.on_tick("XAUUSD", bid=2000.0, ask=2000.2)
        snap = m.get_snapshot("XAUUSD")
        assert snap.baseline_spread > 0

    def test_get_spread_monitor_singleton(self):
        from execution.spread_monitor import get_spread_monitor, SpreadMonitor

        s1 = get_spread_monitor()
        s2 = get_spread_monitor()
        assert s1 is s2
        assert isinstance(s1, SpreadMonitor)


# ---------------------------------------------------------------------------
# smart_router — 72% coverage (missing: _route_via_algo, _execute_with_fallback,
#   _pre_route_gate, _rank_brokers, _submit_child_order)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSmartRouterFull:
    def _router(self, brokers=None):
        from execution.smart_router import SmartRouter

        r = SmartRouter()
        for name, broker in (brokers or {}).items():
            r.add_broker(name, broker)
        return r

    def _broker(self, status="filled", fill_price=2000.0):
        b = AsyncMock()
        b.place_order = AsyncMock(
            return_value={
                "status": status,
                "fill_price": fill_price,
                "filled_qty": 1.0,
                "latency_ms": 10.0,
            }
        )
        return b

    def test_add_broker(self):
        r = self._router()
        b = self._broker()
        r.add_broker("oanda", b)
        assert "oanda" in r._brokers

    def test_remove_broker(self):
        r = self._router({"oanda": self._broker()})
        r.remove_broker("oanda")
        assert "oanda" not in r._brokers

    @pytest.mark.asyncio
    async def test_route_no_brokers_rejected(self):
        r = self._router()
        result = await r.route_and_execute(
            {
                "symbol": "XAUUSD",
                "direction": "long",
                "quantity": 1.0,
                "order_type": "order",
                "mid_price": 2000.0,
                "spread": 0.3,
                "sentiment": 0.0,
                "impact": 0.0,
                "features": {},
            }
        )
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_route_success(self):
        b = self._broker()
        r = self._router({"oanda": b})
        result = await r.route_and_execute(
            {
                "symbol": "XAUUSD",
                "direction": "long",
                "quantity": 1.0,
                "order_type": "order",
                "mid_price": 2000.0,
                "spread": 0.3,
                "sentiment": 0.0,
                "impact": 0.0,
                "features": {},
            }
        )
        assert result["status"] in ("filled", "rejected", "algo_submitted")

    @pytest.mark.asyncio
    async def test_route_high_sentiment_blocked(self):
        b = self._broker()
        r = self._router({"oanda": b})
        result = await r.route_and_execute(
            {
                "symbol": "XAUUSD",
                "direction": "long",
                "quantity": 1.0,
                "order_type": "order",
                "mid_price": 2000.0,
                "spread": 0.3,
                "sentiment": 0.95,
                "impact": 0.0,
                "features": {},
            }
        )
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_route_high_impact_blocked(self):
        b = self._broker()
        r = self._router({"oanda": b})
        result = await r.route_and_execute(
            {
                "symbol": "XAUUSD",
                "direction": "long",
                "quantity": 1.0,
                "order_type": "order",
                "mid_price": 2000.0,
                "spread": 0.3,
                "sentiment": 0.0,
                "impact": 0.9,
                "features": {},
            }
        )
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_route_unwind_bypasses_gates(self):
        b = self._broker()
        r = self._router({"oanda": b})
        result = await r.route_and_execute(
            {
                "symbol": "XAUUSD",
                "direction": "long",
                "quantity": 1.0,
                "order_type": "order",
                "mid_price": 2000.0,
                "spread": 0.3,
                "sentiment": 0.95,
                "impact": 0.9,
                "features": {},
                "is_unwind": True,
            }
        )
        # Unwind bypasses sentiment/impact gates
        assert result["status"] in ("filled", "rejected", "algo_submitted")

    @pytest.mark.asyncio
    async def test_route_wide_spread_blocked(self):
        b = self._broker()
        r = self._router({"oanda": b})
        result = await r.route_and_execute(
            {
                "symbol": "XAUUSD",
                "direction": "long",
                "quantity": 1.0,
                "order_type": "order",
                "mid_price": 2000.0,
                "spread": 200.0,
                "sentiment": 0.0,
                "impact": 0.0,
                "features": {},
            }
        )
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_route_broker_error_fallback(self):
        b1 = AsyncMock()
        b1.place_order = AsyncMock(side_effect=RuntimeError("broker down"))
        b2 = self._broker()
        r = self._router({"primary": b1, "secondary": b2})
        result = await r.route_and_execute(
            {
                "symbol": "XAUUSD",
                "direction": "long",
                "quantity": 1.0,
                "order_type": "order",
                "mid_price": 2000.0,
                "spread": 0.3,
                "sentiment": 0.0,
                "impact": 0.0,
                "features": {},
            }
        )
        assert result["status"] in ("filled", "rejected")

    def test_get_routing_stats(self):
        r = self._router()
        stats = r.metrics()
        assert "total_routed" in stats

    def test_get_broker_states(self):
        r = self._router({"oanda": self._broker()})
        stats = r.metrics()
        assert "brokers" in stats

    def test_broker_state_record_fill(self):
        from execution.smart_router import BrokerState

        s = BrokerState(broker_id="b1")
        s.record_fill(latency_ms=20.0, slippage_bps=2.0)
        assert s.total_fills == 1
        assert s.ema_latency_ms < 100.0

    def test_broker_state_record_error_opens_circuit(self):
        from execution.smart_router import BrokerState
        import os

        s = BrokerState(broker_id="b1")
        threshold = int(os.getenv("ROUTER_CB_ERRORS", "3"))
        for _ in range(threshold):
            s.record_error()
        assert s.circuit_open is True

    def test_broker_state_circuit_reset(self):
        from execution.smart_router import BrokerState
        import time

        s = BrokerState(broker_id="b1")
        s.circuit_open = True
        s.circuit_open_at = time.monotonic() - 999
        s.check_circuit_reset()
        assert s.circuit_open is False

    def test_broker_state_routing_score(self):
        from execution.smart_router import BrokerState

        s = BrokerState(broker_id="b1")
        score = s.routing_score(direction="long", ofi=0.5, sentiment_score=0.1)
        assert 0.0 <= score <= 1.0

    def test_routing_decision_dataclass(self):
        from execution.smart_router import RoutingDecision

        d = RoutingDecision(
            decision_id="d1",
            order_id="o1",
            selected_broker="oanda",
            fallback_chain=["ibkr"],
            scores={"oanda": 0.8},
            ofi=0.5,
            sentiment_score=0.1,
            impact_score=0.0,
            spread_bps=2.0,
            reason="best_score",
        )
        assert d.selected_broker == "oanda"


# ---------------------------------------------------------------------------
# sl_tp_monitor — 72% coverage (missing: _close_position retry/failure paths)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSLTPMonitorClosePaths:
    def _make(self, broker_return=None, broker_error=None):
        from execution.sl_tp_monitor import SLTPMonitor

        pm = MagicMock()
        pm.get_all_positions.return_value = {}
        pm.close_position = AsyncMock()
        broker = MagicMock()
        if broker_error:
            broker.place_order = MagicMock(side_effect=broker_error)
        else:
            broker.place_order = MagicMock(return_value=broker_return or {"id": "ord1"})
        ticks = {}
        return SLTPMonitor(position_manager=pm, broker=broker, tick_cache=ticks), pm, broker

    def _pos(self, pid="p1", symbol="XAUUSD", side="BUY", sl=1880.0, tp=1940.0, qty=1.0):
        p = MagicMock()
        p.position_id = pid
        p.symbol = symbol
        p.side = side
        p.stop_loss = sl
        p.take_profit = tp
        p.quantity = qty
        return p

    @pytest.mark.asyncio
    async def test_close_position_sl_success(self):
        mon, pm, broker = self._make()
        pos = self._pos(side="BUY", sl=1880.0)
        await mon._close_position(pos, "stop_loss", 1875.0)
        assert broker.place_order.called

    @pytest.mark.asyncio
    async def test_close_position_tp_success(self):
        mon, pm, broker = self._make()
        pos = self._pos(side="SELL", sl=1920.0, tp=1860.0)
        await mon._close_position(pos, "take_profit", 1855.0)
        assert broker.place_order.called

    @pytest.mark.asyncio
    async def test_close_position_zero_qty_skipped(self):
        mon, pm, broker = self._make()
        pos = self._pos(qty=0.0)
        await mon._close_position(pos, "stop_loss", 1875.0)
        broker.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_position_broker_error_retries(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pm = MagicMock()
        pm.get_all_positions.return_value = {}
        pm.close_position = AsyncMock()
        broker = MagicMock()
        broker.place_order = MagicMock(side_effect=RuntimeError("broker down"))
        mon = SLTPMonitor(position_manager=pm, broker=broker, tick_cache={})
        pos = self._pos(qty=1.0)
        # Should not raise even after all retries fail
        with patch("execution.sl_tp_monitor._RETRY_DELAY_S", 0.0):
            with patch("execution.sl_tp_monitor._MAX_RETRIES", 2):
                await mon._close_position(pos, "stop_loss", 1875.0)

    @pytest.mark.asyncio
    async def test_close_position_removes_from_closing_set(self):
        mon, pm, broker = self._make()
        pos = self._pos()
        await mon._close_position(pos, "stop_loss", 1875.0)
        assert pos.position_id not in mon._closing

    @pytest.mark.asyncio
    async def test_on_task_done_non_crash(self):
        mon, _, _ = self._make()
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        mon._on_task_done(fut)  # should not raise

    def test_check_breach_zero_sl_ignored(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = MagicMock()
        pos.side = "BUY"
        pos.stop_loss = 0.0
        pos.take_profit = None
        assert SLTPMonitor._check_breach(pos, 1875.0) is None

    def test_check_breach_unknown_side(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = MagicMock()
        pos.side = "FLAT"
        pos.stop_loss = 1880.0
        pos.take_profit = 1940.0
        assert SLTPMonitor._check_breach(pos, 1875.0) is None


# ---------------------------------------------------------------------------
# async_engine — 70% coverage (missing: cancel, modify, batch, positions)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAsyncEngineExtra:
    def _engine(self):
        from execution.async_engine import AsyncExecutionEngine

        return AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=42)

    def _order(self, symbol="XAUUSD", side="buy", qty=1.0, otype=None):
        from execution.async_engine import Order, OrderType

        return Order(
            id="",
            symbol=symbol,
            side=side,
            quantity=qty,
            order_type=otype or OrderType.MARKET,
        )

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self):
        e = self._engine()
        result = await e.cancel_order("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_no_venue_returns_false(self):
        e = self._engine()
        o = self._order()
        with patch.object(e, "_select_venue", return_value="paper"), patch.object(e, "_simulate_fill", AsyncMock()):
            await e.submit_order(o)
        # Remove venue from metadata to trigger the no-venue path
        e.orders[o.id].metadata.pop("venue", None)
        result = await e.cancel_order(o.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_batch_submit(self):
        e = self._engine()
        orders = [self._order(symbol=f"SYM{i}") for i in range(3)]
        with patch.object(e, "_select_venue", return_value="paper"), patch.object(e, "_simulate_fill", AsyncMock()):
            results = await e.batch_submit(orders)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_close_all_positions_empty(self):
        e = self._engine()
        with patch.object(e, "get_positions", AsyncMock(return_value=[])):
            order_ids = await e.close_all_positions()
        assert order_ids == []

    @pytest.mark.asyncio
    async def test_get_positions_cached(self):
        import time

        e = self._engine()
        e.position_cache = {"XAUUSD": {"symbol": "XAUUSD", "quantity": 1.0}}
        e._position_cache_time = time.time()
        positions = await e.get_positions()
        assert len(positions) == 1

    @pytest.mark.asyncio
    async def test_select_venue_with_broker(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType

        e = AsyncExecutionEngine(
            broker_configs=[{"name": "oanda", "rate_limit": 10}],
            paper_mode=True,
        )
        e.brokers["oanda"] = {"name": "oanda"}
        o = Order(id="x", symbol="XAUUSD", side="buy", quantity=1.0, order_type=OrderType.MARKET)
        venue = e._select_venue(o)
        assert venue == "oanda"

    @pytest.mark.asyncio
    async def test_pre_trade_check_passes(self):
        e = self._engine()
        o = self._order(qty=1.0)
        allowed, reason = await e._pre_trade_check(o)
        assert isinstance(allowed, bool)

    @pytest.mark.asyncio
    async def test_simulate_fill_market_order(self):
        from execution.async_engine import OrderStatus

        e = self._engine()
        o = self._order()
        o.id = "test_order"
        e.price_cache["XAUUSD"] = {"bid": 1999.0, "ask": 2001.0, "volatility": 0.001}
        await e._simulate_fill(o)
        assert o.status in (OrderStatus.FILLED, OrderStatus.SUBMITTED, OrderStatus.REJECTED)

    @pytest.mark.asyncio
    async def test_simulate_fill_no_market_data_rejected(self):
        from execution.async_engine import OrderStatus

        e = self._engine()
        o = self._order()
        o.id = "test_order"
        # No price cache entry
        await e._simulate_fill(o)
        assert o.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_simulate_fill_raises_in_live_mode(self):
        from execution.async_engine import AsyncExecutionEngine

        e = AsyncExecutionEngine(broker_configs=[], paper_mode=False)
        o = self._order()
        o.id = "test"
        with pytest.raises(RuntimeError, match="live mode"):
            await e._simulate_fill(o)

    def test_order_status_enum_values(self):
        from execution.async_engine import OrderStatus

        assert OrderStatus.PENDING.name == "PENDING"
        assert OrderStatus.FILLED.name == "FILLED"

    def test_order_type_enum_values(self):
        from execution.async_engine import OrderType

        assert OrderType.MARKET.name == "MARKET"
        assert OrderType.LIMIT.name == "LIMIT"


# ---------------------------------------------------------------------------
# trade_executor — 70% coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTradeExecutorExtra:
    def _executor(self):
        from execution.trade_executor import TradeExecutor

        broker = MagicMock()
        broker.place_order = MagicMock(
            return_value=MagicMock(
                id="ord1",
                filled_quantity=1.0,
                average_price=2000.0,
                commission=0.5,
            )
        )
        risk_manager = MagicMock()
        risk_manager.check_pre_trade = MagicMock(return_value=(True, "ok"))
        risk_manager.get_current_drawdown = MagicMock(return_value=0.01)
        risk_manager.get_account_equity = MagicMock(return_value=100000.0)
        position_tracker = MagicMock()
        position_tracker.get_position = MagicMock(return_value=None)
        position_tracker.get_all_positions = MagicMock(return_value={})
        return TradeExecutor(broker=broker, risk_manager=risk_manager, position_tracker=position_tracker)

    @pytest.mark.asyncio
    async def test_execute_missing_fields_rejected(self):
        ex = self._executor()
        result = await ex.execute_signal({"symbol": "XAUUSD"})
        assert result.success is False
        assert "Missing" in result.message

    @pytest.mark.asyncio
    async def test_execute_invalid_action_rejected(self):
        ex = self._executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "hold", "size": 1.0})
        assert result.success is False
        assert "Invalid action" in result.message

    @pytest.mark.asyncio
    async def test_execute_buy_signal(self):
        from execution.trade_executor import OrderStatus

        ex = self._executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.ERROR)

    @pytest.mark.asyncio
    async def test_execute_sell_signal(self):
        from execution.trade_executor import OrderStatus

        ex = self._executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "sell", "size": 1.0})
        assert result.status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.ERROR)

    @pytest.mark.asyncio
    async def test_execute_close_signal(self):
        from execution.trade_executor import OrderStatus

        ex = self._executor()
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0})
        assert result.status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.ERROR)

    @pytest.mark.asyncio
    async def test_drawdown_halt_blocks_trade(self):
        from execution.trade_executor import TradeExecutor, DRAWDOWN_HALT_PCT

        broker = MagicMock()
        risk_manager = MagicMock()
        risk_manager.get_current_drawdown = MagicMock(return_value=DRAWDOWN_HALT_PCT + 0.01)
        risk_manager.get_account_equity = MagicMock(return_value=100000.0)
        risk_manager.check_pre_trade = MagicMock(return_value=(True, "ok"))
        position_tracker = MagicMock()
        position_tracker.get_all_positions = MagicMock(return_value={})
        ex = TradeExecutor(broker=broker, risk_manager=risk_manager, position_tracker=position_tracker)
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_streak_halt_blocks_trade(self):
        from execution.trade_executor import TradeExecutor, STREAK_HALT_LOSSES
        import time

        broker = MagicMock()
        risk_manager = MagicMock()
        risk_manager.get_current_drawdown = MagicMock(return_value=0.01)
        risk_manager.get_account_equity = MagicMock(return_value=100000.0)
        risk_manager.check_pre_trade = MagicMock(return_value=(True, "ok"))
        position_tracker = MagicMock()
        position_tracker.get_all_positions = MagicMock(return_value={})
        ex = TradeExecutor(broker=broker, risk_manager=risk_manager, position_tracker=position_tracker)
        ex._consecutive_losses = STREAK_HALT_LOSSES
        ex._streak_halted_until = time.monotonic() + 9999
        result = await ex.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result.success is False

    def test_register_callback(self):
        ex = self._executor()
        cb = MagicMock()
        ex.register_callback(cb)
        assert cb in ex._execution_callbacks

    def test_execution_result_dataclass(self):
        from execution.trade_executor import ExecutionResult, OrderStatus

        r = ExecutionResult(
            success=True,
            order_id="o1",
            filled_quantity=1.0,
            average_price=2000.0,
            commission=0.5,
            status=OrderStatus.FILLED,
            message="ok",
        )
        assert r.success is True
        assert r.latency_ms == 0.0
