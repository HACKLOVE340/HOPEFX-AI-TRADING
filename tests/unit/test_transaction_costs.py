# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_transaction_costs.py

Unit tests for backtesting/transaction_costs.py.

Covers:
  1.  TransactionCostModel: known bps values for GC=F
  2.  TransactionCostModel: unknown ticker falls back to defaults
  3.  TransactionCostModel.apply() deducts cost from raw PnL
  4.  TransactionCostModel.cost_summary() returns correct keys
  5.  OvernightSwapModel: XAU/USD long rate matches calibration
  6.  OvernightSwapModel: Wednesday triple-swap is exactly 3x Monday
  7.  OvernightSwapModel: weekday=None gives 1x rate
  8.  OvernightSwapModel: annual_rate_fraction matches USD/lot/night
  9.  OvernightSwapModel: per-unit rate = per-lot rate / lot_size
  10. OvernightSwapModel: short side receives credit (positive value)
  11. Ticker aliases all resolve to the same canonical rates
  12. get_tc_model() and get_swap_model() return singletons
"""

import pytest

from backtesting.transaction_costs import (
    OvernightSwapModel,
    TransactionCostModel,
    get_swap_model,
    get_tc_model,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tc():
    return TransactionCostModel()


@pytest.fixture
def swap():
    return OvernightSwapModel()


# ── TransactionCostModel ──────────────────────────────────────────────────────


class TestTransactionCostModel:
    def test_gc_f_known_bps(self, tc):
        # GC=F: 2*1.5 spread + 3.5 commission = 6.5 bps
        cost = tc.round_trip_cost_frac("GC=F")
        assert abs(cost - 6.5 / 10_000) < 1e-10

    def test_unknown_ticker_uses_defaults(self, tc):
        # Unknown ticker: 2*2.0 + 10.0 = 14.0 bps
        cost = tc.round_trip_cost_frac("UNKNOWN_XYZ")
        assert abs(cost - 14.0 / 10_000) < 1e-10

    def test_apply_deducts_cost(self, tc):
        raw = 0.005  # 0.5% raw return
        net = tc.apply(raw_pnl_pct=raw, entry_price=2000.0, ticker="GC=F")
        expected_cost = 6.5 / 10_000
        assert abs(net - (raw - expected_cost)) < 1e-12

    def test_apply_can_turn_profit_to_loss(self, tc):
        # A 3 bps raw gain on GC=F (6.5 bps cost) should be a net loss
        raw = 3.0 / 10_000
        net = tc.apply(raw_pnl_pct=raw, entry_price=2000.0, ticker="GC=F")
        assert net < 0

    def test_cost_summary_keys(self, tc):
        summary = tc.cost_summary(entry_price=2000.0, ticker="GC=F")
        for key in (
            "ticker",
            "entry_price",
            "half_spread_bps",
            "round_trip_spread_bps",
            "commission_bps",
            "total_cost_bps",
            "total_cost_pct",
            "approx_cost_usd_per_unit",
        ):
            assert key in summary, f"Missing key: {key}"

    def test_extra_spread_adds_to_cost(self):
        tc_base = TransactionCostModel(extra_spread_bps=0.0)
        tc_extra = TransactionCostModel(extra_spread_bps=5.0)
        base_cost = tc_base.round_trip_cost_frac("GC=F")
        extra_cost = tc_extra.round_trip_cost_frac("GC=F")
        # extra_spread_bps=5 adds 2*5=10 bps (entry + exit)
        assert abs(extra_cost - base_cost - 10.0 / 10_000) < 1e-10

    def test_eurusd_lower_cost_than_btc(self, tc):
        eur_cost = tc.round_trip_cost_frac("EUR/USD")
        btc_cost = tc.round_trip_cost_frac("BTC/USD")
        assert eur_cost < btc_cost


# ── OvernightSwapModel ────────────────────────────────────────────────────────


class TestOvernightSwapModel:
    def test_xauusd_long_rate(self, swap):
        # Calibrated: -$4.10/night per 100oz lot
        cost = swap.cost_usd_per_night("XAUUSD", lots=1.0, side="long")
        assert abs(cost - (-4.10)) < 1e-10

    def test_xauusd_short_rate_positive(self, swap):
        # Short XAU/USD: +$0.60/night (you receive)
        cost = swap.cost_usd_per_night("XAUUSD", lots=1.0, side="short")
        assert cost > 0
        assert abs(cost - 0.60) < 1e-10

    def test_wednesday_triple_swap(self, swap):
        # Wednesday (weekday=2) should be exactly 3x Monday (weekday=0)
        wed = swap.cost_usd_per_night("XAUUSD", lots=1.0, side="long", weekday=2)
        mon = swap.cost_usd_per_night("XAUUSD", lots=1.0, side="long", weekday=0)
        assert abs(wed / mon - 3.0) < 1e-10

    def test_no_weekday_gives_1x(self, swap):
        # weekday=None -> no triple-swap multiplier
        no_day = swap.cost_usd_per_night("XAUUSD", lots=1.0, side="long", weekday=None)
        mon = swap.cost_usd_per_night("XAUUSD", lots=1.0, side="long", weekday=0)
        assert abs(no_day - mon) < 1e-10

    def test_annual_rate_fraction_matches_usd_per_night(self, swap):
        # annual_rate = (rate_per_lot_per_night * 365) / (lot_size * entry_price)
        # For XAUUSD: (-4.10 * 365) / (100 * 2000) = -0.007482...
        annual = swap.annual_rate_fraction("XAUUSD", entry_price=2000.0, side="long")
        expected = (-4.10 * 365.0) / (100.0 * 2000.0)
        assert abs(annual - expected) < 1e-10

    def test_per_unit_rate_equals_per_lot_divided_by_lot_size(self, swap):
        per_unit = swap.cost_usd_per_unit_per_night("XAUUSD", side="long")
        per_lot = swap.cost_usd_per_night("XAUUSD", lots=1.0, side="long")
        # XAUUSD lot size = 100 oz
        assert abs(per_unit - per_lot / 100.0) < 1e-10

    def test_lots_scales_linearly(self, swap):
        cost_1 = swap.cost_usd_per_night("XAUUSD", lots=1.0, side="long")
        cost_2 = swap.cost_usd_per_night("XAUUSD", lots=2.0, side="long")
        assert abs(cost_2 - 2.0 * cost_1) < 1e-10

    def test_ticker_aliases_consistent(self, swap):
        # All aliases for gold should give the same rate
        aliases = ["GC=F", "XAU/USD", "XAUUSD", "XAU_USD"]
        rates = [swap.cost_usd_per_night(a, lots=1.0, side="long") for a in aliases]
        assert all(abs(r - rates[0]) < 1e-10 for r in rates), f"Alias mismatch: {rates}"

    def test_swap_summary_keys(self, swap):
        summary = swap.swap_summary("XAUUSD", entry_price=2000.0)
        for key in (
            "ticker",
            "canonical",
            "entry_price",
            "lot_size_units",
            "notional_per_lot_usd",
            "long_swap_usd_per_lot_per_night",
            "short_swap_usd_per_lot_per_night",
            "long_annual_rate_pct",
            "short_annual_rate_pct",
            "wednesday_triple_swap",
        ):
            assert key in summary, f"Missing key: {key}"

    def test_zero_entry_price_returns_zero_annual_rate(self, swap):
        annual = swap.annual_rate_fraction("XAUUSD", entry_price=0.0, side="long")
        assert annual == 0.0


# ── Singletons ────────────────────────────────────────────────────────────────


class TestSingletons:
    def test_get_tc_model_returns_same_instance(self):
        a = get_tc_model()
        b = get_tc_model()
        assert a is b

    def test_get_swap_model_returns_same_instance(self):
        a = get_swap_model()
        b = get_swap_model()
        assert a is b

    def test_get_tc_model_with_extra_spread_creates_new(self):
        base = get_tc_model()
        extra = get_tc_model(extra_spread_bps=5.0)
        # extra_spread_bps != 0 always creates a new instance
        assert extra is not base
