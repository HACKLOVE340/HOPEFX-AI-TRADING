# tests/unit/test_execution_coverage7.py
"""Coverage tests for execution/tca.py — TCAEngine, MarketImpactModel, MarketContextProvider."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

UTC = timezone.utc


def _make_fill(price=2350.0, qty=0.1, commission=0.5, ts=None, side=None):
    from core.types import Fill, Side, Venue

    return Fill(
        order_id="ord1",
        fill_id="fill1",
        symbol="XAUUSD",
        side=side or Side.BUY,
        price=Decimal(str(price)),
        quantity=Decimal(str(qty)),
        commission=Decimal(str(commission)),
        timestamp=ts or datetime.now(UTC),
        venue=Venue.PAPER,
    )


def _make_tick(symbol="XAUUSD", bid=2349.0, ask=2351.0):
    from core.types import Tick, Venue

    mid = (bid + ask) / 2
    return Tick(
        symbol=symbol,
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        mid=Decimal(str(mid)),
        timestamp=datetime.now(UTC),
        venue=Venue.PAPER,
    )


class TestMarketImpactModel:
    def test_calculate_returns_two_decimals(self):
        from execution.tca import MarketImpactModel

        m = MarketImpactModel()
        temp, perm = m.calculate(
            order_size=Decimal("100"),
            avg_daily_volume=Decimal("50000"),
            volatility=0.012,
            spread_bps=2.0,
        )
        assert isinstance(temp, Decimal)
        assert isinstance(perm, Decimal)
        assert temp >= 0
        assert perm >= 0

    def test_zero_adv_no_crash(self):
        from execution.tca import MarketImpactModel

        m = MarketImpactModel()
        temp, perm = m.calculate(
            order_size=Decimal("100"),
            avg_daily_volume=Decimal("0"),
            volatility=0.012,
            spread_bps=2.0,
        )
        assert temp >= 0

    def test_perm_is_fraction_of_temp(self):
        from execution.tca import MarketImpactModel

        m = MarketImpactModel()
        temp, perm = m.calculate(
            order_size=Decimal("1000"),
            avg_daily_volume=Decimal("50000"),
            volatility=0.015,
            spread_bps=3.0,
        )
        # perm ≈ 10% of temp
        assert float(perm) == pytest.approx(float(temp) * 0.1, rel=0.01)


class TestTCAMetrics:
    def test_total_cost_bps_zero_fill_price(self):
        from core.types import Side
        from execution.tca import TCAMetrics

        m = TCAMetrics(
            order_id="o1",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
            arrival_time=datetime.now(UTC),
            avg_fill_price=Decimal("0"),
            implementation_shortfall_bps=Decimal("5"),
        )
        # avg_fill_price=0 → returns isf only
        assert m.total_cost_bps == Decimal("5")

    def test_total_cost_bps_with_fees(self):
        from core.types import Side
        from execution.tca import TCAMetrics

        m = TCAMetrics(
            order_id="o2",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
            arrival_time=datetime.now(UTC),
            avg_fill_price=Decimal("2350"),
            implementation_shortfall_bps=Decimal("5"),
            total_fees=Decimal("1"),
        )
        assert m.total_cost_bps > Decimal("5")

    def test_alpha_extraction_bps_zero(self):
        from core.types import Side
        from execution.tca import TCAMetrics

        m = TCAMetrics(
            order_id="o3",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
            arrival_time=datetime.now(UTC),
        )
        assert m.alpha_extraction_bps == Decimal("0")

    def test_to_dict_keys(self):
        from core.types import Side
        from execution.tca import TCAMetrics

        m = TCAMetrics(
            order_id="o4",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
            arrival_time=datetime.now(UTC),
        )
        d = m.to_dict()
        assert "order_id" in d
        assert "implementation_shortfall_bps" in d
        assert "adv_source" in d


class TestMarketContextProvider:
    def test_get_adv_env_override(self, monkeypatch):
        monkeypatch.setenv("TCA_ADV_XAUUSD", "99999")
        from importlib import reload

        import execution.tca as tca_mod

        reload(tca_mod)
        ctx = tca_mod.MarketContextProvider()
        adv, source = ctx.get_adv("XAUUSD")
        assert adv == pytest.approx(99999.0)
        assert "env" in source

    def test_get_adv_default_fallback(self):
        from execution.tca import MarketContextProvider

        ctx = MarketContextProvider()
        adv, source = ctx.get_adv("UNKNOWN_SYMBOL_XYZ")
        assert adv > 0
        assert source in ("default", "env_global")

    def test_get_volatility_env_override(self, monkeypatch):
        monkeypatch.setenv("TCA_VOL_XAUUSD", "0.025")
        from importlib import reload

        import execution.tca as tca_mod

        reload(tca_mod)
        ctx = tca_mod.MarketContextProvider()
        vol, source = ctx.get_volatility("XAUUSD")
        assert vol == pytest.approx(0.025)
        assert "env" in source

    def test_get_volatility_default_fallback(self):
        from execution.tca import MarketContextProvider

        ctx = MarketContextProvider()
        vol, source = ctx.get_volatility("UNKNOWN_SYMBOL_XYZ")
        assert vol > 0

    def test_accumulate_tick(self):
        from execution.tca import MarketContextProvider

        ctx = MarketContextProvider()
        ctx.accumulate_tick("XAUUSD", volume=1000.0, ts=datetime.now(UTC))
        ctx.accumulate_tick("XAUUSD", volume=2000.0, ts=datetime.now(UTC))
        # After accumulation, in-memory source should be available
        adv, source = ctx.get_adv("XAUUSD")
        assert adv > 0


class TestTCAEngine:
    def _engine(self):
        from execution.tca import TCAEngine

        return TCAEngine()

    @pytest.mark.asyncio
    async def test_start_order_tracking(self):
        from core.types import Side
        from execution.tca import BenchmarkType

        engine = self._engine()
        await engine.start_order(
            order_id="ord1",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
            benchmark=BenchmarkType.ARRIVAL,
        )
        assert "ord1" in engine._active_orders

    @pytest.mark.asyncio
    async def test_record_fill(self):
        from core.types import Side

        engine = self._engine()
        await engine.start_order(
            order_id="ord2",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
        )
        fill = _make_fill(price=2351.0, qty=0.5)
        await engine.record_fill("ord2", fill)
        assert len(engine._active_orders["ord2"]["fills"]) == 1

    @pytest.mark.asyncio
    async def test_record_fill_unknown_order(self):
        engine = self._engine()
        fill = _make_fill()
        # Should not raise
        await engine.record_fill("nonexistent", fill)

    @pytest.mark.asyncio
    async def test_complete_order_buy_isf(self):
        from core.types import Side

        engine = self._engine()
        await engine.start_order(
            order_id="ord3",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
        )
        await engine.record_fill("ord3", _make_fill(price=2355.0, qty=1.0))
        metrics = await engine.complete_order("ord3")
        assert metrics is not None
        assert metrics.implementation_shortfall_bps > 0

    @pytest.mark.asyncio
    async def test_complete_order_sell_isf(self):
        from core.types import Side

        engine = self._engine()
        await engine.start_order(
            order_id="ord4",
            symbol="XAUUSD",
            side=Side.SELL,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
        )
        await engine.record_fill("ord4", _make_fill(price=2345.0, qty=1.0, side=Side.SELL))
        metrics = await engine.complete_order("ord4")
        assert metrics is not None
        assert metrics.implementation_shortfall_bps > 0

    @pytest.mark.asyncio
    async def test_complete_order_no_fills_returns_cancelled(self):
        from core.types import Side

        engine = self._engine()
        await engine.start_order(
            order_id="ord5",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2350"),
        )
        # complete with CANCELLED status to avoid ValueError on no fills
        metrics = await engine.complete_order("ord5", status="CANCELLED")
        assert metrics is not None
        assert metrics.fill_rate == 0.0

    @pytest.mark.asyncio
    async def test_complete_unknown_order_raises(self):
        engine = self._engine()
        with pytest.raises(ValueError, match="Unknown order"):
            await engine.complete_order("nonexistent")

    def test_get_stats_empty(self):
        engine = self._engine()
        stats = engine.get_stats()
        assert stats == {}

    @pytest.mark.asyncio
    async def test_get_stats_after_trade(self):
        from core.types import Side

        engine = self._engine()
        await engine.start_order("ord6", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2350"))
        await engine.record_fill("ord6", _make_fill(price=2351.0, qty=1.0))
        await engine.complete_order("ord6")
        stats = engine.get_stats()
        assert stats["count"] == 1
        assert "mean_cost_bps" in stats

    def test_update_market_data(self):
        engine = self._engine()
        tick = _make_tick()
        engine.update_market_data(tick)
        assert "XAUUSD" in engine._vwap_cache

    @pytest.mark.asyncio
    async def test_cost_callback_fires_on_expensive_trade(self):
        from core.types import Side

        fired = []
        engine = self._engine()
        engine._cost_callbacks.append(lambda m: fired.append(m))
        await engine.start_order("ord7", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2350"))
        await engine.record_fill("ord7", _make_fill(price=2360.0, qty=1.0))
        await engine.complete_order("ord7")
        assert len(fired) == 1

    @pytest.mark.asyncio
    async def test_partial_fill_opportunity_cost(self):
        from core.types import Side

        engine = self._engine()
        await engine.start_order("ord8", "XAUUSD", Side.BUY, Decimal("2"), Decimal("2350"))
        await engine.record_fill("ord8", _make_fill(price=2351.0, qty=1.0))
        metrics = await engine.complete_order("ord8")
        assert metrics.fill_rate == pytest.approx(0.5)
        assert metrics.opportunity_cost_bps >= 0

    @pytest.mark.asyncio
    async def test_window_size_respected(self):
        from core.types import Side

        engine = self._engine()
        engine.window_size = 3
        for i in range(5):
            oid = f"ord_w{i}"
            await engine.start_order(oid, "XAUUSD", Side.BUY, Decimal("1"), Decimal("2350"))
            await engine.record_fill(oid, _make_fill(price=2351.0, qty=1.0))
            await engine.complete_order(oid)
        assert len(engine._completed) <= 3
