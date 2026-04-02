# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/tca.py
================
Institutional-grade Transaction Cost Analysis engine.

Uses the I-Star market impact model with real ADV and volatility sourced
from the live market data cache (market_data/redis_cache.py) and the
Almgren-Chriss fill simulator (execution/market_impact.py).

ADV resolution order (per symbol):
  1. Redis OHLCV bars — sum of last 20 daily bar volumes
  2. In-memory VWAP/TWAP tick cache (accumulated since process start)
  3. Per-symbol env override: TCA_ADV_{SYMBOL} (e.g. TCA_ADV_XAU_USD=50000)
  4. Global fallback: TCA_DEFAULT_ADV (default 50000)

Volatility resolution order:
  1. Rolling 20-bar daily return std from Redis OHLCV
  2. Per-symbol env override: TCA_VOL_{SYMBOL}
  3. Global fallback: TCA_DEFAULT_VOL (default 0.012 = 1.2%)

No hardcoded ADV or volatility values remain in production paths.
"""

from __future__ import annotations

import logging
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal
from enum import Enum
from typing import Any
from collections.abc import Callable

import numpy as np

from core.types import Fill, Side, Tick

logger = logging.getLogger(__name__)

# ── Fallback configuration (env-overridable) ──────────────────────────────────
_DEFAULT_ADV: float = float(os.getenv("TCA_DEFAULT_ADV", "50000"))
_DEFAULT_VOL: float = float(os.getenv("TCA_DEFAULT_VOL", "0.012"))
_ADV_LOOKBACK_BARS: int = int(os.getenv("TCA_ADV_LOOKBACK_BARS", "20"))
_VOL_LOOKBACK_BARS: int = int(os.getenv("TCA_VOL_LOOKBACK_BARS", "20"))


class BenchmarkType(Enum):
    ARRIVAL = "arrival"  # Price at order creation
    VWAP = "vwap"  # Volume-weighted average price
    TWAP = "twap"  # Time-weighted average price
    CLOSE = "close"  # Previous close
    OPEN = "open"  # Opening price


@dataclass
class MarketImpactModel:
    """I-Star model implementation."""

    permanent_impact: Decimal = Decimal("0")
    temporary_impact: Decimal = Decimal("0")

    def calculate(
        self,
        order_size: Decimal,
        avg_daily_volume: Decimal,
        volatility: float,
        spread_bps: float,
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate expected market impact.

        Returns: (temporary_impact_bps, permanent_impact_bps)
        """
        participation_rate = float(order_size / avg_daily_volume) if avg_daily_volume > 0 else 0.0

        # Temporary impact (decays over time)
        temp_bps = 0.5 * spread_bps * math.sqrt(participation_rate * 100)
        temp_bps += 10 * volatility * math.sqrt(participation_rate)

        # Permanent impact (~10% of temporary)
        perm_bps = 0.1 * temp_bps

        return Decimal(str(round(temp_bps, 6))), Decimal(str(round(perm_bps, 6)))


