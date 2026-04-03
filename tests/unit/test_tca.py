# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_tca.py
======================
Unit tests for TCA module:
  - execution/tca_recorder.py  (TCARecorder, TCARecord, TCAReport)
  - execution/tca.py           (TCAEngine, MarketContextProvider, MarketImpactModel)
  - execution/market_impact.py (AlmgrenChrissModel, FillSimulator)
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):  # Python 3.10 compat
        pass
UTC = timezone.utc
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# ── Python 3.10 StrEnum shim ─────────────────────────────────────────────────
if not hasattr(enum, "StrEnum"):

    class _StrEnum(str, enum.Enum):  # type: ignore[no-redef]
        """Backport of enum.StrEnum for Python < 3.11."""

    enum.StrEnum = _StrEnum  # type: ignore[attr-defined]

# ─────────────────────────────────────────────────────────────────────────────
# TCARecorder tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTCARecord:
    def _make_record(self, side="BUY", signal=2000.0, fill=2001.0):
        from execution.tca_recorder import TCARecord

        now = datetime.now(UTC)
        return TCARecord(
            request_id="req1",
            symbol="XAU_USD",
            side=side,
            signal_price=signal,
            fill_price=fill,
            filled_quantity=1.0,
            broker="oanda",
            latency_ms=42.0,
            model_version="v1",
            session="london",
            signal_time=now,
            fill_time=now,
        )

    def test_slippage_bps_buy_adverse(self):
        r = self._make_record("BUY", 2000.0, 2001.0)
        # BUY: paid more → positive slippage
        assert r.slippage_bps == pytest.approx(5.0, rel=0.01)

    def test_slippage_bps_buy_improvement(self):
        r = self._make_record("BUY", 2000.0, 1999.0)
        # BUY: paid less → negative slippage (price improvement)
        assert r.slippage_bps == pytest.approx(-5.0, rel=0.01)

    def test_slippage_bps_sell_adverse(self):
        r = self._make_record("SELL", 2000.0, 1999.0)
        # SELL: received less → positive (adverse)
        assert r.slippage_bps == pytest.approx(5.0, rel=0.01)

    def test_slippage_bps_sell_improvement(self):
        r = self._make_record("SELL", 2000.0, 2001.0)
        # SELL: received more → negative (improvement)
        assert r.slippage_bps == pytest.approx(-5.0, rel=0.01)

    def test_slippage_usd(self):
        r = self._make_record("BUY", 2000.0, 2001.0)
        assert r.slippage_usd == pytest.approx(1.0, rel=0.01)

    def test_zero_signal_price(self):
        r = self._make_record("BUY", 0.0, 1.0)
        assert r.slippage_bps == 0.0

    def test_to_dict_keys(self):
        r = self._make_record()
        d = r.to_dict()
        for key in (
            "request_id",
            "symbol",
            "side",
            "slippage_bps",
            "broker",
            "latency_ms",
        ):
            assert key in d

    def test_signal_to_fill_ms_non_negative(self):
        r = self._make_record()
        assert r.signal_to_fill_ms >= 0.0


