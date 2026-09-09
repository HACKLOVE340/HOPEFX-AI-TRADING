# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# backtesting/enhanced_engine.py  (moved from root enhanced_backtest_engine.py)
"""
=============================================================================
HOPEFX INSTITUTIONAL BACKTEST ENGINE v4.0
=============================================================================
Production-Grade Algorithmic Trading Simulation with Nanosecond Precision

Features:
- Tick-level execution simulation with realistic market microstructure
- Almgren-Chriss market impact model with temporary/permanent separation
- Multi-asset, multi-strategy portfolio backtesting
- GPU-accelerated analytics via CuPy/Numba
- FIA 2024 compliant risk controls with automatic kill switches
- Adaptive slippage based on order flow toxicity
- Regime detection with dynamic strategy allocation

Author: HOPEFX Development Team
License: Proprietary - Institutional Use Only
=============================================================================
"""

import numpy as np

_ENGINE_RNG = np.random.default_rng()

# ── Execution simulation constants ────────────────────────────────────────────
_SLIPPAGE_NOISE_FRAC = 0.20  # std-dev of slippage noise as fraction of impact
_MIN_VOLUME_FLOOR = 1_000  # minimum volume denominator for participation rate
_LIMIT_FILL_LATENCY_SEC = 0.001  # simulated latency for limit-order fills (1 ms)
_ORDER_ID_TIME_SCALE = 1e6  # nanosecond timestamp scale for order ID suffix
_FILL_TOLERANCE = 0.0001  # size tolerance for considering an order fully filled
_ATR_FALLBACK_VOL = 0.001  # fallback volatility when realized variance is zero

# ── Risk check severity constants ─────────────────────────────────────────────
_CIRCUIT_BREAKER_HALT_LEVEL = 2  # circuit_breaker_level at which trading halts

import contextlib
import gzip
import json
import logging
import warnings
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from enum import Enum, IntEnum, auto
from pathlib import Path
from typing import Any

# Performance libraries — imported for availability checks; used conditionally
try:
    import numba  # pylint: disable=unused-import  # noqa: F401
    from numba import cuda, jit, njit, prange  # pylint: disable=unused-import  # noqa: F401

    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    warnings.warn("Numba unavailable - performance degraded", stacklevel=2)

try:
    import cupy as cp  # pylint: disable=unused-import  # noqa: F401
    from cupy.cuda import Device  # pylint: disable=unused-import  # noqa: F401

    CUDA_AVAILABLE = True
except ImportError:
    CUDA_AVAILABLE = False

try:
    from scipy import interpolate, optimize, stats  # pylint: disable=unused-import  # noqa: F401
    from scipy.optimize import differential_evolution, minimize  # pylint: disable=unused-import  # noqa: F401

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("HOPEFX.Backtest")


# =============================================================================
# ENUMERATIONS AND CONSTANTS
# =============================================================================


class ExecutionQuality(IntEnum):
    """Execution venue quality tiers"""

    HFT_COLOCATED = 0  # < 100 microseconds
    HFT_PROXIMITY = 1  # < 1 millisecond
    ULTRA_LOW_LATENCY = 2  # 1-10 milliseconds
    LOW_LATENCY = 3  # 10-50 milliseconds
    STANDARD = 4  # 50-200 milliseconds
    RETAIL = 5  # > 200 milliseconds


class MarketRegime(Enum):
    """Market microstructure regimes"""

    TRENDING_STRONG_BULL = auto()
    TRENDING_WEAK_BULL = auto()
    TRENDING_STRONG_BEAR = auto()
    TRENDING_WEAK_BEAR = auto()
    RANGING_NARROW = auto()
    RANGING_WIDE = auto()
    HIGH_VOLATILITY_BREAKOUT = auto()
    HIGH_VOLATILITY_MEAN_REVERSION = auto()
    LOW_LIQUIDITY = auto()
    NEWS_EVENT = auto()
    MARKET_OPEN = auto()
    MARKET_CLOSE = auto()
    UNKNOWN = auto()


class OrderSide(Enum):
    BUY = 1
    SELL = -1


class OrderStatus(Enum):
    PENDING = auto()
    SUBMITTED = auto()
    PARTIAL_FILL = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
    EXPIRED = auto()


class SlippageModel(Enum):
    """Market impact modeling approaches"""

    NONE = "none"
    FIXED = "fixed"
    LINEAR = "linear"
    SQUARE_ROOT = "square_root"  # Almgren-Chriss
    EXPONENTIAL = "exponential"
    POWER_LAW = "power_law"
    PROPRIETARY_ML = "proprietary_ml"


class RiskEventSeverity(IntEnum):
    INFO = 0
    WARNING = 1
    CRITICAL = 2
    KILL_SWITCH = 3


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass(frozen=True, slots=True)
class NanosecondTimestamp:
    """
    High-precision timestamp with true nanosecond resolution.

    ``seconds``     — Unix epoch seconds (int)
    ``nanoseconds`` — sub-second nanoseconds, 0–999_999_999 (int)

    ``now()`` uses ``time.time_ns()`` which returns the wall-clock time in
    nanoseconds as a single integer, giving genuine nanosecond granularity on
    platforms that support it (Linux CLOCK_REALTIME, macOS mach_absolute_time).
    The previous implementation used ``datetime.microsecond * 1000``, which
    produced values that were always a multiple of 1 000 — microsecond
    precision at best.

    ``from_datetime()`` is limited to microsecond precision because Python's
    ``datetime`` type does not carry sub-microsecond information.  Use
    ``now()`` when real nanosecond resolution is required.
    """

    seconds: int  # Unix epoch seconds
    nanoseconds: int  # 0-999,999,999

    @classmethod
    def now(cls) -> "NanosecondTimestamp":
        """Create from current system time using time.time_ns() for nanosecond resolution."""
        import time as _time

        ns_total = _time.time_ns()
        seconds = ns_total // 1_000_000_000
        nanoseconds = ns_total % 1_000_000_000
        return cls(seconds, nanoseconds)

    @classmethod
    def from_datetime(cls, dt: datetime) -> "NanosecondTimestamp":
        """
        Create from a datetime object.

        Resolution is limited to microseconds because datetime does not carry
        sub-microsecond information.  The sub-microsecond nanosecond digits
        will always be zero.
        """
        seconds = int(dt.timestamp())
        # dt.microsecond gives 0-999999; convert to nanoseconds within the second
        nanoseconds = dt.microsecond * 1_000
        return cls(seconds, nanoseconds)

    def to_datetime(self) -> datetime:
        """Convert to UTC datetime (microsecond precision)."""
        return datetime.fromtimestamp(self.seconds + self.nanoseconds / 1e9, tz=UTC)

    def __float__(self) -> float:
        return self.seconds + self.nanoseconds / 1e9

    def __lt__(self, other: "NanosecondTimestamp") -> bool:
        if self.seconds != other.seconds:
            return self.seconds < other.seconds
        return self.nanoseconds < other.nanoseconds


@dataclass(frozen=True, slots=True)
class TickData:
    """
    Immutable tick data with full market microstructure.
    Supports both L1 and L3 data depending on source.
    """

    timestamp: NanosecondTimestamp
    symbol: str
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    last_price: float | None = None
    last_size: float | None = None
    volume: float = 0.0
    trade_count: int = 0
    vwap: float | None = None
    open_interest: float | None = None

    # Market microstructure
    bid_depth: list[tuple[float, float]] = field(default_factory=list)  # (price, size)
    ask_depth: list[tuple[float, float]] = field(default_factory=list)

    # Derived quality metrics
    source: str = "unknown"
    receive_latency_ns: int = 0

    def __post_init__(self):
        # Validate price integrity
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError(f"Invalid prices: bid={self.bid}, ask={self.ask}")
        if self.bid >= self.ask:
            raise ValueError(f"Negative spread: bid={self.bid} >= ask={self.ask}")
        if self.ask - self.bid > self.mid * 0.1:  # >10% spread
            warnings.warn(f"Extreme spread detected: {(self.ask - self.bid) / self.mid:.2%}", stacklevel=2)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        return (self.spread / self.mid) * 10000

    @property
    def imbalance(self) -> float:
        """Order flow imbalance (-1 to 1)"""
        total = self.bid_size + self.ask_size
        if total == 0:
            return 0.0
        return (self.bid_size - self.ask_size) / total

    def get_price_for_side(self, side: OrderSide, use_aggressive: bool = True) -> float:
        """Get execution price for order side"""
        if side == OrderSide.BUY:
            return self.ask if use_aggressive else self.mid
        return self.bid if use_aggressive else self.mid

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": float(self.timestamp),
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "spread_bps": self.spread_bps,
            "imbalance": self.imbalance,
            "source": self.source,
        }


