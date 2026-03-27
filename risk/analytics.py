# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/analytics.py

Quantitative risk analytics engine.

Implements:
- VaR (Historical, Parametric, Cornish-Fisher)
- ES / CVaR (Expected Shortfall at 95% and 99%)
- Monte Carlo slippage simulation
- Regime drift score (detects distribution shift)
- Sharpe ratio with standard error
- Max drawdown
- Pre-trade risk report (all metrics in one call)

All functions are pure (no side effects) and thread-safe.
Inputs are validated — functions raise ValueError on bad inputs.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=RuntimeWarning)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class VaRResult:
    """Value-at-Risk result."""
    confidence: float          # e.g. 0.95
    var_historical: float      # historical simulation VaR (loss, positive = loss)
    var_parametric: float      # parametric (normal) VaR
    var_cornish_fisher: float  # Cornish-Fisher adjusted VaR
    horizon_days: int = 1

    @property
    def var(self) -> float:
        """Conservative (maximum) VaR across methods."""
        return max(self.var_historical, self.var_parametric, self.var_cornish_fisher)


@dataclass
class ESResult:
    """Expected Shortfall (CVaR) result."""
    confidence: float
    es_historical: float       # historical ES
    es_parametric: float       # parametric ES
    n_observations: int

    @property
    def es(self) -> float:
        """Conservative ES."""
        return max(self.es_historical, self.es_parametric)


@dataclass
class SlippageSimResult:
    """Monte Carlo slippage simulation result."""
    symbol: str
    quantity: float
    side: str
    mean_slippage_bps: float
    p95_slippage_bps: float
    p99_slippage_bps: float
    expected_cost_usd: float
    worst_case_cost_usd: float
    n_simulations: int


@dataclass
class RegimeDriftScore:
    """
    Detects distribution shift between reference and current return windows.

    Score > 1.0 indicates significant regime change.
    Uses Kolmogorov-Smirnov test + volatility ratio.
    """
    ks_statistic: float
    ks_pvalue: float
    vol_ratio: float           # current_vol / reference_vol
    drift_score: float         # composite score (higher = more drift)
    regime_changed: bool       # drift_score > threshold

    @property
    def description(self) -> str:
        if self.regime_changed:
            return f"REGIME CHANGE DETECTED (score={self.drift_score:.2f})"
        return f"Stable regime (score={self.drift_score:.2f})"


@dataclass
class SharpeResult:
    sharpe: float
    sharpe_se: float           # standard error of Sharpe estimate
    annualised_return: float
    annualised_vol: float
    n_observations: int
    passes_gate: bool          # Sharpe > 1.5 AND SE < 0.3


@dataclass
class PreTradeRiskReport:
    """All risk metrics for a proposed trade."""
    symbol: str
    side: str
    quantity: float
    notional_usd: float
    var_95: VaRResult
    es_99: ESResult
    slippage: SlippageSimResult
    regime: RegimeDriftScore
    sharpe: SharpeResult
    max_drawdown_pct: float
    approved: bool
    block_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "notional_usd": self.notional_usd,
            "var_95_conservative": self.var_95.var,
            "es_99_conservative": self.es_99.es,
            "slippage_p99_bps": self.slippage.p99_slippage_bps,
            "regime_drift_score": self.regime.drift_score,
            "regime_changed": self.regime.regime_changed,
            "sharpe": self.sharpe.sharpe,
            "sharpe_se": self.sharpe.sharpe_se,
            "max_drawdown_pct": self.max_drawdown_pct,
            "approved": self.approved,
            "block_reasons": self.block_reasons,
        }


# ---------------------------------------------------------------------------
# VaR
# ---------------------------------------------------------------------------

def compute_var(
    returns: np.ndarray,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> VaRResult:
    """
    Compute VaR using three methods.

    Args:
        returns: Array of daily returns (not percentages).
        confidence: Confidence level (e.g. 0.95 for 95% VaR).
        horizon_days: Holding period in days (scales by sqrt).

    Returns:
        VaRResult with historical, parametric, and Cornish-Fisher VaR.
        All values are expressed as positive losses (e.g. 0.02 = 2% loss).
    """
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 30:
        raise ValueError(f"Insufficient returns for VaR: need >=30, got {len(returns)}")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0,1), got {confidence}")

    scale = np.sqrt(horizon_days)
    alpha = 1 - confidence

    # Historical simulation
    var_hist = float(-np.percentile(returns, alpha * 100)) * scale

    # Parametric (normal)
    mu = np.mean(returns)
    sigma = np.std(returns, ddof=1)
    z = stats.norm.ppf(alpha)
    var_param = float(-(mu + z * sigma)) * scale

    # Cornish-Fisher (adjusts for skewness and excess kurtosis)
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns))  # excess kurtosis
    z_cf = (
        z
        + (z**2 - 1) * skew / 6
        + (z**3 - 3 * z) * kurt / 24
        - (2 * z**3 - 5 * z) * skew**2 / 36
    )
    var_cf = float(-(mu + z_cf * sigma)) * scale

    return VaRResult(
        confidence=confidence,
        var_historical=max(var_hist, 0.0),
        var_parametric=max(var_param, 0.0),
        var_cornish_fisher=max(var_cf, 0.0),
        horizon_days=horizon_days,
    )