class TestTCARecorder:
    def setup_method(self):
        from execution.tca_recorder import TCARecorder

        self.recorder = TCARecorder()

    def test_record_fill_without_signal_returns_none(self):
        result = self.recorder.record_fill("missing_req", 2001.0, 1.0, "oanda", 10.0)
        assert result is None

    def test_record_signal_then_fill_returns_record(self):
        self.recorder.record_signal("req1", "XAU_USD", "BUY", 2000.0, 1.0, "v1")
        rec = self.recorder.record_fill("req1", 2001.0, 1.0, "oanda", 42.0)
        assert rec is not None
        assert rec.symbol == "XAU_USD"
        assert rec.broker == "oanda"
        assert rec.slippage_bps == pytest.approx(5.0, rel=0.01)

    def test_pending_signal_consumed_after_fill(self):
        self.recorder.record_signal("req2", "EUR_USD", "SELL", 1.1000, 1.0, "v1")
        self.recorder.record_fill("req2", 1.0995, 1.0, "ibkr", 20.0)
        # Second fill for same request_id should return None
        result = self.recorder.record_fill("req2", 1.0995, 1.0, "ibkr", 20.0)
        assert result is None

    def test_get_report_returns_none_when_empty(self):
        report = self.recorder.get_report(broker="oanda")
        assert report is None

    def test_get_report_after_fills(self):
        for i in range(5):
            rid = f"req_{i}"
            self.recorder.record_signal(rid, "XAU_USD", "BUY", 2000.0, 1.0, "v1")
            self.recorder.record_fill(rid, 2000.5, 1.0, "oanda", 30.0)
        report = self.recorder.get_report(broker="oanda")
        assert report is not None
        assert report.n_trades == 5
        assert report.mean_slippage_bps == pytest.approx(2.5, rel=0.01)

    def test_get_report_filters_by_symbol(self):
        self.recorder.record_signal("r1", "XAU_USD", "BUY", 2000.0, 1.0, "v1")
        self.recorder.record_fill("r1", 2001.0, 1.0, "oanda", 10.0)
        self.recorder.record_signal("r2", "EUR_USD", "BUY", 1.1, 1.0, "v1")
        self.recorder.record_fill("r2", 1.1001, 1.0, "oanda", 10.0)
        report = self.recorder.get_report(broker="oanda", symbol="XAU_USD")
        assert report is not None
        assert report.n_trades == 1

    def test_get_recent_records_order(self):
        for i in range(3):
            rid = f"r{i}"
            self.recorder.record_signal(rid, "XAU_USD", "BUY", 2000.0, 1.0, "v1")
            self.recorder.record_fill(rid, 2001.0, 1.0, "oanda", 10.0)
        records = self.recorder.get_recent_records(n=3)
        assert len(records) == 3
        # Most recent first
        assert records[0]["request_id"] == "r2"

    def test_is_fill_quality_degraded_false_when_few_fills(self):
        self.recorder.record_signal("r1", "XAU_USD", "BUY", 2000.0, 1.0, "v1")
        self.recorder.record_fill("r1", 2001.0, 1.0, "oanda", 10.0)
        assert self.recorder.is_fill_quality_degraded("oanda") is False

    def test_is_fill_quality_degraded_true_above_threshold(self):
        # Fill at 10x threshold slippage for 15 trades
        for i in range(15):
            rid = f"r{i}"
            self.recorder.record_signal(rid, "XAU_USD", "BUY", 2000.0, 1.0, "v1")
            # 50 bps slippage — well above default 5 bps threshold
            self.recorder.record_fill(rid, 2010.0, 1.0, "bad_broker", 10.0)
        assert self.recorder.is_fill_quality_degraded("bad_broker") is True

    def test_get_all_reports_multi_broker(self):
        for broker in ("oanda", "ibkr"):
            for i in range(3):
                rid = f"{broker}_{i}"
                self.recorder.record_signal(rid, "XAU_USD", "BUY", 2000.0, 1.0, "v1")
                self.recorder.record_fill(rid, 2001.0, 1.0, broker, 10.0)
        reports = self.recorder.get_all_reports()
        brokers = {r.broker for r in reports}
        assert "oanda" in brokers
        assert "ibkr" in brokers

    def test_session_classification(self):
        from execution.tca_recorder import TCARecorder

        assert TCARecorder._get_session(datetime(2024, 1, 1, 10, 0, tzinfo=UTC)) == "london"
        assert TCARecorder._get_session(datetime(2024, 1, 1, 15, 0, tzinfo=UTC)) in ("london", "new_york")
        assert TCARecorder._get_session(datetime(2024, 1, 1, 3, 0, tzinfo=UTC)) == "asia"

    def test_report_alert_triggered(self):
        for i in range(15):
            rid = f"r{i}"
            self.recorder.record_signal(rid, "XAU_USD", "BUY", 2000.0, 1.0, "v1")
            self.recorder.record_fill(rid, 2010.0, 1.0, "bad_broker", 10.0)
        report = self.recorder.get_report(broker="bad_broker")
        assert report is not None
        assert report.alert_triggered is True

    def test_report_no_alert_below_threshold(self):
        for i in range(5):
            rid = f"r{i}"
            self.recorder.record_signal(rid, "XAU_USD", "BUY", 2000.0, 1.0, "v1")
            self.recorder.record_fill(rid, 2000.05, 1.0, "good_broker", 10.0)
        report = self.recorder.get_report(broker="good_broker")
        assert report is not None
        assert report.alert_triggered is False


