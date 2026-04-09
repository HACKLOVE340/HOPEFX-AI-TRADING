# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/analytics.py

Quantitative risk analytics engine.

Implements:
- VaR (Historical, Parametric, Cornish-Fisher) with correct multi-day scaling
- Multi-day VaR via overlapping returns (not sqrt(t) approximation)
- EWMA-based VaR (RiskMetrics lambda=0.94)
- GARCH(1,1) conditional volatility for VaR
- ES / CVaR (Expected Shortfall at 95% and 99%)
- Monte Carlo slippage simulation
- Regime drift score (detects distribution shift)
- Sharpe ratio with standard error
- Max drawdown
- Pre-trade risk report (all metrics in one call)

Multi-day scaling note:
  sqrt(t) scaling is only valid under IID normal returns. For fat-tailed,
  autocorrelated return series like XAUUSD, it systematically understates
  tail risk. Use calculate_var_multiday (overlapping returns) or
  calculate_var_ewma (EWMA conditional vol) for production risk limits.

All functions are pure (no side effects) and thread-safe.
Inputs are validated — functions raise ValueError on bad inputs.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import stats

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=RuntimeWarning)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VaRResult:
    """Value-at-Risk result."""

    confidence: float  # e.g. 0.95
    var_historical: float  # historical simulation VaR (loss, positive = loss)
    var_parametric: float  # parametric (normal) VaR
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
    es_historical: float  # historical ES
    es_parametric: float  # parametric ES
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
    vol_ratio: float  # current_vol / reference_vol
    drift_score: float  # composite score (higher = more drift)
    regime_changed: bool  # drift_score > threshold

    @property
    def description(self) -> str:
        if self.regime_changed:
            return f"REGIME CHANGE DETECTED (score={self.drift_score:.2f})"
        return f"Stable regime (score={self.drift_score:.2f})"


@dataclass
class SharpeResult:
    sharpe: float
    sharpe_se: float  # standard error of Sharpe estimate
    annualised_return: float
    annualised_vol: float
    n_observations: int
    passes_gate: bool  # Sharpe > 1.5 AND SE < 0.3


@dataclass
class MultiDayVaRResult:
    """
    Multi-day VaR computed via overlapping returns (not sqrt(t) scaling).

    Overlapping returns method: construct h-day returns by summing consecutive
    daily returns, then compute VaR on that empirical distribution. This
    correctly captures autocorrelation and fat tails for horizons > 1 day.
    """

    confidence: float
    horizon_days: int
    var_historical: float  # overlapping-returns historical VaR
    var_parametric: float  # parametric scaled by overlapping-returns vol
    var_cornish_fisher: float
    n_overlapping: int  # number of overlapping h-day windows used

    @property
    def var(self) -> float:
        return max(self.var_historical, self.var_parametric, self.var_cornish_fisher)


@dataclass
class EWMAVaRResult:
    """
    VaR using EWMA (RiskMetrics) conditional volatility.

    Uses lambda=0.94 (daily) to estimate current conditional variance,
    then computes parametric VaR from that estimate. More responsive to
    recent volatility spikes than historical simulation.
    """

    confidence: float
    horizon_days: int
    ewma_vol_daily: float  # current EWMA daily vol estimate
    ewma_vol_scaled: float  # scaled to horizon (sqrt(h) * daily_vol — valid for EWMA)
    var_ewma: float  # parametric VaR from EWMA vol
    lambda_: float = 0.94