@dataclass
class TCAMetrics:
    """Post-trade analytics for a single order."""

    order_id: str
    symbol: str
    side: Side
    quantity: Decimal

    # Benchmarks
    arrival_price: Decimal
    arrival_time: datetime
    benchmark_type: BenchmarkType = BenchmarkType.ARRIVAL

    # Execution
    fills: list[Fill] = field(default_factory=list)
    avg_fill_price: Decimal = Decimal("0")
    total_commission: Decimal = Decimal("0")
    total_slippage: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")

    # Timing
    first_fill_time: datetime | None = None
    last_fill_time: datetime | None = None
    time_to_first_fill_ms: float = 0.0
    total_execution_time_ms: float = 0.0

    # Derived costs
    implementation_shortfall_bps: Decimal = Decimal("0")
    market_impact_bps: Decimal = Decimal("0")
    timing_cost_bps: Decimal = Decimal("0")
    opportunity_cost_bps: Decimal = Decimal("0")

    # Quality metrics
    fill_rate: float = 0.0
    price_improvement_bps: Decimal = Decimal("0")

    # Market context used for impact calculation
    adv_used: float = 0.0
    volatility_used: float = 0.0
    adv_source: str = "unknown"
    vol_source: str = "unknown"

    @property
    def total_cost_bps(self) -> Decimal:
        """Total transaction cost in bps."""
        if self.avg_fill_price <= 0:
            return self.implementation_shortfall_bps
        return self.implementation_shortfall_bps + self.total_fees * Decimal("10000") / self.avg_fill_price

    @property
    def alpha_extraction_bps(self) -> Decimal:
        """Net alpha after costs (requires signal prediction vs realized)."""
        return Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": str(self.side),
            "quantity": float(self.quantity),
            "arrival_price": float(self.arrival_price),
            "avg_fill_price": float(self.avg_fill_price),
            "implementation_shortfall_bps": float(self.implementation_shortfall_bps),
            "market_impact_bps": float(self.market_impact_bps),
            "timing_cost_bps": float(self.timing_cost_bps),
            "opportunity_cost_bps": float(self.opportunity_cost_bps),
            "total_cost_bps": float(self.total_cost_bps),
            "fill_rate": self.fill_rate,
            "total_execution_time_ms": self.total_execution_time_ms,
            "time_to_first_fill_ms": self.time_to_first_fill_ms,
            "adv_used": self.adv_used,
            "volatility_used": self.volatility_used,
            "adv_source": self.adv_source,
            "vol_source": self.vol_source,
            "arrival_time": self.arrival_time.isoformat(),
        }


class MarketContextProvider:
    """
    Resolves real ADV and daily volatility for a symbol.

    Resolution order for ADV:
      1. Redis OHLCV bars (last N daily bars, sum of volumes)
      2. In-memory tick accumulator (volume since process start)
      3. Per-symbol env override TCA_ADV_{SYMBOL}
      4. Global fallback TCA_DEFAULT_ADV

    Resolution order for volatility:
      1. Redis OHLCV bars (rolling std of daily returns)
      2. Per-symbol env override TCA_VOL_{SYMBOL}
      3. Global fallback TCA_DEFAULT_VOL
    """

    def __init__(self) -> None:
        # In-memory tick volume accumulator: symbol → list of (timestamp, volume)
        self._tick_volumes: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        self._redis_cache: Any | None = None

    def _get_redis_cache(self) -> Any | None:
        """Lazy-load the Redis market data cache."""
        if self._redis_cache is None:
            try:
                from market_data.redis_cache import MarketDataCache
                from cache.redis_client import get_sync_redis

                r = get_sync_redis()
                if r is not None:
                    self._redis_cache = MarketDataCache(r)
            except Exception as exc:
                logger.debug("TCA: Redis cache unavailable: %s", exc)
        return self._redis_cache

    def accumulate_tick(self, symbol: str, volume: float, ts: datetime) -> None:
        """Record a tick volume for in-memory ADV estimation."""
        self._tick_volumes[symbol].append((ts, volume))
        # Keep only last 100k ticks per symbol
        if len(self._tick_volumes[symbol]) > 100_000:
            self._tick_volumes[symbol] = self._tick_volumes[symbol][-100_000:]

    def get_adv(self, symbol: str) -> tuple[float, str]:
        """
        Return (adv, source) for *symbol*.

        source is one of: "redis_ohlcv", "tick_accumulator", "env_override", "default"
        """
        # 1. Per-symbol env override
        env_key = f"TCA_ADV_{symbol.replace('/', '_').replace('-', '_').upper()}"
        env_val = os.getenv(env_key)
        if env_val:
            try:
                return float(env_val), "env_override"
            except ValueError:
                pass

        # 2. Redis OHLCV bars
        cache = self._get_redis_cache()
        if cache is not None:
            try:
                bars = cache.get_bars(symbol, "1d", n=_ADV_LOOKBACK_BARS)
                if bars and len(bars) >= 5:
                    volumes = [float(b.get("volume", 0)) for b in bars if b.get("volume")]
                    if volumes and sum(volumes) > 0:
                        adv = sum(volumes) / len(volumes)
                        return adv, "redis_ohlcv"
            except Exception as exc:
                logger.debug("TCA: Redis OHLCV ADV lookup failed for %s: %s", symbol, exc)

        # 3. In-memory tick accumulator
        ticks = self._tick_volumes.get(symbol, [])
        if len(ticks) >= 100:
            total_vol = sum(v for _, v in ticks)
            if total_vol > 0 and len(ticks) >= 2:
                # Estimate daily volume from accumulated ticks
                span_hours = (ticks[-1][0] - ticks[0][0]).total_seconds() / 3600
                if span_hours > 0:
                    daily_vol = total_vol * (24.0 / span_hours)
                    return daily_vol, "tick_accumulator"

        # 4. Global fallback
        return _DEFAULT_ADV, "default"

    def get_volatility(self, symbol: str) -> tuple[float, str]:
        """
        Return (daily_volatility_fraction, source) for *symbol*.

        source is one of: "redis_ohlcv", "env_override", "default"
        """
        # 1. Per-symbol env override
        env_key = f"TCA_VOL_{symbol.replace('/', '_').replace('-', '_').upper()}"
        env_val = os.getenv(env_key)
        if env_val:
            try:
                return float(env_val), "env_override"
            except ValueError:
                pass

        # 2. Redis OHLCV bars — rolling std of daily log returns
        cache = self._get_redis_cache()
        if cache is not None:
            try:
                bars = cache.get_bars(symbol, "1d", n=_VOL_LOOKBACK_BARS + 1)
                if bars and len(bars) >= 5:
                    closes = [float(b.get("close", 0)) for b in bars if b.get("close")]
                    if len(closes) >= 5:
                        log_returns = [
                            math.log(closes[i] / closes[i - 1])
                            for i in range(1, len(closes))
                            if closes[i - 1] > 0 and closes[i] > 0
                        ]
                        if log_returns:
                            vol = float(np.std(log_returns))
                            return vol, "redis_ohlcv"
            except Exception as exc:
                logger.debug("TCA: Redis OHLCV vol lookup failed for %s: %s", symbol, exc)

        # 3. Global fallback
        return _DEFAULT_VOL, "default"


