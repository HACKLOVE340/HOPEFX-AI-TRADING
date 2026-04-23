# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
analytics/monte_carlo.py
========================
Bootstrap Monte Carlo simulation for backtest robustness analysis.

Addresses the survivorship bias in single-path backtests by resampling
trade returns with replacement and computing confidence intervals on all
key metrics: Sharpe, max drawdown, CAGR, win rate, profit factor.

Methods
-------
bootstrap_trade_returns()
    Resample the observed trade sequence N times. Each path is an
    independent draw of the same number of trades from the empirical
    distribution. This tests whether the strategy's edge is robust to
    different orderings and subsets of the trade history.

block_bootstrap()
    Preserves autocorrelation structure by resampling contiguous blocks
    of trades rather than individual trades. Better for strategies with
    serial correlation (e.g. trend-following).

Usage
-----
    from analytics.monte_carlo import MonteCarloEngine, run_bootstrap

    # From a list of trade P&L values
    result = run_bootstrap(
        trade_pnls=[42.5, -18.0, 31.2, ...],
        initial_capital=100_000,
        n_paths=5000,
    )
    logger.info(result.sharpe_ci_95)   # (lower, upper) 95% CI on Sharpe
    logger.info(result.max_dd_ci_95)   # (lower, upper) 95% CI on max drawdown
    logger.info(result.ruin_probability)

Configuration (env vars)
------------------------
MC_N_PATHS          — number of bootstrap paths (default: 5000)
MC_RUIN_THRESHOLD   — equity fraction below which path is ruined (default: 0.5)
MC_BLOCK_SIZE       — block size for block bootstrap (default: 10)
MC_RANDOM_SEED      — RNG seed for reproducibility (default: 42)
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


def _ljung_box_p(pnls: np.ndarray, lags: int = 5) -> float:
    """
    Ljung-Box portmanteau test for serial autocorrelation.

    Returns the p-value for the null hypothesis that the first `lags`
    autocorrelations are jointly zero.  A small p-value (< 0.05) means
    significant autocorrelation is present and block bootstrap should be used.

    Implemented without scipy to avoid an optional dependency.  Uses the
    standard Ljung-Box Q statistic:
        Q = n*(n+2) * sum_{k=1}^{lags} rho_k^2 / (n-k)
    which is chi-squared distributed with `lags` degrees of freedom under H0.
    """
    n = len(pnls)
    if n < lags + 2:
        return 1.0  # not enough data — assume no autocorrelation

    mu = float(np.mean(pnls))
    demeaned = pnls - mu
    var = float(np.dot(demeaned, demeaned))
    if var == 0.0:
        return 1.0

    q_stat = 0.0
    for k in range(1, lags + 1):
        rho_k = float(np.dot(demeaned[k:], demeaned[:-k])) / var
        q_stat += rho_k**2 / (n - k)
    q_stat *= n * (n + 2)

    # Chi-squared CDF via regularised incomplete gamma (pure Python)
    # P(chi2 > Q | df=lags) = 1 - regularised_gamma(lags/2, Q/2)
    p_value = _chi2_sf(q_stat, df=lags)
    return p_value


def _chi2_sf(x: float, df: int) -> float:
    """
    Survival function of the chi-squared distribution (1 - CDF).

    Returns the regularised upper incomplete gamma Q(df/2, x/2), which
    equals P(chi2(df) > x).  Implemented without scipy via a continued-
    fraction / series expansion (Numerical Recipes §6.2).
    Accurate to ~1e-7 for the parameter ranges used here.
    """
    if x <= 0.0:
        return 1.0
    a = df / 2.0
    x2 = x / 2.0
    # Q(a, x) = regularised upper incomplete gamma = Gamma(a,x) / Gamma(a)
    return _regularised_upper_gamma(a, x2)


def _regularised_upper_gamma(a: float, x: float) -> float:
    """
    Regularised upper incomplete gamma Q(a, x) = Gamma(a, x) / Gamma(a).

    Uses series expansion for x < a+1, continued fraction for x >= a+1.
    """
    if x < a + 1.0:
        # Q = 1 - P  where P is the regularised lower incomplete gamma
        return 1.0 - _regularised_lower_gamma_series(a, x)
    return _regularised_upper_gamma_cf(a, x)


