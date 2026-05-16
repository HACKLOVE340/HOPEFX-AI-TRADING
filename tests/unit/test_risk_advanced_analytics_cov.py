# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0
"""
tests/unit/test_risk_advanced_analytics_cov.py
Coverage tests for risk/advanced_analytics.py — all major branches.
"""
from __future__ import annotations

import os
import warnings

import numpy as np
import pytest

# Disable multiday enforcement so tests can call historical/parametric with horizon>1
os.environ["HOPEFX_VAR_ENFORCE_MULTIDAY"] = "0"

from risk.advanced_analytics import (
    AdvancedRiskAnalytics,
    DrawdownAnalysis,
    MonteCarloResult,
    RiskAnalytics,
    StressTestResult,
    VaRResult,
)

RNG = np.random.default_rng(42)


def _returns(n: int = 300, mu: float = 0.0003, sigma: float = 0.01) -> np.ndarray:
    return RNG.normal(mu, sigma, n)


def _equity(returns: np.ndarray, start: float = 10_000.0) -> np.ndarray:
    return start * np.cumprod(1 + returns)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def analytics():
    return AdvancedRiskAnalytics({"var_confidence": 0.95, "mc_simulations": 200, "risk_free_rate": 0.05})


@pytest.fixture
def rets():
    return _returns(300)


@pytest.fixture
def long_rets():
    return _returns(500)


# ── VaRResult dataclass ───────────────────────────────────────────────────────


class TestVaRResult:
    def test_to_dict_basic(self):
        r = VaRResult(var_value=0.02, confidence_level=0.95, time_horizon=1, method="historical")
        d = r.to_dict()
        assert d["var_value"] == pytest.approx(0.02)
        assert "timestamp" in d

    def test_to_dict_with_scaling(self):
        r = VaRResult(
            var_value=0.03, confidence_level=0.99, time_horizon=5,
            method="historical", scaling_approximate=True, scaling_note="test note"
        )
        d = r.to_dict()
        assert d["scaling_approximate"] is True
        assert d["scaling_note"] == "test note"


# ── AdvancedRiskAnalytics init ────────────────────────────────────────────────


class TestInit:
    def test_default_config(self):
        a = AdvancedRiskAnalytics()
        assert a.var_confidence == 0.95
        assert a.mc_simulations == 10000

    def test_custom_config(self, analytics):
        assert analytics.mc_simulations == 200

    def test_stress_scenarios_populated(self, analytics):
        assert "market_crash_2008" in analytics.stress_scenarios
        assert len(analytics.stress_scenarios) >= 5

    def test_alias_risk_analytics(self):
        a = RiskAnalytics()
        assert isinstance(a, AdvancedRiskAnalytics)


# ── calculate_var_historical ──────────────────────────────────────────────────


class TestVarHistorical:
    def test_1day_returns_result(self, analytics, rets):
        r = analytics.calculate_var_historical(rets)
        assert isinstance(r, VaRResult)
        assert r.var_value >= 0
        assert r.method == "historical"
        assert r.time_horizon == 1

    def test_with_portfolio_value(self, analytics, rets):
        r = analytics.calculate_var_historical(rets, portfolio_value=100_000)
        assert r.var_value > 1.0  # dollar value

    def test_multiday_with_enough_data(self, analytics, rets):
        import risk.advanced_analytics as _mod
        orig = _mod.ENFORCE_MULTIDAY_VAR
        _mod.ENFORCE_MULTIDAY_VAR = False
        try:
            r = analytics.calculate_var_historical(rets, time_horizon=5)
            assert r.var_value >= 0
        finally:
            _mod.ENFORCE_MULTIDAY_VAR = orig

    def test_multiday_sqrt_fallback(self, analytics):
        import risk.advanced_analytics as _mod
        orig = _mod.ENFORCE_MULTIDAY_VAR
        _mod.ENFORCE_MULTIDAY_VAR = False
        try:
            short = _returns(5)
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                r = analytics.calculate_var_historical(short, time_horizon=10)
            assert r.scaling_approximate is True
            assert any("sqrt" in str(x.message).lower() for x in w)
        finally:
            _mod.ENFORCE_MULTIDAY_VAR = orig

    def test_enforce_multiday_raises(self, rets):
        a = AdvancedRiskAnalytics()
        import risk.advanced_analytics as _mod
        orig = _mod.ENFORCE_MULTIDAY_VAR
        _mod.ENFORCE_MULTIDAY_VAR = True
        try:
            with pytest.raises(RuntimeError, match="time_horizon"):
                a.calculate_var_historical(rets, time_horizon=5)
        finally:
            _mod.ENFORCE_MULTIDAY_VAR = orig

    def test_custom_confidence(self, analytics, rets):
        r99 = analytics.calculate_var_historical(rets, confidence_level=0.99)
        r95 = analytics.calculate_var_historical(rets, confidence_level=0.95)
        assert r99.var_value >= r95.var_value