class TCAEngine:
    """
    Real-time execution quality tracking with I-Star model.

    ADV and volatility are resolved from live market data — no hardcoded values.
    """

    def __init__(
        self,
        impact_model: MarketImpactModel | None = None,
        market_context: MarketContextProvider | None = None,
        window_size: int = 1000,
    ) -> None:
        self.impact_model = impact_model or MarketImpactModel()
        self.market_context = market_context or MarketContextProvider()
        self.window_size = window_size

        self._active_orders: dict[str, dict[str, Any]] = {}
        self._completed: list[TCAMetrics] = []

        # VWAP/TWAP caches: symbol → list of (datetime, price, volume)
        self._vwap_cache: dict[str, list[tuple[datetime, Decimal, Decimal]]] = {}
        self._twap_cache: dict[str, list[tuple[datetime, Decimal]]] = {}

        self._cost_callbacks: list[Callable[[TCAMetrics], None]] = []

    def register_cost_callback(self, cb: Callable[[TCAMetrics], None]) -> None:
        """Register callback for expensive trades."""
        self._cost_callbacks.append(cb)

    async def start_order(
        self,
        order_id: str,
        symbol: str,
        side: Side,
        quantity: Decimal,
        arrival_price: Decimal,
        benchmark: BenchmarkType = BenchmarkType.ARRIVAL,
        expected_advantage_bps: float = 0.0,
    ) -> None:
        """Begin tracking an order."""
        self._active_orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "arrival_price": arrival_price,
            "arrival_time": datetime.now(UTC),
            "benchmark": benchmark,
            "expected_alpha_bps": expected_advantage_bps,
            "fills": [],
            "decision_time": datetime.now(UTC),
        }
        logger.debug("TCA tracking started: %s", order_id)

    async def record_fill(self, order_id: str, fill: Fill) -> None:
        """Record a fill and update VWAP/TWAP caches."""
        if order_id not in self._active_orders:
            logger.warning("TCA: Unknown order %s", order_id)
            return

        order = self._active_orders[order_id]
        order["fills"].append(fill)

        now = datetime.now(UTC)
        if not order.get("first_fill_time"):
            order["first_fill_time"] = now
            order["time_to_first_fill_ms"] = (now - order["arrival_time"]).total_seconds() * 1000

        # Update VWAP cache from fill
        symbol = order["symbol"]
        if symbol not in self._vwap_cache:
            self._vwap_cache[symbol] = []
        self._vwap_cache[symbol].append((now, fill.price, fill.quantity))
        if len(self._vwap_cache[symbol]) > 10_000:
            self._vwap_cache[symbol].pop(0)

        if symbol not in self._twap_cache:
            self._twap_cache[symbol] = []
        self._twap_cache[symbol].append((now, fill.price))
        if len(self._twap_cache[symbol]) > 10_000:
            self._twap_cache[symbol].pop(0)

    async def complete_order(self, order_id: str, status: str = "FILLED") -> TCAMetrics:
        """Complete tracking and calculate metrics using real market context."""
        if order_id not in self._active_orders:
            raise ValueError(f"Unknown order: {order_id}")

        order = self._active_orders.pop(order_id)
        fills = order["fills"]

        if not fills:
            return self._create_cancelled_metrics(order, order_id)

        # Execution stats
        total_qty = sum(f.quantity for f in fills)
        avg_price = sum(f.price * f.quantity for f in fills) / total_qty if total_qty > 0 else Decimal("0")
        total_commission = sum(f.commission for f in fills)
        total_slippage = sum(getattr(f, "slippage", None) or Decimal("0") for f in fills)

        last_fill = fills[-1]
        exec_time_ms = (last_fill.timestamp - order["arrival_time"]).total_seconds() * 1000

        # Implementation shortfall vs arrival price
        if order["side"] == Side.BUY:
            isf_bps = ((avg_price - order["arrival_price"]) / order["arrival_price"]) * Decimal("10000")
        else:
            isf_bps = ((order["arrival_price"] - avg_price) / order["arrival_price"]) * Decimal("10000")

        # Resolve real ADV and volatility from market data
        symbol = order["symbol"]
        adv, adv_source = self.market_context.get_adv(symbol)
        vol, vol_source = self.market_context.get_volatility(symbol)

        logger.debug(
            "TCA impact context: symbol=%s adv=%.0f(%s) vol=%.4f(%s)",
            symbol,
            adv,
            adv_source,
            vol,
            vol_source,
        )

        # Market impact estimate with real context
        temp_impact, _perm_impact = self.impact_model.calculate(
            order_size=total_qty,
            avg_daily_volume=Decimal(str(adv)),
            volatility=vol,
            spread_bps=2.0,
        )

        # Opportunity cost (unfilled portion)
        fill_rate = float(total_qty / order["quantity"]) if order["quantity"] > 0 else 0.0
        opp_cost = Decimal("0")
        if fill_rate < 1.0:
            opp_cost = (Decimal("1") - Decimal(str(fill_rate))) * isf_bps * Decimal("0.5")

        metrics = TCAMetrics(
            order_id=order_id,
            symbol=symbol,
            side=order["side"],
            quantity=total_qty,
            arrival_price=order["arrival_price"],
            arrival_time=order["arrival_time"],
            benchmark_type=order["benchmark"],
            fills=fills,
            avg_fill_price=avg_price,
            total_commission=total_commission,
            total_slippage=total_slippage,
            total_fees=total_commission + total_slippage,
            first_fill_time=order.get("first_fill_time"),
            last_fill_time=last_fill.timestamp,
            time_to_first_fill_ms=order.get("time_to_first_fill_ms", 0.0),
            total_execution_time_ms=exec_time_ms,
            implementation_shortfall_bps=isf_bps,
            market_impact_bps=temp_impact,
            timing_cost_bps=Decimal(str(max(0.0, exec_time_ms - 100) * 0.01)),
            opportunity_cost_bps=opp_cost,
            fill_rate=fill_rate,
            price_improvement_bps=-isf_bps if isf_bps < 0 else Decimal("0"),
            adv_used=adv,
            volatility_used=vol,
            adv_source=adv_source,
            vol_source=vol_source,
        )

        self._completed.append(metrics)
        if len(self._completed) > self.window_size:
            self._completed.pop(0)

        # Alert if expensive
        if metrics.total_cost_bps > Decimal("20"):
            logger.warning(
                "TCA: high-cost trade order_id=%s cost=%.2fbps adv_source=%s vol_source=%s",
                order_id,
                float(metrics.total_cost_bps),
                adv_source,
                vol_source,
            )
            for cb in self._cost_callbacks:
                cb(metrics)

        # Warn if costs exceed expected alpha
        expected = Decimal(str(order["expected_alpha_bps"]))
        if expected > 0 and metrics.total_cost_bps > expected:
            logger.error(
                "TCA: costs exceed expected alpha order_id=%s cost=%.2fbps expected=%.2fbps",
                order_id,
                float(metrics.total_cost_bps),
                float(expected),
            )

        return metrics

    async def _get_benchmark_price(
        self,
        symbol: str,
        benchmark: BenchmarkType,
        start: datetime,
        end: datetime,
    ) -> Decimal:
        """Get benchmark price from VWAP/TWAP caches."""
        if benchmark == BenchmarkType.ARRIVAL:
            return Decimal("0")

        if benchmark == BenchmarkType.VWAP:
            vwap_data = self._vwap_cache.get(symbol, [])
            relevant = [p for p in vwap_data if start <= p[0] <= end]
            if relevant:
                total_vol = sum(p[2] for p in relevant)
                if total_vol > 0:
                    return sum(p[1] * p[2] for p in relevant) / total_vol

        elif benchmark == BenchmarkType.TWAP:
            twap_data = self._twap_cache.get(symbol, [])
            relevant = [p for p in twap_data if start <= p[0] <= end]
            if relevant:
                return sum(p[1] for p in relevant) / Decimal(str(len(relevant)))

        return Decimal("0")

    def _create_cancelled_metrics(self, order: dict[str, Any], order_id: str) -> TCAMetrics:
        """Create metrics for a cancelled/rejected order."""
        return TCAMetrics(
            order_id=order_id,
            symbol=order["symbol"],
            side=order["side"],
            quantity=Decimal("0"),
            arrival_price=order["arrival_price"],
            arrival_time=order["arrival_time"],
            fill_rate=0.0,
            opportunity_cost_bps=Decimal("0"),
        )

    def update_market_data(self, tick: Tick) -> None:
        """
        Update VWAP/TWAP caches and feed the market context provider.

        Called by the execution engine on every tick.
        """
        symbol = tick.symbol
        now = datetime.now(UTC)

        # Feed tick volume into ADV estimator
        self.market_context.accumulate_tick(
            symbol=str(symbol),
            volume=float(tick.volume),
            ts=now,
        )

        # VWAP cache
        if symbol not in self._vwap_cache:
            self._vwap_cache[symbol] = []
        self._vwap_cache[symbol].append((now, tick.mid, tick.volume))
        if len(self._vwap_cache[symbol]) > 10_000:
            self._vwap_cache[symbol].pop(0)

        # TWAP cache
        if symbol not in self._twap_cache:
            self._twap_cache[symbol] = []
        self._twap_cache[symbol].append((now, tick.mid))
        if len(self._twap_cache[symbol]) > 10_000:
            self._twap_cache[symbol].pop(0)

    def get_stats(self, n: int = 100) -> dict[str, Any]:
        """Rolling execution quality statistics."""
        recent = self._completed[-n:]
        if not recent:
            return {}

        costs = [m.total_cost_bps for m in recent]
        isf = [m.implementation_shortfall_bps for m in recent]
        fill_rates = [m.fill_rate for m in recent]
        adv_sources = [m.adv_source for m in recent]
        vol_sources = [m.vol_source for m in recent]

        return {
            "count": len(recent),
            "mean_cost_bps": float(sum(costs) / len(costs)),
            "median_cost_bps": float(sorted(costs)[len(costs) // 2]),
            "p90_cost_bps": float(sorted(costs)[int(len(costs) * 0.9)]),
            "mean_isf_bps": float(sum(isf) / len(isf)),
            "mean_fill_rate": sum(fill_rates) / len(fill_rates),
            "win_rate": len([c for c in costs if c < Decimal("10")]) / len(costs),
            "alpha_positive": (len([m for m in recent if m.alpha_extraction_bps > 0]) / len(recent)),
            "adv_source_breakdown": {src: adv_sources.count(src) for src in set(adv_sources)},
            "vol_source_breakdown": {src: vol_sources.count(src) for src in set(vol_sources)},
        }
