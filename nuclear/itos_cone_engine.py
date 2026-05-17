# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nuclear/itos_cone_engine.py
============================
Ito's Lemma geometric Brownian motion price cone generator.

Produces probabilistic forward price projections (cones) from live
streaming data. All inputs come from Redis pub/sub — no broker APIs.

Theory
------
Under GBM, the log-price follows:

    d(ln S) = (μ - σ²/2) dt + σ dW

where μ is the drift (annualised mean log-return) and σ is the
annualised volatility. The forward price distribution at horizon T is:

    S(T) = S(0) · exp[(μ - σ²/2)T + σ√T · Z],  Z ~ N(0,1)

Cone bands at ±nσ:
    upper_n = S(0) · exp[(μ - σ²/2)T + n·σ√T]
    lower_n = S(0) · exp[(μ - σ²/2)T - n·σ√T]

Outputs
-------
ItosCone dataclass with:
  - centre path (drift only, no diffusion)
  - ±1σ, ±2σ, ±3σ bands
  - dot projections at 1w / 1m / 3m / 6m / 1y horizons
  - annualised drift μ and volatility σ
  - confidence score based on data quality and sample size

Usage
-----
    from nuclear.itos_cone_engine import ItosConeEngine

    engine = ItosConeEngine()
    cone = engine.compute(closes, current_price, symbol="XAU_USD")
    logger.info(cone.upper_2sigma_1m, cone.lower_2sigma_1m)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Trading-day constants ─────────────────────────────────────────────────────
_TRADING_DAYS_PER_YEAR = 252
_TRADING_HOURS_PER_DAY = 24  # gold trades ~24h
_MINUTES_PER_YEAR = _TRADING_DAYS_PER_YEAR * _TRADING_HOURS_PER_DAY * 60

# Horizon fractions of a year (annualised)
_HORIZONS: dict[str, float] = {
    "1d": 1.0 / _TRADING_DAYS_PER_YEAR,
    "1w": 5.0 / _TRADING_DAYS_PER_YEAR,
    "2w": 10.0 / _TRADING_DAYS_PER_YEAR,
    "1m": 21.0 / _TRADING_DAYS_PER_YEAR,
    "3m": 63.0 / _TRADING_DAYS_PER_YEAR,
    "6m": 126.0 / _TRADING_DAYS_PER_YEAR,
    "1y": 1.0,
}

# Sigma bands to compute
_SIGMA_BANDS = [1.0, 1.5, 2.0, 2.5, 3.0]

# Minimum bars required for a reliable estimate
_MIN_BARS_RELIABLE = 30
_MIN_BARS_MINIMUM = 10