# ── calculate_var_parametric ──────────────────────────────────────────────────


class TestVarParametric:
    def test_basic(self, analytics, rets):
        r = analytics.calculate_var_parametric(rets)
        assert isinstance(r, VaRResult)
        assert r.method == "parametric"
        assert r.scaling_approximate is True

    def test_multiday(self, analytics, rets):
        import risk.advanced_analytics as _mod
        orig = _mod.ENFORCE_MULTIDAY_VAR
        _mod.ENFORCE_MULTIDAY_VAR = False
        try:
            r = analytics.calculate_var_parametric(rets, time_horizon=5)
            assert r.var_value >= 0
        finally:
            _mod.ENFORCE_MULTIDAY_VAR = orig

    def test_with_portfolio_value(self, analytics, rets):
        r = analytics.calculate_var_parametric(rets, portfolio_value=50_000)
        assert r.var_value > 1.0

    def test_normality_warning_for_fat_tails(self, analytics):
        fat = np.concatenate([_returns(200), RNG.standard_t(3, 50) * 0.02])
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            r = analytics.calculate_var_parametric(fat)
        assert r.var_value >= 0

    def test_enforce_multiday_raises(self, rets):
        a = AdvancedRiskAnalytics()
        import risk.advanced_analytics as _mod
        orig = _mod.ENFORCE_MULTIDAY_VAR
        _mod.ENFORCE_MULTIDAY_VAR = True
        try:
            with pytest.raises(RuntimeError):
                a.calculate_var_parametric(rets, time_horizon=5)
        finally:
            _mod.ENFORCE_MULTIDAY_VAR = orig

    def test_short_series_skips_jb(self, analytics):
        short = _returns(10)
        r = analytics.calculate_var_parametric(short)
        assert r.var_value >= 0


# ── calculate_var_monte_carlo ─────────────────────────────────────────────────


class TestVarMonteCarlo:
    def test_gaussian_mode(self, analytics, rets):
        r = analytics.calculate_var_monte_carlo(rets, num_simulations=500)
        assert r.method == "monte_carlo_gaussian"
        assert r.scaling_approximate is True

    def test_bootstrap_mode(self, analytics, rets):
        r = analytics.calculate_var_monte_carlo(rets, num_simulations=500, use_historical_bootstrap=True)
        assert r.method == "monte_carlo_bootstrap"
        assert r.scaling_approximate is False

    def test_bootstrap_fallback_insufficient_data(self, analytics):
        short = _returns(3)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = analytics.calculate_var_monte_carlo(short, time_horizon=10, use_historical_bootstrap=True, num_simulations=100)
        assert r.method == "monte_carlo_gaussian"
        assert any("bootstrap" in str(x.message).lower() for x in w)

    def test_with_portfolio_value(self, analytics, rets):
        r = analytics.calculate_var_monte_carlo(rets, portfolio_value=10_000, num_simulations=200)
        assert r.var_value > 0


# ── calculate_var_multiday ────────────────────────────────────────────────────


