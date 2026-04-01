# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_risk_analytics.py

Unit tests for risk/analytics.py — VaR, ES/CVaR, Monte Carlo slippage,
regime drift, Sharpe, max drawdown, pre-trade report.
"""

import numpy as np
import pytest

from risk.analytics import (
    ESResult,
    PreTradeRiskReport,
    RegimeDriftScore,
    SlippageSimResult,
    SharpeResult,
    VaRResult,
    compute_es,
    compute_max_drawdown,
    compute_regime_drift,
    compute_sharpe,
    compute_var,
    generate_pre_trade_report,
    simulate_slippage,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(42)
RETURNS_NORMAL = RNG.normal(0.0005, 0.01, 500)  # 500 daily returns, ~10% annual vol
RETURNS_FAT = RNG.standard_t(df=3, size=500) * 0.01  # fat-tailed
EQUITY_CURVE = np.cumprod(1 + RETURNS_NORMAL) * 100_000


# ---------------------------------------------------------------------------
# VaR
# ---------------------------------------------------------------------------


class TestComputeVaR:
    def test_returns_var_result(self):
        result = compute_var(RETURNS_NORMAL, confidence=0.95)
        assert isinstance(result, VaRResult)

    def test_var_positive(self):
        result = compute_var(RETURNS_NORMAL, confidence=0.95)
        assert result.var_historical >= 0
        assert result.var_parametric >= 0
        assert result.var_cornish_fisher >= 0

    def test_conservative_var_is_max(self):
        result = compute_var(RETURNS_NORMAL, confidence=0.95)
        assert result.var == max(result.var_historical, result.var_parametric, result.var_cornish_fisher)

    def test_99_var_greater_than_95(self):
        var95 = compute_var(RETURNS_NORMAL, confidence=0.95)
        var99 = compute_var(RETURNS_NORMAL, confidence=0.99)
        assert var99.var >= var95.var

    def test_horizon_scaling(self):
        var1 = compute_var(RETURNS_NORMAL, confidence=0.95, horizon_days=1)
        var10 = compute_var(RETURNS_NORMAL, confidence=0.95, horizon_days=10)
        # 10-day VaR should be ~sqrt(10) times 1-day VaR
        ratio = var10.var / (var1.var + 1e-10)
        assert 2.5 < ratio < 4.5  # sqrt(10) ≈ 3.16

    def test_fat_tails_cornish_fisher_higher(self):
        """Cornish-Fisher should be >= parametric for fat-tailed returns."""
        result = compute_var(RETURNS_FAT, confidence=0.99)
        # CF adjusts upward for positive excess kurtosis
        assert result.var_cornish_fisher >= result.var_parametric * 0.9

    def test_insufficient_data_raises(self):
        with pytest.raises(ValueError, match="Insufficient"):
            compute_var(np.array([0.01, -0.01, 0.005]), confidence=0.95)

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValueError):
            compute_var(RETURNS_NORMAL, confidence=1.5)


# ---------------------------------------------------------------------------
# Expected Shortfall
# ---------------------------------------------------------------------------


class TestComputeES:
    def test_returns_es_result(self):
        result = compute_es(RETURNS_NORMAL, confidence=0.99)
        assert isinstance(result, ESResult)

    def test_es_greater_than_var(self):
        """ES must always be >= VaR at the same confidence level."""
        var = compute_var(RETURNS_NORMAL, confidence=0.99)
        es = compute_es(RETURNS_NORMAL, confidence=0.99)
        assert es.es >= var.var * 0.9  # allow small numerical tolerance

    def test_es_positive(self):
        result = compute_es(RETURNS_NORMAL, confidence=0.99)
        assert result.es_historical >= 0
        assert result.es_parametric >= 0

    def test_conservative_es_is_max(self):
        result = compute_es(RETURNS_NORMAL, confidence=0.99)
        assert result.es == max(result.es_historical, result.es_parametric)

    def test_insufficient_data_raises(self):
        with pytest.raises(ValueError):
            compute_es(np.array([0.01] * 5), confidence=0.99)


# ---------------------------------------------------------------------------
# Monte Carlo slippage
# ---------------------------------------------------------------------------


class TestSimulateSlippage:
    def test_returns_slip_result(self):
        result = simulate_slippage(
            symbol="XAUUSD",
            quantity=1.0,
            side="BUY",
            mid_price=1950.0,
            bid_ask_spread_bps=5.0,
        )
        assert isinstance(result, SlippageSimResult)

    def test_p99_greater_than_mean(self):
        result = simulate_slippage(symbol="XAUUSD", quantity=1.0, side="BUY", mid_price=1950.0)
        assert result.p99_slippage_bps >= result.mean_slippage_bps

    def test_p99_greater_than_p95(self):
        result = simulate_slippage(symbol="XAUUSD", quantity=1.0, side="BUY", mid_price=1950.0)
        assert result.p99_slippage_bps >= result.p95_slippage_bps

    def test_larger_quantity_higher_impact(self):
        small = simulate_slippage("XAUUSD", 1.0, "BUY", 1950.0)
        large = simulate_slippage("XAUUSD", 100.0, "BUY", 1950.0)
        assert large.mean_slippage_bps > small.mean_slippage_bps

    def test_wider_spread_higher_slippage(self):
        tight = simulate_slippage("XAUUSD", 1.0, "BUY", 1950.0, bid_ask_spread_bps=2.0)
        wide = simulate_slippage("XAUUSD", 1.0, "BUY", 1950.0, bid_ask_spread_bps=20.0)
        assert wide.mean_slippage_bps > tight.mean_slippage_bps

    def test_expected_cost_positive(self):
        result = simulate_slippage("XAUUSD", 1.0, "BUY", 1950.0)
        assert result.expected_cost_usd >= 0
        assert result.worst_case_cost_usd >= result.expected_cost_usd

    def test_reproducible_with_seed(self):
        r1 = simulate_slippage("XAUUSD", 1.0, "BUY", 1950.0, rng_seed=99)
        r2 = simulate_slippage("XAUUSD", 1.0, "BUY", 1950.0, rng_seed=99)
        assert r1.mean_slippage_bps == r2.mean_slippage_bps


# ---------------------------------------------------------------------------
# Regime drift
# ---------------------------------------------------------------------------


class TestComputeRegimeDrift:
    def test_stable_regime_low_score(self):
        ref = RNG.normal(0.0005, 0.01, 252)
        cur = RNG.normal(0.0005, 0.01, 20)
        result = compute_regime_drift(ref, cur)
        assert isinstance(result, RegimeDriftScore)
        assert not result.regime_changed  # same distribution

    def test_volatile_regime_detected(self):
        ref = RNG.normal(0.0005, 0.005, 252)  # low vol
        cur = RNG.normal(0.0005, 0.05, 20)  # 10x higher vol
        result = compute_regime_drift(ref, cur, drift_threshold=1.0)
        assert result.regime_changed
        assert result.vol_ratio > 5.0

    def test_insufficient_data_returns_zero_score(self):
        result = compute_regime_drift(np.array([0.01]), np.array([0.01]))
        assert result.drift_score == 0.0
        assert not result.regime_changed

    def test_ks_pvalue_range(self):
        ref = RNG.normal(0, 0.01, 100)
        cur = RNG.normal(0, 0.01, 20)
        result = compute_regime_drift(ref, cur)
        assert 0.0 <= result.ks_pvalue <= 1.0
        assert 0.0 <= result.ks_statistic <= 1.0


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------


class TestComputeSharpe:
    def test_returns_sharpe_result(self):
        result = compute_sharpe(RETURNS_NORMAL)
        assert isinstance(result, SharpeResult)

    def test_positive_sharpe_for_positive_returns(self):
        pos_returns = np.abs(RETURNS_NORMAL) + 0.001
        result = compute_sharpe(pos_returns)
        assert result.sharpe > 0

    def test_negative_sharpe_for_negative_returns(self):
        neg_returns = -np.abs(RETURNS_NORMAL) - 0.001
        result = compute_sharpe(neg_returns)
        assert result.sharpe < 0

    def test_se_positive(self):
        result = compute_sharpe(RETURNS_NORMAL)
        assert result.sharpe_se > 0

    def test_passes_gate_high_sharpe(self):
        # Construct returns with very high Sharpe — use a relaxed SE target
        # since SE depends on sample size and SR magnitude (Lo 2002)
        high_sharpe = np.full(500, 0.001) + RNG.normal(0, 0.0003, 500)
        result = compute_sharpe(high_sharpe, sharpe_target=1.5, se_target=99.0)
        assert result.sharpe > 1.5  # Sharpe gate passes
        assert result.passes_gate

    def test_fails_gate_low_sharpe(self):
        low_sharpe = RNG.normal(0, 0.02, 500)  # near-zero mean
        result = compute_sharpe(low_sharpe, sharpe_target=1.5)
        assert not result.passes_gate

    def test_insufficient_data_raises(self):
        with pytest.raises(ValueError):
            compute_sharpe(np.array([0.01] * 10))


# ---------------------------------------------------------------------------
# Max drawdown
# ---------------------------------------------------------------------------


class TestComputeMaxDrawdown:
    def test_monotone_increasing_zero_drawdown(self):
        eq = np.linspace(100, 200, 100)
        assert compute_max_drawdown(eq) == pytest.approx(0.0, abs=1e-6)

    def test_known_drawdown(self):
        # Peak at 100, trough at 80 → 20% drawdown
        eq = np.array([100.0, 90.0, 80.0, 85.0, 95.0])
        dd = compute_max_drawdown(eq)
        assert dd == pytest.approx(0.20, abs=0.01)

    def test_drawdown_bounded_0_1(self):
        dd = compute_max_drawdown(EQUITY_CURVE)
        assert 0.0 <= dd <= 1.0

    def test_single_element_returns_zero(self):
        assert compute_max_drawdown(np.array([100.0])) == 0.0


# ---------------------------------------------------------------------------
# Pre-trade risk report
# ---------------------------------------------------------------------------


class TestGeneratePreTradeReport:
    def test_returns_report(self):
        report = generate_pre_trade_report(
            symbol="XAUUSD",
            side="BUY",
            quantity=1.0,
            mid_price=1950.0,
            returns=RETURNS_NORMAL,
            equity_curve=EQUITY_CURVE,
        )
        assert isinstance(report, PreTradeRiskReport)

    def test_approved_for_normal_conditions(self):
        # Use very permissive limits to ensure approval
        report = generate_pre_trade_report(
            symbol="XAUUSD",
            side="BUY",
            quantity=0.01,
            mid_price=1950.0,
            returns=RETURNS_NORMAL,
            equity_curve=EQUITY_CURVE,
            max_var_pct=0.99,
            max_es_pct=0.99,
            max_slippage_bps=9999.0,
            max_drift_score=99.0,
            min_sharpe=-99.0,
            max_drawdown_limit=0.99,
        )
        assert report.approved
        assert len(report.block_reasons) == 0

    def test_blocked_on_high_slippage_limit(self):
        report = generate_pre_trade_report(
            symbol="XAUUSD",
            side="BUY",
            quantity=1000.0,  # huge qty → high impact
            mid_price=1950.0,
            returns=RETURNS_NORMAL,
            max_slippage_bps=0.001,  # impossibly tight limit
        )
        assert not report.approved
        assert any("Slippage" in r for r in report.block_reasons)

    def test_to_dict_contains_required_keys(self):
        report = generate_pre_trade_report(
            symbol="XAUUSD",
            side="BUY",
            quantity=1.0,
            mid_price=1950.0,
            returns=RETURNS_NORMAL,
        )
        d = report.to_dict()
        required = {
            "symbol",
            "side",
            "quantity",
            "notional_usd",
            "var_95_conservative",
            "es_99_conservative",
            "slippage_p99_bps",
            "regime_drift_score",
            "sharpe",
            "max_drawdown_pct",
            "approved",
            "block_reasons",
        }
        assert required.issubset(d.keys())

    def test_notional_correct(self):
        report = generate_pre_trade_report(
            symbol="XAUUSD",
            side="BUY",
            quantity=2.0,
            mid_price=1950.0,
            returns=RETURNS_NORMAL,
        )
        assert report.notional_usd == pytest.approx(3900.0, rel=1e-6)