@dataclass
class ConeDot:
    """Single projected price point at a given horizon."""

    horizon: str  # "1w", "1m", etc.
    horizon_years: float  # fractional year
    centre: float  # drift-only projection
    upper_1sigma: float
    lower_1sigma: float
    upper_2sigma: float
    lower_2sigma: float
    upper_3sigma: float
    lower_3sigma: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "horizon_years": round(self.horizon_years, 6),
            "centre": round(self.centre, 4),
            "upper_1sigma": round(self.upper_1sigma, 4),
            "lower_1sigma": round(self.lower_1sigma, 4),
            "upper_2sigma": round(self.upper_2sigma, 4),
            "lower_2sigma": round(self.lower_2sigma, 4),
            "upper_3sigma": round(self.upper_3sigma, 4),
            "lower_3sigma": round(self.lower_3sigma, 4),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ItosCone:
    """
    Full probabilistic price cone from Ito's Lemma GBM.

    All prices in the same unit as the input (e.g. USD/oz for gold).
    """

    symbol: str
    current_price: float
    drift_annual: float  # μ annualised log-return
    volatility_annual: float  # σ annualised volatility
    sample_size: int  # number of returns used
    timeframe: str  # bar timeframe of input data
    confidence: float  # 0–1 quality score
    dots: dict[str, ConeDot]  # horizon → ConeDot
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Convenience accessors for the most-used horizons
    @property
    def upper_2sigma_1w(self) -> float:
        return self.dots["1w"].upper_2sigma if "1w" in self.dots else self.current_price

    @property
    def lower_2sigma_1w(self) -> float:
        return self.dots["1w"].lower_2sigma if "1w" in self.dots else self.current_price

    @property
    def upper_2sigma_1m(self) -> float:
        return self.dots["1m"].upper_2sigma if "1m" in self.dots else self.current_price

    @property
    def lower_2sigma_1m(self) -> float:
        return self.dots["1m"].lower_2sigma if "1m" in self.dots else self.current_price

    @property
    def upper_2sigma_1y(self) -> float:
        return self.dots["1y"].upper_2sigma if "1y" in self.dots else self.current_price

    @property
    def lower_2sigma_1y(self) -> float:
        return self.dots["1y"].lower_2sigma if "1y" in self.dots else self.current_price

    @property
    def bias(self) -> str:
        """Directional bias from drift: 'bullish', 'bearish', or 'neutral'."""
        if self.drift_annual > 0.02:
            return "bullish"
        if self.drift_annual < -0.02:
            return "bearish"
        return "neutral"

    @property
    def vol_regime(self) -> str:
        """Volatility regime label."""
        if self.volatility_annual > 0.25:
            return "high_vol"
        if self.volatility_annual < 0.08:
            return "low_vol"
        return "normal_vol"

    def price_in_cone(self, price: float, horizon: str = "1m", sigma: float = 2.0) -> bool:
        """Return True if price falls within ±sigma band at horizon."""
        dot = self.dots.get(horizon)
        if dot is None:
            return True
        if sigma <= 1.0:
            return dot.lower_1sigma <= price <= dot.upper_1sigma
        if sigma <= 2.0:
            return dot.lower_2sigma <= price <= dot.upper_2sigma
        return dot.lower_3sigma <= price <= dot.upper_3sigma

    def cone_direction_at(self, horizon: str = "1m") -> str:
        """
        Return 'long', 'short', or 'neutral' based on cone centre vs current price.
        Used by strategy engine to align trades with probabilistic drift.
        """
        dot = self.dots.get(horizon)
        if dot is None:
            return "neutral"
        pct = (dot.centre - self.current_price) / (self.current_price + 1e-9)
        if pct > 0.005:
            return "long"
        if pct < -0.005:
            return "short"
        return "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "current_price": round(self.current_price, 4),
            "drift_annual": round(self.drift_annual, 6),
            "volatility_annual": round(self.volatility_annual, 6),
            "volatility_pct": round(self.volatility_annual * 100, 2),
            "sample_size": self.sample_size,
            "timeframe": self.timeframe,
            "confidence": round(self.confidence, 3),
            "bias": self.bias,
            "vol_regime": self.vol_regime,
            "dots": {h: d.to_dict() for h, d in self.dots.items()},
            "computed_at": self.computed_at.isoformat(),
        }