class TestVarMultiday:
    def test_overlapping(self, analytics, long_rets):
        r = analytics.calculate_var_multiday(long_rets, time_horizon=10)
        assert r.method == "multiday_overlapping"

    def test_non_overlapping(self, analytics, long_rets):
        r = analytics.calculate_var_multiday(long_rets, time_horizon=5, method="non_overlapping")
        assert "multiday" in r.method

    def test_non_overlapping_fallback_to_overlapping(self, analytics):
        short = _returns(20)
        r = analytics.calculate_var_multiday(short, time_horizon=5, method="non_overlapping")
        assert r.var_value >= 0

    def test_horizon_1_delegates(self, analytics, rets):
        r = analytics.calculate_var_multiday(rets, time_horizon=1)
        assert r.method == "historical"

    def test_insufficient_data_sqrt_fallback(self, analytics):
        tiny = _returns(5)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = analytics.calculate_var_multiday(tiny, time_horizon=10)
        assert r.scaling_approximate is True
        assert any("sqrt" in str(x.message).lower() for x in w)

    def test_with_portfolio_value(self, analytics, long_rets):
        r = analytics.calculate_var_multiday(long_rets, time_horizon=5, portfolio_value=100_000)
        assert r.var_value > 1.0


# ── calculate_var_ewma ────────────────────────────────────────────────────────


class TestVarEwma:
    def test_1day(self, analytics, rets):
        r = analytics.calculate_var_ewma(rets)
        assert r.method == "ewma"

    def test_multiday(self, analytics, long_rets):
        r = analytics.calculate_var_ewma(long_rets, time_horizon=5)
        assert r.method == "ewma"

    def test_short_series_delegates(self, analytics):
        tiny = _returns(5)
        r = analytics.calculate_var_ewma(tiny)
        assert r.var_value >= 0

    def test_zero_hist_vol_delegates(self, analytics):
        flat = np.zeros(50)
        r = analytics.calculate_var_ewma(flat)
        assert r.var_value >= 0

    def test_sqrt_fallback_insufficient(self, analytics):
        short = _returns(8)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            r = analytics.calculate_var_ewma(short, time_horizon=10)
        assert r.var_value >= 0

    def test_with_portfolio_value(self, analytics, rets):
        r = analytics.calculate_var_ewma(rets, portfolio_value=50_000)
        assert r.var_value > 0


# ── recommended_var ───────────────────────────────────────────────────────────


class TestRecommendedVar:
    def test_1day_uses_historical(self, analytics, rets):
        r = analytics.recommended_var(rets, time_horizon=1)
        assert r.method == "historical"

    def test_multiday_uses_ewma(self, analytics, long_rets):
        r = analytics.recommended_var(long_rets, time_horizon=5)
        assert r.method == "ewma"


# ── calculate_cvar ────────────────────────────────────────────────────────────


class TestCvar:
    def test_basic(self, analytics, rets):
        cvar = analytics.calculate_cvar(rets)
        assert cvar >= 0

    def test_with_portfolio_value(self, analytics, rets):
        cvar = analytics.calculate_cvar(rets, portfolio_value=100_000)
        assert cvar > 1.0

    def test_confidence_alias(self, analytics, rets):
        cvar = analytics.calculate_cvar(rets, confidence=0.99)
        assert cvar >= 0

    def test_empty_tail(self, analytics):
        all_positive = np.abs(_returns(100)) + 0.1
        cvar = analytics.calculate_cvar(all_positive, confidence_level=0.01)
        assert cvar >= 0


# ── run_monte_carlo_simulation ────────────────────────────────────────────────


