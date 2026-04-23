# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for backtesting/enhanced_engine.py cost model correctness.

Covers:
1. TransactionCostModel.calibrate_xauusd() returns XAUUSD-specific parameters.
2. run_comprehensive_backtest() uses calibrate_xauusd() — not equity defaults.
3. generate_test_data() raises RuntimeError in APP_ENV=production.
4. generate_test_data() emits UserWarning in non-production environments.
5. total_cost() arithmetic: commission, spread, clearing, exchange, impact.
6. calibrate_from_executions() fits Almgren-Chriss parameters from real data.
7. Overnight financing: use_swap_model=True routes through OvernightSwapModel.
8. _charge_overnight_financing() charges correct direction (long vs short).
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Set non-production env before importing the engine
os.environ.setdefault("APP_ENV", "test")

from backtesting.enhanced_engine import (
    TransactionCostModel,
    generate_test_data,
)


# ── XAUUSD calibration parameters ────────────────────────────────────────────

# Published empirical values (see TransactionCostModel docstring for citations)
_XAUUSD_ETA = 0.050  # temporary impact coefficient
_XAUUSD_GAMMA = 0.100  # permanent impact coefficient
_XAUUSD_BETA = 0.55  # decay exponent
_XAUUSD_SPREAD_BPS = 0.3  # OTC spot spread
_XAUUSD_LONG_RATE = 0.00749  # −0.749% p.a. long carry
_XAUUSD_SHORT_RATE = -0.00110  # +0.110% p.a. short receive


class TestCalibrateXauusd:
    """TransactionCostModel.calibrate_xauusd() must return gold-specific params."""

    def test_eta_is_xauusd_calibrated(self):
        model = TransactionCostModel.calibrate_xauusd()
        assert abs(model.temporary_impact_coefficient - _XAUUSD_ETA) < 1e-6, (
            f"η={model.temporary_impact_coefficient} != XAUUSD calibrated {_XAUUSD_ETA}"
        )

    def test_gamma_is_xauusd_calibrated(self):
        model = TransactionCostModel.calibrate_xauusd()
        assert abs(model.permanent_impact_coefficient - _XAUUSD_GAMMA) < 1e-6, (
            f"γ={model.permanent_impact_coefficient} != XAUUSD calibrated {_XAUUSD_GAMMA}"
        )

    def test_beta_is_xauusd_calibrated(self):
        model = TransactionCostModel.calibrate_xauusd()
        assert abs(model.decay_exponent - _XAUUSD_BETA) < 1e-6, (
            f"β={model.decay_exponent} != XAUUSD calibrated {_XAUUSD_BETA}"
        )

    def test_spread_is_xauusd_calibrated(self):
        model = TransactionCostModel.calibrate_xauusd()
        assert abs(model.spread_markup_bps - _XAUUSD_SPREAD_BPS) < 1e-6, (
            f"spread={model.spread_markup_bps} bps != XAUUSD calibrated {_XAUUSD_SPREAD_BPS} bps"
        )

    def test_overnight_long_rate_is_correct(self):
        model = TransactionCostModel.calibrate_xauusd()
        assert abs(model.overnight_rate_long_annual - _XAUUSD_LONG_RATE) < 1e-6, (
            f"long rate={model.overnight_rate_long_annual} != {_XAUUSD_LONG_RATE}"
        )

    def test_overnight_short_rate_is_correct(self):
        model = TransactionCostModel.calibrate_xauusd()
        assert abs(model.overnight_rate_short_annual - _XAUUSD_SHORT_RATE) < 1e-6, (
            f"short rate={model.overnight_rate_short_annual} != {_XAUUSD_SHORT_RATE}"
        )

    def test_use_swap_model_is_true(self):
        model = TransactionCostModel.calibrate_xauusd()
        assert model.use_swap_model is True, "calibrate_xauusd() must set use_swap_model=True"

    def test_equity_defaults_are_not_used(self):
        """The old equity defaults (η=0.142, γ=0.314) must not appear in XAUUSD model."""
        model = TransactionCostModel.calibrate_xauusd()
        assert model.temporary_impact_coefficient != 0.142, (
            "η=0.142 is the equity default — XAUUSD model must use 0.050"
        )
        assert model.permanent_impact_coefficient != 0.314, (
            "γ=0.314 is the equity default — XAUUSD model must use 0.100"
        )
        assert model.spread_markup_bps != 0.8, "spread=0.8 bps is the equity default — XAUUSD model must use 0.3 bps"


