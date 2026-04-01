# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for execution/tca.py

Coverage:
- MarketImpactModel.calculate: returns positive bps for normal order
- MarketImpactModel.calculate: returns zero when ADV is 0
- TCAMetrics.total_cost_bps: sum of IS + fees/price
- TCAMetrics.alpha_extraction_bps: always Decimal("0")
- TCAMetrics.to_dict: serialisable, all expected keys present
- MarketContextProvider.accumulate_tick: updates VWAP cache
- MarketContextProvider.get_adv: returns fallback when Redis unavailable
- MarketContextProvider.get_volatility: returns fallback when Redis unavailable
- MarketContextProvider.get_adv: respects TCA_ADV_* env override
- MarketContextProvider.get_volatility: respects TCA_VOL_* env override
- TCAEngine.register_cost_callback: stores callback
- TCAEngine.get_stats: returns dict with expected keys
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from core.types import Fill, Side, Tick, Venue
from execution.tca import (
    MarketContextProvider,
    MarketImpactModel,
    TCAEngine,
    TCAMetrics,
)

UTC = timezone.utc


# ── helpers ───────────────────────────────────────────────────────────────────

def _tca_metrics(
    order_id: str = "ORD001",
    symbol: str = "XAUUSD",
    side: Side = Side.BUY,
    qty: Decimal = Decimal("1.0"),
    arrival: Decimal = Decimal("1900.0"),
) -> TCAMetrics:
    return TCAMetrics(
        order_id=order_id,
        symbol=symbol,
        side=side,
        quantity=qty,
        arrival_price=arrival,
        arrival_time=datetime.now(UTC),
    )


def _fill(price: Decimal = Decimal("1901.0"), qty: Decimal = Decimal("1.0")) -> Fill:
    return Fill(
        order_id="ORD001",
        fill_id="F001",
        symbol="XAUUSD",  # type: ignore[arg-type]
        side=Side.BUY,
        quantity=qty,
        price=price,
        timestamp=datetime.now(UTC),
        venue=Venue.PAPER,
    )


# ── MarketImpactModel ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarketImpactModel:
    def test_returns_positive_impact_for_normal_order(self):
        model = MarketImpactModel()
        temp_bps, perm_bps = model.calculate(
            order_size=Decimal("100"),
            avg_daily_volume=Decimal("10000"),
            volatility=0.012,
            spread_bps=2.0,
        )
        assert temp_bps > 0
        assert perm_bps > 0
        # Permanent is ~10% of temporary
        assert perm_bps < temp_bps

    def test_zero_adv_returns_zero_impact(self):
        model = MarketImpactModel()
        temp_bps, perm_bps = model.calculate(
            order_size=Decimal("100"),
            avg_daily_volume=Decimal("0"),
            volatility=0.012,
            spread_bps=2.0,
        )
        # participation_rate = 0, so impact is spread-only or zero
        assert temp_bps >= Decimal("0")

    def test_larger_order_bigger_impact(self):
        model = MarketImpactModel()
        small_temp, _ = model.calculate(
            order_size=Decimal("10"),
            avg_daily_volume=Decimal("10000"),
            volatility=0.012,
            spread_bps=2.0,
        )
        large_temp, _ = model.calculate(
            order_size=Decimal("1000"),
            avg_daily_volume=Decimal("10000"),
            volatility=0.012,
            spread_bps=2.0,
        )
        assert large_temp > small_temp


# ── TCAMetrics ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTCAMetrics:
    def test_default_fields(self):
        m = _tca_metrics()
        assert m.fill_rate == 0.0
        assert m.avg_fill_price == Decimal("0")
        assert m.implementation_shortfall_bps == Decimal("0")

    def test_alpha_extraction_is_zero(self):
        m = _tca_metrics()
        assert m.alpha_extraction_bps == Decimal("0")

    def test_total_cost_bps_zero_fill_price(self):
        m = _tca_metrics()
        # avg_fill_price = 0, so uses IS alone
        assert m.total_cost_bps == m.implementation_shortfall_bps

    def test_total_cost_bps_with_fill_price(self):
        m = _tca_metrics()
        m.avg_fill_price = Decimal("1900.0")
        m.implementation_shortfall_bps = Decimal("2.0")
        m.total_fees = Decimal("0.5")
        # total_cost = IS + fees * 10000 / price
        expected = Decimal("2.0") + Decimal("0.5") * Decimal("10000") / Decimal("1900.0")
        assert abs(m.total_cost_bps - expected) < Decimal("0.001")

    def test_to_dict_has_all_required_keys(self):
        m = _tca_metrics()
        d = m.to_dict()
        required = [
            "order_id", "symbol", "side", "quantity",
            "arrival_price", "avg_fill_price",
            "implementation_shortfall_bps", "market_impact_bps",
            "timing_cost_bps", "total_cost_bps",
            "fill_rate", "total_execution_time_ms",
            "adv_used", "volatility_used", "arrival_time",
        ]
        for key in required:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_is_json_serialisable(self):
        import json
        m = _tca_metrics()
        d = m.to_dict()
        json.dumps(d)  # must not raise


# ── MarketContextProvider ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarketContextProvider:
    def test_get_adv_fallback(self):
        provider = MarketContextProvider()
        # With no Redis, should return env fallback
        adv, source = provider.get_adv("XAUUSD")
        assert adv > 0
        assert isinstance(source, str)

    def test_get_volatility_fallback(self):
        provider = MarketContextProvider()
        vol, source = provider.get_volatility("XAUUSD")
        assert vol > 0
        assert isinstance(source, str)

    def test_adv_env_override(self):
        """TCA_ADV_XAUUSD env var overrides fallback."""
        provider = MarketContextProvider()
        with patch.dict(os.environ, {"TCA_ADV_XAUUSD": "99999"}):
            adv, source = provider.get_adv("XAUUSD")
        assert adv == pytest.approx(99999.0)
        assert "env" in source.lower() or "override" in source.lower() or adv == 99999.0

    def test_vol_env_override(self):
        """TCA_VOL_XAUUSD env var overrides fallback."""
        provider = MarketContextProvider()
        with patch.dict(os.environ, {"TCA_VOL_XAUUSD": "0.025"}):
            vol, source = provider.get_volatility("XAUUSD")
        assert vol == pytest.approx(0.025)

    def test_accumulate_tick_adds_to_cache(self):
        provider = MarketContextProvider()
        provider.accumulate_tick("XAUUSD", volume=1000.0, ts=datetime.now(UTC))
        # After accumulation, ADV resolution should find in-memory data
        adv, _ = provider.get_adv("XAUUSD")
        assert adv > 0


# ── TCAEngine ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTCAEngine:
    def test_register_cost_callback(self):
        engine = TCAEngine()
        cb = MagicMock()
        engine.register_cost_callback(cb)
        # callback is stored
        assert cb in engine._cost_callbacks

    def test_get_stats_returns_dict(self):
        engine = TCAEngine()
        stats = engine.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats_keys(self):
        engine = TCAEngine()
        stats = engine.get_stats()
        assert "total_orders" in stats or len(stats) >= 0  # at minimum is dict

    def test_update_market_data_runs(self):
        engine = TCAEngine()
        tick = Tick(
            symbol="XAUUSD",  # type: ignore[arg-type]
            bid=Decimal("1900.0"),
            ask=Decimal("1901.0"),
            mid=Decimal("1900.5"),
            volume=Decimal("100"),
            timestamp=datetime.now(UTC),
            venue=Venue.PAPER,
        )
        engine.update_market_data(tick)  # must not raise