@dataclass
class TransactionCostModel:
    """
    Institutional transaction cost model with full market impact separation.
    Implements Almgren-Chriss with proprietary extensions.
    """

    # Fixed costs (explicit)
    commission_per_lot: float = 7.0  # USD per standard lot
    commission_per_million: float = 25.0  # USD per million notional
    clearing_fee_bps: float = 0.1
    exchange_fee_bps: float = 0.2
    sec_fee_bps: float = 0.00227  # US equities only

    # Variable costs (implicit)
    spread_markup_bps: float = 0.8
    slippage_model: SlippageModel = SlippageModel.SQUARE_ROOT

    # ── Almgren-Chriss market impact parameters ───────────────────────────────
    # Calibrated to XAUUSD (spot gold) using published empirical estimates.
    #
    # Sources and calibration basis:
    #   Almgren & Chriss (2001) "Optimal execution of portfolio transactions"
    #   Kissell & Glantz (2003) "Optimal Trading Strategies" — commodity calibration
    #   Frazzini, Israel & Moskowitz (2018) "Trading Costs" — cross-asset impact
    #   WFE/LBMA Gold Market Structure Report (2019) — XAUUSD liquidity profile
    #
    # XAUUSD market characteristics vs equities:
    #   - Average daily volume: ~$130B (OTC spot + futures), far deeper than most equities
    #   - Bid-ask spread: 2–5 bps (tight), vs 5–20 bps for mid-cap equities
    #   - Temporary impact decays faster (minutes vs hours) due to high liquidity
    #   - Permanent impact is lower (gold is a macro asset, not information-driven)
    #
    # Parameter derivation:
    #   η (temporary_impact_coefficient):
    #     Almgren (2001) equity baseline: η ≈ 0.142
    #     XAUUSD adjustment: divide by ~3 for deeper liquidity and tighter spreads
    #     → η_xauusd ≈ 0.050
    #
    #   γ (permanent_impact_coefficient):
    #     Almgren (2001) equity baseline: γ ≈ 0.314
    #     XAUUSD: permanent impact is minimal for macro assets (Frazzini et al. 2018
    #     find commodity permanent impact ~40% of equity permanent impact)
    #     → γ_xauusd ≈ 0.100
    #
    #   β (decay_exponent):
    #     Square-root law (β=0.5) is well-established for liquid markets.
    #     XAUUSD empirical fit from LBMA data: β ≈ 0.55 (slightly super-linear
    #     at high participation rates due to OTC fragmentation).
    #     → β_xauusd ≈ 0.55
    #
    # These are best-available public estimates. For production use, calibrate
    # against your own execution data using calibrate_from_executions().
    temporary_impact_coefficient: float = 0.050  # η — XAUUSD calibrated (was 0.142 equity default)
    permanent_impact_coefficient: float = 0.100  # γ — XAUUSD calibrated (was 0.314 equity default)
    decay_exponent: float = 0.55  # β — XAUUSD calibrated (was 0.6 equity default)

    # Advanced features
    use_volatility_adjustment: bool = True
    use_order_flow_toxicity: bool = True
    use_adaptive_spread: bool = True

    # ── Overnight financing (swap) ────────────────────────────────────────────
    # Charged every bar on open positions.  The engine calls OvernightSwapModel
    # directly (USD per lot per night) rather than using these annual-rate fields
    # when use_swap_model=True (the default).
    #
    # Correct XAUUSD rates (industry-standard, April 2026):
    #   Long  (buy gold): −$4.10/night per 100oz lot = −0.749% p.a. on notional
    #   Short (sell gold): +$0.60/night per 100oz lot = +0.110% p.a. on notional
    #
    # The old 0.40% p.a. long rate undercharged by ~47%.
    # These annual-rate fields are kept for backward compatibility and are used
    # only when use_swap_model=False.
    overnight_rate_annual: float = 0.00749  # −0.749% p.a. — XAUUSD long (corrected)
    overnight_rate_long_annual: float = 0.00749  # −0.749% p.a. — long carry cost
    overnight_rate_short_annual: float = -0.00110  # +0.110% p.a. — short (receive)
    # use_swap_model: when True (default), OvernightSwapModel is used for all
    # overnight financing calculations (USD/lot/night with Wednesday triple-swap).
    # Set False only to reproduce legacy results for comparison.
    use_swap_model: bool = True

    def calculate_market_impact(
        self,
        order_size: float,
        participation_rate: float,
        daily_volatility: float,
        order_flow_toxicity: float = 0.0,
    ) -> dict[str, float]:
        """
        Calculate temporary and permanent market impact.

        Temporary impact decays after execution.
        Permanent impact persists and affects future prices.
        """
        if participation_rate <= 0 or participation_rate > 1:
            raise ValueError(f"Invalid participation rate: {participation_rate}")

        # Base Almgren-Chriss model
        temp_impact = self.temporary_impact_coefficient * daily_volatility * (participation_rate**self.decay_exponent)

        perm_impact = self.permanent_impact_coefficient * daily_volatility * participation_rate

        # Adjust for order flow toxicity (VPIN-like)
        if self.use_order_flow_toxicity and order_flow_toxicity > 0.5:
            # Toxic flow = higher impact
            toxicity_multiplier = 1 + (order_flow_toxicity - 0.5) * 2
            temp_impact *= toxicity_multiplier

        return {
            "temporary_bps": temp_impact * 10000,
            "permanent_bps": perm_impact * 10000,
            "total_bps": (temp_impact + perm_impact) * 10000,
            "temporary_decay_time": self._estimate_decay_time(participation_rate),
            "is_toxic": order_flow_toxicity > 0.7,
        }

    def _estimate_decay_time(self, participation_rate: float) -> timedelta:
        """Estimate how long temporary impact persists.

        XAUUSD temporary impact decays faster than equities due to higher
        liquidity and continuous OTC market making.  Empirical estimate:
        ~5–15 minutes for typical participation rates (vs 30–60 min for equities).
        """
        # XAUUSD: faster decay — cap at 15 minutes for typical participation
        minutes = 15 * participation_rate
        return timedelta(minutes=max(2, minutes))

    @classmethod
    def calibrate_xauusd(cls) -> "TransactionCostModel":
        """
        Return a TransactionCostModel pre-calibrated for XAUUSD spot gold.

        Parameters are derived from published empirical literature on gold
        market microstructure (see class docstring for full citation list).
        Use calibrate_from_executions() to refine with your own fill data.
        """
        model = cls()
        # Almgren-Chriss — XAUUSD calibrated
        model.temporary_impact_coefficient = 0.050
        model.permanent_impact_coefficient = 0.100
        model.decay_exponent = 0.55
        # Spread: XAUUSD OTC spot is typically 2–5 bps; use 3 bps as default
        model.spread_markup_bps = 0.3
        # Overnight: corrected XAUUSD rates (−$4.10/night per 100oz lot long)
        # = −0.749% p.a. on notional.  OvernightSwapModel is used directly
        # when use_swap_model=True (the default); these fields are fallback only.
        model.overnight_rate_annual = 0.00749
        model.overnight_rate_long_annual = 0.00749
        model.overnight_rate_short_annual = -0.00110
        model.use_swap_model = True
        return model

    def calibrate_from_executions(
        self,
        executions: list,
        min_samples: int = 50,
    ) -> dict:
        """
        Fit Almgren-Chriss η, γ, β to observed execution data via OLS.

        Each element of `executions` must be a dict with:
            participation_rate : float  — order size / ADV
            daily_volatility   : float  — realised vol on execution day
            observed_impact_bps: float  — actual slippage in basis points

        The model is:
            impact_bps = η * σ * x^β  +  γ * σ * x
        where x = participation_rate, σ = daily_volatility.

        Fitting is done by linearising with log transform on the temporary
        component and solving via scipy.optimize.curve_fit.

        Returns a dict with fitted parameters and goodness-of-fit metrics.
        If fewer than min_samples are provided, returns the current parameters
        unchanged with a warning.
        """
        if len(executions) < min_samples:
            warnings.warn(
                f"calibrate_from_executions: only {len(executions)} samples "
                f"(need >= {min_samples}). Parameters unchanged.",
                RuntimeWarning,
                stacklevel=2,
            )
            return {
                "calibrated": False,
                "reason": f"insufficient samples ({len(executions)} < {min_samples})",
                "current_params": {
                    "eta": self.temporary_impact_coefficient,
                    "gamma": self.permanent_impact_coefficient,
                    "beta": self.decay_exponent,
                },
            }

        try:
            from scipy.optimize import curve_fit as _curve_fit

            x_arr = np.array([e["participation_rate"] for e in executions])
            s_arr = np.array([e["daily_volatility"] for e in executions])
            y_arr = np.array([e["observed_impact_bps"] for e in executions]) / 10000  # → fraction

            def _model(X, eta, gamma, beta):
                x, s = X
                return eta * s * (x**beta) + gamma * s * x

            popt, pcov = _curve_fit(
                _model,
                (x_arr, s_arr),
                y_arr,
                p0=[
                    self.temporary_impact_coefficient,
                    self.permanent_impact_coefficient,
                    self.decay_exponent,
                ],
                bounds=([0.001, 0.001, 0.3], [2.0, 2.0, 1.0]),
                maxfev=5000,
            )
            eta_fit, gamma_fit, beta_fit = popt
            perr = np.sqrt(
                np.abs(np.nan_to_num(np.diag(pcov), nan=0.0))
            )  # abs guards negative diag from ill-conditioned fits

            # Goodness of fit
            y_pred = _model((x_arr, s_arr), *popt)
            ss_res = np.sum((y_arr - y_pred) ** 2)
            ss_tot = np.sum((y_arr - np.mean(y_arr)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

            self.temporary_impact_coefficient = float(eta_fit)
            self.permanent_impact_coefficient = float(gamma_fit)
            self.decay_exponent = float(beta_fit)

            logger.info(
                "Almgren-Chriss calibrated: η=%.4f γ=%.4f β=%.4f R²=%.3f (n=%d)",
                eta_fit,
                gamma_fit,
                beta_fit,
                r2,
                len(executions),
            )
            return {
                "calibrated": True,
                "n_samples": len(executions),
                "eta": round(float(eta_fit), 6),
                "gamma": round(float(gamma_fit), 6),
                "beta": round(float(beta_fit), 6),
                "eta_stderr": round(float(perr[0]), 6),
                "gamma_stderr": round(float(perr[1]), 6),
                "beta_stderr": round(float(perr[2]), 6),
                "r_squared": round(float(r2), 4),
            }

        except (ValueError, RuntimeError, TypeError) as exc:
            logger.warning("calibrate_from_executions failed: %s", exc)
            return {"calibrated": False, "error": "Calibration failed — check server logs"}

    def total_cost(self, order_size: float, price: float, is_maker: bool = False, **kwargs) -> dict[str, float]:
        """Calculate all-in transaction cost"""
        notional = abs(order_size) * price

        # Explicit costs
        commission = max(
            (abs(order_size) / 100000) * self.commission_per_lot,
            notional * self.commission_per_million / 1e6,
        )
        clearing = notional * self.clearing_fee_bps / 10000
        exchange = notional * self.exchange_fee_bps / 10000

        # Implicit costs
        spread_cost = notional * self.spread_markup_bps / 10000 if not is_maker else 0

        # Market impact (if provided)
        impact_cost = 0.0
        if "participation_rate" in kwargs:
            impact = self.calculate_market_impact(
                order_size,
                kwargs["participation_rate"],
                kwargs.get("daily_volatility", 0.02),
                kwargs.get("order_flow_toxicity", 0.0),
            )
            impact_cost = notional * impact["total_bps"] / 10000

        total = commission + clearing + exchange + spread_cost + impact_cost

        return {
            "commission": commission,
            "clearing": clearing,
            "exchange": exchange,
            "spread": spread_cost,
            "market_impact": impact_cost,
            "total_explicit": commission + clearing + exchange,
            "total_implicit": spread_cost + impact_cost,
            "total_cost": total,
            "cost_bps": (total / notional) * 10000 if notional > 0 else 0,
        }


@dataclass
class Position:
    """
    Advanced position tracking with comprehensive P&L attribution.
    Tracks realized, unrealized, and risk-adjusted P&L.
    """

    symbol: str
    side: OrderSide

    # Size and entry
    size: float = 0.0
    avg_entry_price: float = 0.0
    entry_timestamp: NanosecondTimestamp | None = None

    # Cost tracking
    total_commission_paid: float = 0.0
    total_slippage_paid: float = 0.0
    total_financing_paid: float = 0.0  # For overnight positions

    # Risk metrics (MFE/MAE tracking)
    max_favorable_excursion: float = 0.0  # Best unrealized P&L
    max_adverse_excursion: float = 0.0  # Worst unrealized P&L (drawdown)
    mfe_timestamp: NanosecondTimestamp | None = None
    mae_timestamp: NanosecondTimestamp | None = None

    # Trade history
    opening_trades: list[dict] = field(default_factory=list)
    closing_trades: list[dict] = field(default_factory=list)

    # Current state
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    def update_mfe_mae(self, current_price: float, timestamp: NanosecondTimestamp):
        """Update max favorable and adverse excursion"""
        if self.size == 0:
            return

        # Calculate current unrealized P&L
        current_pnl = self.size * (current_price - self.avg_entry_price)
        if self.side == OrderSide.SELL:
            current_pnl = -current_pnl

        # Update MFE (best case)
        if current_pnl > self.max_favorable_excursion:
            self.max_favorable_excursion = current_pnl
            self.mfe_timestamp = timestamp

        # Update MAE (worst case - drawdown)
        if -current_pnl > self.max_adverse_excursion:
            self.max_adverse_excursion = -current_pnl
            self.mae_timestamp = timestamp

        self.unrealized_pnl = current_pnl

    def add_trade(
        self,
        trade_size: float,
        trade_price: float,
        commission: float,
        slippage: float,
        timestamp: NanosecondTimestamp,
        is_opening: bool,
    ):
        """Record trade in position history"""
        trade_record = {
            "timestamp": float(timestamp),
            "size": trade_size,
            "price": trade_price,
            "commission": commission,
            "slippage": slippage,
            "notional": abs(trade_size) * trade_price,
        }

        if is_opening:
            self.opening_trades.append(trade_record)
        else:
            self.closing_trades.append(trade_record)
            # Calculate realized P&L for this close
            if self.side == OrderSide.BUY:
                pnl = (trade_price - self.avg_entry_price) * trade_size
            else:
                pnl = (self.avg_entry_price - trade_price) * abs(trade_size)
            self.realized_pnl += pnl - commission - slippage

    def get_performance_metrics(self) -> dict[str, float]:
        """Calculate position-level performance metrics"""
        if not self.opening_trades:
            return {}

        total_opened = sum(t["size"] for t in self.opening_trades)
        total_closed = sum(abs(t["size"]) for t in self.closing_trades)

        return {
            "total_opened": total_opened,
            "total_closed": total_closed,
            "remaining": self.size,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.realized_pnl + self.unrealized_pnl,
            "mfe": self.max_favorable_excursion,
            "mae": self.max_adverse_excursion,
            "mfe_ratio": self.max_favorable_excursion / abs(self.realized_pnl) if self.realized_pnl != 0 else 0,
            "mae_ratio": self.max_adverse_excursion / abs(self.realized_pnl) if self.realized_pnl != 0 else 0,
            "efficiency": self.realized_pnl / self.max_favorable_excursion if self.max_favorable_excursion > 0 else 0,
        }


@dataclass
class TradeRecord:
    """
    Complete trade record with full execution quality metrics.
    """

    trade_id: str
    parent_order_id: str | None

    # Timing
    entry_time: NanosecondTimestamp
    exit_time: NanosecondTimestamp

    # Instrument
    symbol: str
    side: OrderSide

    # Prices
    entry_price: float
    exit_price: float
    entry_slippage_bps: float
    exit_slippage_bps: float

    # Size
    size: float
    filled_size: float

    # Costs
    entry_commission: float
    exit_commission: float

    # Market conditions
    entry_regime: MarketRegime
    exit_regime: MarketRegime
    entry_volatility: float
    exit_volatility: float
    entry_spread_bps: float
    exit_spread_bps: float

    # Risk metrics
    mfe: float  # Max favorable excursion
    mae: float  # Max adverse excursion
    mfe_pct: float
    mae_pct: float

    # Performance
    @property
    def duration_ns(self) -> int:
        return (self.exit_time.seconds - self.entry_time.seconds) * 1_000_000_000 + (
            self.exit_time.nanoseconds - self.entry_time.nanoseconds
        )

    @property
    def duration_seconds(self) -> float:
        return self.duration_ns / 1_000_000_000

    @property
    def gross_pnl(self) -> float:
        if self.side == OrderSide.BUY:
            return (self.exit_price - self.entry_price) * self.filled_size
        return (self.entry_price - self.exit_price) * self.filled_size

    @property
    def net_pnl(self) -> float:
        slippage_cost = (self.entry_slippage_bps + self.exit_slippage_bps) / 10000 * self.filled_size * self.entry_price
        return self.gross_pnl - self.entry_commission - self.exit_commission - slippage_cost

    @property
    def return_pct(self) -> float:
        cost_basis = self.filled_size * self.entry_price
        return self.net_pnl / cost_basis if cost_basis > 0 else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side.name,
            "entry": float(self.entry_time),
            "exit": float(self.exit_time),
            "duration_sec": self.duration_seconds,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "return_pct": self.return_pct,
            "mfe_pct": self.mfe_pct,
            "mae_pct": self.mae_pct,
            "regime_entry": self.entry_regime.name,
            "regime_exit": self.exit_regime.name,
        }


# =============================================================================
# MARKET MICROSTRUCTURE ANALYSIS
# =============================================================================


class MarketMicrostructureAnalyzer:
    """
    Real-time market microstructure analysis with regime detection.
    Uses high-frequency metrics to classify market conditions.
    """

    def __init__(self, lookback_ticks: int = 100, volatility_window: int = 20):
        self.lookback = lookback_ticks
        self.vol_window = volatility_window

        # Data storage
        self.ticks: deque = deque(maxlen=lookback_ticks)
        self.returns: deque = deque(maxlen=lookback_ticks)
        self.trade_flow: deque = deque(maxlen=lookback_ticks)

        # Realized metrics
        self.realized_variance: float = 0.0
        self.realized_skewness: float = 0.0
        self.realized_kurtosis: float = 0.0

        # Microstructure metrics
        self.effective_spread: float = 0.0
        self.price_impact: float = 0.0
        self.adverse_selection: float = 0.0

        # VPIN-like toxicity
        self.order_flow_toxicity: float = 0.0
        self.volume_sync_vpин: float = 0.0

        # Current regime
        self.current_regime: MarketRegime = MarketRegime.UNKNOWN
        self.regime_confidence: float = 0.0
        self.regime_history: deque = deque(maxlen=50)

        # Technical indicators
        self.hurst_exponent: float = 0.5
        self.fractal_dimension: float = 1.5
        self.entropy: float = 1.0

    def add_tick(self, tick: TickData):
        """Process new tick and update all metrics"""
        # Store tick
        self.ticks.append(tick)

        # Calculate return if possible
        if len(self.ticks) > 1:
            prev_tick = self.ticks[-2]
            if prev_tick.mid > 0 and tick.mid > 0:
                ret = float(np.nan_to_num(np.log(tick.mid / prev_tick.mid), nan=0.0, posinf=0.0, neginf=0.0))
                self.returns.append(ret)

        # Update trade flow if available
        if tick.last_price and tick.last_size:
            self.trade_flow.append(
                {
                    "price": tick.last_price,
                    "size": tick.last_size,
                    "timestamp": tick.timestamp,
                    "side": "buy" if tick.last_price >= tick.ask else "sell",
                }
            )

        # Update all metrics
        self._update_realized_metrics()
        self._update_microstructure_metrics()
        self._update_toxicity_metrics()
        self._detect_regime()

    def _update_realized_metrics(self):
        """Update realized volatility, skewness, kurtosis"""
        if len(self.returns) < self.vol_window:
            return

        returns_array = np.array(list(self.returns)[-self.vol_window :])

        self.realized_variance = np.var(returns_array) * len(returns_array)
        self.realized_skewness = stats.skew(returns_array) if SCIPY_AVAILABLE else 0
        self.realized_kurtosis = stats.kurtosis(returns_array) if SCIPY_AVAILABLE else 3

    def _update_microstructure_metrics(self):
        """Update spread and impact metrics"""
        if len(self.ticks) < 20:
            return

        recent_ticks = list(self.ticks)[-20:]

        # Effective spread (Roll measure)
        price_changes = [t.mid for t in recent_ticks]
        if len(price_changes) > 1:
            cov = float(np.nan_to_num(np.cov(price_changes[:-1], price_changes[1:])[0, 1], nan=0.0))
            self.effective_spread = 2 * np.sqrt(max(-cov, 0.0)) if cov < 0 else 0

        # Realized spread vs quoted spread
        quoted_spreads = [t.spread_bps for t in recent_ticks]
        self.price_impact = np.mean(quoted_spreads) - self.effective_spread if quoted_spreads else 0

    def _update_toxicity_metrics(self):
        """Calculate VPIN-like order flow toxicity"""
        if len(self.trade_flow) < 50:
            return

        recent_flow = list(self.trade_flow)[-50:]

        # Buy vs sell volume
        buy_vol = sum(t["size"] for t in recent_flow if t["side"] == "buy")
        sell_vol = sum(t["size"] for t in recent_flow if t["side"] == "sell")
        total_vol = buy_vol + sell_vol

        if total_vol > 0:
            # VPIN = |2vB/V - 1| (volume-synchronized probability of informed trading)
            self.order_flow_toxicity = abs(2 * buy_vol / total_vol - 1)
            self.volume_sync_vpин = self.order_flow_toxicity

    def _detect_regime(self):
        """Detect current market regime using multiple classifiers"""
        if len(self.ticks) < 50:
            self.current_regime = MarketRegime.UNKNOWN
            return

        # Calculate features
        self._extract_regime_features()

        # Rule-based classification (ML could be added)
        volatility = (
            np.sqrt(max(float(np.nan_to_num(self.realized_variance, nan=0.0)), 0.0))
            if self.realized_variance > 0
            else 0
        )

        # Trend detection via Hurst
        self._calculate_hurst()

        # Classify
        if volatility > 0.05:  # >5% realized vol
            if self.realized_skewness < -1:
                self.current_regime = MarketRegime.HIGH_VOLATILITY_BREAKOUT
            else:
                self.current_regime = MarketRegime.HIGH_VOLATILITY_MEAN_REVERSION
        elif self.hurst_exponent > 0.6:
            if self.returns and np.mean(list(self.returns)[-10:]) > 0:
                self.current_regime = MarketRegime.TRENDING_STRONG_BULL
            else:
                self.current_regime = MarketRegime.TRENDING_STRONG_BEAR
        elif self.hurst_exponent > 0.5:
            self.current_regime = (
                MarketRegime.TRENDING_WEAK_BULL
                if (self.returns and np.mean(list(self.returns)[-10:]) > 0)
                else MarketRegime.TRENDING_WEAK_BEAR
            )
        elif volatility < 0.01:
            self.current_regime = MarketRegime.RANGING_NARROW
        else:
            self.current_regime = MarketRegime.RANGING_WIDE

        # Confidence based on data quality
        self.regime_confidence = min(1.0, len(self.ticks) / self.lookback)
        self.regime_history.append((self.current_regime, self.regime_confidence))

    def _extract_regime_features(self) -> dict[str, float]:
        """Extract features for regime classification"""
        return {
            "realized_vol": np.sqrt(max(float(np.nan_to_num(self.realized_variance, nan=0.0)), 0.0)),
            "skewness": self.realized_skewness,
            "kurtosis": self.realized_kurtosis,
            "spread": self.effective_spread,
            "toxicity": self.order_flow_toxicity,
            "hurst": self.hurst_exponent,
        }

    def _calculate_hurst(self, max_lag: int = 20):
        """Estimate Hurst exponent via R/S analysis"""
        if len(self.ticks) < max_lag * 2:
            self.hurst_exponent = 0.5
            return

        prices = np.array([t.mid for t in self.ticks])
        lags = range(2, min(max_lag, len(prices) // 4))

        tau = [np.std(np.subtract(prices[lag:], prices[:-lag])) for lag in lags]

        if any(t == 0 for t in tau):
            self.hurst_exponent = 0.5
            return

        tau_arr = np.array(tau, dtype=float)
        if not np.all(tau_arr > 0):
            self.hurst_exponent = 0.5
            return
        lags_arr = np.nan_to_num(np.array(list(lags), dtype=float), nan=1.0)
        log_lags = np.log(np.where(lags_arr > 0, lags_arr, 1e-9))
        log_tau = np.log(np.where(tau_arr > 0, tau_arr, 1e-9))

        try:
            slope = np.polyfit(log_lags, log_tau, 1)[0]
            self.hurst_exponent = max(0, min(1, slope))
        except (ValueError, RuntimeError, TypeError):
            self.hurst_exponent = 0.5

    def get_execution_recommendation(self) -> dict[str, Any]:
        """Get execution strategy recommendation based on regime"""
        regime_recommendations = {
            MarketRegime.TRENDING_STRONG_BULL: {
                "urgency": "high",
                "strategy": "aggressive",
                "time_in_force": "IOC",
                "price_aggression": 0.5,  # Pay up to 0.5 bps
                "reason": "Strong momentum - execute quickly",
            },
            MarketRegime.TRENDING_STRONG_BEAR: {
                "urgency": "high",
                "strategy": "aggressive",
                "time_in_force": "IOC",
                "price_aggression": 0.5,
                "reason": "Strong downtrend - exit quickly",
            },
            MarketRegime.HIGH_VOLATILITY_BREAKOUT: {
                "urgency": "high",
                "strategy": "twap",
                "time_in_force": "IOC",
                "price_aggression": 1.0,
                "reason": "High volatility - use TWAP with tight limits",
            },
            MarketRegime.RANGING_NARROW: {
                "urgency": "low",
                "strategy": "patient",
                "time_in_force": "GTC",
                "price_aggression": -0.2,  # Work inside spread
                "reason": "Quiet market - be patient for fills",
            },
            MarketRegime.LOW_LIQUIDITY: {
                "urgency": "low",
                "strategy": "iceberg",
                "time_in_force": "GTC",
                "price_aggression": 0.0,
                "reason": "Low liquidity - hide size",
            },
        }

        default = {
            "urgency": "medium",
            "strategy": "standard",
            "time_in_force": "DAY",
            "price_aggression": 0.0,
            "reason": "Standard execution",
        }

        rec = regime_recommendations.get(self.current_regime, default)
        rec["regime"] = self.current_regime.name
        rec["confidence"] = self.regime_confidence
        rec["toxicity"] = self.order_flow_toxicity
        rec["realized_vol"] = (
            np.sqrt(max(float(np.nan_to_num(self.realized_variance, nan=0.0)), 0.0))
            if self.realized_variance > 0
            else 0
        )

        return rec

    def get_microstructure_report(self) -> dict[str, Any]:
        """Generate comprehensive microstructure report"""
        return {
            "regime": {
                "current": self.current_regime.name,
                "confidence": self.regime_confidence,
                "history": [(r.name, c) for r, c in self.regime_history],
            },
            "volatility": {
                "realized": np.sqrt(max(float(np.nan_to_num(self.realized_variance, nan=0.0)), 0.0)),
                "skewness": self.realized_skewness,
                "kurtosis": self.realized_kurtosis,
            },
            "liquidity": {
                "effective_spread_bps": self.effective_spread * 10000,
                "price_impact_bps": self.price_impact * 10000,
                "order_flow_toxicity": self.order_flow_toxicity,
            },
            "dynamics": {
                "hurst_exponent": self.hurst_exponent,
                "trend_strength": abs(self.hurst_exponent - 0.5) * 2,
                "mean_reversion_probability": max(0, 0.5 - self.hurst_exponent) * 2,
            },
        }


# =============================================================================
# RISK MANAGEMENT SYSTEM
# =============================================================================


class InstitutionalRiskManager:
    """
    FIA 2024 compliant risk management with automatic kill switches.
    Implements pre-trade, intraday, and post-trade risk controls.
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        max_position_pct: float = 0.05,  # 5% per position
        max_sector_pct: float = 0.20,  # 20% per sector
        max_portfolio_var_1day: float = 0.02,  # 2% daily VaR
        max_daily_loss_pct: float = 0.03,  # 3% daily stop
        max_drawdown_pct: float = 0.10,  # 10% max drawdown
        max_leverage: float = 3.0,  # 3x gross exposure
        max_turnover_annual: float = 10.0,  # 10x annual turnover
        kelly_fraction: float = 0.3,  # Conservative Kelly
        correlation_limit: float = 0.80,
    ):  # Max correlation
        # Capital
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital
        self.high_water_mark = initial_capital

        # Limits
        self.limits = {
            "position": max_position_pct,
            "sector": max_sector_pct,
            "var": max_portfolio_var_1day,
            "daily_loss": max_daily_loss_pct,
            "drawdown": max_drawdown_pct,
            "leverage": max_leverage,
            "turnover": max_turnover_annual,
            "correlation": correlation_limit,
        }

        # Kelly criterion
        self.kelly_fraction = kelly_fraction

        # State
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.daily_turnover = 0.0
        self.positions: dict[str, Position] = {}
        self.trade_history: deque = deque(maxlen=10_000)
        self.risk_events: deque = deque(maxlen=1_000)

        # Kill switch state
        self.kill_switch_active = False
        self.kill_switch_reason: str | None = None
        self.circuit_breaker_level = 0  # 0=normal, 1=warning, 2=halt

        # VaR calculation
        self.returns_history: deque = deque(maxlen=252)  # 1 year daily

        # Correlation matrix
        self.correlation_window: deque = deque(maxlen=50)

        # Callbacks for emergency actions
        self.emergency_callbacks: list[Callable] = []

        logger.info("RiskManager initialized: $%s capital", initial_capital)

    def register_emergency_callback(self, callback: Callable):
        """Register callback for kill switch activation"""
        self.emergency_callbacks.append(callback)

    @staticmethod
    def _failed_check(name: str, limit: float, projected: float, severity: "RiskEventSeverity") -> dict:
        """Build a standardised failed-check dict for pre-trade risk results."""
        return {"check": name, "passed": False, "limit": limit, "projected": projected, "severity": severity}

    def _check_position_size(self, symbol: str, side: "OrderSide", size: float, price: float) -> dict | None:
        """FIA 1.1: Reject if projected notional exceeds position limit."""
        current = self.positions.get(symbol, Position(symbol, side))
        delta = size if side == OrderSide.BUY else -size
        proj_not = abs(current.size + delta) * price
        limit = self.current_capital * self.limits["position"]
        return (
            self._failed_check("POSITION_SIZE", limit, proj_not, RiskEventSeverity.CRITICAL)
            if proj_not > limit
            else None
        )

    def _check_leverage(self, notional: float) -> dict | None:
        """Reject if projected total exposure exceeds leverage limit."""
        current_exp = sum(abs(p.size * p.avg_entry_price) for p in self.positions.values())
        proj_exp = current_exp + notional
        max_exp = self.current_capital * self.limits["leverage"]
        return (
            self._failed_check("LEVERAGE", max_exp, proj_exp, RiskEventSeverity.CRITICAL)
            if proj_exp > max_exp
            else None
        )

    def _check_var_limit(self, symbol: str, size: float, price: float) -> dict | None:
        """Warn if projected VaR exceeds the configured limit."""
        current_var = self.calculate_var(0.95)
        projected_var = self._estimate_var_change(symbol, size, price)
        var_limit = self.current_capital * self.limits["var"]
        if current_var + projected_var > var_limit:
            return {
                "check": "VAR_LIMIT",
                "passed": False,
                "current_var": current_var,
                "projected_var": projected_var,
                "severity": RiskEventSeverity.WARNING,
            }
        return None

    def check_pre_trade_risk(
        self,
        symbol: str,
        side: "OrderSide",
        size: float,
        price: float,
        portfolio_state: dict,
    ) -> tuple[bool, str, dict]:
        """
        Pre-trade risk check — FIA 1.1, 1.2, 1.3 compliant.

        Returns (allowed, reason, risk_metadata).
        """
        if self.kill_switch_active:
            return False, "KILL_SWITCH_ACTIVE", {"severity": RiskEventSeverity.KILL_SWITCH}

        if self.circuit_breaker_level >= _CIRCUIT_BREAKER_HALT_LEVEL:
            return False, "CIRCUIT_BREAKER_HALT", {"severity": RiskEventSeverity.CRITICAL}

        # FIA 1.5: daily loss — triggers kill switch immediately
        if self.daily_pnl < -self.current_capital * self.limits["daily_loss"]:
            self._trigger_kill_switch("Daily loss limit breached")
            return False, "DAILY_LOSS_LIMIT", {"severity": RiskEventSeverity.KILL_SWITCH}

        notional = size * price
        checks = list(
            filter(
                None,
                [
                    self._check_position_size(symbol, side, size, price),
                    self._check_leverage(notional),
                    self._check_var_limit(symbol, size, price),
                ],
            )
        )

        critical = [c for c in checks if c["severity"] == RiskEventSeverity.CRITICAL]
        warnings = [c for c in checks if c["severity"] == RiskEventSeverity.WARNING]

        if critical:
            self._log_risk_event(f"Pre-trade blocked: {critical[0]['check']}", RiskEventSeverity.CRITICAL)
            return False, critical[0]["check"], {"failed_checks": checks}

        if warnings:
            self._log_risk_event(f"Pre-trade warning: {warnings[0]['check']}", RiskEventSeverity.WARNING)

        return True, "OK", {"checks_passed": len(checks)}

    def check_intraday_risk(self, timestamp: NanosecondTimestamp) -> tuple[bool, str]:
        """
        Intraday risk monitoring - continuous checks.
        """
        # Update drawdown
        current_drawdown = (self.peak_capital - self.current_capital) / self.peak_capital

        # Circuit breaker levels
        if current_drawdown > self.limits["drawdown"]:
            self._trigger_kill_switch(f"Max drawdown breached: {current_drawdown:.2%}")
            return False, "MAX_DRAWDOWN"

        if current_drawdown > self.limits["drawdown"] * 0.8:
            self.circuit_breaker_level = 2
            self._log_risk_event(
                f"Circuit breaker level 2: {current_drawdown:.2%}",
                RiskEventSeverity.CRITICAL,
            )
            return False, "CIRCUIT_BREAKER_2"

        if current_drawdown > self.limits["drawdown"] * 0.5:
            self.circuit_breaker_level = 1
            self._log_risk_event(
                f"Circuit breaker level 1: {current_drawdown:.2%}",
                RiskEventSeverity.WARNING,
            )

        # Check for unusual trading patterns
        if self.daily_trades > 1000:  # >1000 trades/day is unusual
            self._log_risk_event("High trade frequency detected", RiskEventSeverity.WARNING)

        return True, "OK"

    def update_capital(self, pnl: float, timestamp: NanosecondTimestamp):
        """Update capital and track all risk metrics"""
        self.current_capital += pnl
        self.daily_pnl += pnl

        # Update high water mark
        if self.current_capital > self.high_water_mark:
            self.high_water_mark = self.current_capital
            self.peak_capital = max(self.peak_capital, self.current_capital)

        # Record return for VaR
        if self.current_capital > 0:
            daily_return = pnl / self.current_capital
            self.returns_history.append(daily_return)

        # Check intraday risk
        self.check_intraday_risk(timestamp)

    def calculate_var(self, confidence: float = 0.95, method: str = "historical") -> float:
        """
        Calculate Value at Risk using specified method.
        """
        if len(self.returns_history) < 30:
            # Not enough data - use parametric fallback
            return self.current_capital * 0.02  # Conservative 2%

        returns = np.array(self.returns_history)

        if method == "historical":
            return np.percentile(returns, (1 - confidence) * 100) * self.current_capital
        if method == "parametric" and SCIPY_AVAILABLE:
            mu, sigma = np.mean(returns), np.std(returns)
            z_score = stats.norm.ppf(1 - confidence)
            return (mu + z_score * sigma) * self.current_capital
        if method == "cornish_fisher" and SCIPY_AVAILABLE:
            # Adjust for skewness and kurtosis
            z = stats.norm.ppf(1 - confidence)
            s = stats.skew(returns)
            k = stats.kurtosis(returns)
            z_cf = z + (z**2 - 1) * s / 6 + (z**3 - 3 * z) * (k - 3) / 24
            return (np.mean(returns) + z_cf * np.std(returns)) * self.current_capital

        return np.percentile(returns, (1 - confidence) * 100) * self.current_capital

    def calculate_cvar(self, confidence: float = 0.95) -> float:
        """Calculate Conditional VaR (Expected Shortfall)"""
        var = self.calculate_var(confidence)
        returns = np.array(self.returns_history)
        cvar_returns = returns[returns * self.current_capital <= var]
        return np.mean(cvar_returns) * self.current_capital if len(cvar_returns) > 0 else var

    def calculate_kelly_criterion(self) -> float:
        """
        Calculate optimal Kelly fraction based on trade history.
        f* = (bp - q) / b
        """
        if len(self.trade_history) < 20:
            return self.kelly_fraction  # Default

        wins = [t.net_pnl for t in self.trade_history if t.net_pnl > 0]
        losses = [abs(t.net_pnl) for t in self.trade_history if t.net_pnl < 0]

        if not wins or not losses:
            return 0.0

        p = len(wins) / len(self.trade_history)
        q = 1 - p
        b = np.mean(wins) / np.mean(losses)

        kelly = (b * p - q) / b if b > 0 else 0
        return max(0, min(kelly, 0.5)) * self.kelly_fraction  # Half-Kelly for safety

    def get_optimal_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        volatility: float,
        correlation_matrix: np.ndarray | None = None,
    ) -> float:
        """
        Calculate optimal position size using Kelly with risk constraints.
        """
        # Base Kelly size
        kelly_fraction = self.calculate_kelly_criterion()
        risk_amount = self.current_capital * self.limits["position"] * kelly_fraction

        # Volatility adjustment
        vol_adj = 1 / (1 + volatility * 5)
        risk_amount *= vol_adj

        # Stop-based sizing
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance == 0:
            return 0.0

        position_size = risk_amount / stop_distance

        # Check portfolio constraints
        max_by_exposure = (self.current_capital * self.limits["leverage"]) / entry_price
        position_size = min(position_size, max_by_exposure)

        return position_size

    def _trigger_kill_switch(self, reason: str):
        """Activate emergency kill switch"""
        self.kill_switch_active = True
        self.kill_switch_reason = reason
        self.circuit_breaker_level = 2

        logger.critical("=" * 70)
        logger.critical("KILL SWITCH ACTIVATED")
        logger.critical("Reason: %s", reason)

        logger.critical("Daily P&L: $%s", self.daily_pnl)

        logger.critical("Current Capital: $%s", self.current_capital)

        logger.critical("Drawdown: %s", (self.peak_capital - self.current_capital) / self.peak_capital)

        logger.critical("=" * 70)

        # Execute emergency callbacks
        for callback in self.emergency_callbacks:
            try:
                callback(reason, self.daily_pnl, self.current_capital)
            except (RuntimeError, ValueError, AttributeError) as e:
                logger.error("Emergency callback failed: %s", e)

        self._log_risk_event(f"Kill switch: {reason}", RiskEventSeverity.KILL_SWITCH)

    def _log_risk_event(self, message: str, severity: RiskEventSeverity):
        """Log risk event for audit trail"""
        event = {
            "timestamp": float(NanosecondTimestamp.now()),
            "message": message,
            "severity": severity.value,
            "capital": self.current_capital,
            "daily_pnl": self.daily_pnl,
        }
        self.risk_events.append(event)
        logger.log(
            logging.CRITICAL if severity >= RiskEventSeverity.CRITICAL else logging.WARNING,
            "Risk Event [%s]: %s",
            severity.name,
            message,
        )

    def _estimate_var_change(self, symbol: str, size: float, price: float) -> float:
        """Estimate how VaR changes with new position"""
        # Simplified - would use proper marginal VaR calculation
        notional = abs(size) * price
        return notional * 0.02  # Assume 2% daily vol

    def get_risk_report(self) -> dict[str, Any]:
        """Generate comprehensive risk report"""
        current_drawdown = (
            (self.peak_capital - self.current_capital) / self.peak_capital if self.peak_capital > 0 else 0
        )

        return {
            "capital": {
                "initial": self.initial_capital,
                "current": self.current_capital,
                "peak": self.peak_capital,
                "high_water_mark": self.high_water_mark,
                "drawdown_pct": current_drawdown * 100,
                "daily_pnl": self.daily_pnl,
            },
            "limits": self.limits,
            "utilization": {
                "position": max(
                    (abs(p.size * p.avg_entry_price) / self.current_capital) for p in self.positions.values()
                )
                if self.positions
                else 0,
                "leverage": sum(abs(p.size * p.avg_entry_price) for p in self.positions.values()) / self.current_capital
                if self.current_capital > 0
                else 0,
                "daily_loss": abs(self.daily_pnl) / self.current_capital if self.current_capital > 0 else 0,
            },
            "risk_metrics": {
                "var_95": self.calculate_var(0.95),
                "cvar_95": self.calculate_cvar(0.95),
                "kelly_fraction": self.calculate_kelly_criterion(),
                "circuit_breaker": self.circuit_breaker_level,
                "kill_switch": self.kill_switch_active,
            },
            "recent_events": list(self.risk_events)[-10:],
            "positions": {
                symbol: {
                    "size": pos.size,
                    "notional": pos.size * pos.avg_entry_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "mfe": pos.max_favorable_excursion,
                    "mae": pos.max_adverse_excursion,
                }
                for symbol, pos in self.positions.items()
            },
        }


# =============================================================================
# =============================================================================
# PERFORMANCE REPORT HELPERS
# Module-level functions extracted from get_performance_report() so each
# metric section is independently testable without instantiating the engine.
# =============================================================================

# Annualisation factor: minute bars assumed (252 trading days × 390 min/day).
_ANNUAL_BARS = 252 * 390


def _compute_drawdown_series(
    equity_curve: list[tuple],
    initial_capital: float,
) -> tuple[float, list[dict]]:
    """
    Compute maximum drawdown and completed drawdown periods from an equity curve.

    Returns (max_drawdown_fraction, drawdown_periods_list).
    max_drawdown_fraction is in [0, 1]; multiply by 100 for percentage.
    """
    peak = initial_capital
    max_dd = 0.0
    dd_start = None
    dd_periods: list[dict] = []

    for ts, eq in equity_curve:
        if eq > peak:
            if dd_start is not None:
                ts_dt = ts.to_datetime() if hasattr(ts, "to_datetime") else datetime.now(UTC)
                if (ts_dt - dd_start).total_seconds() > 0:
                    dd_periods.append(
                        {
                            "start": dd_start.isoformat(),
                            "end": ts_dt.isoformat(),
                            "max_dd": max_dd,
                        }
                    )
            peak = eq
            max_dd = 0.0
            dd_start = None
        else:
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                if dd_start is None:
                    dd_start = ts.to_datetime() if hasattr(ts, "to_datetime") else datetime.now(UTC)

    return max_dd, dd_periods


def _calculate_sortino(returns: "np.ndarray", target: float = 0.0) -> float:
    """Sortino ratio: excess return over target divided by downside deviation.

    The denominator was ``np.std(arr[arr < target])`` — the dispersion among the
    losses rather than the shortfall of the series. F120 named that defect and
    fixed it in ``backtesting/engine_config.py``; this engine kept a copy, so it
    reported +inf whenever the losses were all the same size. Both engines now
    share ``analytics.ratios.downside_deviation``.
    """
    from analytics.ratios import downside_deviation

    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]  # drop NaN/inf before any calculation
    if len(arr) == 0:
        return 0.0
    downside_std = downside_deviation(arr, target=target)
    return float((np.mean(arr) - target) / downside_std) if downside_std > 0 else 0.0


def _calculate_calmar(returns: "np.ndarray", max_dd: float) -> float:
    """Calmar ratio: annualised return divided by maximum drawdown."""
    if max_dd <= 0 or len(returns) == 0:
        return 0.0
    annual_return = float(np.mean(returns)) * _ANNUAL_BARS
    return annual_return / max_dd


def _build_report_metadata(engine: "EnhancedBacktestEngine") -> dict[str, Any]:
    """Build the metadata section of the performance report."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "initial_capital": engine.initial_capital,
        "final_capital": engine.capital,
        "total_return_pct": (engine.capital - engine.initial_capital) / engine.initial_capital * 100,
        "backtest_periods": len(engine.equity_curve),
        "execution_quality": engine.execution_quality.name,
    }


def _build_trade_statistics(trades: list, pnls: list[float]) -> dict[str, Any]:
    """Compute win/loss counts, profit factor, payoff ratio, and P&L distribution."""
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf"),
        "payoff_ratio": abs(float(np.mean(wins)) / float(np.mean(losses))) if wins and losses else 0,
        "total_pnl": sum(pnls),
        "avg_trade_pnl": float(np.mean(pnls)),
        "avg_win": float(np.mean(wins)) if wins else 0,
        "avg_loss": float(np.mean(losses)) if losses else 0,
        "largest_win": max(wins) if wins else 0,
        "largest_loss": min(losses) if losses else 0,
        "std_dev_pnl": float(np.std(pnls)),
    }


def _build_time_analysis(trades: list) -> dict[str, Any]:
    """Compute trade duration statistics in seconds and minutes."""
    durations = [t.duration_seconds for t in trades]
    return {
        "avg_duration_sec": float(np.mean(durations)) if durations else 0,
        "avg_duration_min": float(np.mean(durations)) / 60 if durations else 0,
        "max_duration_sec": max(durations) if durations else 0,
        "min_duration_sec": min(durations) if durations else 0,
    }


def _build_risk_metrics(
    returns: list[float],
    equity_returns: "np.ndarray",
    max_dd: float,
    dd_periods: list[dict],
    current_capital: float,
    risk_manager: "InstitutionalRiskManager",
) -> dict[str, Any]:
    """
    Compute Sharpe, Sortino, Calmar, VaR, CVaR, skewness, and kurtosis.

    All ratio metrics use the annualisation factor _ANNUAL_BARS (minute bars).
    """
    eq_safe = np.nan_to_num(np.array(equity_returns, dtype=float), nan=0.0)
    eq_std = float(np.std(eq_safe)) if len(eq_safe) > 1 else 0.0
    eq_mean = float(np.mean(eq_safe)) if len(eq_safe) > 1 else 0.0
    sharpe = (eq_mean / max(eq_std, 1e-9) * np.sqrt(_ANNUAL_BARS)) if eq_std > 0 else 0.0
    annual_vol = eq_std * np.sqrt(_ANNUAL_BARS) if len(eq_safe) > 1 else 0.0

    ret_arr = np.array(returns)
    var_95 = float(np.percentile(ret_arr, 5)) if len(returns) > 10 else 0.0
    cvar_95 = float(np.mean(ret_arr[ret_arr <= var_95])) if len(returns) > 10 else 0.0

    skewness = float(stats.skew(returns)) if SCIPY_AVAILABLE and len(returns) > 2 else 0.0
    kurtosis = float(stats.kurtosis(returns)) if SCIPY_AVAILABLE and len(returns) > 2 else 0.0

    current_dd_pct = (
        (risk_manager.peak_capital - current_capital) / risk_manager.peak_capital * 100
        if risk_manager.peak_capital > 0
        else 0.0
    )

    return {
        "max_drawdown_pct": max_dd * 100,
        "max_drawdown_periods": dd_periods,
        "current_drawdown_pct": current_dd_pct,
        "volatility_annual": annual_vol,
        "sharpe_ratio": float(sharpe),
        "sortino_ratio": _calculate_sortino(equity_returns),
        "calmar_ratio": _calculate_calmar(equity_returns, max_dd),
        "var_95": var_95,
        "cvar_95": cvar_95,
        "skewness": skewness,
        "kurtosis": kurtosis,
    }


def _build_execution_quality(
    execution_log: list[dict],
    positions: dict,
    initial_capital: float,
    cost_model: "TransactionCostModel",
) -> dict[str, Any]:
    """Aggregate slippage, latency, commission, and overnight financing costs."""
    total_financing = sum(p.total_financing_paid for p in positions.values())
    total_cost = sum(e["costs"].get("total_cost", 0) for e in execution_log if "costs" in e)
    return {
        "avg_slippage_bps": float(np.mean([e.get("slippage_bps", 0) for e in execution_log])) if execution_log else 0,
        "avg_latency_ms": float(np.mean([e.get("latency_ms", 0) for e in execution_log])) if execution_log else 0,
        "total_commission": sum(e["costs"].get("commission", 0) for e in execution_log if "costs" in e),
        "total_slippage_cost": sum(e["costs"].get("market_impact", 0) for e in execution_log if "costs" in e),
        "cost_drag_pct": (total_cost / initial_capital * 100) if initial_capital > 0 else 0,
        "total_financing_paid": total_financing,
        "financing_drag_pct": (total_financing / initial_capital * 100) if initial_capital > 0 else 0,
        "overnight_rate_annual_pct": getattr(cost_model, "overnight_rate_annual", 0.004) * 100,
    }


def _build_mfe_mae_analysis(trades: list) -> dict[str, Any]:
    """Compute MFE/MAE efficiency metrics across all closed trades."""
    total_mae = sum(t.mae for t in trades)
    return {
        "avg_mfe_pct": float(np.mean([t.mfe_pct for t in trades])),
        "avg_mae_pct": float(np.mean([t.mae_pct for t in trades])),
        "avg_efficiency": float(np.mean([t.net_pnl / t.mfe if t.mfe > 0 else 0 for t in trades])),
        "profit_factor_mfe": sum(t.mfe for t in trades) / total_mae if total_mae > 0 else 0,
    }


# =============================================================================
# MAIN BACKTEST ENGINE
# =============================================================================


class EnhancedBacktestEngine:
    """
    Institutional-grade backtesting engine with tick-level precision.
    Supports multi-asset, multi-strategy portfolios with realistic execution.
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        cost_model: TransactionCostModel | None = None,
        risk_manager: InstitutionalRiskManager | None = None,
        execution_quality: ExecutionQuality = ExecutionQuality.STANDARD,
        enable_gpu: bool = False,
        parallel_workers: int = 1,
    ):
        # Configuration
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.cost_model = cost_model or TransactionCostModel()
        self.risk_manager = risk_manager or InstitutionalRiskManager(initial_capital)
        self.execution_quality = execution_quality
        self.enable_gpu = enable_gpu and CUDA_AVAILABLE
        self.parallel_workers = parallel_workers

        # State
        self.positions: dict[str, Position] = {}
        self.closed_trades: list[TradeRecord] = []
        self.open_orders: dict[str, Any] = {}  # Track working orders

        # Market data
        self.current_time: NanosecondTimestamp | None = None
        self.microstructure = MarketMicrostructureAnalyzer()
        self.price_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

        # Performance tracking
        self.equity_curve: list[tuple[NanosecondTimestamp, float]] = []
        self.benchmark_curve: list[tuple[NanosecondTimestamp, float]] = []
        self.daily_stats: dict[str, dict] = {}

        # Execution tracking
        self.execution_log: list[dict] = []
        self.trade_count = 0

        # Slippage model parameters based on execution quality
        self.latency_model = self._get_latency_model()

        logger.info("BacktestEngine initialized: $%s", initial_capital)

        logger.info("Execution quality: %s", execution_quality.name)

        if self.enable_gpu:
            logger.info("GPU acceleration enabled")

    def _get_latency_model(self) -> dict[str, float]:
        """Get latency distribution parameters for execution quality"""
        models = {
            ExecutionQuality.HFT_COLOCATED: {"mean": 0.0001, "std": 0.00005},  # 100μs
            ExecutionQuality.HFT_PROXIMITY: {"mean": 0.0005, "std": 0.0002},  # 500μs
            ExecutionQuality.ULTRA_LOW_LATENCY: {"mean": 0.005, "std": 0.002},  # 5ms
            ExecutionQuality.LOW_LATENCY: {"mean": 0.05, "std": 0.02},  # 50ms
            ExecutionQuality.STANDARD: {"mean": 0.15, "std": 0.05},  # 150ms
            ExecutionQuality.RETAIL: {"mean": 0.5, "std": 0.2},  # 500ms
        }
        return models.get(self.execution_quality, models[ExecutionQuality.STANDARD])

    def _get_position_price(self, symbol: str, tick: "TickData", position: "Position") -> float:
        """Return the best available current price for a position."""
        if symbol == tick.symbol:
            return tick.mid
        history = self.price_history.get(symbol)
        return history[-1] if history else position.avg_entry_price

    def _annual_financing_rate(self, position: "Position") -> float:
        """
        Return the annual overnight financing rate for a position side.

        Used only when cost_model.use_swap_model=False (legacy path).
        """
        is_long = position.side.name == "BUY" if hasattr(position.side, "name") else str(position.side) == "BUY"
        default_annual = getattr(self.cost_model, "overnight_rate_annual", 0.00749)
        if is_long:
            return getattr(self.cost_model, "overnight_rate_long_annual", default_annual)
        return getattr(self.cost_model, "overnight_rate_short_annual", -default_annual * 0.147)

    def _charge_overnight_financing(self, tick: "TickData", bars_per_day: float) -> float:
        """
        Charge overnight financing on all open positions for one bar.

        When cost_model.use_swap_model=True (default), uses OvernightSwapModel
        (USD per standard lot per night) with Wednesday triple-swap applied
        from tick.timestamp.weekday().

        When use_swap_model=False, falls back to the legacy annual-rate model
        (notional × annual_rate / 365 / bars_per_day).

        Returns the total financing cost charged this bar (positive = cost paid).
        """
        from backtesting.transaction_costs import get_swap_model

        use_swap = getattr(self.cost_model, "use_swap_model", True)
        swap_model = get_swap_model() if use_swap else None

        # Extract weekday for Wednesday triple-swap
        weekday: int | None = None
        if use_swap and tick.timestamp is not None:
            with contextlib.suppress(Exception):  # nosec B110 — non-fatal; fall back to no triple-swap
                weekday = int(tick.timestamp.weekday())

        total_financing = 0.0
        for symbol, position in self.positions.items():
            if position.size == 0:
                continue
            current_price = self._get_position_price(symbol, tick, position)
            is_long = position.side.name == "BUY" if hasattr(position.side, "name") else str(position.side) == "BUY"
            side = "long" if is_long else "short"

            if use_swap and swap_model is not None:
                # OvernightSwapModel: USD per standard lot per night.
                # Distribute evenly across bars_per_day so total per calendar
                # day equals exactly one nightly charge.
                lots = abs(position.size) / 100.0  # 100 oz per standard lot
                financing_cost = abs(
                    swap_model.cost_usd_per_night(
                        symbol or "XAUUSD",
                        lots=lots,
                        side=side,
                        weekday=weekday,
                    )
                ) / max(bars_per_day, 1.0)
            else:
                # Legacy: annualised rate on notional
                notional = abs(position.size) * current_price
                annual_rate = self._annual_financing_rate(position)
                financing_cost = notional * annual_rate / 365.0 / max(bars_per_day, 1.0)

            if financing_cost != 0.0:
                self.capital -= financing_cost
                position.total_financing_paid += financing_cost
                total_financing += financing_cost

            position.update_mfe_mae(current_price, tick.timestamp)
        return total_financing

    def process_tick(self, tick: TickData) -> dict[str, Any]:
        """
        Process a single tick with full market microstructure analysis.

        Overnight financing is charged every tick on open position notional.
        The per-tick rate is derived from the annual rate in TransactionCostModel
        scaled by the estimated number of ticks per year (252 trading days ×
        ticks_per_day, where ticks_per_day defaults to 1 for daily bars and is
        set by the caller via self._ticks_per_day).
        """
        self.current_time = tick.timestamp

        # Update microstructure
        self.microstructure.add_tick(tick)

        # Update price history
        self.price_history[tick.symbol].append(tick.mid)

        # ── Overnight financing ───────────────────────────────────────────────
        bars_per_day: float = getattr(self, "_bars_per_day", 1.0)
        financing_paid_this_tick = self._charge_overnight_financing(tick, bars_per_day)

        # Calculate equity
        equity = self._calculate_equity(tick)
        self.equity_curve.append((tick.timestamp, equity))

        # Update risk manager
        self.risk_manager.current_capital = equity

        # Check intraday risk
        can_trade, risk_msg = self.risk_manager.check_intraday_risk(tick.timestamp)

        # Get execution recommendation
        exec_rec = self.microstructure.get_execution_recommendation()

        return {
            "equity": equity,
            "can_trade": can_trade,
            "risk_status": risk_msg,
            "regime": exec_rec["regime"],
            "regime_confidence": exec_rec["confidence"],
            "toxicity": exec_rec["toxicity"],
            "execution_recommendation": exec_rec,
            "financing_paid": financing_paid_this_tick,
        }

    def _calculate_equity(self, mark_tick: TickData) -> float:
        """Calculate total equity with mark-to-market"""
        equity = self.capital

        for symbol, position in self.positions.items():
            # Get current price for this symbol
            if symbol == mark_tick.symbol:
                current_price = mark_tick.mid
            else:
                # Use last known price
                history = self.price_history.get(symbol, deque())
                current_price = history[-1] if history else position.avg_entry_price

            # Mark to market
            if position.side == OrderSide.BUY:
                mark_price = mark_tick.bid if symbol == mark_tick.symbol else current_price
            else:
                mark_price = mark_tick.ask if symbol == mark_tick.symbol else current_price

            position.update_mfe_mae(mark_price, self.current_time or NanosecondTimestamp.now())
            equity += position.unrealized_pnl

        return equity

    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        order_type: str = "market",
        limit_price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "GTC",
        strategy_id: str | None = None,
    ) -> tuple[bool, str, str | None]:
        """
        Submit order with full pre-trade risk checks.
        """
        # Get current price
        history = self.price_history.get(symbol, deque())
        if not history:
            return False, "NO_PRICE_DATA", None

        current_price = history[-1]

        # Pre-trade risk check
        allowed, reason, _ = self.risk_manager.check_pre_trade_risk(symbol, side, size, current_price, {})

        if not allowed:
            return False, reason, None

        # Generate order ID
        order_id = f"ORD{self.trade_count:06d}_{int(float(self.current_time or NanosecondTimestamp.now()) * 1e6)}"
        self.trade_count += 1

        # Store order
        self.open_orders[order_id] = {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "tif": time_in_force,
            "strategy_id": strategy_id,
            "submitted_at": self.current_time,
            "status": "working",
        }

        return True, "OK", order_id

    def _resolve_market_fill(self, order: dict, tick: "TickData", size: float) -> tuple[float, float, float]:
        """
        Compute fill price, slippage, and latency for a market order.

        Returns (fill_price, slippage_bps, latency_sec).
        """
        is_buy = order["side"] == OrderSide.BUY
        base_price = tick.ask if is_buy else tick.bid
        volatility = (
            self.microstructure.realized_variance**0.5
            if self.microstructure.realized_variance > 0
            else _ATR_FALLBACK_VOL
        )
        participation = abs(size) / max(tick.volume, _MIN_VOLUME_FLOOR)
        impact = self.cost_model.calculate_market_impact(
            abs(size),
            participation,
            volatility,
            self.microstructure.order_flow_toxicity,
        )
        slippage_bps = impact["temporary_bps"] + _ENGINE_RNG.normal(0, impact["temporary_bps"] * _SLIPPAGE_NOISE_FRAC)
        sign = 1 if is_buy else -1
        fill_price = base_price * (1 + sign * slippage_bps / 10_000)
        latency = _ENGINE_RNG.normal(self.latency_model["mean"], self.latency_model["std"])
        return fill_price, slippage_bps, latency

    def _resolve_limit_fill(self, order: dict, tick: "TickData") -> tuple[float, float, float]:
        """
        Validate and return fill parameters for a limit order.

        Returns (fill_price, slippage_bps=0, latency_sec).
        Raises ValueError when the limit is not yet marketable.
        """
        is_buy = order["side"] == OrderSide.BUY
        lp = order["limit_price"]
        if is_buy and lp < tick.ask:
            raise ValueError("Limit below ask")
        if not is_buy and lp > tick.bid:
            raise ValueError("Limit above bid")
        return lp, 0.0, _LIMIT_FILL_LATENCY_SEC

    def _apply_fill_to_position(
        self,
        order: dict,
        position: "Position",
        size: float,
        fill_price: float,
        costs: dict,
        tick: "TickData",
        order_id: str,
    ) -> None:
        """
        Update position state after a fill — handles open, add, and close paths.
        """
        is_closing = position.size * size < 0

        if is_closing:
            trade = self._close_position(
                position,
                size,
                fill_price,
                tick.timestamp,
                costs.get("slippage_bps", 0.0),
                costs["total_cost"],
                order["side"],
                order_id,
            )
            if trade:
                self.closed_trades.append(trade)
                self.risk_manager.trade_history.append(trade)
                self.capital += trade.net_pnl
                self.risk_manager.update_capital(trade.net_pnl, tick.timestamp)

        remaining = size
        if is_closing and abs(size) > abs(position.size):
            remaining = size + position.size

        if remaining == 0:
            return

        if position.size == 0:
            position.side = order["side"]
            position.avg_entry_price = fill_price
            position.entry_timestamp = tick.timestamp
            position.size = remaining
        else:
            total_size = position.size + remaining
            position.avg_entry_price = (position.size * position.avg_entry_price + remaining * fill_price) / total_size
            position.size = total_size

        position.total_commission_paid += costs["commission"]
        position.total_slippage_paid += costs["market_impact"]
        position.add_trade(
            trade_size=remaining,
            trade_price=fill_price,
            commission=costs["commission"],
            slippage=costs["market_impact"],
            timestamp=tick.timestamp,
            is_opening=True,
        )

    def _update_order_status(self, order_id: str, order: dict, size: float) -> None:
        """Mark order filled or reduce remaining size."""
        order["filled_size"] = order.get("filled_size", 0) + size
        if abs(order["filled_size"] - order["size"]) < _FILL_TOLERANCE:
            order["status"] = "filled"
            del self.open_orders[order_id]
        else:
            order["size"] -= size

    def execute_order(
        self, order_id: str, tick: "TickData", fill_size: float | None = None
    ) -> tuple[bool, dict[str, Any]]:
        """Execute an order with realistic market simulation."""
        if order_id not in self.open_orders:
            return False, {"error": "Order not found"}

        order = self.open_orders[order_id]
        size = fill_size or order["size"]
        if abs(size) > abs(order["size"]):
            size = order["size"] if order["size"] > 0 else -abs(order["size"])

        # ── Resolve fill price ─────────────────────────────────────────────
        try:
            if order["type"] == "market":
                fill_price, slippage_bps, latency = self._resolve_market_fill(order, tick, size)
                volatility = (
                    self.microstructure.realized_variance**0.5
                    if self.microstructure.realized_variance > 0
                    else _ATR_FALLBACK_VOL
                )
                participation = abs(size) / max(tick.volume, _MIN_VOLUME_FLOOR)
            elif order["type"] == "limit" and order.get("limit_price"):
                fill_price, slippage_bps, latency = self._resolve_limit_fill(order, tick)
                volatility = _ATR_FALLBACK_VOL
                participation = 0.0
            else:
                return False, {"error": "Invalid order type"}
        except ValueError as exc:
            logger.warning("Order fill resolution failed: %s", exc)
            return False, {"error": "Invalid order parameters", "status": "pending"}

        # ── Calculate transaction costs ────────────────────────────────────
        costs = self.cost_model.total_cost(
            size,
            fill_price,
            participation_rate=participation,
            daily_volatility=volatility,
            order_flow_toxicity=self.microstructure.order_flow_toxicity,
        )
        costs["slippage_bps"] = slippage_bps

        # ── Ensure position exists ─────────────────────────────────────────
        if order["symbol"] not in self.positions:
            self.positions[order["symbol"]] = Position(
                symbol=order["symbol"],
                side=order["side"],
                size=0.0,
                avg_entry_price=0.0,
            )
        position = self.positions[order["symbol"]]

        self._apply_fill_to_position(order, position, size, fill_price, costs, tick, order_id)
        self._update_order_status(order_id, order, size)

        self.execution_log.append(
            {
                "timestamp": float(tick.timestamp),
                "order_id": order_id,
                "symbol": order["symbol"],
                "side": order["side"].name if isinstance(order["side"], OrderSide) else order["side"],
                "size": size,
                "price": fill_price,
                "slippage_bps": slippage_bps,
                "costs": costs,
                "latency_sec": latency,
                "regime": self.microstructure.current_regime.name,
            }
        )

        return True, {
            "filled": True,
            "fill_price": fill_price,
            "fill_size": size,
            "slippage_bps": slippage_bps,
            "costs": costs,
            "position_size": position.size,
            "unrealized_pnl": position.unrealized_pnl,
            "latency_ms": latency * 1000,
        }

    def _close_position(
        self,
        position: Position,
        closing_size: float,
        exit_price: float,
        timestamp: NanosecondTimestamp,
        slippage_bps: float,
        total_cost: float,
        side: OrderSide,
        parent_order_id: str,
    ) -> TradeRecord | None:
        """Close position and create trade record"""
        if position.size == 0:
            return None

        # Calculate actual close size
        close_size = min(abs(closing_size), abs(position.size))
        is_full_close = close_size >= abs(position.size) - 0.0001

        # Calculate P&L
        if position.side == OrderSide.BUY:
            gross_pnl = (exit_price - position.avg_entry_price) * close_size
        else:
            gross_pnl = (position.avg_entry_price - exit_price) * close_size

        # Proportional costs
        close_ratio = close_size / abs(position.size)
        prop_commission = position.total_commission_paid * close_ratio
        prop_slippage = position.total_slippage_paid * close_ratio

        net_pnl = gross_pnl - prop_slippage - prop_commission - total_cost

        # Create trade record
        trade = TradeRecord(
            trade_id=f"T{len(self.closed_trades):06d}",
            parent_order_id=parent_order_id,
            entry_time=position.entry_timestamp or timestamp,
            exit_time=timestamp,
            symbol=position.symbol,
            side=position.side,
            entry_price=position.avg_entry_price,
            exit_price=exit_price,
            size=close_size,
            filled_size=close_size,
            entry_slippage_bps=0,  # Would track from entry fills
            exit_slippage_bps=slippage_bps,
            entry_commission=prop_commission,
            exit_commission=total_cost * 0.3,  # Assume 30% is commission
            entry_regime=self.microstructure.current_regime,
            exit_regime=self.microstructure.current_regime,
            entry_volatility=self.microstructure.realized_variance**0.5,
            exit_volatility=self.microstructure.realized_variance**0.5,
            entry_spread_bps=0,
            exit_spread_bps=(exit_price - position.avg_entry_price) / position.avg_entry_price * 10000
            if position.avg_entry_price
            else 0,
            mfe=position.max_favorable_excursion,
            mae=position.max_adverse_excursion,
            mfe_pct=position.max_favorable_excursion / (abs(position.size) * position.avg_entry_price) * 100
            if position.avg_entry_price and position.size
            else 0,
            mae_pct=position.max_adverse_excursion / (abs(position.size) * position.avg_entry_price) * 100
            if position.avg_entry_price and position.size
            else 0,
        )

        # Update position
        position.realized_pnl += net_pnl
        position.size = position.size + (closing_size if position.size > 0 else -closing_size)

        if is_full_close or abs(position.size) < 0.0001:
            # Archive position
            position.closing_trades.append({"trade_id": trade.trade_id, "exit_price": exit_price, "pnl": net_pnl})

        return trade

    def get_performance_report(self) -> dict[str, Any]:
        """Generate comprehensive institutional-grade performance report."""
        if not self.closed_trades:
            return {"error": "No completed trades"}

        trades = self.closed_trades
        pnls = [t.net_pnl for t in trades]
        returns = [t.return_pct for t in trades]
        equity_values = [e[1] for e in self.equity_curve]
        equity_returns = np.diff(equity_values) / equity_values[:-1] if len(equity_values) > 1 else np.array([])
        max_dd, dd_periods = _compute_drawdown_series(self.equity_curve, self.initial_capital)

        return {
            "metadata": _build_report_metadata(self),
            "trade_statistics": _build_trade_statistics(trades, pnls),
            "time_analysis": _build_time_analysis(trades),
            "risk_metrics": _build_risk_metrics(
                returns, equity_returns, max_dd, dd_periods, self.capital, self.risk_manager
            ),
            "execution_quality": _build_execution_quality(
                self.execution_log, self.positions, self.initial_capital, self.cost_model
            ),
            "regime_performance": self._analyze_regime_performance(),
            "mfe_mae_analysis": _build_mfe_mae_analysis(trades),
            "risk_manager_report": self.risk_manager.get_risk_report(),
            "monthly_returns": self._calculate_monthly_returns(),
            "equity_curve_sample": [{"timestamp": float(ts), "equity": eq} for ts, eq in self.equity_curve[-100:]],
        }

    def _analyze_regime_performance(self) -> dict[str, dict]:
        """Aggregate trade P&L and win-rate by entry market regime."""
        regime_stats: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        for trade in self.closed_trades:
            regime = trade.entry_regime.name
            regime_stats[regime]["trades"] += 1
            regime_stats[regime]["pnl"] += trade.net_pnl
            if trade.net_pnl > 0:
                regime_stats[regime]["wins"] += 1
            else:
                regime_stats[regime]["losses"] += 1

        return {
            regime: {
                "total_trades": s["trades"],
                "total_pnl": s["pnl"],
                "win_rate": s["wins"] / s["trades"] if s["trades"] > 0 else 0,
                "avg_pnl": s["pnl"] / s["trades"] if s["trades"] > 0 else 0,
            }
            for regime, s in regime_stats.items()
        }

    def _calculate_monthly_returns(self) -> dict[str, float]:
        """Compute month-over-month equity returns from the equity curve."""
        if not self.equity_curve:
            return {}
        monthly_equity: dict[str, float] = {}
        for ts, eq in self.equity_curve:
            dt = ts.to_datetime() if hasattr(ts, "to_datetime") else datetime.fromtimestamp(float(ts))
            monthly_equity[dt.strftime("%Y-%m")] = eq  # last equity value wins per month

        months = sorted(monthly_equity)
        return {
            month: (monthly_equity[month] - monthly_equity[months[i - 1]]) / monthly_equity[months[i - 1]]
            if monthly_equity[months[i - 1]] > 0
            else 0.0
            for i, month in enumerate(months[1:], 1)
        }

    def save_state(self, filepath: str, compress: bool = True):
        """Save complete engine state to disk"""
        state = {
            "metadata": {
                "saved_at": datetime.now(UTC).isoformat(),
                "version": "4.0",
                "initial_capital": self.initial_capital,
            },
            "capital": self.capital,
            "positions": {
                symbol: {
                    "symbol": pos.symbol,
                    "side": pos.side.name if isinstance(pos.side, OrderSide) else pos.side,
                    "size": pos.size,
                    "avg_entry": pos.avg_entry_price,
                    "realized_pnl": pos.realized_pnl,
                    "mfe": pos.max_favorable_excursion,
                    "mae": pos.max_adverse_excursion,
                }
                for symbol, pos in self.positions.items()
            },
            "closed_trades": [t.to_dict() for t in self.closed_trades],
            "equity_curve": [{"timestamp": float(ts), "equity": eq} for ts, eq in self.equity_curve],
            "risk_manager_state": self.risk_manager.get_risk_report(),
            "execution_log": self.execution_log[-1000:],  # Last 1000 executions
        }

        if compress:
            with gzip.open(filepath, "wt") as f:
                json.dump(state, f, default=str, indent=2)
        else:
            with Path(filepath).open("w", encoding="utf-8") as f:
                json.dump(state, f, default=str, indent=2)

        logger.info("State saved to %s (%s)", filepath, "compressed" if compress else "raw")

    def load_state(self, filepath: str):
        """Load engine state from disk"""
        opener = gzip.open if filepath.endswith(".gz") else open

        with opener(filepath, "rt") as f:
            state = json.load(f)

        self.initial_capital = state["metadata"]["initial_capital"]
        self.capital = state["capital"]

        # Restore positions
        self.positions = {}
        for symbol, pos_data in state.get("positions", {}).items():
            pos = Position(
                symbol=pos_data["symbol"],
                side=OrderSide.BUY if pos_data["side"] == "BUY" else OrderSide.SELL,
                size=pos_data["size"],
                avg_entry_price=pos_data["avg_entry"],
                realized_pnl=pos_data["realized_pnl"],
                max_favorable_excursion=pos_data.get("mfe", 0),
                max_adverse_excursion=pos_data.get("mae", 0),
            )
            self.positions[symbol] = pos

        logger.info("State loaded from %s", filepath)

        return state


# =============================================================================
# EXAMPLE USAGE & COMPREHENSIVE TESTING
# =============================================================================


def generate_test_data(n_ticks: int = 10000, symbol: str = "XAUUSD") -> list[TickData]:
    """
    Generate SYNTHETIC tick data for unit tests and engine smoke-tests ONLY.

    WARNING — this data is NOT suitable for strategy validation or performance
    reporting.  Specifically:
      - Price path is a simple GBM with fixed seed — no fat tails, no regime
        shifts, no liquidity gaps, no news events.
      - The "GARCH-like" volatility clustering is a single-line approximation
        that bears no resemblance to actual GARCH(1,1).
      - Spread is uniform random — not microstructure-realistic.
      - There are no overnight gaps, halts, or extreme events.

    For real backtesting use real_data_backtest.py with actual XAUUSD tick data
    from a vendor (e.g. Dukascopy, Tick Data Suite, OANDA history API).
    """
    import os as _os

    if _os.getenv("APP_ENV", "production").lower() == "production":
        raise RuntimeError(
            "generate_test_data() cannot be called in production (APP_ENV=production). "
            "Use real_data_backtest.py with actual XAUUSD tick data."
        )
    warnings.warn(
        "generate_test_data() produces SYNTHETIC GBM data. "
        "Do not use for strategy validation or performance reporting. "
        "Use real_data_backtest.py with actual tick data instead.",
        UserWarning,
        stacklevel=2,
    )

    rng = np.random.default_rng(42)

    base_price = 1950.0
    volatility = 0.0002

    # Simple GBM with a single-step volatility-clustering approximation.
    # This is NOT a real GARCH model — it is only here to produce non-i.i.d.
    # looking data for engine smoke-tests.
    returns = rng.normal(0, volatility, n_ticks)
    for i in range(1, n_ticks):
        returns[i] *= 1 + abs(returns[i - 1]) * 5

    cum_returns = np.cumsum(np.nan_to_num(returns, nan=0.0))
    cum_returns = np.clip(cum_returns, -50, 50)  # prevent overflow in exp
    prices = base_price * np.exp(cum_returns)

    # Uniform random spread — not microstructure-realistic
    spreads = rng.uniform(0.02, 0.08, n_ticks)  # 2-8 pips for gold

    ticks = []
    start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

    for i in range(n_ticks):
        price = prices[i]
        spread = spreads[i]

        tick = TickData(
            timestamp=NanosecondTimestamp.from_datetime(
                start_time + timedelta(milliseconds=i * 100)  # 10 ticks/second
            ),
            symbol=symbol,
            bid=price - spread / 2,
            ask=price + spread / 2,
            bid_size=rng.exponential(10.0),
            ask_size=rng.exponential(10.0),
            volume=int(rng.poisson(100)),
            source="synthetic",
        )
        ticks.append(tick)

    return ticks


def _load_real_ticks(symbol: str = "XAUUSD", max_bars: int = 5000) -> list["TickData"] | None:
    """
    Attempt to load real OHLCV data via real_data_backtest.py and convert to
    TickData objects for use by the backtest engine.

    Returns None if real data is unavailable (ccxt not installed, network
    error, or fewer than 100 bars returned).
    """
    try:
        import importlib

        rdb = importlib.import_module("real_data_backtest")
        import ccxt as _ccxt

        exchange = _ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        since_ms = exchange.parse8601("2022-01-01T00:00:00Z")
        df = rdb.fetch_ohlcv_paginated(exchange, "XAU/USDT", "1h", since_ms=since_ms, max_bars=max_bars)
        if df is None or len(df) < 100:
            return None

        ticks: list[TickData] = []
        for ts, row in df.iterrows():
            mid = float(row["close"])
            spread = mid * 0.00005  # ~0.5 pip spread for gold
            ticks.append(
                TickData(
                    timestamp=NanosecondTimestamp.from_datetime(ts),
                    symbol=symbol,
                    bid=mid - spread / 2,
                    ask=mid + spread / 2,
                    bid_size=100.0,
                    ask_size=100.0,
                    volume=float(row.get("volume", 0)),
                    source="real/binance",
                )
            )
        return ticks
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        logger.warning("Could not load real tick data: %s", exc)
        return None


def run_comprehensive_backtest(use_real_data: bool = True):
    """
    Run full backtest with all engine features.

    Args:
        use_real_data: When True (default), fetch real XAUUSD 1h bars from
                       Binance via real_data_backtest.py.  Raises RuntimeError
                       if real data is unavailable in APP_ENV=production.
                       Pass False only in APP_ENV=development/test (smoke-test).

    WARNING: Results on synthetic data are NOT valid for strategy evaluation.
    The synthetic GBM path exists only for engine smoke-tests in non-production.
    """
    import os as _os

    _app_env = _os.getenv("APP_ENV", "production").lower()
    _is_production = _app_env == "production"

    logger.info("=" * 80)
    logger.info("HOPEFX ENHANCED BACKTEST ENGINE v4.0 - COMPREHENSIVE TEST")
    logger.info("=" * 80)

    # ── Data loading ──────────────────────────────────────────────────────────
    ticks: list[TickData] | None = None
    data_source = "real/binance"

    if use_real_data:
        logger.info("\n[1] Attempting to load real XAUUSD data via real_data_backtest.py ...")
        ticks = _load_real_ticks(max_bars=5000)
        if ticks:
            logger.info(f"    Loaded {len(ticks)} real ticks")
            logger.info(f"    Time range: {ticks[0].timestamp.to_datetime()} to {ticks[-1].timestamp.to_datetime()}")
        else:
            if _is_production:
                raise RuntimeError(
                    "run_comprehensive_backtest(): real XAUUSD data unavailable. "
                    "Install ccxt and ensure network access to Binance. "
                    "Do not use synthetic data for production backtests."
                )
            logger.info("    Real data unavailable — falling back to SYNTHETIC data (non-production only).")
            logger.warning("    *** WARNING: Results are NOT valid for strategy evaluation. ***")

    if ticks is None:
        if _is_production:
            raise RuntimeError(
                "run_comprehensive_backtest(): cannot use synthetic data in production "
                "(APP_ENV=production). Provide real XAUUSD tick data."
            )
        logger.info("\n[1] Generating SYNTHETIC tick data (smoke-test only)...")
        warnings.warn(
            "run_comprehensive_backtest() is using SYNTHETIC GBM data. "
            "Results are not valid for strategy evaluation. "
            "Pass use_real_data=True (default) and ensure ccxt is installed "
            "to use real XAUUSD data.",
            UserWarning,
            stacklevel=2,
        )
        data_source = "synthetic"
        ticks = generate_test_data(n_ticks=5000)
        logger.info(f"    Generated {len(ticks)} synthetic ticks")
        logger.info(f"    Time range: {ticks[0].timestamp.to_datetime()} to {ticks[-1].timestamp.to_datetime()}")

    logger.info(f"    Data source: {data_source}")

    # Initialize engine with XAUUSD-calibrated institutional settings.
    # Parameters are derived from Almgren-Chriss (2001) adjusted for gold
    # market microstructure (see TransactionCostModel.calibrate_xauusd()).
    # The old equity defaults (η=0.142, γ=0.314, spread=0.8 bps) overstated
    # costs by ~3× for XAUUSD — replaced with gold-specific calibration.
    logger.info("\n[2] Initializing backtest engine...")
    cost_model = TransactionCostModel.calibrate_xauusd()

    risk_manager = InstitutionalRiskManager(
        initial_capital=1_000_000.0,
        max_position_pct=0.05,
        max_daily_loss_pct=0.02,
        max_drawdown_pct=0.10,
        kelly_fraction=0.3,
    )

    engine = EnhancedBacktestEngine(
        initial_capital=1_000_000.0,
        cost_model=cost_model,
        risk_manager=risk_manager,
        execution_quality=ExecutionQuality.LOW_LATENCY,
    )

    # Define strategy: Adaptive MA Crossover with Regime Filter
    class AdaptiveMACrossover:
        def __init__(self, fast=10, slow=30):
            self.fast = fast
            self.slow = slow
            self.prices = deque(maxlen=slow + 10)

        def generate_signal(self, tick: TickData, regime: MarketRegime) -> tuple[OrderSide, float] | None:
            self.prices.append(tick.mid)

            if len(self.prices) < self.slow:
                return None

            fast_ma = np.mean(list(self.prices)[-self.fast :])
            slow_ma = np.mean(self.prices)

            # Regime filter: only trade in trending or ranging (not high vol)
            if regime in [
                MarketRegime.HIGH_VOLATILITY_BREAKOUT,
                MarketRegime.NEWS_EVENT,
            ]:
                return None

            threshold = 0.0002  # 2 pips

            if fast_ma > slow_ma * (1 + threshold):
                return (OrderSide.BUY, 0.8)  # 80% confidence
            if fast_ma < slow_ma * (1 - threshold):
                return (OrderSide.SELL, 0.8)

            return None

    strategy = AdaptiveMACrossover(fast=20, slow=50)

    # Run backtest
    logger.info("\n[3] Running backtest...")
    position = 0.0
    position_size = 10.0  # Standard lots

    for i, tick in enumerate(ticks[100:], 100):  # Skip first 100 for indicators
        # Process tick
        result = engine.process_tick(tick)

        # Generate signal
        signal = strategy.generate_signal(tick, result["regime"])

        if signal and result["can_trade"]:
            side, confidence = signal

            # Risk-based position sizing
            if confidence > 0.7:
                size = position_size * confidence

                # Check if we need to reverse
                if (side == OrderSide.BUY and position < 0) or (side == OrderSide.SELL and position > 0):
                    # Close existing position
                    close_side = OrderSide.SELL if position > 0 else OrderSide.BUY
                    success, order_id = engine.submit_order(
                        "XAUUSD",
                        close_side,
                        abs(position),
                        "market",
                        strategy_id="ma_crossover",
                    )
                    if success:
                        engine.execute_order(order_id, tick)
                    position = 0

                # Open new position
                if position == 0:
                    success, order_id = engine.submit_order("XAUUSD", side, size, "market", strategy_id="ma_crossover")
                    if success:
                        fill_result = engine.execute_order(order_id, tick)
                        if fill_result[0]:
                            position = size if side == OrderSide.BUY else -size

        # Progress update
        if i % 1000 == 0:
            logger.info(f"    Processed {i}/{len(ticks)} ticks | Equity: ${engine.capital:,.2f}")

    # Generate report
    logger.info("\n[4] Generating performance report...")
    report = engine.get_performance_report()

    # Display results
    logger.info("\n" + "=" * 80)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 80)

    meta = report["metadata"]
    logger.info(f"\nPeriod: {meta['backtest_periods']} ticks")
    logger.info(f"Initial Capital: ${meta['initial_capital']:,.2f}")
    logger.info(f"Final Capital: ${meta['final_capital']:,.2f}")
    logger.info(f"Total Return: {meta['total_return_pct']:+.2f}%")

    stats = report["trade_statistics"]
    logger.info("\n--- Trade Statistics ---")
    logger.info(f"Total Trades: {stats['total_trades']}")
    logger.info(f"Win Rate: {stats['win_rate']:.1%}")
    logger.info(f"Profit Factor: {stats['profit_factor']:.2f}")
    logger.info(f"Payoff Ratio: {stats['payoff_ratio']:.2f}")
    logger.info(f"Total P&L: ${stats['total_pnl']:,.2f}")
    logger.info(f"Avg Trade: ${stats['avg_trade_pnl']:,.2f}")
    logger.info(f"Largest Win: ${stats['largest_win']:,.2f}")
    logger.info(f"Largest Loss: ${stats['largest_loss']:,.2f}")

    risk = report["risk_metrics"]
    logger.info("\n--- Risk Metrics ---")
    logger.info(f"Max Drawdown: {risk['max_drawdown_pct']:.2f}%")
    logger.info(f"Sharpe Ratio: {risk['sharpe_ratio']:.2f}")
    logger.info(f"Sortino Ratio: {risk['sortino_ratio']:.2f}")
    logger.info(f"Calmar Ratio: {risk['calmar_ratio']:.2f}")
    logger.info(f"VaR (95%): {risk['var_95']:.4f}")
    logger.info(f"CVaR (95%): {risk['cvar_95']:.4f}")

    exec_quality = report["execution_quality"]
    logger.info("\n--- Execution Quality ---")
    logger.info(f"Avg Slippage: {exec_quality['avg_slippage_bps']:.2f} bps")
    logger.info(f"Avg Latency: {exec_quality['avg_latency_ms']:.2f} ms")
    logger.info(f"Total Commission: ${exec_quality['total_commission']:,.2f}")
    logger.info(f"Cost Drag: {exec_quality['cost_drag_pct']:.3f}%")

    # Regime performance
    logger.info("\n--- Performance by Regime ---")
    for regime, perf in report["regime_performance"].items():
        logger.info(
            f"{regime:25}: {perf['total_trades']:3d} trades | "
            f"P&L: ${perf['total_pnl']:>10,.2f} | "
            f"Win Rate: {perf['win_rate']:.1%}"
        )

    # Save state
    logger.info("\n[5] Saving state...")
    engine.save_state("backtest_state.json.gz")

    # Risk manager report
    logger.info("\n--- Risk Manager Status ---")
    risk_report = report["risk_manager_report"]
    logger.info(f"Kill Switch Active: {risk_report['risk_metrics']['kill_switch']}")
    logger.info(f"Circuit Breaker Level: {risk_report['risk_metrics']['circuit_breaker']}")
    logger.info(f"Current VaR: ${risk_report['risk_metrics']['var_95']:,.2f}")

    logger.info("\n" + "=" * 80)
    logger.info("✅ BACKTEST COMPLETED SUCCESSFULLY")
    logger.info("=" * 80)

    return engine, report


if __name__ == "__main__":
    # Attempt real data first; falls back to synthetic with a warning if
    # ccxt is not installed or the network is unavailable.
    engine, report = run_comprehensive_backtest(use_real_data=True)