# ─────────────────────────────────────────────────────────────────────────────
# AlmgrenChrissModel tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAlmgrenChrissModel:
    def setup_method(self):
        from execution.market_impact import AlmgrenChrissModel

        self.model = AlmgrenChrissModel()

    def test_zero_adv_returns_spread_only(self):
        est = self.model.estimate(100, 0, 0.012, 3.0, 2000.0)
        assert est.temporary_impact_bps == 0.0
        assert est.permanent_impact_bps == 0.0
        assert est.spread_cost_bps > 0

    def test_larger_order_higher_impact(self):
        small = self.model.estimate(100, 10000, 0.012, 3.0, 2000.0)
        large = self.model.estimate(1000, 10000, 0.012, 3.0, 2000.0)
        assert large.temporary_impact_bps > small.temporary_impact_bps

    def test_higher_vol_higher_impact(self):
        low_vol = self.model.estimate(100, 10000, 0.005, 3.0, 2000.0)
        high_vol = self.model.estimate(100, 10000, 0.030, 3.0, 2000.0)
        assert high_vol.temporary_impact_bps > low_vol.temporary_impact_bps

    def test_participation_cap(self):
        # Order larger than ADV should be capped at max_participation
        est = self.model.estimate(100000, 1000, 0.012, 3.0, 2000.0)
        assert est.participation_rate <= self.model.max_participation

    def test_fill_price_buy_above_signal(self):
        est = self.model.estimate(100, 10000, 0.012, 3.0, 2000.0)
        assert est.fill_price("BUY") > 2000.0

    def test_fill_price_sell_below_signal(self):
        est = self.model.estimate(100, 10000, 0.012, 3.0, 2000.0)
        assert est.fill_price("SELL") < 2000.0

    def test_total_cost_usd_positive(self):
        est = self.model.estimate(100, 10000, 0.012, 3.0, 2000.0)
        assert est.total_cost_usd > 0

    def test_slippage_bps_alias(self):
        est = self.model.estimate(100, 10000, 0.012, 3.0, 2000.0)
        assert est.slippage_bps == est.total_impact_bps