@dataclass
class GARCHVaRResult:
    """
    VaR using GARCH(1,1) conditional volatility.

    Fits omega, alpha, beta via MLE on the return series, forecasts
    h-day conditional variance by iterating the GARCH recursion, then
    computes parametric VaR from the forecast.
    """

    confidence: float
    horizon_days: int
    omega: float
    alpha: float
    beta: float
    sigma2_forecast: float  # h-day ahead conditional variance
    var_garch: float  # parametric VaR from GARCH forecast
    converged: bool  # whether MLE converged


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
    block_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
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
    returns: NDArray[np.float64],
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> VaRResult:
    """
    Compute 1-day VaR using three methods (historical, parametric, Cornish-Fisher).

    For horizon_days > 1, use calculate_var_multiday (overlapping returns) or
    calculate_var_ewma / calculate_var_garch instead of this function.
    sqrt(t) scaling applied here is only valid for IID normal returns and
    understates tail risk for fat-tailed series like XAUUSD.

    Args:
        returns: Array of daily returns (not percentages).
        confidence: Confidence level (e.g. 0.95 for 95% VaR).
        horizon_days: Holding period in days. For h>1, prefer calculate_var_multiday.

    Returns:
        VaRResult with historical, parametric, and Cornish-Fisher VaR.
        All values are expressed as positive losses (e.g. 0.02 = 2% loss).
    """
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 30:
        raise ValueError(f"Insufficient returns for VaR: need >=30, got {len(returns)}")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0,1), got {confidence}")

    # NOTE: sqrt(t) scaling is a known approximation. For h>1 use calculate_var_multiday.
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
    z_cf = z + (z**2 - 1) * skew / 6 + (z**3 - 3 * z) * kurt / 24 - (2 * z**3 - 5 * z) * skew**2 / 36
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
    returns: NDArray[np.float64],
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
    total_slippage_bps = half_spread_bps + impact_bps + direction * timing_slippage

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
    reference_returns: NDArray[np.float64],
    current_returns: NDArray[np.float64],
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
    returns: NDArray[np.float64],
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
            sharpe=0.0,
            sharpe_se=999.0,
            annualised_return=0.0,
            annualised_vol=0.0,
            n_observations=n,
            passes_gate=False,
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


def compute_max_drawdown(equity_curve: NDArray[np.float64]) -> float:
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


@dataclass
class PreTradeRiskLimits:
    """Risk limits for :func:`generate_pre_trade_report`."""

    bid_ask_spread_bps: float = 5.0
    max_var_pct: float = 0.02
    max_es_pct: float = 0.03
    max_slippage_bps: float = 20.0
    max_drift_score: float = 2.0
    min_sharpe: float = 1.5
    max_drawdown_limit: float = 0.08


