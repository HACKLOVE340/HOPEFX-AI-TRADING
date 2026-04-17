# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Advanced Risk Analytics

Professional-grade risk management tools:
- Value at Risk (VaR) calculations
- Monte Carlo simulations
- Stress testing framework
- Drawdown analysis
- Risk-adjusted performance metrics

VaR multi-day scaling policy (P4)
----------------------------------
``calculate_var_historical`` and ``calculate_var_parametric`` use sqrt(t) only
as a last-resort fallback when there is insufficient history for direct
multi-day window estimation.  Both methods set ``scaling_approximate=True``
and emit a RuntimeWarning when the fallback fires.

For production risk limits on XAUUSD (time_horizon > 1), always use:
  - ``calculate_var_multiday()``  — direct overlapping/non-overlapping windows
  - ``calculate_var_ewma()``      — EWMA-weighted historical simulation

The module-level ``ENFORCE_MULTIDAY_VAR`` flag (default True) causes
``calculate_var_historical`` and ``calculate_var_parametric`` to raise
``RuntimeError`` when called with ``time_horizon > 1`` in production, forcing
callers to use the correct multi-day methods.  Set to False only in tests.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Production enforcement flag (P4)
# ---------------------------------------------------------------------------
# When True, calculate_var_historical and calculate_var_parametric raise
# RuntimeError for time_horizon > 1, forcing callers to use
# calculate_var_multiday or calculate_var_ewma.
#
# Set HOPEFX_VAR_ENFORCE_MULTIDAY=0 in .env to disable (tests / legacy callers).
# Default: True in production.
ENFORCE_MULTIDAY_VAR: bool = os.getenv("HOPEFX_VAR_ENFORCE_MULTIDAY", "1") != "0"


class RiskMetricType(Enum):
    """Types of risk metrics."""

    VAR_HISTORICAL = "var_historical"
    VAR_PARAMETRIC = "var_parametric"
    VAR_MONTE_CARLO = "var_monte_carlo"
    CVAR = "cvar"  # Conditional VaR / Expected Shortfall
    MAX_DRAWDOWN = "max_drawdown"
    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    CALMAR_RATIO = "calmar_ratio"


@dataclass
class VaRResult:
    """Value at Risk calculation result."""

    var_value: float  # Dollar or percent loss
    confidence_level: float  # e.g., 0.95 for 95%
    time_horizon: int  # Days
    method: str
    # scaling_approximate is True when sqrt(t) was used as a fallback because
    # there was insufficient history for direct multi-day window estimation.
    # It is also True for parametric/Monte Carlo methods that assume normality,
    # since real gold/FX returns have fat tails and volatility clustering.
    scaling_approximate: bool = False
    scaling_note: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "var_value": self.var_value,
            "confidence_level": self.confidence_level,
            "time_horizon": self.time_horizon,
            "method": self.method,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.scaling_approximate:
            d["scaling_approximate"] = True
            d["scaling_note"] = self.scaling_note
        return d


@dataclass
class MonteCarloResult:
    """Monte Carlo simulation result."""

    expected_return: float
    expected_volatility: float
    var_95: float
    var_99: float
    cvar_95: float
    max_gain: float
    max_loss: float
    simulated_paths: NDArray[np.float64] | None = None
    num_simulations: int = 10000
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_return": self.expected_return,
            "expected_volatility": self.expected_volatility,
            "var_95": self.var_95,
            "var_99": self.var_99,
            "cvar_95": self.cvar_95,
            "max_gain": self.max_gain,
            "max_loss": self.max_loss,
            "num_simulations": self.num_simulations,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class StressTestResult:
    """Stress test scenario result."""

    scenario_name: str
    portfolio_impact: float  # Percentage impact
    dollar_impact: float  # Dollar impact
    affected_positions: list[str]
    risk_level: str  # 'low', 'medium', 'high', 'severe'
    recommendation: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class DrawdownAnalysis:
    """Drawdown analysis result."""

    current_drawdown: float
    max_drawdown: float
    max_drawdown_duration: int  # Days
    current_drawdown_duration: int
    recovery_rate: float  # Historical recovery rate
    drawdown_events: list[dict[str, Any]]
    underwater_periods: list[dict[str, Any]]