class TestFillSimulator:
    def setup_method(self):
        from execution.market_impact import FillSimulator

        self.sim = FillSimulator()

    def test_buy_fill_above_signal(self):
        fill = self.sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=10,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=5000,
            adv=10000,
            volatility_daily=0.012,
        )
        assert fill.fill_price >= 2000.0

    def test_sell_fill_below_signal(self):
        fill = self.sim.simulate_fill(
            signal_price=2000.0,
            side="SELL",
            quantity=10,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=5000,
            adv=10000,
            volatility_daily=0.012,
        )
        assert fill.fill_price <= 2000.0

    def test_fill_clamped_to_bar_range_buy(self):
        fill = self.sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=10,
            bar_high=2001.0,
            bar_low=1999.0,
            bar_volume=5000,
            adv=10000,
            volatility_daily=0.012,
        )
        assert fill.fill_price <= 2001.0

    def test_partial_fill_when_order_exceeds_liquidity(self):
        fill = self.sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=10000,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=100,
            adv=10000,
            volatility_daily=0.012,
        )
        assert fill.partial_fill is True
        assert fill.fill_quantity < 10000

    def test_no_partial_fill_small_order(self):
        fill = self.sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=1,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=100000,
            adv=10000,
            volatility_daily=0.012,
        )
        assert fill.partial_fill is False
        assert fill.fill_quantity == 1

    def test_slippage_non_negative(self):
        fill = self.sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=10,
            bar_high=2005.0,
            bar_low=1995.0,
            bar_volume=5000,
            adv=10000,
            volatility_daily=0.012,
        )
        assert fill.slippage_bps >= 0.0
        assert fill.slippage_usd >= 0.0

    def test_batch_simulate(self):
        signals = [
            {
                "signal_price": 2000.0,
                "side": "BUY",
                "quantity": 10,
                "bar_high": 2005.0,
                "bar_low": 1995.0,
                "bar_volume": 5000,
            }
            for _ in range(5)
        ]
        fills = self.sim.simulate_fills_batch(signals, adv=10000, volatility_daily=0.012)
        assert len(fills) == 5

    def test_get_fill_simulator_singleton(self):
        from execution.market_impact import get_fill_simulator

        a = get_fill_simulator()
        b = get_fill_simulator()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# MarketContextProvider tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMarketContextProvider:
    def setup_method(self):
        from execution.tca import MarketContextProvider

        self.ctx = MarketContextProvider()

    def test_default_adv_when_no_data(self):
        adv, source = self.ctx.get_adv("XAU_USD")
        assert adv > 0
        assert source in ("default", "env_override")

    def test_default_vol_when_no_data(self):
        vol, source = self.ctx.get_volatility("XAU_USD")
        assert 0 < vol < 1
        assert source in ("default", "env_override")

    def test_env_override_adv(self, monkeypatch):
        monkeypatch.setenv("TCA_ADV_XAU_USD", "75000")
        adv, source = self.ctx.get_adv("XAU_USD")
        assert adv == pytest.approx(75000.0)
        assert source == "env_override"

    def test_env_override_vol(self, monkeypatch):
        monkeypatch.setenv("TCA_VOL_XAU_USD", "0.008")
        vol, source = self.ctx.get_volatility("XAU_USD")
        assert vol == pytest.approx(0.008)
        assert source == "env_override"

    def test_tick_accumulator_adv(self):
        from datetime import timedelta

        now = datetime.now(UTC)
        # Simulate 200 ticks over 2 hours with volume=100 each
        for i in range(200):
            ts = now - timedelta(hours=2) + timedelta(seconds=i * 36)
            self.ctx.accumulate_tick("XAU_USD", 100.0, ts)
        adv, source = self.ctx.get_adv("XAU_USD")
        assert source == "tick_accumulator"
        # 200 ticks × 100 vol over 2h → ~240,000 daily
        assert adv > 0

    def test_redis_ohlcv_adv(self):
        # Mock Redis cache returning bars
        mock_cache = MagicMock()
        mock_cache.get_bars.return_value = [
            {"volume": 50000, "close": 2000.0},
            {"volume": 60000, "close": 2001.0},
            {"volume": 55000, "close": 1999.0},
            {"volume": 52000, "close": 2002.0},
            {"volume": 48000, "close": 2000.5},
        ]
        self.ctx._redis_cache = mock_cache
        adv, source = self.ctx.get_adv("XAU_USD")
        assert source == "redis_ohlcv"
        assert adv == pytest.approx(53000.0, rel=0.01)

    def test_redis_ohlcv_vol(self):
        mock_cache = MagicMock()
        closes = [2000.0, 2010.0, 1990.0, 2005.0, 1995.0, 2008.0]
        mock_cache.get_bars.return_value = [{"close": c} for c in closes]
        self.ctx._redis_cache = mock_cache
        vol, source = self.ctx.get_vol = self.ctx.get_volatility("XAU_USD")
        # Just check it returns a reasonable value
        assert source == "redis_ohlcv"
        assert 0 < vol < 0.5