def generate_pre_trade_report(
    symbol: str,
    side: str,
    quantity: float,
    mid_price: float,
    returns: NDArray[np.float64],
    equity_curve: NDArray[np.float64] | None = None,
    reference_returns: NDArray[np.float64] | None = None,
    bid_ask_spread_bps: float = 5.0,
    max_var_pct: float = 0.02,  # block if VaR > 2% of notional
    max_es_pct: float = 0.03,  # block if ES > 3% of notional
    max_slippage_bps: float = 20.0,  # block if p99 slippage > 20bps
    max_drift_score: float = 2.0,  # block if regime drift > 2.0
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
    block_reasons: list[str] = []

    # VaR (95%)
    var_result = compute_var(returns, confidence=0.95)
    var_pct = var_result.var / (mid_price + 1e-10)
    if var_pct > max_var_pct:
        block_reasons.append(
            f"VaR {var_pct:.2%} > limit {max_var_pct:.2%}",
        )

    # ES (99%)
    es_result = compute_es(returns, confidence=0.99)
    es_pct = es_result.es / (mid_price + 1e-10)
    if es_pct > max_es_pct:
        block_reasons.append(
            f"ES/CVaR {es_pct:.2%} > limit {max_es_pct:.2%}",
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
            f"Slippage p99 {slip_result.p99_slippage_bps:.1f}bps > limit {max_slippage_bps:.0f}bps",
        )

    # Regime drift
    ref = reference_returns if reference_returns is not None else returns
    recent = returns[-20:] if len(returns) >= 20 else returns
    regime = compute_regime_drift(ref, recent)
    if regime.drift_score > max_drift_score:
        block_reasons.append(
            f"Regime drift score {regime.drift_score:.2f} > limit {max_drift_score:.1f}",
        )

    # Sharpe
    sharpe = compute_sharpe(returns)
    if sharpe.sharpe < min_sharpe:
        block_reasons.append(
            f"Sharpe {sharpe.sharpe:.2f} < minimum {min_sharpe:.1f}",
        )

    # Max drawdown
    if equity_curve is not None and len(equity_curve) >= 2:
        mdd = compute_max_drawdown(equity_curve)
    else:
        # Estimate from returns
        eq: NDArray[np.float64] = np.asarray(np.cumprod(1 + returns), dtype=np.float64)
        mdd = compute_max_drawdown(eq)

    if mdd > max_drawdown_limit:
        block_reasons.append(
            f"Max drawdown {mdd:.2%} > limit {max_drawdown_limit:.2%}",
        )

    approved = len(block_reasons) == 0

    if not approved:
        logger.warning(
            "PRE-TRADE RISK REPORT: BLOCKED | symbol=%s side=%s qty=%.4f notional=%.2f reasons=%s",
            symbol,
            side,
            quantity,
            notional,
            block_reasons,
        )
    else:
        logger.info(
            "PRE-TRADE RISK REPORT: APPROVED | symbol=%s side=%s qty=%.4f "
            "notional=%.2f var95=%.4f es99=%.4f slip_p99=%.1fbps "
            "drift=%.2f sharpe=%.2f mdd=%.2f%%",
            symbol,
            side,
            quantity,
            notional,
            var_result.var,
            es_result.es,
            slip_result.p99_slippage_bps,
            regime.drift_score,
            sharpe.sharpe,
            mdd * 100,
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


# ---------------------------------------------------------------------------
# Multi-day VaR via overlapping returns (replaces sqrt(t) scaling)
# ---------------------------------------------------------------------------


def calculate_var_multiday(
    returns: NDArray[np.float64],
    confidence: float = 0.95,
    horizon_days: int = 10,
) -> MultiDayVaRResult:
    """
    Compute multi-day VaR using overlapping h-day returns.

    Constructs the empirical distribution of h-day returns by summing
    consecutive daily returns with a sliding window. This correctly
    captures autocorrelation and fat tails — unlike sqrt(t) scaling which
    assumes IID normal returns.

    For XAUUSD, 10-day VaR computed this way is typically 20-40% larger
    than the sqrt(10) approximation due to volatility clustering.

    Args:
        returns: Daily return series (at least 252 + horizon_days observations
                 recommended for stable estimates).
        confidence: VaR confidence level (e.g. 0.95).
        horizon_days: Holding period in days (h).

    Returns:
        MultiDayVaRResult with overlapping-returns VaR estimates.
    """
    returns = np.asarray(returns, dtype=float)
    min_obs = max(30, horizon_days * 3)
    if len(returns) < min_obs:
        raise ValueError(f"Need at least {min_obs} observations for {horizon_days}-day VaR, got {len(returns)}")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0,1), got {confidence}")
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be >= 1, got {horizon_days}")

    # Build overlapping h-day log-return windows
    # r_t^(h) = sum(r_{t}, r_{t+1}, ..., r_{t+h-1})
    n = len(returns)
    h_returns = np.array([np.sum(returns[i : i + horizon_days]) for i in range(n - horizon_days + 1)])
    n_windows = len(h_returns)

    alpha = 1 - confidence

    # Historical VaR from overlapping h-day distribution
    var_hist = float(-np.percentile(h_returns, alpha * 100))

    # Parametric: use std of overlapping h-day returns (not sqrt(h) * daily_std)
    mu_h = float(np.mean(h_returns))
    sigma_h = float(np.std(h_returns, ddof=1))
    z = float(stats.norm.ppf(alpha))
    var_param = float(-(mu_h + z * sigma_h))

    # Cornish-Fisher on h-day distribution
    skew_h = float(stats.skew(h_returns))
    kurt_h = float(stats.kurtosis(h_returns))
    z_cf = z + (z**2 - 1) * skew_h / 6 + (z**3 - 3 * z) * kurt_h / 24 - (2 * z**3 - 5 * z) * skew_h**2 / 36
    var_cf = float(-(mu_h + z_cf * sigma_h))

    return MultiDayVaRResult(
        confidence=confidence,
        horizon_days=horizon_days,
        var_historical=max(var_hist, 0.0),
        var_parametric=max(var_param, 0.0),
        var_cornish_fisher=max(var_cf, 0.0),
        n_overlapping=n_windows,
    )


# ---------------------------------------------------------------------------
# EWMA VaR (RiskMetrics)
# ---------------------------------------------------------------------------


def calculate_var_ewma(
    returns: NDArray[np.float64],
    confidence: float = 0.95,
    horizon_days: int = 1,
    lambda_: float = 0.94,
) -> EWMAVaRResult:
    """
    Compute VaR using EWMA (RiskMetrics) conditional volatility.

    EWMA assigns exponentially decaying weights to past squared returns,
    making it more responsive to recent volatility spikes than rolling
    historical vol. lambda=0.94 is the RiskMetrics daily standard.

    For multi-day horizons, sqrt(h) scaling of the EWMA daily vol is
    valid under the assumption that the EWMA process is approximately
    stationary over the horizon — acceptable for h <= 10 days.

    Args:
        returns: Daily return series.
        confidence: VaR confidence level.
        horizon_days: Holding period in days.
        lambda_: EWMA decay factor (0.94 for daily, 0.97 for monthly).

    Returns:
        EWMAVaRResult with current conditional vol and VaR.
    """
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 30:
        raise ValueError(f"Need >=30 returns for EWMA VaR, got {len(returns)}")
    if not 0 < lambda_ < 1:
        raise ValueError(f"lambda_ must be in (0,1), got {lambda_}")

    # Initialise with sample variance of first 30 observations
    sigma2 = float(np.var(returns[:30], ddof=1))

    # Iterate EWMA recursion: sigma2_t = lambda * sigma2_{t-1} + (1-lambda) * r_{t-1}^2
    for r in returns:
        sigma2 = lambda_ * sigma2 + (1 - lambda_) * float(r) ** 2

    ewma_vol_daily = float(np.sqrt(sigma2))

    # Scale to horizon: sqrt(h) * daily_vol (valid for EWMA under stationarity)
    ewma_vol_scaled = ewma_vol_daily * np.sqrt(horizon_days)

    alpha = 1 - confidence
    z = float(stats.norm.ppf(alpha))
    mu = float(np.mean(returns)) * horizon_days  # drift over horizon
    var_ewma = float(-(mu + z * ewma_vol_scaled))

    return EWMAVaRResult(
        confidence=confidence,
        horizon_days=horizon_days,
        ewma_vol_daily=ewma_vol_daily,
        ewma_vol_scaled=ewma_vol_scaled,
        var_ewma=max(var_ewma, 0.0),
        lambda_=lambda_,
    )


# ---------------------------------------------------------------------------
# GARCH(1,1) VaR
# ---------------------------------------------------------------------------


def _garch11_loglik(
    params: NDArray[np.float64],
    returns: NDArray[np.float64],
) -> float:
    """Negative log-likelihood for GARCH(1,1)."""
    omega, alpha, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
        return 1e10

    n = len(returns)
    sigma2 = np.empty(n)
    # Initialise with unconditional variance
    sigma2[0] = omega / (1 - alpha - beta + 1e-10)

    for t in range(1, n):
        sigma2[t] = omega + alpha * returns[t - 1] ** 2 + beta * sigma2[t - 1]
        if sigma2[t] <= 0:
            return 1e10

    # Gaussian log-likelihood
    ll = -0.5 * np.sum(np.log(sigma2) + returns**2 / sigma2)
    return -ll  # return negative for minimisation


def calculate_var_garch(
    returns: NDArray[np.float64],
    confidence: float = 0.95,
    horizon_days: int = 10,
) -> GARCHVaRResult:
    """
    Compute multi-day VaR using GARCH(1,1) conditional volatility forecast.

    Fits GARCH(1,1) via MLE, then iterates the variance recursion h steps
    ahead to obtain the conditional variance forecast. This is the industry
    standard for multi-day VaR on assets with volatility clustering (XAUUSD,
    equities, crypto).

    The h-step forecast uses:
        sigma2_{t+h} = omega/(1-alpha-beta) + (alpha+beta)^h * (sigma2_t - omega/(1-alpha-beta))

    Args:
        returns: Daily return series (minimum 252 observations recommended).
        confidence: VaR confidence level.
        horizon_days: Forecast horizon in days.

    Returns:
        GARCHVaRResult with fitted parameters and h-day VaR.
    """
    from scipy.optimize import minimize

    returns = np.asarray(returns, dtype=float)
    if len(returns) < 100:
        raise ValueError(f"Need >=100 returns for GARCH VaR, got {len(returns)}")

    # Initial parameter guess: small omega, typical alpha/beta
    sample_var = float(np.var(returns, ddof=1))
    x0 = np.array([sample_var * 0.05, 0.08, 0.88])
    bounds = [(1e-8, None), (1e-6, 0.5), (1e-6, 0.9999)]

    result = minimize(
        _garch11_loglik,
        x0,
        args=(returns,),
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 500, "ftol": 1e-9},
    )

    converged = result.success
    omega, alpha, beta = result.x if converged else x0

    # Compute current conditional variance (last observation)
    n = len(returns)
    sigma2_t = omega / (1 - alpha - beta + 1e-10)
    for t in range(1, n):
        sigma2_t = omega + alpha * returns[t - 1] ** 2 + beta * sigma2_t
        sigma2_t = max(sigma2_t, 1e-10)

    # h-step ahead variance forecast (GARCH recursion)
    persistence = alpha + beta
    long_run_var = omega / (1 - persistence + 1e-10)

    if horizon_days == 1:
        sigma2_forecast = sigma2_t
    else:
        # Sum of h conditional variances (for VaR of h-day return)
        sigma2_forecast = 0.0
        sigma2_i = sigma2_t
        for _i in range(horizon_days):
            sigma2_forecast += sigma2_i
            sigma2_i = long_run_var + persistence * (sigma2_i - long_run_var)
            sigma2_i = max(sigma2_i, 1e-10)

    sigma_forecast = float(np.sqrt(sigma2_forecast))

    alpha_level = 1 - confidence
    z = float(stats.norm.ppf(alpha_level))
    mu_h = float(np.mean(returns)) * horizon_days
    var_garch = float(-(mu_h + z * sigma_forecast))

    return GARCHVaRResult(
        confidence=confidence,
        horizon_days=horizon_days,
        omega=float(omega),
        alpha=float(alpha),
        beta=float(beta),
        sigma2_forecast=float(sigma2_forecast),
        var_garch=max(var_garch, 0.0),
        converged=converged,
    )