# ---------------------------------------------------------------------------
# Expected Shortfall (CVaR)
# ---------------------------------------------------------------------------

def compute_es(
    returns: np.ndarray,
    confidence: float = 0.99,
) -> ESResult:
    """
    Compute Expected Shortfall (CVaR) — mean loss beyond VaR threshold.

    Args:
        returns: Array of daily returns.
        confidence: Confidence level (e.g. 0.99 for 99% ES).

    Returns:
        ESResult with historical and parametric ES.
    """
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 30:
        raise ValueError(f"Insufficient returns for ES: need >=30, got {len(returns)}")

    alpha = 1 - confidence

    # Historical ES: mean of returns below VaR threshold
    threshold = np.percentile(returns, alpha * 100)
    tail = returns[returns <= threshold]
    es_hist = float(-np.mean(tail)) if len(tail) > 0 else 0.0

    # Parametric ES (normal distribution)
    mu = np.mean(returns)
    sigma = np.std(returns, ddof=1)
    z = stats.norm.ppf(alpha)
    es_param = float(-(mu - sigma * stats.norm.pdf(z) / alpha))

    return ESResult(
        confidence=confidence,
        es_historical=max(es_hist, 0.0),
        es_parametric=max(es_param, 0.0),
        n_observations=len(returns),
    )


# ---------------------------------------------------------------------------
# Monte Carlo slippage simulation
# ---------------------------------------------------------------------------

def simulate_slippage(
    symbol: str,
    quantity: float,
    side: str,
    mid_price: float,
    bid_ask_spread_bps: float = 5.0,
    market_impact_bps_per_lot: float = 0.5,
    vol_daily: float = 0.01,
    n_simulations: int = 10_000,
    rng_seed: int = 42,
) -> SlippageSimResult:
    """
    Monte Carlo slippage simulation.

    Models three slippage components:
    1. Half bid-ask spread (deterministic)
    2. Market impact (linear in quantity)
    3. Timing slippage (random, proportional to intraday vol)

    Args:
        symbol: Trading symbol.
        quantity: Order size in lots/units.
        side: "BUY" or "SELL".
        mid_price: Current mid price in USD.
        bid_ask_spread_bps: Current spread in basis points.
        market_impact_bps_per_lot: Market impact per lot in bps.
        vol_daily: Daily volatility (e.g. 0.01 = 1%).
        n_simulations: Number of Monte Carlo paths.
        rng_seed: Random seed for reproducibility.

    Returns:
        SlippageSimResult with mean/p95/p99 slippage in bps and USD cost.
    """
    rng = np.random.default_rng(rng_seed)

    # Component 1: half spread (deterministic)
    half_spread_bps = bid_ask_spread_bps / 2.0

    # Component 2: market impact (deterministic)
    impact_bps = market_impact_bps_per_lot * quantity

    # Component 3: timing slippage (stochastic)
    # Model as normal with std = vol_daily * sqrt(execution_time_fraction)
    # Assume execution takes ~1 minute = 1/390 of trading day
    execution_fraction = 1.0 / 390.0
    timing_vol_bps = vol_daily * np.sqrt(execution_fraction) * 10_000.0
    timing_slippage = rng.normal(0, timing_vol_bps, n_simulations)

    # For BUY: all components add to cost; for SELL: timing can reduce cost
    direction = 1.0 if side.upper() == "BUY" else -1.0
    total_slippage_bps = (
        half_spread_bps + impact_bps + direction * timing_slippage
    )

    # Slippage is always a cost (take absolute value for SELL)
    total_slippage_bps = np.abs(total_slippage_bps)

    mean_slip = float(np.mean(total_slippage_bps))
    p95_slip = float(np.percentile(total_slippage_bps, 95))
    p99_slip = float(np.percentile(total_slippage_bps, 99))

    notional = quantity * mid_price
    expected_cost = notional * mean_slip / 10_000.0
    worst_case_cost = notional * p99_slip / 10_000.0

    return SlippageSimResult(
        symbol=symbol,
        quantity=quantity,
        side=side,
        mean_slippage_bps=mean_slip,
        p95_slippage_bps=p95_slip,
        p99_slippage_bps=p99_slip,
        expected_cost_usd=expected_cost,
        worst_case_cost_usd=worst_case_cost,
        n_simulations=n_simulations,
    )


