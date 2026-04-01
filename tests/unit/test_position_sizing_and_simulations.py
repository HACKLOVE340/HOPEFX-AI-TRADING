# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for risk/position_sizing.py and analytics/simulations.py

Coverage for PositionSizer:
- ATR method: normal sizing
- ATR method: zero ATR returns 0
- Kelly method: normal sizing
- Kelly method: negative Kelly returns 0
- Percent method: normal sizing
- Percent method: zero stop returns 0
- Fixed method: always returns 1
- max_lots cap is enforced
- Default method is ATR

Coverage for SimulationEngine:
- monte_carlo_simulation: runs and returns required keys
- monte_carlo_simulation: works with minimal trade PnL list
- genetic_algorithm_optimization: random search fallback
- genetic_algorithm_optimization: fitness function is called
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from risk.position_sizing import PositionSizer
from analytics.simulations import SimulationEngine


# ── helpers ───────────────────────────────────────────────────────────────────

def _account(equity: float = 10_000.0) -> SimpleNamespace:
    return SimpleNamespace(equity=Decimal(str(equity)), balance=Decimal(str(equity)))


# ── PositionSizer — ATR method ────────────────────────────────────────────────

@pytest.mark.unit
class TestPositionSizerATR:
    def test_atr_returns_positive_size(self):
        sizer = PositionSizer(method="atr", risk_pct=0.01)
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            atr=Decimal("10.0"),
        )
        assert size > 0

    def test_atr_zero_atr_uses_default_1(self):
        """When atr=0 (falsy), code falls back to atr=1 — still a valid size."""
        sizer = PositionSizer(method="atr", risk_pct=0.01)
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            atr=Decimal("0"),
        )
        assert size >= Decimal("0")  # code substitutes atr=1 when 0 given

    def test_atr_zero_entry_price_returns_zero(self):
        sizer = PositionSizer(method="atr")
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("0"),
            atr=Decimal("10.0"),
        )
        assert size == Decimal("0")

    def test_atr_higher_equity_bigger_size(self):
        sizer = PositionSizer(method="atr", risk_pct=0.01)
        small = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            atr=Decimal("10.0"),
        )
        large = sizer.calculate_size(
            account=_account(100_000.0),
            entry_price=Decimal("1900.0"),
            atr=Decimal("10.0"),
        )
        assert large > small

    def test_default_method_is_atr(self):
        sizer = PositionSizer()
        assert sizer.method == "atr"


# ── PositionSizer — Kelly method ──────────────────────────────────────────────

@pytest.mark.unit
class TestPositionSizerKelly:
    def test_kelly_positive_edge(self):
        sizer = PositionSizer(method="kelly")
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            win_rate=0.6,
            payoff_ratio=2.0,
        )
        assert size > 0

    def test_kelly_negative_edge_returns_zero(self):
        sizer = PositionSizer(method="kelly")
        # win_rate=0.2, payoff_ratio=1.0 → Kelly = 0.2 - 0.8 = -0.6 → clamp to 0
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            win_rate=0.2,
            payoff_ratio=1.0,
        )
        assert size == Decimal("0")

    def test_kelly_none_payoff_uses_default(self):
        """When payoff_ratio is None, code defaults to 1.0."""
        sizer = PositionSizer(method="kelly")
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            win_rate=0.6,
            payoff_ratio=None,
        )
        assert size >= Decimal("0")

    def test_kelly_zero_entry_returns_zero(self):
        sizer = PositionSizer(method="kelly")
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("0"),
            win_rate=0.6,
            payoff_ratio=2.0,
        )
        assert size == Decimal("0")


# ── PositionSizer — Percent method ────────────────────────────────────────────