class AdvancedRiskAnalytics:
    """
    Professional risk analytics engine.

    Features:
    - Multiple VaR calculation methods
    - Monte Carlo portfolio simulation
    - Stress testing scenarios
    - Comprehensive drawdown analysis
    - Risk-adjusted performance metrics
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize risk analytics.

        Args:
            config: Configuration dict with:
                - var_confidence: VaR confidence level (default: 0.95)
                - mc_simulations: Monte Carlo simulations (default: 10000)
                - risk_free_rate: Annual risk-free rate (default: 0.05)
        """
        self.config = config or {}
        self.var_confidence = self.config.get("var_confidence", 0.95)
        self.mc_simulations = self.config.get("mc_simulations", 10000)
        self.risk_free_rate = self.config.get("risk_free_rate", 0.05)

        # Stress test scenarios
        self.stress_scenarios = self._initialize_stress_scenarios()

        logger.info("Advanced Risk Analytics initialized")

    def _initialize_stress_scenarios(self) -> dict[str, dict[str, Any]]:
        """Initialize predefined stress test scenarios."""
        return {
            "market_crash_2008": {
                "name": "Market Crash (2008 Style)",
                "equities": -0.50,
                "forex": -0.15,
                "gold": 0.10,
                "crypto": -0.60,
                "bonds": 0.05,
                "description": "Severe market downturn similar to 2008 financial crisis",
            },
            "flash_crash": {
                "name": "Flash Crash",
                "equities": -0.10,
                "forex": -0.05,
                "gold": 0.02,
                "crypto": -0.25,
                "bonds": 0.01,
                "description": "Sudden sharp decline with quick recovery",
            },
            "rate_hike_shock": {
                "name": "Interest Rate Shock (+200bps)",
                "equities": -0.15,
                "forex": 0.05,
                "gold": -0.10,
                "crypto": -0.20,
                "bonds": -0.12,
                "description": "Unexpected aggressive rate hike by central banks",
            },
            "geopolitical_crisis": {
                "name": "Geopolitical Crisis",
                "equities": -0.20,
                "forex": -0.08,
                "gold": 0.15,
                "crypto": -0.15,
                "bonds": 0.03,
                "description": "Major geopolitical event causing market uncertainty",
            },
            "crypto_winter": {
                "name": "Crypto Winter",
                "equities": -0.05,
                "forex": 0.00,
                "gold": 0.02,
                "crypto": -0.80,
                "bonds": 0.00,
                "description": "Severe cryptocurrency market downturn",
            },
            "dollar_collapse": {
                "name": "USD Collapse",
                "equities": -0.10,
                "forex": 0.20,  # Non-USD pairs benefit
                "gold": 0.30,
                "crypto": 0.15,
                "bonds": -0.05,
                "description": "Sharp devaluation of US Dollar",
            },
            "best_case": {
                "name": "Bull Market Rally",
                "equities": 0.30,
                "forex": 0.05,
                "gold": -0.05,
                "crypto": 0.50,
                "bonds": -0.02,
                "description": "Strong bull market across assets",
            },
        }

    # ============================================================
    # VALUE AT RISK (VaR)
    # ============================================================

    def calculate_var_historical(
        self,
        returns: NDArray[np.float64],
        confidence_level: float | None = None,
        time_horizon: int = 1,
        portfolio_value: float | None = None,
    ) -> VaRResult:
        """
        Calculate Historical VaR.

        Uses historical returns to estimate potential losses.

        Args:
            returns: Array of historical returns
            confidence_level: VaR confidence (default from config)
            time_horizon: Time horizon in days
            portfolio_value: Optional portfolio value for dollar VaR

        Returns:
            VaRResult object

        Note on sqrt(t) scaling (P4)
        ----------------------------
        Scaling 1-day VaR by sqrt(t) is the Basel II square-root-of-time rule.
        It is only theoretically valid when returns are i.i.d. and normally
        distributed — an assumption violated by real financial returns (fat
        tails, autocorrelation, volatility clustering).  For gold/FX intraday
        returns the error can be material at horizons beyond 1 day.

        When ENFORCE_MULTIDAY_VAR=True (default), calling this method with
        time_horizon > 1 raises RuntimeError.  Use calculate_var_multiday()
        or calculate_var_ewma() for production risk limits on XAUUSD.
        """
        confidence_level = confidence_level or self.var_confidence

        # P4 enforcement: block sqrt(t) paths for multi-day production limits
        if time_horizon > 1 and ENFORCE_MULTIDAY_VAR:
            raise RuntimeError(
                f"calculate_var_historical called with time_horizon={time_horizon} > 1. "
                "sqrt(t) scaling is not valid for XAUUSD (fat tails, autocorrelation). "
                "Use calculate_var_multiday() or calculate_var_ewma() instead. "
                "Set HOPEFX_VAR_ENFORCE_MULTIDAY=0 to disable this check (tests only).",
            )

        # 1-day VaR at the requested confidence level
        var_percentile = np.percentile(returns, (1 - confidence_level) * 100)

        scaling_approximate = False
        scaling_note = ""

        if time_horizon == 1:
            var_scaled = var_percentile
        else:
            # ENFORCE_MULTIDAY_VAR=False path (tests / legacy callers only).
            # Multi-day VaR via overlapping return windows (no sqrt(t) assumption).
            t = int(time_horizon)
            if len(returns) >= t * 2:
                multi_day = np.array(
                    [np.sum(returns[i : i + t]) for i in range(len(returns) - t + 1)],
                )
                var_scaled = np.percentile(multi_day, (1 - confidence_level) * 100)
            else:
                # Insufficient history — fall back to sqrt(t) with a warning.
                # sqrt(t) is only valid for i.i.d. normal returns; real gold/FX
                # returns have fat tails and autocorrelation so this is approximate.
                import warnings as _w

                _w.warn(
                    f"calculate_var_historical: insufficient data for {t}-day window "
                    f"({len(returns)} bars). Falling back to sqrt(t) scaling "
                    f"(approximate — valid only for i.i.d. normal returns).",
                    RuntimeWarning,
                    stacklevel=3,
                )
                var_percentile = float(np.nan_to_num(var_percentile, nan=0.0))
                var_scaled = var_percentile * np.sqrt(max(time_horizon, 0.0))
                scaling_approximate = True
                scaling_note = (
                    f"sqrt(t) fallback used: only {len(returns)} bars available for "
                    f"{t}-day window. Result is approximate (assumes i.i.d. normal returns)."
                )

        var_value = abs(var_scaled * portfolio_value) if portfolio_value else abs(var_scaled)

        return VaRResult(
            var_value=var_value,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method="historical",
            scaling_approximate=scaling_approximate,
            scaling_note=scaling_note,
        )

    def calculate_var_parametric(
        self,
        returns: NDArray[np.float64],
        confidence_level: float | None = None,
        time_horizon: int = 1,
        portfolio_value: float | None = None,
    ) -> VaRResult:
        """
        Calculate Parametric (Variance-Covariance) VaR.

        Assumes returns are normally distributed.  For gold/FX intraday returns
        this assumption is violated: empirical kurtosis is typically 4–8 (fat
        tails) and volatility is autocorrelated.  The result will underestimate
        tail risk at high confidence levels (99%+).

        Multi-day scaling uses mu_t = mu*t, sigma_t = sigma*sqrt(t) — the
        correct formula under normality.  The sqrt(t) component is approximate
        for real returns with autocorrelation or GARCH effects.

        Args:
            returns: Array of historical returns
            confidence_level: VaR confidence (default from config)
            time_horizon: Time horizon in days
            portfolio_value: Optional portfolio value for dollar VaR

        Returns:
            VaRResult with scaling_approximate=True (normality assumed)

        Note (P4)
        ---------
        When ENFORCE_MULTIDAY_VAR=True (default), calling this method with
        time_horizon > 1 raises RuntimeError.  Use calculate_var_multiday()
        or calculate_var_ewma() for production risk limits on XAUUSD.
        """
        from scipy import stats

        confidence_level = confidence_level or self.var_confidence

        # P4 enforcement: block sqrt(t) paths for multi-day production limits
        if time_horizon > 1 and ENFORCE_MULTIDAY_VAR:
            raise RuntimeError(
                f"calculate_var_parametric called with time_horizon={time_horizon} > 1. "
                "Parametric sqrt(t) scaling assumes i.i.d. normal returns — invalid for "
                "XAUUSD (fat tails, autocorrelation). "
                "Use calculate_var_multiday() or calculate_var_ewma() instead. "
                "Set HOPEFX_VAR_ENFORCE_MULTIDAY=0 to disable this check (tests only).",
            )

        # Test normality (Jarque-Bera) and warn if rejected at 5% level.
        # This is informational — the calculation proceeds regardless.
        if len(returns) >= 20:
            try:
                _, jb_pvalue = stats.jarque_bera(returns)
                if jb_pvalue < 0.05:
                    import warnings as _w

                    _w.warn(
                        f"calculate_var_parametric: Jarque-Bera normality test rejected "
                        f"(p={jb_pvalue:.4f}). Returns are non-normal; parametric VaR "
                        f"will underestimate tail risk. Consider calculate_var_historical() "
                        f"or calculate_var_multiday() instead.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
            except Exception as _jb_exc:
                logger.debug(
                    "calculate_var_parametric: Jarque-Bera test skipped: %s",
                    _jb_exc,
                )

        mean_return = np.mean(returns)
        std_return = np.std(returns)

        # Z-score for confidence level
        z_score = stats.norm.ppf(1 - confidence_level)

        # Calculate 1-day VaR
        var_value = -(mean_return + z_score * std_return)

        if time_horizon == 1:
            var_scaled = var_value
        else:
            # ENFORCE_MULTIDAY_VAR=False path (tests / legacy callers only).
            # Scale mean and std to the t-day horizon, then recompute VaR.
            # Under normality: mu_t = mu*t, sigma_t = sigma*sqrt(t).
            # This is more accurate than scaling the 1-day VaR by sqrt(t)
            # because it correctly scales the mean component linearly.
            mean_return = float(np.nan_to_num(mean_return, nan=0.0))
            std_return = float(np.nan_to_num(std_return, nan=0.0))
            mean_t = mean_return * time_horizon
            std_t = std_return * np.sqrt(max(time_horizon, 0.0))
            var_scaled = -(mean_t + z_score * std_t)

        # Convert to dollar value if portfolio value provided
        var_final = abs(var_scaled * portfolio_value) if portfolio_value else abs(var_scaled)

        return VaRResult(
            var_value=var_final,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method="parametric",
            # Parametric VaR always assumes normality; flag as approximate for
            # any asset with fat tails (gold, FX, crypto).
            scaling_approximate=True,
            scaling_note=(
                "Parametric VaR assumes normally distributed returns. "
                "Gold/FX returns have fat tails (excess kurtosis); this method "
                "underestimates tail risk at high confidence levels. "
                "Use calculate_var_historical() or calculate_var_multiday() for "
                "more accurate estimates."
            ),
        )

    def calculate_var_monte_carlo(
        self,
        returns: NDArray[np.float64],
        confidence_level: float | None = None,
        time_horizon: int = 1,
        num_simulations: int | None = None,
        portfolio_value: float | None = None,
        use_historical_bootstrap: bool = False,
    ) -> VaRResult:
        """
        Calculate Monte Carlo VaR.

        Two simulation modes:

        Gaussian (default, use_historical_bootstrap=False)
            Simulates t-day returns from N(mu*t, sigma*sqrt(t)).  Fast but
            assumes normality — underestimates tail risk for fat-tailed assets.
            sqrt(t) scaling is approximate for autocorrelated returns.

        Historical bootstrap (use_historical_bootstrap=True)
            Resamples 1-day returns with replacement and sums t draws to form
            each t-day path.  Preserves the empirical fat-tail distribution
            without assuming normality.  Preferred for gold/FX.

        Args:
            returns: Array of historical 1-day returns
            confidence_level: VaR confidence (default from config)
            time_horizon: Time horizon in days
            num_simulations: Number of simulated paths
            portfolio_value: Optional portfolio value for dollar VaR
            use_historical_bootstrap: If True, use bootstrap resampling instead
                of Gaussian simulation (more accurate for fat-tailed assets)

        Returns:
            VaRResult; scaling_approximate=True when Gaussian mode is used
        """
        confidence_level = confidence_level or self.var_confidence
        num_simulations = num_simulations or self.mc_simulations

        mean_return = np.mean(returns)
        std_return = np.std(returns)

        # Use a local Generator seeded from OS entropy so we do not corrupt the
        # global numpy RNG state. Reproducibility is not required for Monte Carlo VaR.
        rng = np.random.default_rng(seed=int.from_bytes(os.urandom(4), "little"))

        if use_historical_bootstrap and len(returns) >= time_horizon:
            # Bootstrap: resample 1-day returns and sum t draws per path.
            # Preserves empirical fat tails and skewness without normality assumption.
            idx = rng.integers(0, len(returns), size=(num_simulations, time_horizon))
            simulated_returns = returns[idx].sum(axis=1)
            scaling_approximate = False
            scaling_note = ""
            method_tag = "monte_carlo_bootstrap"
        else:
            # Gaussian simulation: N(mu*t, sigma*sqrt(t)).
            # sqrt(t) scaling is the Basel II rule — valid only for i.i.d. normal
            # returns.  For gold/FX with fat tails this underestimates tail risk.
            if use_historical_bootstrap and len(returns) < time_horizon:
                import warnings as _w

                _w.warn(
                    f"calculate_var_monte_carlo: insufficient history for bootstrap "
                    f"({len(returns)} bars < {time_horizon}-day horizon). "
                    f"Falling back to Gaussian simulation (approximate).",
                    RuntimeWarning,
                    stacklevel=2,
                )
            mean_return = float(np.nan_to_num(mean_return, nan=0.0))
            std_return = float(np.nan_to_num(std_return, nan=0.0))
            simulated_returns = rng.normal(
                mean_return * time_horizon,
                std_return * np.sqrt(max(time_horizon, 0.0)),
                num_simulations,
            )
            scaling_approximate = True
            scaling_note = (
                "Gaussian Monte Carlo uses sqrt(t) scaling which assumes i.i.d. normal "
                "returns. Gold/FX returns have fat tails; this underestimates tail risk. "
                "Set use_historical_bootstrap=True for a distribution-free estimate."
            )
            method_tag = "monte_carlo_gaussian"

        # Calculate VaR from simulations
        var_value = -np.percentile(simulated_returns, (1 - confidence_level) * 100)

        var_final = abs(var_value * portfolio_value) if portfolio_value else abs(var_value)

        return VaRResult(
            var_value=var_final,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method=method_tag,
            scaling_approximate=scaling_approximate,
            scaling_note=scaling_note,
        )

    def calculate_var_multiday(
        self,
        returns: NDArray[np.float64],
        confidence_level: float | None = None,
        time_horizon: int = 10,
        portfolio_value: float | None = None,
        method: str = "overlapping",
    ) -> "VaRResult":
        """
        Calculate multi-day VaR without the sqrt(t) i.i.d. assumption.

        Two methods are supported:

        overlapping (default)
            Compute t-day overlapping returns directly from the return series.
            Captures autocorrelation and fat tails at the cost of overlapping
            observations (Christoffersen & Diebold, 1997).  Preferred when the
            return series is long enough (≥ 5× time_horizon observations).

        non_overlapping
            Use non-overlapping t-day blocks.  Fewer observations but
            statistically independent.  Preferred for regulatory reporting.

        Both methods are strictly more accurate than sqrt(t) scaling for
        assets with autocorrelation or fat tails (e.g. XAUUSD).

        Args:
            returns        : 1-day return series (numpy array)
            confidence_level: VaR confidence level (default from config)
            time_horizon   : Horizon in days
            portfolio_value: Optional portfolio value for dollar VaR
            method         : 'overlapping' or 'non_overlapping'

        Returns:
            VaRResult with method='multiday_<method>'
        """
        confidence_level = confidence_level or self.var_confidence

        if time_horizon <= 1:
            # Delegate to historical 1-day VaR
            return self.calculate_var_historical(
                returns,
                confidence_level,
                time_horizon=1,
                portfolio_value=portfolio_value,
            )

        if method == "non_overlapping":
            # Non-overlapping t-day blocks
            n_blocks = len(returns) // time_horizon
            if n_blocks < 10:
                # Fall back to overlapping if too few blocks
                method = "overlapping"
            else:
                blocks = [np.sum(returns[i * time_horizon : (i + 1) * time_horizon]) for i in range(n_blocks)]
                multiday_returns = np.array(blocks)

        if method == "overlapping":
            # Overlapping t-day cumulative returns
            if len(returns) < time_horizon + 1:
                # Not enough data — fall back to sqrt(t) with explicit warning.
                import warnings as _w

                _w.warn(
                    f"calculate_var_multiday: only {len(returns)} bars available for "
                    f"{time_horizon}-day horizon. Falling back to sqrt(t) scaling "
                    f"(approximate — valid only for i.i.d. normal returns).",
                    RuntimeWarning,
                    stacklevel=2,
                )
                var_1d = float(np.nan_to_num(np.percentile(returns, (1 - confidence_level) * 100), nan=0.0))
                var_scaled = var_1d * np.sqrt(max(time_horizon, 0.0))
                val = abs(var_scaled * portfolio_value) if portfolio_value else abs(var_scaled)
                return VaRResult(
                    var_value=val,
                    confidence_level=confidence_level,
                    time_horizon=time_horizon,
                    method="multiday_sqrtt_fallback",
                    scaling_approximate=True,
                    scaling_note=(
                        f"sqrt(t) fallback: only {len(returns)} bars available for "
                        f"{time_horizon}-day window. Collect more history for accurate "
                        f"multi-day VaR."
                    ),
                )
            multiday_returns = np.array(
                [np.sum(returns[i : i + time_horizon]) for i in range(len(returns) - time_horizon + 1)],
            )

        var_percentile = np.percentile(multiday_returns, (1 - confidence_level) * 100)  # pylint: disable=possibly-used-before-assignment
        val = abs(var_percentile * portfolio_value) if portfolio_value else abs(var_percentile)

        return VaRResult(
            var_value=val,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method=f"multiday_{method}",
        )

    def calculate_var_ewma(
        self,
        returns: NDArray[np.float64],
        confidence_level: float | None = None,
        time_horizon: int = 1,
        portfolio_value: float | None = None,
        decay: float = 0.94,
    ) -> "VaRResult":
        """
        EWMA (RiskMetrics) VaR — volatility-weighted historical simulation.

        Uses exponentially weighted variance to scale each historical return
        by the ratio of current volatility to historical volatility.  This
        captures volatility clustering (GARCH-like) without requiring a full
        GARCH fit.

        For time_horizon > 1, EWMA-scaled returns are summed over overlapping
        t-day windows — no sqrt(t) assumption.  This is the recommended method
        for production risk limits on XAUUSD.

        decay = 0.94 is the RiskMetrics daily decay factor.
        decay = 0.97 is recommended for weekly data.

        Args:
            returns        : 1-day return series
            confidence_level: VaR confidence level
            time_horizon   : Horizon in days
            portfolio_value: Optional portfolio value
            decay          : EWMA decay factor λ (0 < λ < 1)

        Returns:
            VaRResult with method='ewma'
        """
        confidence_level = confidence_level or self.var_confidence

        if len(returns) < 10:
            # Delegate to 1-day historical (no multi-day scaling needed)
            return self.calculate_var_historical(
                returns,
                confidence_level,
                1,
                portfolio_value,
            )

        # Compute EWMA variance
        ewma_var = np.zeros(len(returns))
        ewma_var[0] = returns[0] ** 2
        for i in range(1, len(returns)):
            ewma_var[i] = decay * ewma_var[i - 1] + (1 - decay) * returns[i] ** 2

        ewma_var = np.nan_to_num(ewma_var, nan=0.0)
        current_vol = np.sqrt(max(float(ewma_var[-1]), 0.0))
        hist_vol = np.sqrt(max(float(np.mean(ewma_var)), 0.0))

        if hist_vol == 0:
            return self.calculate_var_historical(
                returns,
                confidence_level,
                1,
                portfolio_value,
            )

        # Scale historical returns by vol ratio (volatility-weighted HS)
        vol_ratio = current_vol / hist_vol
        scaled_returns = returns * vol_ratio

        scaling_approximate = False
        scaling_note = ""

        if time_horizon <= 1:
            var_percentile = np.percentile(scaled_returns, (1 - confidence_level) * 100)
            var_scaled = var_percentile
        else:
            t = int(time_horizon)
            if len(scaled_returns) >= t * 2:
                # Overlapping t-day windows on EWMA-scaled returns.
                # No sqrt(t) assumption — captures autocorrelation and fat tails.
                multi_day = np.array(
                    [np.sum(scaled_returns[i : i + t]) for i in range(len(scaled_returns) - t + 1)],
                )
                var_scaled = np.percentile(multi_day, (1 - confidence_level) * 100)
            else:
                # Insufficient history — sqrt(t) fallback with explicit warning.
                import warnings as _w

                _w.warn(
                    f"calculate_var_ewma: insufficient data for {t}-day overlapping "
                    f"windows ({len(scaled_returns)} bars). Falling back to sqrt(t) "
                    f"scaling (approximate).",
                    RuntimeWarning,
                    stacklevel=2,
                )
                var_1d = float(np.nan_to_num(np.percentile(scaled_returns, (1 - confidence_level) * 100), nan=0.0))
                var_scaled = var_1d * np.sqrt(max(time_horizon, 0.0))
                scaling_approximate = True
                scaling_note = (
                    f"sqrt(t) fallback: only {len(scaled_returns)} bars for "
                    f"{t}-day window. Collect more history for accurate EWMA VaR."
                )

        val = abs(var_scaled * portfolio_value) if portfolio_value else abs(var_scaled)

        return VaRResult(
            var_value=val,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method="ewma",
            scaling_approximate=scaling_approximate,
            scaling_note=scaling_note,
        )

    def recommended_var(
        self,
        returns: NDArray[np.float64],
        confidence_level: float | None = None,
        time_horizon: int = 1,
        portfolio_value: float | None = None,
    ) -> "VaRResult":
        """
        Return the recommended VaR estimate for XAUUSD production risk limits.

        Routing logic:
          time_horizon == 1  → calculate_var_historical (direct percentile)
          time_horizon  > 1  → calculate_var_ewma (EWMA-weighted overlapping windows)

        This method always avoids sqrt(t) scaling and is safe to call regardless
        of the ENFORCE_MULTIDAY_VAR flag.

        Args:
            returns        : 1-day return series
            confidence_level: VaR confidence level (default from config)
            time_horizon   : Horizon in days
            portfolio_value: Optional portfolio value for dollar VaR

        Returns:
            VaRResult from the appropriate method
        """
        if time_horizon <= 1:
            # Call calculate_var_historical directly with time_horizon=1.
            # calculate_var_historical does not enforce the multiday flag for
            # 1-day horizons, so no global mutation is needed.
            result = self.calculate_var_historical(
                returns,
                confidence_level,
                1,
                portfolio_value,
            )
            return result
        return self.calculate_var_ewma(
            returns,
            confidence_level,
            time_horizon,
            portfolio_value,
        )

    def calculate_cvar(
        self,
        returns: NDArray[np.float64],
        confidence_level: float | None = None,
        portfolio_value: float | None = None,
        confidence: float | None = None,
    ) -> float:
        """
        Calculate Conditional VaR (Expected Shortfall).

        CVaR is the expected loss given that loss exceeds VaR.

        Args:
            returns: Array of historical returns
            confidence_level: Confidence level (also accepted as ``confidence``)
            portfolio_value: Optional portfolio value
            confidence: Alias for confidence_level

        Returns:
            CVaR value (always positive)
        """
        cl: float = confidence or confidence_level or self.var_confidence

        returns_arr = np.asarray(returns, dtype=float)
        var_threshold = np.percentile(returns_arr, (1 - cl) * 100)

        # Calculate expected shortfall (average of returns below VaR)
        tail_returns = returns_arr[returns_arr <= var_threshold]

        cvar = abs(float(var_threshold)) if len(tail_returns) == 0 else abs(float(np.mean(tail_returns)))

        if portfolio_value:
            cvar = cvar * portfolio_value

        return cvar

    # ============================================================
    # MONTE CARLO SIMULATION
    # ============================================================

    def run_monte_carlo_simulation(
        self,
        initial_value: float,
        expected_return: float,
        volatility: float,
        time_horizon: int = 252,  # Trading days
        num_simulations: int | None = None,
        return_paths: bool = False,
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation for portfolio projection.

        Args:
            initial_value: Starting portfolio value
            expected_return: Annual expected return
            volatility: Annual volatility
            time_horizon: Simulation horizon in trading days
            num_simulations: Number of simulations
            return_paths: Whether to return all simulated paths

        Returns:
            MonteCarloResult object
        """
        num_simulations = num_simulations or self.mc_simulations

        # Daily parameters
        daily_return = float(np.nan_to_num(expected_return / 252, nan=0.0))
        daily_vol = float(np.nan_to_num(volatility / np.sqrt(252), nan=0.0))

        # Generate random walks — use local RNG to avoid mutating global state
        rng = np.random.default_rng(42)
        random_returns = rng.normal(
            daily_return,
            daily_vol,
            (num_simulations, time_horizon),
        )

        # Calculate cumulative returns (geometric)
        cumulative_returns = np.cumprod(1 + random_returns, axis=1)

        # Final portfolio values
        final_values = initial_value * cumulative_returns[:, -1]

        # Calculate statistics
        final_returns = (final_values - initial_value) / initial_value

        fr: NDArray[np.float64] = np.asarray(final_returns, dtype=np.float64)
        paths: NDArray[np.float64] | None = np.asarray(cumulative_returns, dtype=np.float64) if return_paths else None
        result = MonteCarloResult(
            expected_return=float(np.mean(fr)),
            expected_volatility=float(np.std(fr)),
            var_95=float(-np.percentile(fr, 5)),
            var_99=float(-np.percentile(fr, 1)),
            cvar_95=self.calculate_cvar(fr, confidence_level=0.95),
            max_gain=float(np.max(fr)),
            max_loss=float(np.min(fr)),
            simulated_paths=paths,
            num_simulations=num_simulations,
        )

        return result

    def simulate_portfolio_scenarios(
        self,
        positions: dict[str, dict[str, Any]],
        correlations: NDArray[np.float64] | None = None,
        time_horizon: int = 30,
        num_simulations: int | None = None,
    ) -> dict[str, Any]:
        """
        Simulate portfolio scenarios with correlated assets.

        Args:
            positions: Dict of positions with 'value', 'expected_return', 'volatility'
            correlations: Correlation matrix (optional)
            time_horizon: Days to simulate
            num_simulations: Number of simulations

        Returns:
            Simulation results
        """
        num_simulations = num_simulations or self.mc_simulations
        n_assets = len(positions)
        asset_names = list(positions.keys())

        # Extract parameters
        values = np.array([positions[a]["value"] for a in asset_names])
        returns = np.array(
            [positions[a].get("expected_return", 0.0) for a in asset_names],
        )
        vols = np.array([positions[a].get("volatility", 0.20) for a in asset_names])

        # Default to identity correlation if not provided
        if correlations is None:
            correlations = np.eye(n_assets)

        # Daily parameters
        daily_returns = np.nan_to_num(returns / 252, nan=0.0)
        daily_vols = np.nan_to_num(vols / np.sqrt(252), nan=0.0)

        # Cholesky decomposition for correlated random variables
        L = np.linalg.cholesky(correlations)

        # Generate correlated random returns — use local RNG to avoid mutating global state
        rng = np.random.default_rng(42)
        uncorrelated = rng.standard_normal((num_simulations, time_horizon, n_assets))
        correlated = np.einsum("ijk,lk->ijl", uncorrelated, L)

        # Apply mean and volatility
        simulated_returns = daily_returns + daily_vols * correlated

        # Calculate portfolio paths
        asset_paths = np.cumprod(1 + simulated_returns, axis=1)
        portfolio_paths = np.sum(values * asset_paths, axis=2)

        # Final values
        final_portfolio_values = portfolio_paths[:, -1]
        initial_portfolio_value = np.sum(values)

        # Calculate metrics
        portfolio_returns = (final_portfolio_values - initial_portfolio_value) / initial_portfolio_value

        return {
            "initial_value": initial_portfolio_value,
            "expected_final_value": np.mean(final_portfolio_values),
            "expected_return": np.mean(portfolio_returns),
            "volatility": np.std(portfolio_returns),
            "var_95": -np.percentile(portfolio_returns, 5) * initial_portfolio_value,
            "var_99": -np.percentile(portfolio_returns, 1) * initial_portfolio_value,
            "best_case": np.percentile(final_portfolio_values, 95),
            "worst_case": np.percentile(final_portfolio_values, 5),
            "probability_loss": np.mean(portfolio_returns < 0),
            "probability_gain_10pct": np.mean(portfolio_returns > 0.10),
        }

    # ============================================================
    # STRESS TESTING
    # ============================================================

    def run_stress_test(
        self,
        portfolio: dict[str, dict[str, Any]],
        scenario_name: str,
    ) -> StressTestResult:
        """
        Run a stress test scenario on portfolio.

        Args:
            portfolio: Portfolio positions with 'value' and 'asset_class'
            scenario_name: Name of stress scenario

        Returns:
            StressTestResult object
        """
        if scenario_name not in self.stress_scenarios:
            raise ValueError(f"Unknown scenario: {scenario_name}")

        scenario = self.stress_scenarios[scenario_name]
        total_value = sum(p["value"] for p in portfolio.values())

        # Calculate impact on each position
        total_impact = 0.0
        affected = []

        for position_name, position in portfolio.items():
            asset_class = position.get("asset_class", "equities")
            value = position["value"]

            # Get shock for asset class
            shock = scenario.get(asset_class, 0.0)
            position_impact = value * shock
            total_impact += position_impact

            if shock != 0:
                affected.append(position_name)

        # Calculate percentage impact
        pct_impact = total_impact / total_value if total_value > 0 else 0

        # Determine risk level
        if abs(pct_impact) < 0.05:
            risk_level = "low"
            recommendation = "Portfolio is resilient to this scenario"
        elif abs(pct_impact) < 0.15:
            risk_level = "medium"
            recommendation = "Consider hedging or reducing exposure"
        elif abs(pct_impact) < 0.30:
            risk_level = "high"
            recommendation = "Significant risk - implement protective measures"
        else:
            risk_level = "severe"
            recommendation = "Critical exposure - immediate risk reduction required"

        return StressTestResult(
            scenario_name=scenario["name"],
            portfolio_impact=pct_impact,
            dollar_impact=total_impact,
            affected_positions=affected,
            risk_level=risk_level,
            recommendation=recommendation,
        )

    def run_all_stress_tests(
        self,
        portfolio: dict[str, dict[str, Any]],
    ) -> list[StressTestResult]:
        """Run all stress test scenarios."""
        results = []
        for scenario_name in self.stress_scenarios:
            result = self.run_stress_test(portfolio, scenario_name)
            results.append(result)
        return results

    # ============================================================
    # DRAWDOWN ANALYSIS
    # ============================================================

    def analyze_drawdowns(self, equity_curve: NDArray[np.float64]) -> DrawdownAnalysis:
        """
        Comprehensive drawdown analysis.

        Args:
            equity_curve: Array of portfolio values over time

        Returns:
            DrawdownAnalysis object
        """
        # Calculate running maximum
        running_max = np.maximum.accumulate(equity_curve)

        # Calculate drawdown series
        drawdown = (equity_curve - running_max) / running_max

        # Current drawdown
        current_drawdown = drawdown[-1]

        # Maximum drawdown
        max_drawdown = np.min(drawdown)
        max_drawdown_idx = np.argmin(drawdown)

        # Find drawdown start (last peak before max drawdown)
        max_drawdown_start = np.argmax(
            equity_curve[: max_drawdown_idx + 1] == running_max[max_drawdown_idx],
        )
        max_drawdown_duration = max_drawdown_idx - max_drawdown_start

        # Current drawdown duration
        current_peak_idx = np.argmax(equity_curve == running_max[-1])
        current_drawdown_duration = len(equity_curve) - 1 - current_peak_idx

        # Identify all drawdown events
        drawdown_events = self._identify_drawdown_events(drawdown, threshold=-0.05)

        # Calculate recovery rate
        recovery_rate = self._calculate_recovery_rate(drawdown_events)

        # Underwater periods
        underwater_periods = self._calculate_underwater_periods(drawdown)

        return DrawdownAnalysis(
            current_drawdown=float(current_drawdown),
            max_drawdown=float(max_drawdown),
            max_drawdown_duration=int(max_drawdown_duration),
            current_drawdown_duration=int(current_drawdown_duration),
            recovery_rate=recovery_rate,
            drawdown_events=drawdown_events,
            underwater_periods=underwater_periods,
        )

    def _identify_drawdown_events(
        self,
        drawdown: NDArray[np.float64],
        threshold: float = -0.05,
    ) -> list[dict[str, Any]]:
        """Identify significant drawdown events."""
        events = []
        in_drawdown = False
        start_idx = 0

        for i, dd in enumerate(drawdown):
            if dd < threshold and not in_drawdown:
                in_drawdown = True
                start_idx = i
            elif dd >= 0 and in_drawdown:
                in_drawdown = False
                events.append(
                    {
                        "start_idx": start_idx,
                        "end_idx": i,
                        "duration": i - start_idx,
                        "max_drawdown": float(np.min(drawdown[start_idx : i + 1])),
                        "recovered": True,
                    },
                )

        # Handle ongoing drawdown
        if in_drawdown:
            events.append(
                {
                    "start_idx": start_idx,
                    "end_idx": len(drawdown) - 1,
                    "duration": len(drawdown) - start_idx,
                    "max_drawdown": float(np.min(drawdown[start_idx:])),
                    "recovered": False,
                },
            )

        return events

    def _calculate_recovery_rate(self, drawdown_events: list[dict[str, Any]]) -> float:
        """Calculate historical recovery rate."""
        if not drawdown_events:
            return 1.0

        recovered = sum(1 for e in drawdown_events if e["recovered"])
        return recovered / len(drawdown_events)

    def _calculate_underwater_periods(self, drawdown: NDArray[np.float64]) -> list[dict[str, Any]]:
        """Calculate time spent underwater."""
        underwater = drawdown < 0
        periods = []

        in_period = False
        start_idx = 0

        for i, uw in enumerate(underwater):
            if uw and not in_period:
                in_period = True
                start_idx = i
            elif not uw and in_period:
                in_period = False
                periods.append(
                    {"start_idx": start_idx, "end_idx": i, "duration": i - start_idx},
                )

        if in_period:
            periods.append(
                {
                    "start_idx": start_idx,
                    "end_idx": len(drawdown) - 1,
                    "duration": len(drawdown) - start_idx,
                },
            )

        return periods

    # ============================================================
    # RISK-ADJUSTED METRICS
    # ============================================================

    def calculate_sharpe_ratio(self, returns: NDArray[np.float64], periods_per_year: int = 252) -> float:
        """Calculate annualized Sharpe ratio."""
        arr = np.asarray(returns, dtype=float)
        excess_returns = arr - self.risk_free_rate / periods_per_year
        if np.std(arr) == 0:
            return 0.0
        std_arr = float(np.std(arr))
        if std_arr == 0:
            return 0.0
        return float(np.sqrt(periods_per_year) * np.nan_to_num(np.mean(excess_returns), nan=0.0) / std_arr)

    def calculate_sortino_ratio(
        self,
        returns: NDArray[np.float64],
        periods_per_year: int = 252,
    ) -> float:
        """Calculate annualized Sortino ratio (using downside deviation)."""
        returns = np.nan_to_num(returns, nan=0.0)
        excess_returns = returns - self.risk_free_rate / periods_per_year
        downside_returns = returns[returns < 0]

        if len(downside_returns) == 0 or np.std(downside_returns) == 0:
            return float("inf") if float(np.mean(excess_returns)) > 0 else 0.0

        downside_std = float(np.nan_to_num(np.std(downside_returns), nan=1e-9))
        return float(np.nan_to_num(np.sqrt(periods_per_year) * np.mean(excess_returns) / max(downside_std, 1e-9), nan=0.0))

    def calculate_calmar_ratio(
        self,
        returns: NDArray[np.float64],
        equity_curve: NDArray[np.float64] | None = None,
    ) -> float:
        """Calculate Calmar ratio (annual return / max drawdown)."""
        annual_return = float(np.mean(returns) * 252)

        ec: NDArray[np.float64] = (
            equity_curve if equity_curve is not None else np.asarray(np.cumprod(1 + returns), dtype=np.float64)
        )

        analysis = self.analyze_drawdowns(ec)
        max_dd = abs(analysis.max_drawdown)

        if max_dd == 0:
            return float("inf") if annual_return > 0 else 0.0

        return annual_return / max_dd

    @staticmethod
    def _garch_current_variance(
        arr: NDArray[np.float64],
        omega: float,
        alpha: float,
        beta: float,
    ) -> float:
        """Iterate GARCH(1,1) recursion to obtain the current conditional variance."""
        sigma2 = omega / max(1 - alpha - beta, 1e-10)
        for t in range(1, len(arr)):
            sigma2 = omega + alpha * arr[t - 1] ** 2 + beta * sigma2
            sigma2 = max(sigma2, 1e-10)
        return sigma2

    @staticmethod
    def _garch_hstep_variance(
        sigma2_t: float,
        omega: float,
        alpha: float,
        beta: float,
        time_horizon: int,
    ) -> float:
        """Return the sum of h-step-ahead GARCH(1,1) conditional variance forecasts."""
        if time_horizon == 1:
            return sigma2_t
        persistence = alpha + beta
        long_run_var = omega / max(1 - persistence, 1e-10)
        total = 0.0
        sigma2_i = sigma2_t
        for _ in range(time_horizon):
            total += sigma2_i
            sigma2_i = long_run_var + persistence * (sigma2_i - long_run_var)
            sigma2_i = max(sigma2_i, 1e-10)
        return total

    def calculate_var_garch(
        self,
        returns: NDArray[np.float64],
        confidence_level: float | None = None,
        time_horizon: int = 10,
        portfolio_value: float | None = None,
    ) -> "VaRResult":
        """
        Compute multi-day VaR using GARCH(1,1) conditional volatility forecast.

        Fits GARCH(1,1) via MLE on the return series, then iterates the variance
        recursion h steps ahead to obtain the conditional variance forecast.
        This is the industry standard for multi-day VaR on assets with volatility
        clustering (XAUUSD, equities, crypto).

        The h-step forecast uses:
            sigma2_{t+h} = omega/(1-alpha-beta)
                         + (alpha+beta)^h * (sigma2_t - omega/(1-alpha-beta))

        Args:
            returns: Daily return series (minimum 100 observations required,
                     252+ recommended for stable MLE estimates).
            confidence_level: VaR confidence level (default from config).
            time_horizon: Forecast horizon in days.
            portfolio_value: Optional portfolio value for dollar VaR.

        Returns:
            VaRResult with method='garch11' and scaling_approximate=False.
        """
        from scipy import stats as _stats
        from scipy.optimize import minimize as _minimize

        confidence_level = confidence_level or self.var_confidence
        arr = np.asarray(returns, dtype=float)

        if len(arr) < 100:
            raise ValueError(
                f"calculate_var_garch requires >= 100 observations, got {len(arr)}. "
                "Use calculate_var_ewma or calculate_var_multiday for shorter series."
            )

        # ── GARCH(1,1) negative log-likelihood ──────────────────────────────
        def _neg_loglik(params: NDArray[np.float64]) -> float:
            omega, alpha, beta = params
            if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1.0:
                return 1e10
            n = len(arr)
            sigma2 = np.empty(n)
            sigma2[0] = omega / max(1 - alpha - beta, 1e-10)
            for t in range(1, n):
                sigma2[t] = omega + alpha * arr[t - 1] ** 2 + beta * sigma2[t - 1]
                if sigma2[t] <= 0:
                    return 1e10
            sigma2_safe = np.maximum(np.nan_to_num(sigma2, nan=1e-12), 1e-12)
            ll = -0.5 * np.sum(np.log(sigma2_safe) + arr**2 / sigma2_safe)
            return -ll

        # Initial guess: small omega, typical alpha/beta for FX/gold
        sample_var = float(np.var(arr, ddof=1))
        x0 = np.array([sample_var * 0.05, 0.08, 0.88])
        bounds = [(1e-8, None), (1e-6, 0.5), (1e-6, 0.9999)]

        result = _minimize(
            _neg_loglik,
            x0,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500, "ftol": 1e-9},
        )

        converged = result.success
        omega, alpha, beta = result.x if converged else x0

        # ── Compute current conditional variance ─────────────────────────────
        sigma2_t = self._garch_current_variance(arr, omega, alpha, beta)

        # ── h-step ahead variance forecast (sum of conditional variances) ────
        sigma2_forecast = self._garch_hstep_variance(sigma2_t, omega, alpha, beta, time_horizon)

        sigma_forecast = float(np.sqrt(max(float(np.nan_to_num(sigma2_forecast, nan=0.0)), 0.0)))
        alpha_level = 1.0 - confidence_level
        z = float(_stats.norm.ppf(alpha_level))
        mu_h = float(np.mean(arr)) * time_horizon
        var_garch = float(-(mu_h + z * sigma_forecast))
        var_garch = max(var_garch, 0.0)

        val = abs(var_garch * portfolio_value) if portfolio_value else var_garch

        if not converged:
            import warnings as _w

            _w.warn(
                "calculate_var_garch: MLE did not converge — using initial parameter "
                "guess. Result may be inaccurate. Increase series length or check for "
                "outliers.",
                RuntimeWarning,
                stacklevel=2,
            )

        return VaRResult(
            var_value=val,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method="garch11",
            scaling_approximate=not converged,
            scaling_note=(
                ""
                if converged
                else f"GARCH(1,1) MLE did not converge (omega={omega:.2e}, "
                f"alpha={alpha:.4f}, beta={beta:.4f}). Result is approximate."
            ),
        )

    def calculate_all_metrics(
        self,
        returns: NDArray[np.float64],
        equity_curve: NDArray[np.float64] | None = None,
        portfolio_value: float | None = None,
    ) -> dict[str, Any]:
        """Calculate comprehensive risk metrics."""

        ec: NDArray[np.float64] = (
            equity_curve
            if equity_curve is not None
            else np.asarray(
                np.cumprod(1 + returns) * (portfolio_value or 10000),
                dtype=np.float64,
            )
        )

        # VaR calculations
        var_hist = self.calculate_var_historical(
            returns,
            portfolio_value=portfolio_value,
        )
        var_param = self.calculate_var_parametric(
            returns,
            portfolio_value=portfolio_value,
        )
        var_mc = self.calculate_var_monte_carlo(
            returns,
            portfolio_value=portfolio_value,
        )
        cvar = self.calculate_cvar(returns, portfolio_value=portfolio_value)

        # Multi-day VaR (10-day) — correct methods, no sqrt(t)
        var_multiday_10 = None
        var_garch_10 = None
        if len(returns) >= 30:
            var_multiday_10 = self.calculate_var_multiday(returns, time_horizon=10, portfolio_value=portfolio_value)
        if len(returns) >= 100:
            var_garch_10 = self.calculate_var_garch(returns, time_horizon=10, portfolio_value=portfolio_value)

        # Drawdown analysis
        drawdown = self.analyze_drawdowns(ec)

        # Risk-adjusted metrics
        sharpe = self.calculate_sharpe_ratio(returns)
        sortino = self.calculate_sortino_ratio(returns)
        calmar = self.calculate_calmar_ratio(returns, ec)

        return {
            "var_historical_95": var_hist.var_value,
            "var_parametric_95": var_param.var_value,
            "var_monte_carlo_95": var_mc.var_value,
            "var_multiday_10d": var_multiday_10.var_value if var_multiday_10 else None,
            "var_garch_10d": var_garch_10.var_value if var_garch_10 else None,
            "cvar_95": cvar,
            "max_drawdown": drawdown.max_drawdown,
            "max_drawdown_duration": drawdown.max_drawdown_duration,
            "current_drawdown": drawdown.current_drawdown,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "calmar_ratio": calmar,
            "total_return": float(ec[-1] / ec[0]) - 1.0,
            "annual_return": float(np.mean(returns) * 252),
            "annual_volatility": float(np.nan_to_num(np.std(returns), nan=0.0) * np.sqrt(252)),
            "positive_days": float(np.mean(returns > 0)),
            "recovery_rate": drawdown.recovery_rate,
        }

    # ------------------------------------------------------------------
    # Portfolio-level VaR (multi-asset, correlated)
    # ------------------------------------------------------------------

    def calculate_portfolio_var(
        self,
        positions: dict[str, dict[str, Any]],
        confidence_level: float | None = None,
        time_horizon: int = 1,
        method: str = "historical",
    ) -> VaRResult:
        """
        Calculate portfolio-level VaR across multiple correlated positions.

        Each position entry must contain:
            - ``returns``: NDArray of historical daily returns
            - ``value``:   Current market value (dollar)

        The portfolio return series is constructed as a value-weighted
        combination of individual position returns, then VaR is computed
        on the aggregate series using the requested method.

        Args:
            positions: Dict keyed by asset name.
            confidence_level: VaR confidence (default from config).
            time_horizon: Horizon in days (use calculate_var_multiday for >1).
            method: "historical" | "parametric" | "monte_carlo"

        Returns:
            VaRResult for the combined portfolio.
        """
        confidence_level = confidence_level or self.var_confidence

        if not positions:
            raise ValueError("positions dict must not be empty")

        names = list(positions.keys())
        total_value = sum(positions[n].get("value", 0.0) for n in names)
        if total_value <= 0:
            raise ValueError("Total portfolio value must be positive")

        # Build value-weighted portfolio return series
        min_len = min(len(np.asarray(positions[n]["returns"])) for n in names)
        if min_len < 2:
            raise ValueError("Each position must have at least 2 return observations")

        portfolio_returns = np.zeros(min_len, dtype=np.float64)
        for name in names:
            weight = positions[name].get("value", 0.0) / total_value
            ret = np.asarray(positions[name]["returns"], dtype=np.float64)[-min_len:]
            portfolio_returns += weight * ret

        if method == "parametric":
            return self.calculate_var_parametric(
                portfolio_returns,
                confidence_level=confidence_level,
                time_horizon=time_horizon,
                portfolio_value=total_value,
            )
        if method == "monte_carlo":
            return self.calculate_var_monte_carlo(
                portfolio_returns,
                confidence_level=confidence_level,
                time_horizon=time_horizon,
                portfolio_value=total_value,
                use_historical_bootstrap=True,
            )
        # Default: historical
        if time_horizon > 1:
            return self.calculate_var_multiday(
                portfolio_returns,
                confidence_level=confidence_level,
                time_horizon=time_horizon,
                portfolio_value=total_value,
            )
        return self.calculate_var_historical(
            portfolio_returns,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            portfolio_value=total_value,
        )

    # ------------------------------------------------------------------
    # Risk report
    # ------------------------------------------------------------------

    def get_risk_report(
        self,
        returns: NDArray[np.float64],
        equity_curve: NDArray[np.float64] | None = None,
        portfolio_value: float | None = None,
        symbol: str = "PORTFOLIO",
    ) -> dict[str, Any]:
        """
        Generate a full production risk report.

        Combines all metrics into a single dict suitable for API responses,
        dashboards, and compliance logging.

        Args:
            returns: Daily return series.
            equity_curve: Optional equity curve (computed from returns if absent).
            portfolio_value: Optional current portfolio value for dollar VaR.
            symbol: Label for the report.

        Returns:
            Dict with all risk metrics, VaR results, drawdown analysis,
            stress test summary, and metadata.
        """
        returns = np.asarray(returns, dtype=np.float64)
        ec: NDArray[np.float64] = (
            equity_curve
            if equity_curve is not None
            else np.asarray(
                np.cumprod(1 + returns) * (portfolio_value or 10_000.0),
                dtype=np.float64,
            )
        )

        metrics = self.calculate_all_metrics(returns, ec, portfolio_value)

        # Stress test summary — built from the real symbol and portfolio value
        # passed into this method, not synthetic data.
        portfolio_snapshot = {
            symbol: {
                "value": portfolio_value or float(ec[-1]),
                "asset_class": "gold" if "XAU" in symbol.upper() else "equities",
            }
        }
        stress_results: list[StressTestResult] = self.run_all_stress_tests(portfolio_snapshot)
        stress_summary = {
            r.scenario_name: {
                "portfolio_impact_pct": r.portfolio_impact,
                "dollar_impact": r.dollar_impact,
                "risk_level": r.risk_level,
            }
            for r in stress_results
        }

        return {
            "symbol": symbol,
            "generated_at": datetime.now(UTC).isoformat(),
            "portfolio_value": portfolio_value or float(ec[-1]),
            "metrics": metrics,
            "stress_scenarios": stress_summary,
            "data_points": len(returns),
            "var_enforcement": {
                "multiday_enforced": ENFORCE_MULTIDAY_VAR,
                "env_var": "HOPEFX_VAR_ENFORCE_MULTIDAY",
            },
        }

    # ------------------------------------------------------------------
    # Drawdown alias (analyze_drawdown → analyze_drawdowns)
    # ------------------------------------------------------------------

    def analyze_drawdown(
        self,
        equity_curve: NDArray[np.float64],
    ) -> "DrawdownAnalysis":
        """Alias for analyze_drawdowns (singular form used by some callers)."""
        return self.analyze_drawdowns(equity_curve)

    # ------------------------------------------------------------------
    # Convenience aliases expected by tests
    # ------------------------------------------------------------------

    def calculate_var(
        self,
        returns: Any,
        confidence: float | None = None,
        confidence_level: float | None = None,
    ) -> float:
        """Return VaR as a negative number (loss). Uses historical simulation."""
        cl: float = confidence or confidence_level or self.var_confidence
        arr: NDArray[np.float64] = np.asarray(returns, dtype=float)
        return float(np.percentile(arr, (1 - cl) * 100))

    def calculate_sharpe(
        self,
        returns: Any,
        risk_free_rate: float | None = None,
    ) -> float:
        """Alias for calculate_sharpe_ratio with optional risk_free_rate override."""
        old_rfr = self.risk_free_rate
        if risk_free_rate is not None:
            self.risk_free_rate = risk_free_rate
        result = self.calculate_sharpe_ratio(np.asarray(returns, dtype=float))
        self.risk_free_rate = old_rfr
        return float(result)


# Alias expected by tests
RiskAnalytics = AdvancedRiskAnalytics
