"""Institutional-grade transaction cost analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

import numpy as np
import structlog

from src.core.types import Fill, Order, Side, Tick

logger = structlog.get_logger()


class BenchmarkType(Enum):
    ARRIVAL = "arrival"  # Price at order creation
    VWAP = "vwap"        # Volume-weighted average price
    TWAP = "twap"        # Time-weighted average price
    CLOSE = "close"      # Previous close
    OPEN = "open"        # Opening price


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
        spread_bps: float
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate expected market impact.
        Returns: (temporary_impact_bps, permanent_impact_bps)
        """
        # I-Star model: I = a * (size/ADV)^b * sigma^c
        # Simplified institutional model
        participation_rate = float(order_size / avg_daily_volume) if avg_daily_volume > 0 else 0
        
        # Temporary impact (decays over time)
        temp_bps = 0.5 * spread_bps * np.sqrt(participation_rate * 100)
        temp_bps += 10 * volatility * np.sqrt(participation_rate)
        
        # Permanent impact (persists)
        perm_bps = 0.1 * temp_bps  # ~10% of temporary
        
        return Decimal(str(temp_bps)), Decimal(str(perm_bps))


@dataclass
class TCAMetrics:
    """Post-trade analytics."""
    order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    
    # Benchmarks
    arrival_price: Decimal  # Price when order decided
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
    implementation_shortfall_bps: Decimal = Decimal("0")  # vs arrival
    market_impact_bps: Decimal = Decimal("0")  # estimated
    timing_cost_bps: Decimal = Decimal("0")  # delay from decision
    opportunity_cost_bps: Decimal = Decimal("0")  # unexecuted portion
    
    # Quality metrics
    fill_rate: float = 0.0  # filled / intended
    price_improvement_bps: Decimal = Decimal("0")  # better than arrival
    
    @property
    def total_cost_bps(self) -> Decimal:
        """Total transaction cost."""
        return (
            self.implementation_shortfall_bps + 
            self.total_fees * Decimal("10000") / self.avg_fill_price
        )
    
    @property
    def alpha_extraction_bps(self) -> Decimal:
        """Net alpha after costs."""
        # Would need signal prediction vs realized
        return Decimal("0")