def _regularised_lower_gamma_series(a: float, x: float) -> float:
    """Regularised lower incomplete gamma P(a, x) via series expansion."""
    if x == 0.0:
        return 0.0
    ap = a
    delta = 1.0 / a
    total = delta
    for _ in range(300):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * 1e-12:
            break
    # P(a,x) = e^{-x} * x^a / Gamma(a) * series_sum
    log_factor = -x + a * math.log(x) - math.lgamma(a)
    return math.exp(log_factor) * total


def _regularised_upper_gamma_cf(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) via Lentz continued fraction."""
    fpmin = 1e-300
    b = x + 1.0 - a
    c = 1.0 / fpmin
    d = 1.0 / b if abs(b) > fpmin else 1.0 / fpmin
    h = d
    for i in range(1, 301):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < fpmin:
            d = fpmin
        c = b + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    # Q(a,x) = e^{-x} * x^a / Gamma(a) * h
    log_factor = -x + a * math.log(x) - math.lgamma(a)
    return math.exp(log_factor) * h


def choose_bootstrap_method(
    pnls: np.ndarray,
    autocorr_p_threshold: float = 0.05,
    lags: int = 5,
) -> str:
    """
    Automatically choose between IID and block bootstrap.

    Runs a Ljung-Box test on the trade PnL sequence.  If the p-value is
    below `autocorr_p_threshold`, significant serial autocorrelation is
    present and block bootstrap is used.  Otherwise IID bootstrap is used.

    Parameters
    ----------
    pnls                  : Array of per-trade P&L values.
    autocorr_p_threshold  : Significance level for the Ljung-Box test.
                            Default 0.05 (5%).
    lags                  : Number of lags to test. Default 5.

    Returns
    -------
    "block" if autocorrelation is detected, "iid" otherwise.
    """
    if len(pnls) < lags + 2:
        # Not enough trades to test — default to block (conservative)
        return "block"
    p = _ljung_box_p(pnls, lags=lags)
    method = "block" if p < autocorr_p_threshold else "iid"
    logger.debug(
        "choose_bootstrap_method: Ljung-Box p=%.4f (threshold=%.2f) -> %s",
        p,
        autocorr_p_threshold,
        method,
    )
    return method


# ── Configuration ─────────────────────────────────────────────────────────────
MC_N_PATHS: int = int(os.getenv("MC_N_PATHS", "5000"))
MC_RUIN_THRESHOLD: float = float(os.getenv("MC_RUIN_THRESHOLD", "0.5"))
MC_BLOCK_SIZE: int = int(os.getenv("MC_BLOCK_SIZE", "10"))
MC_RANDOM_SEED: int = int(os.getenv("MC_RANDOM_SEED", "42"))

# Annualisation factor for Sharpe (trade-level, assuming ~252 trades/year)
_ANNUALISE = math.sqrt(252)


# ── Result data structures ────────────────────────────────────────────────────


@dataclass
class BootstrapResult:
    """
    Full bootstrap Monte Carlo result with confidence intervals.

    All CI tuples are (lower_bound, upper_bound) at the specified level.
    """

    n_paths: int
    n_trades: int
    initial_capital: float

    # Point estimates from original trade sequence
    original_sharpe: float
    original_max_dd: float
    original_cagr: float
    original_win_rate: float
    original_profit_factor: float

    # Bootstrap distributions (all paths)
    sharpe_distribution: list[float] = field(default_factory=list)
    max_dd_distribution: list[float] = field(default_factory=list)
    cagr_distribution: list[float] = field(default_factory=list)
    final_equity_distribution: list[float] = field(default_factory=list)

    # Confidence intervals (95% and 99%)
    sharpe_ci_95: tuple[float, float] = (0.0, 0.0)
    sharpe_ci_99: tuple[float, float] = (0.0, 0.0)
    max_dd_ci_95: tuple[float, float] = (0.0, 0.0)
    max_dd_ci_99: tuple[float, float] = (0.0, 0.0)
    cagr_ci_95: tuple[float, float] = (0.0, 0.0)
    final_equity_ci_95: tuple[float, float] = (0.0, 0.0)

    # Risk metrics
    ruin_probability: float = 0.0
    probability_of_profit: float = 0.0
    expected_shortfall_5pct: float = 0.0  # CVaR at 5%

    # Sharpe standard error: 1/sqrt(2*(N-1))
    sharpe_se: float = 0.0

    # Robustness score: fraction of paths with Sharpe > 0
    sharpe_positive_fraction: float = 0.0

    def summary(self) -> dict[str, object]:
        """Return a JSON-serialisable summary dict."""
        return {
            "n_paths": self.n_paths,
            "n_trades": self.n_trades,
            "original_sharpe": round(self.original_sharpe, 4),
            "original_max_dd": round(self.original_max_dd, 4),
            "original_cagr": round(self.original_cagr, 4),
            "original_win_rate": round(self.original_win_rate, 4),
            "original_profit_factor": round(self.original_profit_factor, 4),
            "sharpe_ci_95": [round(x, 4) for x in self.sharpe_ci_95],
            "sharpe_ci_99": [round(x, 4) for x in self.sharpe_ci_99],
            "max_dd_ci_95": [round(x, 4) for x in self.max_dd_ci_95],
            "cagr_ci_95": [round(x, 4) for x in self.cagr_ci_95],
            "final_equity_ci_95": [round(x, 4) for x in self.final_equity_ci_95],
            "ruin_probability": round(self.ruin_probability, 4),
            "probability_of_profit": round(self.probability_of_profit, 4),
            "expected_shortfall_5pct": round(self.expected_shortfall_5pct, 4),
            "sharpe_se": round(self.sharpe_se, 4),
            "sharpe_positive_fraction": round(self.sharpe_positive_fraction, 4),
        }


# ── Core engine ───────────────────────────────────────────────────────────────


class MonteCarloEngine:
    """
    Bootstrap Monte Carlo engine for backtest robustness analysis.

    Two resampling methods:
    - IID bootstrap: resample individual trades with replacement.
      Best for strategies with independent trade returns.
    - Block bootstrap: resample contiguous blocks of trades.
      Better for strategies with serial correlation.
    """

    def __init__(
        self,
        n_paths: int = MC_N_PATHS,
        ruin_threshold: float = MC_RUIN_THRESHOLD,
        block_size: int = MC_BLOCK_SIZE,
        seed: int = MC_RANDOM_SEED,
    ) -> None:
        self.n_paths = n_paths
        self.ruin_threshold = ruin_threshold
        self.block_size = block_size
        self._rng = np.random.default_rng(seed)

    def run(
        self,
        trade_pnls: list[float],
        initial_capital: float = 100_000.0,
        method: str = "auto",
        avg_hold_bars: int | None = None,
    ) -> BootstrapResult:
        """
        Run bootstrap Monte Carlo simulation.

        Parameters
        ----------
        trade_pnls      : List of per-trade net P&L values in USD.
        initial_capital : Starting equity for each path.
        method          : Resampling method:
                          "auto"  — run Ljung-Box autocorrelation test and
                                    choose "block" or "iid" automatically.
                                    This is the default and recommended choice.
                          "block" — block bootstrap (preserves autocorrelation).
                                    Use for trend-following strategies.
                          "iid"   — IID bootstrap (assumes independent trades).
                                    Only use when autocorrelation is confirmed absent.
        avg_hold_bars   : Average trade hold period in bars.  When provided and
                          method="block" or "auto" selects block, the block size
                          is set to avg_hold_bars (aligns with the natural
                          autocorrelation horizon).  Overrides self.block_size.

        Returns
        -------
        BootstrapResult with confidence intervals on all key metrics.
        """
        if len(trade_pnls) < 2:
            logger.warning("MonteCarloEngine: need at least 2 trades — returning empty result")
            return self._empty_result(initial_capital)

        pnls = np.array(trade_pnls, dtype=float)
        n_trades = len(pnls)

        # ── Resolve method ────────────────────────────────────────────────────
        resolved_method = choose_bootstrap_method(pnls) if method == "auto" else method

        # ── Resolve block size ────────────────────────────────────────────────
        # When avg_hold_bars is provided, use it as the block size so the
        # resampling block aligns with the strategy's natural autocorrelation
        # horizon.  Minimum block size is 2.
        if avg_hold_bars is not None and avg_hold_bars > 0:
            effective_block_size = max(2, int(round(avg_hold_bars)))
        else:
            effective_block_size = self.block_size

        # ── Point estimates from original sequence ────────────────────────────
        orig_sharpe = self._sharpe(pnls)
        orig_max_dd = self._max_drawdown(pnls, initial_capital)
        orig_cagr = self._cagr(pnls, initial_capital, n_trades)
        orig_win_rate = float(np.mean(pnls > 0))
        gross_profit = float(np.sum(pnls[pnls > 0]))
        gross_loss = float(abs(np.sum(pnls[pnls < 0])))
        orig_pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        logger.info(
            "MonteCarloEngine.run: method=%s (resolved=%s) block_size=%d n_trades=%d",
            method,
            resolved_method,
            effective_block_size,
            n_trades,
        )

        # ── Bootstrap paths ───────────────────────────────────────────────────
        sharpe_dist: list[float] = []
        max_dd_dist: list[float] = []
        cagr_dist: list[float] = []
        final_equity_dist: list[float] = []
        ruin_count = 0

        for _ in range(self.n_paths):
            if resolved_method == "block":
                sampled = self._block_resample(pnls, n_trades, effective_block_size)
            else:
                sampled = self._rng.choice(pnls, size=n_trades, replace=True)

            # Equity path
            equity = initial_capital
            ruined = False
            for pnl in sampled:
                equity += pnl
                if equity <= initial_capital * self.ruin_threshold:
                    ruined = True
                    break

            if ruined:
                ruin_count += 1
                final_equity_dist.append(initial_capital * self.ruin_threshold)
                max_dd_dist.append(1.0 - self.ruin_threshold)
                sharpe_dist.append(-999.0)
                cagr_dist.append(-1.0)
            else:
                final_equity_dist.append(equity)
                sharpe_dist.append(self._sharpe(sampled))
                max_dd_dist.append(self._max_drawdown(sampled, initial_capital))
                cagr_dist.append(self._cagr(sampled, initial_capital, n_trades))

        sharpe_arr = np.array(sharpe_dist)
        max_dd_arr = np.array(max_dd_dist)
        cagr_arr = np.array(cagr_dist)
        final_arr = np.array(final_equity_dist)

        # ── Confidence intervals ──────────────────────────────────────────────
        def ci(arr: np.ndarray, level: float) -> tuple[float, float]:
            alpha = (1 - level) / 2 * 100
            return (
                float(np.percentile(arr, alpha)),
                float(np.percentile(arr, 100 - alpha)),
            )

        # Filter out ruin paths for Sharpe CI (they're -999 sentinels)
        valid_sharpe = sharpe_arr[sharpe_arr > -100]

        result = BootstrapResult(
            n_paths=self.n_paths,
            n_trades=n_trades,
            initial_capital=initial_capital,
            original_sharpe=orig_sharpe,
            original_max_dd=orig_max_dd,
            original_cagr=orig_cagr,
            original_win_rate=orig_win_rate,
            original_profit_factor=orig_pf,
            sharpe_distribution=sharpe_dist,
            max_dd_distribution=max_dd_dist,
            cagr_distribution=cagr_dist,
            final_equity_distribution=final_equity_dist,
            sharpe_ci_95=ci(valid_sharpe, 0.95) if len(valid_sharpe) > 1 else (0.0, 0.0),
            sharpe_ci_99=ci(valid_sharpe, 0.99) if len(valid_sharpe) > 1 else (0.0, 0.0),
            max_dd_ci_95=ci(max_dd_arr, 0.95),
            max_dd_ci_99=ci(max_dd_arr, 0.99),
            cagr_ci_95=ci(cagr_arr, 0.95),
            final_equity_ci_95=ci(final_arr, 0.95),
            ruin_probability=ruin_count / self.n_paths,
            probability_of_profit=float(np.mean(final_arr > initial_capital)),
            expected_shortfall_5pct=float(np.mean(final_arr[final_arr <= np.percentile(final_arr, 5)]))
            if len(final_arr) > 0
            else 0.0,
            sharpe_se=1.0 / math.sqrt(2 * (n_trades - 1)) if n_trades > 1 else 0.0,
            sharpe_positive_fraction=float(np.mean(valid_sharpe > 0)) if len(valid_sharpe) > 0 else 0.0,
        )

        logger.info(
            "MonteCarloEngine: %d paths, %d trades | "
            "Sharpe=%.3f CI95=[%.3f, %.3f] | MaxDD=%.1f%% CI95=[%.1f%%, %.1f%%] | "
            "Ruin=%.1f%% | Sharpe>0=%.1f%%",
            self.n_paths,
            n_trades,
            orig_sharpe,
            result.sharpe_ci_95[0],
            result.sharpe_ci_95[1],
            orig_max_dd * 100,
            result.max_dd_ci_95[0] * 100,
            result.max_dd_ci_95[1] * 100,
            result.ruin_probability * 100,
            result.sharpe_positive_fraction * 100,
        )
        return result

    def _block_resample(
        self,
        pnls: np.ndarray,
        n_trades: int,
        block_size: int | None = None,
    ) -> np.ndarray:
        """
        Resample contiguous blocks of trades (preserves autocorrelation).

        Parameters
        ----------
        pnls       : Source trade PnL array.
        n_trades   : Number of trades in the resampled path.
        block_size : Block length.  None = use self.block_size.
        """
        bs = block_size if block_size is not None else self.block_size
        n = len(pnls)
        blocks = []
        total = 0
        while total < n_trades:
            start = int(self._rng.integers(0, n))
            end = min(start + bs, n)
            blocks.append(pnls[start:end])
            total += end - start
        return np.concatenate(blocks)[:n_trades]

    @staticmethod
    def _sharpe(pnls: np.ndarray) -> float:
        """Trade-level annualised Sharpe ratio."""
        if len(pnls) < 2:
            return 0.0
        std = float(np.std(pnls))
        if std == 0:
            return 0.0
        return float(np.mean(pnls) / std * _ANNUALISE)

    @staticmethod
    def _max_drawdown(pnls: np.ndarray, initial_capital: float = 100_000.0) -> float:
        """Maximum drawdown as a fraction of peak equity."""
        equity = initial_capital + np.cumsum(pnls)
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        return float(np.max(dd)) if len(dd) > 0 else 0.0

    @staticmethod
    def _cagr(pnls: np.ndarray, initial_capital: float, n_trades: int) -> float:
        """Approximate CAGR assuming 252 trades per year."""
        final = initial_capital + float(np.sum(pnls))
        if final <= 0 or initial_capital <= 0:
            return -1.0
        years = n_trades / 252.0
        if years <= 0:
            return 0.0
        return float((final / initial_capital) ** (1.0 / years) - 1.0)

    def _empty_result(self, initial_capital: float) -> BootstrapResult:
        return BootstrapResult(
            n_paths=0,
            n_trades=0,
            initial_capital=initial_capital,
            original_sharpe=0.0,
            original_max_dd=0.0,
            original_cagr=0.0,
            original_win_rate=0.0,
            original_profit_factor=0.0,
        )


# ── Convenience function ──────────────────────────────────────────────────────


def run_bootstrap(
    trade_pnls: list[float],
    initial_capital: float = 100_000.0,
    n_paths: int = MC_N_PATHS,
    method: str = "auto",
    avg_hold_bars: int | None = None,
) -> BootstrapResult:
    """
    Run bootstrap Monte Carlo on a list of trade P&L values.

    Parameters
    ----------
    trade_pnls      : Per-trade net P&L in USD.
    initial_capital : Starting equity.
    n_paths         : Number of bootstrap paths.
    method          : "auto" (default) — Ljung-Box test selects "block" or
                      "iid" automatically.  Pass "block" or "iid" to override.
    avg_hold_bars   : Average trade hold period in bars.  When provided and
                      block bootstrap is used, sets the block size to match
                      the strategy's natural autocorrelation horizon.

    Returns
    -------
    BootstrapResult with confidence intervals on Sharpe, drawdown, CAGR.
    """
    engine = MonteCarloEngine(n_paths=n_paths)
    return engine.run(
        trade_pnls,
        initial_capital=initial_capital,
        method=method,
        avg_hold_bars=avg_hold_bars,
    )