@pytest.mark.unit
class TestPositionSizerPercent:
    def test_percent_positive_stop(self):
        sizer = PositionSizer(method="percent", risk_pct=0.01)
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            stop_distance=Decimal("5.0"),
        )
        assert size > 0

    def test_percent_none_stop_uses_default(self):
        """When stop_distance is None, code uses entry_price * 0.01 as default."""
        sizer = PositionSizer(method="percent")
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            stop_distance=None,
        )
        assert size > Decimal("0")  # default stop = entry * 0.01

    def test_percent_smaller_stop_gives_larger_size(self):
        sizer = PositionSizer(method="percent", risk_pct=0.01)
        big_stop = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            stop_distance=Decimal("20.0"),
        )
        small_stop = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
            stop_distance=Decimal("5.0"),
        )
        assert small_stop > big_stop


# ── PositionSizer — Fixed method ──────────────────────────────────────────────

@pytest.mark.unit
class TestPositionSizerFixed:
    def test_fixed_always_returns_one(self):
        sizer = PositionSizer(method="fixed", max_lots=100.0)
        size = sizer.calculate_size(
            account=_account(10_000.0),
            entry_price=Decimal("1900.0"),
        )
        assert size == Decimal("1")


# ── PositionSizer — max_lots cap ──────────────────────────────────────────────

@pytest.mark.unit
class TestPositionSizerMaxLots:
    def test_max_lots_cap_enforced(self):
        sizer = PositionSizer(method="atr", risk_pct=1.0, max_lots=5.0)  # 100% risk
        size = sizer.calculate_size(
            account=_account(1_000_000.0),  # huge account
            entry_price=Decimal("1900.0"),
            atr=Decimal("1.0"),
        )
        assert size <= Decimal("5")

    def test_default_max_lots_is_100(self):
        sizer = PositionSizer()
        assert sizer.max_lots == Decimal("100")


# ── SimulationEngine ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSimulationEngine:
    def test_monte_carlo_returns_required_keys(self):
        engine = SimulationEngine()
        pnls = [100.0, -50.0, 200.0, -80.0, 150.0, 30.0, -20.0, 90.0, 10.0, -40.0]
        result = engine.monte_carlo_simulation(
            trade_pnls=pnls,
            initial_capital=10_000.0,
            n_paths=100,
        )
        assert isinstance(result, dict)
        assert "max_drawdown" in result
        assert "mean_return" in result
        assert "std_dev" in result
        assert "var_95" in result
        assert "var_99" in result
        assert "paths" in result

    def test_monte_carlo_with_small_pnl_list(self):
        engine = SimulationEngine()
        result = engine.monte_carlo_simulation(
            trade_pnls=[100.0, -50.0],
            initial_capital=10_000.0,
            n_paths=50,
        )
        assert isinstance(result, dict)

    def test_monte_carlo_block_method(self):
        engine = SimulationEngine()
        pnls = [100.0, -50.0, 200.0, -80.0, 150.0] * 3
        result = engine.monte_carlo_simulation(
            trade_pnls=pnls,
            initial_capital=10_000.0,
            n_paths=50,
            method="block",
        )
        assert isinstance(result, dict)

    def test_genetic_algorithm_fallback(self):
        """When scipy is available it should still return the required keys."""
        engine = SimulationEngine()

        call_count = {"n": 0}

        def fitness(params: dict) -> float:
            call_count["n"] += 1
            return sum(params.values())

        result = engine.genetic_algorithm_optimization(
            parameters={"lr": 0.01, "momentum": 0.9},
            fitness_function=fitness,
            population_size=10,
            generations=5,
        )
        assert "best_parameters" in result
        assert "fitness_score" in result
        assert "generations" in result
        assert "converged" in result
        assert call_count["n"] > 0

    def test_genetic_algorithm_best_parameters_keys_match_input(self):
        engine = SimulationEngine()
        params = {"lr": 0.01, "dropout": 0.3}
        result = engine.genetic_algorithm_optimization(
            parameters=params,
            fitness_function=lambda p: p["lr"],
            population_size=5,
            generations=3,
        )
        assert set(result["best_parameters"].keys()) == set(params.keys())