class TCAEngine:
    """Real-time execution quality tracking with I-Star model."""
    
    def __init__(
        self,
        impact_model: MarketImpactModel | None = None,
        window_size: int = 1000
    ) -> None:
        self.impact_model = impact_model or MarketImpactModel()
        self.window_size = window_size
        
        # Active orders being tracked
        self._active_orders: dict[str, dict[str, Any]] = {}
        
        # Completed analytics
        self._completed: list[TCAMetrics] = []
        
        # Market data cache for benchmarks
        self._vwap_cache: dict[str, list[tuple[datetime, Decimal, Decimal]]] = {}
        self._twap_cache: dict[str, list[tuple[datetime, Decimal]]] = {}
        
        # Callbacks for high-cost alerts
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
        expected_advantage_bps: float = 0.0  # Predicted alpha
    ) -> None:
        """Begin tracking an order."""
        self._active_orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "arrival_price": arrival_price,
            "arrival_time": datetime.utcnow(),
            "benchmark": benchmark,
            "expected_alpha_bps": expected_advantage_bps,
            "fills": [],
            "decision_time": datetime.utcnow(),
        }
        
        logger.debug(f"TCA tracking started: {order_id}")
    
    async def record_fill(self, order_id: str, fill: Fill) -> None:
        """Record a fill."""
        if order_id not in self._active_orders:
            logger.warning(f"TCA: Unknown order {order_id}")
            return
        
        order = self._active_orders[order_id]
        order["fills"].append(fill)
        
        # Track timing
        now = datetime.utcnow()
        if not order.get("first_fill_time"):
            order["first_fill_time"] = now
            order["time_to_first_fill_ms"] = (
                now - order["arrival_time"]
            ).total_seconds() * 1000
    
    async def complete_order(
        self,
        order_id: str,
        status: str = "FILLED"
    ) -> TCAMetrics:
        """Complete tracking and calculate metrics."""
        if order_id not in self._active_orders:
            raise ValueError(f"Unknown order: {order_id}")
        
        order = self._active_orders.pop(order_id)
        fills = order["fills"]
        
        if not fills:
            # Cancelled or rejected
            return self._create_cancelled_metrics(order)
        
        # Calculate execution stats
        total_qty = sum(f.quantity for f in fills)
        avg_price = sum(
            f.price * f.quantity for f in fills
        ) / total_qty if total_qty > 0 else Decimal("0")
        
        total_commission = sum(f.commission for f in fills)
        total_slippage = sum(f.slippage or Decimal("0") for f in fills)
        
        # Timing
        last_fill = fills[-1]
        exec_time_ms = (
            last_fill.timestamp - order["arrival_time"]
        ).total_seconds() * 1000
        
        # Calculate benchmark
        benchmark_price = await self._get_benchmark_price(
            order["symbol"],
            order["benchmark"],
            order["arrival_time"],
            last_fill.timestamp
        )
        
        # Implementation shortfall
        if order["side"] == Side.BUY:
            isf_bps = ((avg_price - order["arrival_price"]) / order["arrival_price"]) * Decimal("10000")
        else:
            isf_bps = ((order["arrival_price"] - avg_price) / order["arrival_price"]) * Decimal("10000")
        
        # Market impact estimate
        temp_impact, perm_impact = self.impact_model.calculate(
            order_size=total_qty,
            avg_daily_volume=Decimal("100000"),  # Would query actual ADV
            volatility=0.15,  # Would query actual vol
            spread_bps=2.0
        )
        
        # Opportunity cost (unfilled portion)
        fill_rate = float(total_qty / order["quantity"]) if order["quantity"] > 0 else 0
        opp_cost = Decimal("0")
        if fill_rate < 1.0:
            # Cost of not participating in move
            opp_cost = (Decimal("1") - Decimal(str(fill_rate))) * isf_bps * Decimal("0.5")
        
        metrics = TCAMetrics(
            order_id=order_id,
            symbol=order["symbol"],
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
            time_to_first_fill_ms=order.get("time_to_first_fill_ms", 0),
            total_execution_time_ms=exec_time_ms,
            implementation_shortfall_bps=isf_bps,
            market_impact_bps=temp_impact,
            timing_cost_bps=Decimal(str(max(0, exec_time_ms - 100) * 0.01)),  # Cost of delay
            opportunity_cost_bps=opp_cost,
            fill_rate=fill_rate,
            price_improvement_bps=-isf_bps if isf_bps < 0 else Decimal("0")
        )
        
        # Store and check
        self._completed.append(metrics)
        if len(self._completed) > self.window_size:
            self._completed.pop(0)
        
        # Alert if expensive
        if metrics.total_cost_bps > Decimal("20"):  # 20bps threshold
            logger.warning(f"High-cost trade: {metrics.total_cost_bps:.2f} bps")
            for cb in self._cost_callbacks:
                cb(metrics)
        
        # Alpha extraction check
        expected = Decimal(str(order["expected_alpha_bps"]))
        if metrics.total_cost_bps > expected:
            logger.error(
                f"Costs exceed expected alpha: "
                f"cost={metrics.total_cost_bps:.2f}bps, "
                f"expected={expected:.2f}bps"
            )
        
        return metrics
    
    async def _get_benchmark_price(
        self,
        symbol: str,
        benchmark: BenchmarkType,
        start: datetime,
        end: datetime
    ) -> Decimal:
        """Get benchmark price."""
        if benchmark == BenchmarkType.ARRIVAL:
            # Already have arrival price
            return Decimal("0")  # Placeholder
        
        elif benchmark == BenchmarkType.VWAP:
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
                return sum(p[1] for p in relevant) / len(relevant)
        
        return Decimal("0")
    
    def _create_cancelled_metrics(self, order: dict) -> TCAMetrics:
        """Create metrics for cancelled order."""
        return TCAMetrics(
            order_id=order.get("order_id", "unknown"),
            symbol=order["symbol"],
            side=order["side"],
            quantity=Decimal("0"),
            arrival_price=order["arrival_price"],
            arrival_time=order["arrival_time"],
            fill_rate=0.0,
            opportunity_cost_bps=Decimal("0")  # Would estimate missed opportunity
        )
    
    def update_market_data(self, tick: Tick) -> None:
        """Update VWAP/TWAP caches."""
        symbol = tick.symbol
        
        # VWAP
        if symbol not in self._vwap_cache:
            self._vwap_cache[symbol] = []
        self._vwap_cache[symbol].append((
            datetime.utcnow(),
            tick.mid,
            tick.volume
        ))
        if len(self._vwap_cache[symbol]) > 10000:
            self._vwap_cache[symbol].pop(0)
        
        # TWAP
        if symbol not in self._twap_cache:
            self._twap_cache[symbol] = []
        self._twap_cache[symbol].append((datetime.utcnow(), tick.mid))
        if len(self._twap_cache[symbol]) > 10000:
            self._twap_cache[symbol].pop(0)
    
    def get_stats(self, n: int = 100) -> dict[str, Any]:
        """Rolling statistics."""
        recent = self._completed[-n:]
        if not recent:
            return {}
        
        costs = [m.total_cost_bps for m in recent]
        isf = [m.implementation_shortfall_bps for m in recent]
        fill_rates = [m.fill_rate for m in recent]
        
        return {
            "count": len(recent),
            "mean_cost_bps": float(sum(costs) / len(costs)),
            "median_cost_bps": float(sorted(costs)[len(costs)//2]),
            "p90_cost_bps": float(sorted(costs)[int(len(costs)*0.9)]),
            "mean_isf_bps": float(sum(isf) / len(isf)),
            "mean_fill_rate": sum(fill_rates) / len(fill_rates),
            "win_rate": len([c for c in costs if c < Decimal("10")]) / len(costs),
            "alpha_positive": len([m for m in recent if m.alpha_extraction_bps > 0]) / len(recent)
        }