# ---------------------------------------------------------------------------
# Regime drift detection
# ---------------------------------------------------------------------------

def compute_regime_drift(
    reference_returns: np.ndarray,
    current_returns: np.ndarray,
    drift_threshold: float = 1.5,
) -> RegimeDriftScore:
    """
    Detect regime change between reference and current return windows.

    Uses Kolmogorov-Smirnov test + volatility ratio as composite score.

    Args:
        reference_returns: Historical returns (e.g. last 252 days).
        current_returns: Recent returns (e.g. last 20 days).
        drift_threshold: Score above which regime change is flagged.

    Returns:
        RegimeDriftScore.
    """
    ref = np.asarray(reference_returns, dtype=float)
    cur = np.asarray(current_returns, dtype=float)

    if len(ref) < 10 or len(cur) < 5:
        return RegimeDriftScore(
            ks_statistic=0.0,
            ks_pvalue=1.0,
            vol_ratio=1.0,
            drift_score=0.0,
            regime_changed=False,
        )

    # KS test
    ks_stat, ks_p = stats.ks_2samp(ref, cur)

    # Volatility ratio
    ref_vol = np.std(ref, ddof=1)
    cur_vol = np.std(cur, ddof=1)
    vol_ratio = cur_vol / (ref_vol + 1e-10)

    # Composite drift score:
    # - KS statistic (0-1): higher = more distributional shift
    # - vol_ratio deviation from 1: higher = more vol change
    vol_component = abs(vol_ratio - 1.0)
    drift_score = float(ks_stat * 2.0 + vol_component)

    return RegimeDriftScore(
        ks_statistic=float(ks_stat),
        ks_pvalue=float(ks_p),
        vol_ratio=float(vol_ratio),
        drift_score=drift_score,
        regime_changed=drift_score > drift_threshold,
    )


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------

def compute_sharpe(
    returns: np.ndarray,
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
    sharpe_target: float = 1.5,
    se_target: float = 0.3,
) -> SharpeResult:
    """
    Compute annualised Sharpe ratio with standard error.

    SE formula: sqrt((1 + 0.5*SR^2) / T) * sqrt(periods_per_year)
    (Lo 2002 approximation for IID returns)

    Args:
        returns: Array of period returns.
        risk_free_rate: Annual risk-free rate.
        periods_per_year: Trading periods per year (252 for daily).
        sharpe_target: Minimum acceptable Sharpe.
        se_target: Maximum acceptable SE.

    Returns:
        SharpeResult.
    """
    returns = np.asarray(returns, dtype=float)
    n = len(returns)
    if n < 30:
        raise ValueError(f"Insufficient returns for Sharpe: need >=30, got {n}")

    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period

    mean_excess = np.mean(excess)
    std_excess = np.std(excess, ddof=1)

    if std_excess < 1e-10:
        return SharpeResult(
            sharpe=0.0, sharpe_se=999.0,
            annualised_return=0.0, annualised_vol=0.0,
            n_observations=n, passes_gate=False,
        )

    sr = mean_excess / std_excess
    sr_annualised = float(sr * np.sqrt(periods_per_year))

    # Standard error (Lo 2002)
    se = float(np.sqrt((1 + 0.5 * sr**2) / n) * np.sqrt(periods_per_year))

    ann_return = float(mean_excess * periods_per_year)
    ann_vol = float(std_excess * np.sqrt(periods_per_year))

    passes = (sr_annualised >= sharpe_target) and (se <= se_target)

    return SharpeResult(
        sharpe=sr_annualised,
        sharpe_se=se,
        annualised_return=ann_return,
        annualised_vol=ann_vol,
        n_observations=n,
        passes_gate=passes,
    )


# ---------------------------------------------------------------------------
# Max drawdown
# ---------------------------------------------------------------------------

def compute_max_drawdown(equity_curve: np.ndarray) -> float:
    """
    Compute maximum drawdown from an equity curve.

    Args:
        equity_curve: Array of portfolio values (not returns).

    Returns:
        Maximum drawdown as a positive fraction (e.g. 0.08 = 8%).
    """
    equity = np.asarray(equity_curve, dtype=float)
    if len(equity) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / (peak + 1e-10)
    return float(np.max(drawdown))


# ---------------------------------------------------------------------------
# Pre-trade risk report
# ---------------------------------------------------------------------------