# ─────────────────────────────────────────────────────────────────────────────
# TCAEngine tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTCAEngine:
    def setup_method(self):
        # Patch StrEnum before importing tca module
        from execution.tca import MarketContextProvider, TCAEngine

        ctx = MarketContextProvider()
        self.engine = TCAEngine(market_context=ctx)

    def _make_fill(self, price=2001.0, qty=1.0):
        """Create a minimal fill-like object without importing core.types."""
        fill = MagicMock()
        fill.price = Decimal(str(price))
        fill.quantity = Decimal(str(qty))
        fill.commission = Decimal("0.5")
        fill.slippage = Decimal("0.1")
        fill.timestamp = datetime.now(UTC)
        return fill

    @pytest.mark.asyncio
    async def test_start_and_complete_order(self):
        from execution.tca import BenchmarkType, Side

        await self.engine.start_order(
            "ord1",
            "XAU_USD",
            Side.BUY,
            Decimal("1.0"),
            Decimal("2000.0"),
            BenchmarkType.ARRIVAL,
        )
        fill = self._make_fill(2001.0, 1.0)
        await self.engine.record_fill("ord1", fill)
        metrics = await self.engine.complete_order("ord1")
        assert metrics.order_id == "ord1"
        assert metrics.fill_rate == pytest.approx(1.0)
        assert metrics.avg_fill_price == Decimal("2001.0")

    @pytest.mark.asyncio
    async def test_implementation_shortfall_buy(self):
        from execution.tca import BenchmarkType, Side

        await self.engine.start_order(
            "ord2",
            "XAU_USD",
            Side.BUY,
            Decimal("1.0"),
            Decimal("2000.0"),
            BenchmarkType.ARRIVAL,
        )
        fill = self._make_fill(2010.0, 1.0)
        await self.engine.record_fill("ord2", fill)
        metrics = await self.engine.complete_order("ord2")
        # Paid more than arrival → positive ISF
        assert metrics.implementation_shortfall_bps > 0

    @pytest.mark.asyncio
    async def test_implementation_shortfall_sell(self):
        from execution.tca import BenchmarkType, Side

        await self.engine.start_order(
            "ord3",
            "XAU_USD",
            Side.SELL,
            Decimal("1.0"),
            Decimal("2000.0"),
            BenchmarkType.ARRIVAL,
        )
        fill = self._make_fill(1990.0, 1.0)
        await self.engine.record_fill("ord3", fill)
        metrics = await self.engine.complete_order("ord3")
        # Received less than arrival → positive ISF
        assert metrics.implementation_shortfall_bps > 0

    @pytest.mark.asyncio
    async def test_complete_unknown_order_raises(self):
        with pytest.raises(ValueError, match="Unknown order"):
            await self.engine.complete_order("nonexistent")

    @pytest.mark.asyncio
    async def test_cancelled_order_zero_fill_rate(self):
        from execution.tca import BenchmarkType, Side

        await self.engine.start_order(
            "ord4",
            "XAU_USD",
            Side.BUY,
            Decimal("1.0"),
            Decimal("2000.0"),
            BenchmarkType.ARRIVAL,
        )
        # No fills — complete immediately
        metrics = await self.engine.complete_order("ord4", status="CANCELLED")
        assert metrics.fill_rate == 0.0

    @pytest.mark.asyncio
    async def test_cost_callback_fired_on_expensive_trade(self):
        from execution.tca import BenchmarkType, Side

        fired = []
        self.engine.register_cost_callback(fired.append)
        await self.engine.start_order(
            "ord5",
            "XAU_USD",
            Side.BUY,
            Decimal("1.0"),
            Decimal("2000.0"),
            BenchmarkType.ARRIVAL,
        )
        # 100 bps slippage → total_cost_bps > 20 threshold
        fill = self._make_fill(2020.0, 1.0)
        await self.engine.record_fill("ord5", fill)
        await self.engine.complete_order("ord5")
        assert len(fired) == 1

    @pytest.mark.asyncio
    async def test_get_stats_empty(self):
        stats = self.engine.get_stats()
        assert stats == {}

    @pytest.mark.asyncio
    async def test_get_stats_after_trades(self):
        from execution.tca import BenchmarkType, Side

        for i in range(5):
            oid = f"s{i}"
            await self.engine.start_order(
                oid,
                "XAU_USD",
                Side.BUY,
                Decimal("1.0"),
                Decimal("2000.0"),
                BenchmarkType.ARRIVAL,
            )
            fill = self._make_fill(2001.0, 1.0)
            await self.engine.record_fill(oid, fill)
            await self.engine.complete_order(oid)
        stats = self.engine.get_stats()
        assert stats["count"] == 5
        assert "mean_cost_bps" in stats
        assert "adv_source_breakdown" in stats

    @pytest.mark.asyncio
    async def test_adv_source_recorded_in_metrics(self):
        from execution.tca import BenchmarkType, Side

        await self.engine.start_order(
            "ord6",
            "XAU_USD",
            Side.BUY,
            Decimal("1.0"),
            Decimal("2000.0"),
            BenchmarkType.ARRIVAL,
        )
        fill = self._make_fill(2001.0, 1.0)
        await self.engine.record_fill("ord6", fill)
        metrics = await self.engine.complete_order("ord6")
        assert metrics.adv_source in (
            "default",
            "env_override",
            "redis_ohlcv",
            "tick_accumulator",
        )
        assert metrics.vol_source in ("default", "env_override", "redis_ohlcv")
        assert metrics.adv_used > 0
        assert metrics.volatility_used > 0

    def test_update_market_data_feeds_context(self):
        tick = MagicMock()
        tick.symbol = "XAU_USD"
        tick.mid = Decimal("2000.0")
        tick.volume = Decimal("500.0")
        self.engine.update_market_data(tick)
        # Tick should be in VWAP cache
        assert "XAU_USD" in self.engine._vwap_cache
        assert len(self.engine._vwap_cache["XAU_USD"]) == 1