class TestMonteCarloSimulation:
    def test_basic(self, analytics):
        r = analytics.run_monte_carlo_simulation(10_000, 0.10, 0.20, time_horizon=30, num_simulations=200)
        assert isinstance(r, MonteCarloResult)
        assert r.num_simulations == 200

    def test_return_paths(self, analytics):
        r = analytics.run_monte_carlo_simulation(10_000, 0.10, 0.20, time_horizon=10, num_simulations=100, return_paths=True)
        assert r.simulated_paths is not None

    def test_no_paths(self, analytics):
        r = analytics.run_monte_carlo_simulation(10_000, 0.10, 0.20, time_horizon=10, num_simulations=100, return_paths=False)
        assert r.simulated_paths is None

    def test_to_dict(self, analytics):
        r = analytics.run_monte_carlo_simulation(10_000, 0.10, 0.20, time_horizon=10, num_simulations=100)
        d = r.to_dict()
        assert "expected_return" in d


# ── simulate_portfolio_scenarios ─────────────────────────────────────────────


class TestPortfolioScenarios:
    def test_basic(self, analytics):
        positions = {
            "gold": {"value": 50_000, "expected_return": 0.08, "volatility": 0.15},
            "equities": {"value": 50_000, "expected_return": 0.12, "volatility": 0.20},
        }
        result = analytics.simulate_portfolio_scenarios(positions, time_horizon=10, num_simulations=100)
        assert "expected_return" in result
        assert result["initial_value"] == pytest.approx(100_000)

    def test_with_correlations(self, analytics):
        positions = {
            "a": {"value": 30_000, "expected_return": 0.08, "volatility": 0.15},
            "b": {"value": 70_000, "expected_return": 0.10, "volatility": 0.18},
        }
        corr = np.array([[1.0, 0.3], [0.3, 1.0]])
        result = analytics.simulate_portfolio_scenarios(positions, correlations=corr, time_horizon=5, num_simulations=100)
        assert "var_95" in result


# ── run_stress_test ───────────────────────────────────────────────────────────


class TestStressTest:
    def _portfolio(self):
        return {
            "gold_position": {"value": 100_000, "asset_class": "gold"},
            "equity_position": {"value": 50_000, "asset_class": "equities"},
        }

    def test_known_scenario(self, analytics):
        r = analytics.run_stress_test(self._portfolio(), "market_crash_2008")
        assert isinstance(r, StressTestResult)
        assert r.risk_level in ("low", "medium", "high", "severe")

    def test_unknown_scenario_raises(self, analytics):
        with pytest.raises(ValueError, match="Unknown scenario"):
            analytics.run_stress_test(self._portfolio(), "nonexistent_scenario")

    def test_all_scenarios(self, analytics):
        results = analytics.run_all_stress_tests(self._portfolio())
        assert len(results) == len(analytics.stress_scenarios)

    def test_low_risk_level(self, analytics):
        portfolio = {"cash": {"value": 100_000, "asset_class": "bonds"}}
        r = analytics.run_stress_test(portfolio, "flash_crash")
        assert r.risk_level in ("low", "medium", "high", "severe")

    def test_severe_risk_level(self, analytics):
        portfolio = {"crypto": {"value": 100_000, "asset_class": "crypto"}}
        r = analytics.run_stress_test(portfolio, "crypto_winter")
        assert r.risk_level == "severe"

    def test_medium_risk_level(self, analytics):
        portfolio = {"equities": {"value": 100_000, "asset_class": "equities"}}
        r = analytics.run_stress_test(portfolio, "flash_crash")
        assert r.risk_level in ("low", "medium")

    def test_high_risk_level(self, analytics):
        portfolio = {"equities": {"value": 100_000, "asset_class": "equities"}}
        r = analytics.run_stress_test(portfolio, "market_crash_2008")
        assert r.risk_level in ("high", "severe")

    def test_zero_total_value(self, analytics):
        portfolio = {"pos": {"value": 0, "asset_class": "equities"}}
        r = analytics.run_stress_test(portfolio, "flash_crash")
        assert r.portfolio_impact == 0.0


# ── analyze_drawdowns ─────────────────────────────────────────────────────────