class ItosConeEngine:
    """
    Computes Ito's Lemma GBM price cones from streaming close prices.

    Inputs come exclusively from Redis OHLCV channels via RedisStreamReader.
    No external API calls are made here.

    Parameters
    ----------
    annualise_factor : float
        Multiplier to convert per-bar variance to annual variance.
        Computed automatically from timeframe when not provided.
    ewm_span : int
        Exponential weighting span for drift/vol estimation.
        Longer span = more stable but slower to adapt.
    """

    def __init__(
        self,
        ewm_span: int = 60,
        min_bars: int = _MIN_BARS_MINIMUM,
    ) -> None:
        self._ewm_span = ewm_span
        self._min_bars = min_bars

    # ── Public API ────────────────────────────────────────────────────────────

    def compute(
        self,
        closes: np.ndarray | list[float],
        current_price: float | None = None,
        symbol: str = "XAU_USD",
        timeframe: str = "1d",
        horizons: dict[str, float] | None = None,
    ) -> ItosCone:
        """
        Compute the full ITOS cone from an array of close prices.

        Parameters
        ----------
        closes : array-like
            Historical close prices, oldest first.
        current_price : float, optional
            Live price to anchor the cone. Defaults to closes[-1].
        symbol : str
            Instrument symbol (e.g. "XAU_USD").
        timeframe : str
            Bar timeframe of the closes array ("1m", "5m", "1h", "1d", etc.).
        horizons : dict, optional
            Override default horizon map {label: years_fraction}.

        Returns
        -------
        ItosCone
        """
        closes_arr = np.asarray(closes, dtype=float)
        closes_arr = closes_arr[np.isfinite(closes_arr) & (closes_arr > 0)]

        if len(closes_arr) < self._min_bars:
            logger.warning(
                "ItosConeEngine: only %d bars for %s/%s — cone confidence will be low",
                len(closes_arr),
                symbol,
                timeframe,
            )

        S0 = float(current_price) if current_price and current_price > 0 else float(closes_arr[-1])
        ann_factor = self._annualise_factor(timeframe)
        mu, sigma, n = self._estimate_params(closes_arr, ann_factor)
        confidence = self._confidence_score(n, sigma)
        hmap = horizons if horizons is not None else _HORIZONS

        dots: dict[str, ConeDot] = {}
        for label, T in hmap.items():
            dots[label] = self._build_dot(S0, mu, sigma, T, label)

        cone = ItosCone(
            symbol=symbol,
            current_price=S0,
            drift_annual=mu,
            volatility_annual=sigma,
            sample_size=n,
            timeframe=timeframe,
            confidence=confidence,
            dots=dots,
        )

        logger.debug(
            "ItosCone %s/%s: μ=%.4f σ=%.4f bias=%s vol=%s conf=%.2f",
            symbol,
            timeframe,
            mu,
            sigma,
            cone.bias,
            cone.vol_regime,
            confidence,
        )
        return cone

    def compute_from_ohlcv(
        self,
        bars: list[dict[str, Any]],
        symbol: str = "XAU_USD",
        timeframe: str = "1d",
        current_price: float | None = None,
    ) -> ItosCone:
        """
        Convenience wrapper: accepts list of OHLCV dicts with 'close' key.
        Bars must be sorted oldest-first.
        """
        closes = [float(b["close"]) for b in bars if b.get("close") and float(b["close"]) > 0]
        return self.compute(
            closes=closes,
            current_price=current_price,
            symbol=symbol,
            timeframe=timeframe,
        )

    def compute_multi_timeframe(
        self,
        tf_bars: dict[str, list[dict[str, Any]]],
        symbol: str = "XAU_USD",
        current_price: float | None = None,
    ) -> dict[str, ItosCone]:
        """
        Compute cones for multiple timeframes simultaneously.

        Parameters
        ----------
        tf_bars : dict
            Mapping of timeframe → list of OHLCV dicts.
            e.g. {"1d": [...], "1w": [...], "1m_bars": [...]}
        symbol : str
        current_price : float, optional

        Returns
        -------
        dict of timeframe → ItosCone
        """
        result: dict[str, ItosCone] = {}
        for tf, bars in tf_bars.items():
            if not bars:
                continue
            try:
                result[tf] = self.compute_from_ohlcv(
                    bars=bars,
                    symbol=symbol,
                    timeframe=tf,
                    current_price=current_price,
                )
            except Exception as exc:
                logger.error("ItosConeEngine multi-TF error for %s: %s", tf, exc)
        return result

    def merge_cones(
        self,
        cones: dict[str, ItosCone],
        weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """
        Merge multi-timeframe cones into a single consensus view.

        Higher-timeframe cones carry more weight for long-horizon dots.
        Returns a dict with merged bias, vol_regime, and per-horizon bands.
        """
        if not cones:
            return {}

        # Default weights: longer TF = higher weight
        tf_order = ["1m", "5m", "30m", "1h", "daily", "weekly", "monthly", "yearly"]
        if weights is None:
            weights = {}
            for i, tf in enumerate(tf_order):
                if tf in cones:
                    weights[tf] = float(i + 1)

        total_w = sum(weights.get(tf, 1.0) for tf in cones)
        if total_w == 0:
            total_w = 1.0

        # Weighted drift and vol — nan_to_num guards against cones with NaN params
        import math as _math

        mu_merged = sum(
            (c.drift_annual if _math.isfinite(c.drift_annual) else 0.0) * weights.get(tf, 1.0) / total_w
            for tf, c in cones.items()
        )
        sigma_merged = sum(
            (c.volatility_annual if _math.isfinite(c.volatility_annual) else 0.15) * weights.get(tf, 1.0) / total_w
            for tf, c in cones.items()
        )
        conf_merged = sum(c.confidence * weights.get(tf, 1.0) / total_w for tf, c in cones.items())

        # Use the highest-confidence cone's current price
        best_cone = max(cones.values(), key=lambda c: c.confidence)
        S0 = best_cone.current_price

        # Build merged dots
        merged_dots: dict[str, dict[str, Any]] = {}
        for label, T in _HORIZONS.items():
            dot = self._build_dot(S0, mu_merged, sigma_merged, T, label)
            merged_dots[label] = dot.to_dict()

        bias = "bullish" if mu_merged > 0.02 else ("bearish" if mu_merged < -0.02 else "neutral")
        vol_regime = "high_vol" if sigma_merged > 0.25 else ("low_vol" if sigma_merged < 0.08 else "normal_vol")

        return {
            "symbol": best_cone.symbol,
            "current_price": round(S0, 4),
            "drift_annual_merged": round(mu_merged, 6),
            "volatility_annual_merged": round(sigma_merged, 6),
            "confidence_merged": round(conf_merged, 3),
            "bias": bias,
            "vol_regime": vol_regime,
            "dots": merged_dots,
            "source_timeframes": list(cones.keys()),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _estimate_params(
        self,
        closes: np.ndarray,
        ann_factor: float,
    ) -> tuple[float, float, int]:
        """
        Estimate annualised drift μ and volatility σ from log-returns.

        Uses exponentially weighted moments to give more weight to recent data.
        Returns (mu, sigma, n_samples).
        """
        if len(closes) < 2:
            return 0.0, 0.15, 0  # fallback: 15% vol, zero drift

        closes_safe = np.where(np.nan_to_num(closes, nan=1e-9) > 0, closes, 1e-9)
        log_returns = np.diff(np.log(closes_safe))
        n = len(log_returns)

        if n < 2:
            return 0.0, 0.15, n

        # Exponential weights — more weight to recent observations
        span = min(self._ewm_span, n)
        alpha = 2.0 / (span + 1)
        weights = np.array([(1 - alpha) ** (n - 1 - i) for i in range(n)])
        weights /= weights.sum()

        mu_per_bar = float(np.dot(weights, log_returns))
        # Bessel-corrected weighted variance
        var_per_bar = float(np.dot(weights, (log_returns - mu_per_bar) ** 2))

        # Annualise
        mu_annual = mu_per_bar * ann_factor
        sigma_annual = math.sqrt(max(var_per_bar * ann_factor, 1e-10))

        # Ito correction: drift in GBM is μ - σ²/2 per unit time
        # We store the raw μ; the correction is applied in _build_dot
        return mu_annual, sigma_annual, n

    def _build_dot(
        self,
        S0: float,
        mu: float,
        sigma: float,
        T: float,
        label: str,
    ) -> ConeDot:
        """
        Build a ConeDot at horizon T (years) using GBM closed-form solution.

        centre = S0 · exp[(μ - σ²/2) · T]
        upper_n = S0 · exp[(μ - σ²/2) · T + n·σ·√T]
        lower_n = S0 · exp[(μ - σ²/2) · T - n·σ·√T]
        """
        drift_term = (mu - 0.5 * sigma**2) * T
        diffusion = sigma * math.sqrt(max(T, 1e-10))

        centre = S0 * math.exp(drift_term)

        def band(n: float) -> tuple[float, float]:
            upper = S0 * math.exp(drift_term + n * diffusion)
            lower = S0 * math.exp(drift_term - n * diffusion)
            return upper, lower

        u1, l1 = band(1.0)
        u2, l2 = band(2.0)
        u3, l3 = band(3.0)

        return ConeDot(
            horizon=label,
            horizon_years=T,
            centre=centre,
            upper_1sigma=u1,
            lower_1sigma=l1,
            upper_2sigma=u2,
            lower_2sigma=l2,
            upper_3sigma=u3,
            lower_3sigma=l3,
        )

    @staticmethod
    def _annualise_factor(timeframe: str) -> float:
        """
        Return the number of bars per year for a given timeframe string.
        Used to convert per-bar variance to annualised variance.
        """
        _MAP: dict[str, float] = {
            "1m": _TRADING_DAYS_PER_YEAR * 24 * 60,
            "5m": _TRADING_DAYS_PER_YEAR * 24 * 12,
            "15m": _TRADING_DAYS_PER_YEAR * 24 * 4,
            "30m": _TRADING_DAYS_PER_YEAR * 24 * 2,
            "1h": _TRADING_DAYS_PER_YEAR * 24,
            "4h": _TRADING_DAYS_PER_YEAR * 6,
            "daily": _TRADING_DAYS_PER_YEAR,
            "1d": _TRADING_DAYS_PER_YEAR,
            "weekly": 52.0,
            "1w": 52.0,
            "monthly": 12.0,
            "1mo": 12.0,
            "yearly": 1.0,
            "1y": 1.0,
        }
        factor = _MAP.get(timeframe.lower())
        if factor is None:
            logger.warning("Unknown timeframe '%s' — defaulting to daily", timeframe)
            factor = _TRADING_DAYS_PER_YEAR
        return factor

    @staticmethod
    def _confidence_score(n: int, sigma: float) -> float:
        """
        Heuristic confidence score [0, 1] based on sample size and vol sanity.

        - n < 10  → very low confidence
        - n >= 252 → full confidence from sample size
        - Extreme vol (>100% or <1%) reduces confidence
        """
        # Sample size component
        size_score = min(n / _MIN_BARS_RELIABLE, 1.0)

        # Volatility sanity component
        if sigma < 0.005 or sigma > 2.0:
            vol_score = 0.3
        elif sigma < 0.02 or sigma > 1.0:
            vol_score = 0.6
        else:
            vol_score = 1.0

        return round(0.7 * size_score + 0.3 * vol_score, 3)


# ── Module-level singleton ────────────────────────────────────────────────────

_engine_instance: ItosConeEngine | None = None


def get_cone_engine(ewm_span: int = 60) -> ItosConeEngine:
    """Return the process-wide ItosConeEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ItosConeEngine(ewm_span=ewm_span)
    return _engine_instance