# ── High-level facade used by superadmin dashboard ───────────────────────────


class RiskAnalytics:
    """Facade that bundles the module-level analytics functions into a class.

    Superadmin endpoints instantiate this and call methods to get platform-wide
    risk metrics without needing to know the individual function names.
    """

    def platform_var(self, confidence: float = 0.95) -> dict[str, object]:
        """Return a platform-wide VaR summary.

        Attempts to fetch live returns from the execution engine; falls back to
        empty data gracefully.

        Args:
            confidence: Confidence level for VaR (default 0.95).

        Returns:
            Dict with ``var_95``, ``var_99``, ``expected_shortfall``, and
            supporting metrics.
        """
        try:
            import execution.engine as _eng_mod

            # The engine module exposes a module-level singleton when running;
            # fall back gracefully if it is not yet initialised.
            engine = getattr(_eng_mod, "_engine_instance", None) or getattr(_eng_mod, "engine", None)
            returns = getattr(engine, "daily_returns", []) or []
        except Exception:
            returns = []

        if len(returns) < 10:
            return {
                "var_95": 0.0,
                "var_99": 0.0,
                "expected_shortfall": 0.0,
                "max_drawdown": 0.0,
                "current_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "portfolio_value": 0.0,
                "currency": "USD",
                "note": "Insufficient return history for VaR calculation",
            }

        import numpy as np

        arr = np.asarray(returns, dtype=float)
        var95 = float(compute_var(arr, confidence=0.95).var)
        var99 = float(compute_var(arr, confidence=0.99).var)
        es95 = float(compute_es(arr, confidence=0.95).es)
        sharpe = float(compute_sharpe(arr).sharpe)
        max_dd = float(compute_max_drawdown(np.cumsum(arr)))

        return {
            "var_95": round(var95, 4),
            "var_99": round(var99, 4),
            "expected_shortfall": round(es95, 4),
            "max_drawdown": round(max_dd, 4),
            "current_drawdown": 0.0,
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "portfolio_value": 0.0,
            "currency": "USD",
        }
