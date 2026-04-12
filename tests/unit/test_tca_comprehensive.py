# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Comprehensive tests for execution/tca.py."""

from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
import pytest
from execution.tca import (
    BenchmarkType,
    MarketContextProvider,
    MarketImpactModel,
    TCAEngine,
    TCAMetrics,
)

UTC = timezone.utc

# ── helpers ────────────────────────────────────────────────────────────────────


def _fill(price=2005.0, qty=1.0, commission=0.5):
    from execution.tca import Fill, Side
    from core.types import Venue

    return Fill(
        order_id="o1",
        fill_id="f1",
        symbol="XAUUSD",
        side=Side.BUY,
        price=Decimal(str(price)),
        quantity=Decimal(str(qty)),
        commission=Decimal(str(commission)),
        timestamp=datetime.now(UTC),
        venue=Venue.PAPER,
    )


def _engine():
    return TCAEngine()


# ── MarketImpactModel ──────────────────────────────────────────────────────────


class TestMarketImpactModel:
    def test_calculate_returns_tuple(self):
        m = MarketImpactModel()
        result = m.calculate(Decimal("1"), Decimal("50000"), 0.012, 2.0)
        assert isinstance(result, tuple) and len(result) == 2

    def test_calculate_zero_adv_returns_zero(self):
        m = MarketImpactModel()
        temp, perm = m.calculate(Decimal("1"), Decimal("0"), 0.012, 2.0)
        assert temp == Decimal(0) and perm == Decimal(0)

    def test_calculate_zero_size_returns_zero(self):
        m = MarketImpactModel()
        temp, perm = m.calculate(Decimal("0"), Decimal("50000"), 0.012, 2.0)
        assert temp == Decimal(0) and perm == Decimal(0)

    def test_calculate_larger_order_higher_impact(self):
        m = MarketImpactModel()
        small, _ = m.calculate(Decimal("1"), Decimal("50000"), 0.012, 2.0)
        large, _ = m.calculate(Decimal("100"), Decimal("50000"), 0.012, 2.0)
        assert large >= small

    def test_calculate_higher_volatility_higher_impact(self):
        m = MarketImpactModel()
        low, _ = m.calculate(Decimal("10"), Decimal("50000"), 0.005, 2.0)
        high, _ = m.calculate(Decimal("10"), Decimal("50000"), 0.05, 2.0)
        assert high >= low

    def test_perm_impact_less_than_temp(self):
        m = MarketImpactModel()
        temp, perm = m.calculate(Decimal("10"), Decimal("50000"), 0.012, 2.0)
        assert perm <= temp


# ── TCAMetrics ─────────────────────────────────────────────────────────────────


class TestTCAMetrics:
    def _make(self):
        from execution.tca import Side

        return TCAMetrics(
            order_id="o1",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2000"),
            arrival_time=datetime.now(UTC),
            implementation_shortfall_bps=Decimal("2.5"),
            market_impact_bps=Decimal("1.0"),
            total_fees=Decimal("0.5"),
            avg_fill_price=Decimal("2005"),
        )

    def test_total_cost_bps_is_decimal(self):
        m = self._make()
        assert isinstance(m.total_cost_bps, Decimal)

    def test_alpha_extraction_bps_is_decimal(self):
        m = self._make()
        assert isinstance(m.alpha_extraction_bps, Decimal)

    def test_to_dict_has_required_keys(self):
        m = self._make()
        d = m.to_dict()
        for k in ("order_id", "symbol", "side", "quantity", "arrival_price", "avg_fill_price", "total_cost_bps"):
            assert k in d

    def test_to_dict_symbol_value(self):
        m = self._make()
        assert m.to_dict()["symbol"] == "XAUUSD"

    def test_to_dict_fill_rate(self):
        m = self._make()
        assert "fill_rate" in m.to_dict()

    def test_zero_avg_fill_price_total_cost(self):
        from execution.tca import Side

        m = TCAMetrics(
            order_id="o2",
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("1"),
            arrival_price=Decimal("2000"),
            arrival_time=datetime.now(UTC),
            implementation_shortfall_bps=Decimal("3"),
            avg_fill_price=Decimal("0"),
        )
        # Should return implementation_shortfall_bps when avg_fill_price == 0
        assert m.total_cost_bps == Decimal("3")


# ── MarketContextProvider ──────────────────────────────────────────────────────