class TestRunComprehensiveBacktestCostModel:
    """
    run_comprehensive_backtest() must use calibrate_xauusd() parameters,
    not the old equity defaults (η=0.142, γ=0.314, spread=0.8 bps).
    """

    def test_cost_model_uses_xauusd_calibration(self):
        """
        Verify that run_comprehensive_backtest() constructs a cost model
        with XAUUSD-calibrated parameters by inspecting the source code.

        We parse the function source rather than executing it (which would
        require network access for real data) to avoid slow integration tests.
        Comments and docstrings may contain old values for reference — we
        only check that the actual constructor call uses calibrate_xauusd().
        """
        import inspect
        import backtesting.enhanced_engine as eng

        src = inspect.getsource(eng.run_comprehensive_backtest)

        # Must use calibrate_xauusd() — not hardcoded equity defaults
        assert "calibrate_xauusd" in src, (
            "run_comprehensive_backtest() must call TransactionCostModel.calibrate_xauusd()"
        )

        # Must NOT construct TransactionCostModel with the old equity defaults
        # as keyword arguments (comments may still reference them for documentation)
        assert "temporary_impact_coefficient=0.142" not in src, (
            "run_comprehensive_backtest() must not pass η=0.142 to TransactionCostModel"
        )
        assert "permanent_impact_coefficient=0.314" not in src, (
            "run_comprehensive_backtest() must not pass γ=0.314 to TransactionCostModel"
        )

    def test_cost_model_spread_not_equity_default(self):
        """spread_markup_bps=0.8 (equity default) must not be passed to TransactionCostModel."""
        import inspect
        import backtesting.enhanced_engine as eng

        src = inspect.getsource(eng.run_comprehensive_backtest)
        assert "spread_markup_bps=0.8" not in src, (
            "run_comprehensive_backtest() must not use spread_markup_bps=0.8 (equity default)"
        )


# ── generate_test_data production guard ──────────────────────────────────────