class TestAnalyzeDrawdowns:
    def test_basic(self, analytics):
        ec = _equity(_returns(200))
        result = analytics.analyze_drawdowns(ec)
        assert isinstance(result, DrawdownAnalysis)
        assert result.max_drawdown <= 0

    def test_no_drawdown(self, analytics):
        ec = np.linspace(10_000, 20_000, 100)
        result = analytics.analyze_drawdowns(ec)
        assert result.max_drawdown <= 0

    def test_recovery_rate(self, analytics):
        ec = _equity(_returns(300))
        result = analytics.analyze_drawdowns(ec)
        assert 0.0 <= result.recovery_rate <= 1.0

    def test_analyze_drawdown_alias(self, analytics):
        ec = _equity(_returns(100))
        r1 = analytics.analyze_drawdowns(ec)
        r2 = analytics.analyze_drawdown(ec)
        assert r1.max_drawdown == r2.max_drawdown

    def test_ongoing_drawdown_event(self, analytics):
        # Equity that ends in drawdown
        ec = np.array([10000.0, 10500.0, 9000.0, 8500.0, 8000.0])
        result = analytics.analyze_drawdowns(ec)
        assert result.max_drawdown < 0

    def test_underwater_periods(self, analytics):
        ec = _equity(_returns(200))
        result = analytics.analyze_drawdowns(ec)
        assert isinstance(result.underwater_periods, list)


# ── Risk-adjusted metrics ─────────────────────────────────────────────────────


class TestRiskAdjustedMetrics:
    def test_sharpe_ratio(self, analytics, rets):
        s = analytics.calculate_sharpe_ratio(rets)
        assert isinstance(s, float)

    def test_sharpe_zero_std(self, analytics):
        flat = np.zeros(100)
        assert analytics.calculate_sharpe_ratio(flat) == 0.0

    def test_sortino_ratio(self, analytics, rets):
        s = analytics.calculate_sortino_ratio(rets)
        assert isinstance(s, float)

    def test_sortino_no_downside(self, analytics):
        positive = np.abs(_returns(100)) + 0.01
        s = analytics.calculate_sortino_ratio(positive)
        assert s == float("inf") or s > 0

    def test_sortino_all_negative(self, analytics):
        negative = -np.abs(_returns(100)) - 0.01
        s = analytics.calculate_sortino_ratio(negative)
        assert isinstance(s, float)

    def test_calmar_ratio(self, analytics, rets):
        c = analytics.calculate_calmar_ratio(rets)
        assert isinstance(c, float)

    def test_calmar_zero_drawdown(self, analytics):
        positive = np.abs(_returns(100)) + 0.01
        c = analytics.calculate_calmar_ratio(positive)
        assert c == float("inf") or c > 0

    def test_calmar_with_equity_curve(self, analytics, rets):
        ec = _equity(rets)
        c = analytics.calculate_calmar_ratio(rets, equity_curve=ec)
        assert isinstance(c, float)


# ── calculate_var_garch ───────────────────────────────────────────────────────


class TestVarGarch:
    def test_basic(self, analytics):
        rets = _returns(200)
        r = analytics.calculate_var_garch(rets, time_horizon=5)
        assert isinstance(r, VaRResult)
        assert r.method == "garch11"
        assert r.var_value >= 0

    def test_too_short_raises(self, analytics):
        short = _returns(50)
        with pytest.raises(ValueError, match="100 observations"):
            analytics.calculate_var_garch(short)

    def test_with_portfolio_value(self, analytics):
        rets = _returns(200)
        r = analytics.calculate_var_garch(rets, time_horizon=1, portfolio_value=100_000)
        assert r.var_value > 0

    def test_garch_hstep_variance(self):
        v = AdvancedRiskAnalytics._garch_hstep_variance(0.0001, 0.00001, 0.08, 0.88, 1)
        assert v == pytest.approx(0.0001)

    def test_garch_hstep_multiday(self):
        v = AdvancedRiskAnalytics._garch_hstep_variance(0.0001, 0.00001, 0.08, 0.88, 10)
        assert v > 0

    def test_garch_current_variance(self):
        rets = _returns(50)
        v = AdvancedRiskAnalytics._garch_current_variance(rets, 1e-6, 0.08, 0.88)
        assert v > 0