class TestMarketContextProvider:
    def test_get_adv_returns_positive(self):
        mcp = MarketContextProvider()
        adv, source = mcp.get_adv("XAUUSD")
        assert adv > 0 and isinstance(source, str)

    def test_get_adv_env_override(self, monkeypatch):
        monkeypatch.setenv("TCA_ADV_XAUUSD", "77777")
        mcp = MarketContextProvider()
        adv, source = mcp.get_adv("XAUUSD")
        assert adv > 0

    def test_get_adv_unknown_symbol_uses_default(self):
        mcp = MarketContextProvider()
        adv, source = mcp.get_adv("UNKNOWN_XYZ_999")
        assert adv > 0

    def test_get_volatility_returns_positive(self):
        mcp = MarketContextProvider()
        vol, source = mcp.get_volatility("XAUUSD")
        assert vol > 0 and isinstance(source, str)

    def test_get_volatility_env_override(self, monkeypatch):
        monkeypatch.setenv("TCA_VOL_XAUUSD", "0.025")
        mcp = MarketContextProvider()
        vol, source = mcp.get_volatility("XAUUSD")
        assert vol > 0

    def test_get_volatility_unknown_symbol_uses_default(self):
        mcp = MarketContextProvider()
        vol, source = mcp.get_volatility("UNKNOWN_XYZ_999")
        assert vol > 0

    def test_accumulate_tick_no_raise(self):
        mcp = MarketContextProvider()
        mcp.accumulate_tick("XAUUSD", 100.0, datetime.now(UTC))


# ── TCAEngine ──────────────────────────────────────────────────────────────────


class TestTCAEngine:
    @pytest.mark.asyncio
    async def test_start_order_tracks_order(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        assert "o1" in e._active_orders

    @pytest.mark.asyncio
    async def test_record_fill_updates_order(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        await e.record_fill("o1", _fill())
        assert len(e._active_orders["o1"]["fills"]) == 1

    @pytest.mark.asyncio
    async def test_record_fill_unknown_order_noop(self):
        e = _engine()
        await e.record_fill("ghost", _fill())  # must not raise

    @pytest.mark.asyncio
    async def test_complete_order_returns_metrics(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        await e.record_fill("o1", _fill(price=2005.0, qty=1.0))
        result = await e.complete_order("o1")
        assert isinstance(result, TCAMetrics)
        assert result.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_complete_order_no_fills_returns_cancelled(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        result = await e.complete_order("o1")
        assert isinstance(result, TCAMetrics)

    @pytest.mark.asyncio
    async def test_complete_order_unknown_raises(self):
        e = _engine()
        with pytest.raises(ValueError, match="Unknown order"):
            await e.complete_order("ghost")

    @pytest.mark.asyncio
    async def test_complete_order_calls_callback(self):
        from execution.tca import Side

        e = _engine()
        calls = []
        e.register_cost_callback(lambda m: calls.append(m))
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        await e.record_fill("o1", _fill())
        await e.complete_order("o1")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_complete_order_removes_from_active(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        await e.record_fill("o1", _fill())
        await e.complete_order("o1")
        assert "o1" not in e._active_orders

    @pytest.mark.asyncio
    async def test_complete_order_adds_to_completed(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        await e.record_fill("o1", _fill())
        await e.complete_order("o1")
        assert len(e._completed) == 1

    @pytest.mark.asyncio
    async def test_sell_order_isf_calculation(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.SELL, Decimal("1"), Decimal("2000"))
        await e.record_fill("o1", _fill(price=1995.0, qty=1.0))
        result = await e.complete_order("o1")
        assert isinstance(result, TCAMetrics)

    @pytest.mark.asyncio
    async def test_multiple_fills_aggregated(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("2"), Decimal("2000"))
        await e.record_fill("o1", _fill(price=2003.0, qty=1.0))
        await e.record_fill("o1", _fill(price=2007.0, qty=1.0))
        result = await e.complete_order("o1")
        assert result.avg_fill_price == pytest.approx(Decimal("2005.0"), rel=1e-3)

    def test_register_cost_callback(self):
        e = _engine()
        cb = MagicMock()
        e.register_cost_callback(cb)
        assert cb in e._cost_callbacks

    def test_get_stats_empty(self):
        e = _engine()
        stats = e.get_stats()
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_get_stats_after_completion(self):
        from execution.tca import Side

        e = _engine()
        await e.start_order("o1", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2000"))
        await e.record_fill("o1", _fill())
        await e.complete_order("o1")
        stats = e.get_stats()
        assert isinstance(stats, dict)

    def test_update_market_data_no_raise(self):
        from data.real_time_price_engine import Tick
        import time

        e = _engine()
        tick = Tick(symbol="XAUUSD", bid=1999.0, ask=2001.0, mid=2000.0, timestamp=time.time())
        e.update_market_data(tick)

    def test_create_cancelled_metrics(self):
        from execution.tca import Side

        e = _engine()
        order = {
            "symbol": "XAUUSD",
            "side": Side.BUY,
            "quantity": Decimal("1"),
            "arrival_price": Decimal("2000"),
            "arrival_time": datetime.now(UTC),
            "benchmark": BenchmarkType.ARRIVAL,
            "fills": [],
        }
        result = e._create_cancelled_metrics(order, "o_cancelled")
        assert isinstance(result, TCAMetrics)
        assert result.order_id == "o_cancelled"


# ── BenchmarkType ──────────────────────────────────────────────────────────────


class TestBenchmarkType:
    def test_arrival_exists(self):
        assert BenchmarkType.ARRIVAL

    def test_vwap_exists(self):
        assert BenchmarkType.VWAP

    def test_twap_exists(self):
        assert BenchmarkType.TWAP