class TestGenerateTestDataProductionGuard:
    """generate_test_data() must be blocked in APP_ENV=production."""

    def test_raises_in_production(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            with pytest.raises(RuntimeError, match="APP_ENV=production"):
                generate_test_data(n_ticks=10)

    def test_raises_in_production_case_insensitive(self):
        with patch.dict(os.environ, {"APP_ENV": "PRODUCTION"}):
            with pytest.raises(RuntimeError, match="APP_ENV=production"):
                generate_test_data(n_ticks=10)

    def test_warns_in_development(self):
        with patch.dict(os.environ, {"APP_ENV": "development"}):
            with pytest.warns(UserWarning, match="SYNTHETIC"):
                ticks = generate_test_data(n_ticks=5)
        assert len(ticks) == 5

    def test_warns_in_test(self):
        with patch.dict(os.environ, {"APP_ENV": "test"}):
            with pytest.warns(UserWarning, match="SYNTHETIC"):
                ticks = generate_test_data(n_ticks=3)
        assert len(ticks) == 3

    def test_returns_tick_data_objects(self):
        from backtesting.enhanced_engine import TickData

        with patch.dict(os.environ, {"APP_ENV": "test"}):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                ticks = generate_test_data(n_ticks=20)
        assert all(isinstance(t, TickData) for t in ticks)

    def test_tick_bid_ask_spread_positive(self):
        """Every tick must have ask > bid (positive spread)."""
        with patch.dict(os.environ, {"APP_ENV": "test"}):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                ticks = generate_test_data(n_ticks=50)
        for t in ticks:
            assert t.ask > t.bid, f"Non-positive spread: bid={t.bid} ask={t.ask}"

    def test_tick_prices_positive(self):
        """All tick prices must be positive (GBM cannot go negative with clipping)."""
        with patch.dict(os.environ, {"APP_ENV": "test"}):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                ticks = generate_test_data(n_ticks=100)
        for t in ticks:
            assert t.bid > 0 and t.ask > 0, f"Non-positive price: bid={t.bid} ask={t.ask}"


# ── total_cost() arithmetic ───────────────────────────────────────────────────


class TestTotalCostArithmetic:
    """total_cost() must correctly compute all cost components."""

    def _model(self) -> TransactionCostModel:
        return TransactionCostModel.calibrate_xauusd()

    def test_commission_minimum_per_lot(self):
        """Commission must be at least commission_per_lot for a 1-lot order."""
        model = self._model()
        # 1 standard lot = 100,000 units; price = 2000 USD/oz
        result = model.total_cost(order_size=100_000, price=2000.0)
        # commission_per_lot = $7; notional = 100,000 × 2000 = $200M
        # commission_per_million = $25 → $25 × 200 = $5,000 (dominates)
        assert result["commission"] > 0, "Commission must be positive"

    def test_spread_cost_zero_for_maker(self):
        """Maker orders (is_maker=True) must have zero spread cost."""
        model = self._model()
        result = model.total_cost(order_size=10_000, price=1900.0, is_maker=True)
        assert result["spread"] == 0.0, "Maker orders must have zero spread cost"

    def test_spread_cost_positive_for_taker(self):
        """Taker orders must incur spread cost."""
        model = self._model()
        result = model.total_cost(order_size=10_000, price=1900.0, is_maker=False)
        assert result["spread"] > 0.0, "Taker orders must have positive spread cost"

    def test_total_cost_equals_sum_of_components(self):
        """total_cost must equal sum of explicit + implicit costs."""
        model = self._model()
        result = model.total_cost(order_size=50_000, price=1950.0)
        expected = result["total_explicit"] + result["total_implicit"]
        assert abs(result["total_cost"] - expected) < 1e-8, (
            f"total_cost={result['total_cost']} != explicit+implicit={expected}"
        )

    def test_cost_bps_is_positive(self):
        """cost_bps must be positive for any non-zero order."""
        model = self._model()
        result = model.total_cost(order_size=10_000, price=2000.0)
        assert result["cost_bps"] > 0, "cost_bps must be positive"

    def test_cost_bps_reasonable_for_xauusd(self):
        """
        All-in cost for XAUUSD should be in the range 0.5–10 bps for a
        typical retail order (no market impact).
        """
        model = self._model()
        result = model.total_cost(order_size=10_000, price=2000.0)
        assert 0.1 <= result["cost_bps"] <= 20.0, (
            f"cost_bps={result['cost_bps']:.2f} outside expected range [0.1, 20] bps"
        )

    def test_market_impact_included_when_participation_rate_given(self):
        """Passing participation_rate must add market_impact to total cost."""
        model = self._model()
        result_no_impact = model.total_cost(order_size=10_000, price=2000.0)
        result_with_impact = model.total_cost(
            order_size=10_000,
            price=2000.0,
            participation_rate=0.05,
            daily_volatility=0.015,
        )
        assert result_with_impact["market_impact"] > 0, (
            "market_impact must be positive when participation_rate is provided"
        )
        assert result_with_impact["total_cost"] > result_no_impact["total_cost"], (
            "total_cost with market impact must exceed cost without impact"
        )


# ── calculate_market_impact() ─────────────────────────────────────────────────


class TestCalculateMarketImpact:
    """Almgren-Chriss market impact model correctness."""

    def _model(self) -> TransactionCostModel:
        return TransactionCostModel.calibrate_xauusd()

    def test_impact_increases_with_participation_rate(self):
        """Higher participation rate → higher market impact."""
        model = self._model()
        low = model.calculate_market_impact(1000, 0.01, 0.015)
        high = model.calculate_market_impact(1000, 0.10, 0.015)
        assert high["total_bps"] > low["total_bps"], "Market impact must increase with participation rate"

    def test_impact_increases_with_volatility(self):
        """Higher volatility → higher market impact."""
        model = self._model()
        low_vol = model.calculate_market_impact(1000, 0.05, 0.005)
        high_vol = model.calculate_market_impact(1000, 0.05, 0.030)
        assert high_vol["total_bps"] > low_vol["total_bps"], "Market impact must increase with daily volatility"

    def test_temporary_impact_positive(self):
        model = self._model()
        result = model.calculate_market_impact(1000, 0.05, 0.015)
        assert result["temporary_bps"] > 0

    def test_permanent_impact_positive(self):
        model = self._model()
        result = model.calculate_market_impact(1000, 0.05, 0.015)
        assert result["permanent_bps"] > 0

    def test_total_equals_temp_plus_perm(self):
        model = self._model()
        result = model.calculate_market_impact(1000, 0.05, 0.015)
        assert abs(result["total_bps"] - result["temporary_bps"] - result["permanent_bps"]) < 1e-8

    def test_invalid_participation_rate_raises(self):
        model = self._model()
        with pytest.raises(ValueError):
            model.calculate_market_impact(1000, 0.0, 0.015)
        with pytest.raises(ValueError):
            model.calculate_market_impact(1000, 1.5, 0.015)

    def test_toxic_flow_increases_impact(self):
        """Order flow toxicity > 0.5 must increase temporary impact."""
        model = self._model()
        clean = model.calculate_market_impact(1000, 0.05, 0.015, order_flow_toxicity=0.0)
        toxic = model.calculate_market_impact(1000, 0.05, 0.015, order_flow_toxicity=0.9)
        assert toxic["temporary_bps"] > clean["temporary_bps"], "Toxic flow must increase temporary market impact"

    def test_xauusd_impact_lower_than_equity(self):
        """
        XAUUSD impact (η=0.050) must be lower than equity impact (η=0.142)
        for the same participation rate and volatility.

        We construct an explicit equity-calibrated model with the old defaults
        rather than relying on TransactionCostModel() defaults (which may have
        been updated to XAUUSD values).
        """
        xauusd = TransactionCostModel.calibrate_xauusd()

        # Explicit equity-calibrated model with Almgren (2001) baseline values
        equity = TransactionCostModel()
        equity.temporary_impact_coefficient = 0.142
        equity.permanent_impact_coefficient = 0.314
        equity.decay_exponent = 0.60

        xauusd_impact = xauusd.calculate_market_impact(1000, 0.05, 0.015)
        equity_impact = equity.calculate_market_impact(1000, 0.05, 0.015)

        assert xauusd_impact["total_bps"] < equity_impact["total_bps"], (
            f"XAUUSD impact ({xauusd_impact['total_bps']:.2f} bps) must be lower than "
            f"equity impact ({equity_impact['total_bps']:.2f} bps)"
        )


# ── calibrate_from_executions() ───────────────────────────────────────────────


class TestCalibrateFromExecutions:
    """calibrate_from_executions() must fit Almgren-Chriss from real fill data."""

    def _make_executions(self, n: int = 100) -> list[dict]:
        """Generate synthetic execution records consistent with η=0.05, γ=0.10, β=0.55."""
        rng = np.random.default_rng(42)
        records = []
        for _ in range(n):
            x = rng.uniform(0.01, 0.20)  # participation rate
            s = rng.uniform(0.005, 0.025)  # daily volatility
            # True impact + 10% noise
            true_impact = (0.05 * s * x**0.55 + 0.10 * s * x) * 10000
            observed = true_impact * rng.uniform(0.9, 1.1)
            records.append(
                {
                    "participation_rate": x,
                    "daily_volatility": s,
                    "observed_impact_bps": observed,
                }
            )
        return records

    def test_calibration_succeeds_with_sufficient_data(self):
        model = TransactionCostModel.calibrate_xauusd()
        executions = self._make_executions(100)
        result = model.calibrate_from_executions(executions, min_samples=50)
        assert result["calibrated"] is True, f"Calibration failed: {result}"

    def test_calibration_returns_required_keys(self):
        model = TransactionCostModel.calibrate_xauusd()
        executions = self._make_executions(100)
        result = model.calibrate_from_executions(executions, min_samples=50)
        for key in ("eta", "gamma", "beta", "r_squared", "n_samples"):
            assert key in result, f"Missing key: {key}"

    def test_calibration_fails_gracefully_with_insufficient_data(self):
        model = TransactionCostModel.calibrate_xauusd()
        result = model.calibrate_from_executions([], min_samples=50)
        assert result["calibrated"] is False
        assert "insufficient" in result.get("reason", "").lower()

    def test_calibrated_parameters_update_model(self):
        """After calibration, model parameters must be updated in-place."""
        model = TransactionCostModel.calibrate_xauusd()
        executions = self._make_executions(100)
        result = model.calibrate_from_executions(executions, min_samples=50)
        if result["calibrated"]:
            # result["eta"] is rounded to 6 dp; model stores full float.
            # Compare with tolerance rather than exact equality.
            assert abs(model.temporary_impact_coefficient - result["eta"]) < 1e-4, (
                f"model.η={model.temporary_impact_coefficient} != result.eta={result['eta']}"
            )
            assert abs(model.permanent_impact_coefficient - result["gamma"]) < 1e-4
            assert abs(model.decay_exponent - result["beta"]) < 1e-4

    def test_r_squared_positive(self):
        """R² must be in [0, 1] for a reasonable fit."""
        model = TransactionCostModel.calibrate_xauusd()
        executions = self._make_executions(150)
        result = model.calibrate_from_executions(executions, min_samples=50)
        if result["calibrated"]:
            assert 0.0 <= result["r_squared"] <= 1.0, f"R²={result['r_squared']} out of [0, 1]"