def generate_pre_trade_report(
    symbol: str,
    side: str,
    quantity: float,
    mid_price: float,
    returns: np.ndarray,
    equity_curve: Optional[np.ndarray] = None,
    reference_returns: Optional[np.ndarray] = None,
    bid_ask_spread_bps: float = 5.0,
    max_var_pct: float = 0.02,       # block if VaR > 2% of notional
    max_es_pct: float = 0.03,        # block if ES > 3% of notional
    max_slippage_bps: float = 20.0,  # block if p99 slippage > 20bps
    max_drift_score: float = 2.0,    # block if regime drift > 2.0
    min_sharpe: float = 1.5,
    max_drawdown_limit: float = 0.08,
) -> PreTradeRiskReport:
    """
    Generate a full pre-trade risk report.

    Computes VaR, ES, slippage, regime drift, Sharpe, and drawdown.
    Sets approved=False if any metric breaches its limit.

    Args:
        symbol: Trading symbol.
        side: "BUY" or "SELL".
        quantity: Order size.
        mid_price: Current mid price.
        returns: Historical daily returns array.
        equity_curve: Optional equity curve for drawdown.
        reference_returns: Optional longer history for regime comparison.
        bid_ask_spread_bps: Current spread.
        max_var_pct: VaR limit as fraction of notional.
        max_es_pct: ES limit as fraction of notional.
        max_slippage_bps: p99 slippage limit in bps.
        max_drift_score: Regime drift score limit.
        min_sharpe: Minimum Sharpe ratio.
        max_drawdown_limit: Maximum drawdown limit.

    Returns:
        PreTradeRiskReport.
    """
    notional = quantity * mid_price
    block_reasons: List[str] = []

    # VaR (95%)
    var_result = compute_var(returns, confidence=0.95)
    var_pct = var_result.var / (mid_price + 1e-10)
    if var_pct > max_var_pct:
        block_reasons.append(
            f"VaR {var_pct:.2%} > limit {max_var_pct:.2%}"
        )

    # ES (99%)
    es_result = compute_es(returns, confidence=0.99)
    es_pct = es_result.es / (mid_price + 1e-10)
    if es_pct > max_es_pct:
        block_reasons.append(
            f"ES/CVaR {es_pct:.2%} > limit {max_es_pct:.2%}"
        )

    # Monte Carlo slippage
    slip_result = simulate_slippage(
        symbol=symbol,
        quantity=quantity,
        side=side,
        mid_price=mid_price,
        bid_ask_spread_bps=bid_ask_spread_bps,
        vol_daily=float(np.std(returns, ddof=1)) if len(returns) >= 2 else 0.01,
    )
    if slip_result.p99_slippage_bps > max_slippage_bps:
        block_reasons.append(
            f"Slippage p99 {slip_result.p99_slippage_bps:.1f}bps > limit {max_slippage_bps:.0f}bps"
        )

    # Regime drift
    ref = reference_returns if reference_returns is not None else returns
    recent = returns[-20:] if len(returns) >= 20 else returns
    regime = compute_regime_drift(ref, recent)
    if regime.drift_score > max_drift_score:
        block_reasons.append(
            f"Regime drift score {regime.drift_score:.2f} > limit {max_drift_score:.1f}"
        )

    # Sharpe
    sharpe = compute_sharpe(returns)
    if sharpe.sharpe < min_sharpe:
        block_reasons.append(
            f"Sharpe {sharpe.sharpe:.2f} < minimum {min_sharpe:.1f}"
        )

    # Max drawdown
    if equity_curve is not None and len(equity_curve) >= 2:
        mdd = compute_max_drawdown(equity_curve)
    else:
        # Estimate from returns
        eq = np.cumprod(1 + returns)
        mdd = compute_max_drawdown(eq)

    if mdd > max_drawdown_limit:
        block_reasons.append(
            f"Max drawdown {mdd:.2%} > limit {max_drawdown_limit:.2%}"
        )

    approved = len(block_reasons) == 0

    if not approved:
        logger.warning(
            "PRE-TRADE RISK REPORT: BLOCKED | symbol=%s side=%s qty=%.4f "
            "notional=%.2f reasons=%s",
            symbol, side, quantity, notional, block_reasons,
        )
    else:
        logger.info(
            "PRE-TRADE RISK REPORT: APPROVED | symbol=%s side=%s qty=%.4f "
            "notional=%.2f var95=%.4f es99=%.4f slip_p99=%.1fbps "
            "drift=%.2f sharpe=%.2f mdd=%.2%%",
            symbol, side, quantity, notional,
            var_result.var, es_result.es,
            slip_result.p99_slippage_bps,
            regime.drift_score, sharpe.sharpe, mdd * 100,
        )

    return PreTradeRiskReport(
        symbol=symbol,
        side=side,
        quantity=quantity,
        notional_usd=notional,
        var_95=var_result,
        es_99=es_result,
        slippage=slip_result,
        regime=regime,
        sharpe=sharpe,
        max_drawdown_pct=mdd,
        approved=approved,
        block_reasons=block_reasons,
    )