# ── calculate_all_metrics ─────────────────────────────────────────────────────


class TestCalculateAllMetrics:
    def test_basic(self, analytics, long_rets):
        result = analytics.calculate_all_metrics(long_rets)
        assert "var_historical_95" in result
        assert "sharpe_ratio" in result
        assert "max_drawdown" in result

    def test_with_equity_curve(self, analytics, long_rets):
        ec = _equity(long_rets)
        result = analytics.calculate_all_metrics(long_rets, equity_curve=ec)
        assert result["total_return"] is not None

    def test_with_portfolio_value(self, analytics, long_rets):
        result = analytics.calculate_all_metrics(long_rets, portfolio_value=100_000)
        assert result["var_historical_95"] > 1.0

    def test_short_series_no_garch(self, analytics):
        short = _returns(50)
        result = analytics.calculate_all_metrics(short)
        assert result["var_garch_10d"] is None


# ── calculate_portfolio_var ───────────────────────────────────────────────────


class TestPortfolioVar:
    def _positions(self):
        r1 = _returns(200)
        r2 = _returns(200)
        return {
            "gold": {"returns": r1, "value": 60_000},
            "equities": {"returns": r2, "value": 40_000},
        }

    def test_historical(self, analytics):
        r = analytics.calculate_portfolio_var(self._positions())
        assert r.var_value >= 0

    def test_parametric(self, analytics):
        r = analytics.calculate_portfolio_var(self._positions(), method="parametric")
        assert r.method == "parametric"

    def test_monte_carlo(self, analytics):
        r = analytics.calculate_portfolio_var(self._positions(), method="monte_carlo")
        assert "monte_carlo" in r.method

    def test_multiday(self, analytics):
        r = analytics.calculate_portfolio_var(self._positions(), time_horizon=5)
        assert r.var_value >= 0

    def test_empty_positions_raises(self, analytics):
        with pytest.raises(ValueError, match="empty"):
            analytics.calculate_portfolio_var({})

    def test_zero_total_value_raises(self, analytics):
        positions = {"a": {"returns": _returns(50), "value": 0}}
        with pytest.raises(ValueError, match="positive"):
            analytics.calculate_portfolio_var(positions)

    def test_too_few_returns_raises(self, analytics):
        positions = {"a": {"returns": np.array([0.01]), "value": 1000}}
        with pytest.raises(ValueError, match="2 return"):
            analytics.calculate_portfolio_var(positions)


# ── get_risk_report ───────────────────────────────────────────────────────────


class TestGetRiskReport:
    def test_basic(self, analytics, long_rets):
        report = analytics.get_risk_report(long_rets, symbol="XAUUSD")
        assert report["symbol"] == "XAUUSD"
        assert "metrics" in report
        assert "stress_scenarios" in report

    def test_with_portfolio_value(self, analytics, long_rets):
        report = analytics.get_risk_report(long_rets, portfolio_value=100_000)
        assert report["portfolio_value"] == 100_000

    def test_with_equity_curve(self, analytics, long_rets):
        ec = _equity(long_rets)
        report = analytics.get_risk_report(long_rets, equity_curve=ec)
        assert "generated_at" in report


# ── Convenience aliases ───────────────────────────────────────────────────────


class TestConvenienceAliases:
    def test_calculate_var(self, analytics, rets):
        v = analytics.calculate_var(rets)
        assert isinstance(v, float)

    def test_calculate_var_confidence(self, analytics, rets):
        v = analytics.calculate_var(rets, confidence=0.99)
        assert isinstance(v, float)

    def test_calculate_sharpe(self, analytics, rets):
        s = analytics.calculate_sharpe(rets)
        assert isinstance(s, float)

    def test_calculate_sharpe_with_rfr(self, analytics, rets):
        s = analytics.calculate_sharpe(rets, risk_free_rate=0.02)
        assert isinstance(s, float)
        # risk_free_rate should be restored
        assert analytics.risk_free_rate == 0.05
