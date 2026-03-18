"""Transaction cost analytics."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from src.core.types import Fill, Order, Side

logger = structlog.get_logger()


@dataclass
class TCAMetrics:
    """Post-trade analytics."""
    order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    
    # Benchmarks
    arrival_price: Decimal  # Price when order decided
    decision_time: datetime
    
    # Execution
    fills: list[Fill] = field(default_factory=list)
    avg_fill_price: Decimal = Decimal("0")
    total_commission: Decimal = Decimal("0")
    total_slippage: Decimal = Decimal("0")
    
    # Derived metrics
    implementation_shortfall: Decimal = Decimal("0")  # vs arrival
    market_impact: Decimal = Decimal("0")  # vs pre-trade mid
    timing_cost: Decimal = Decimal("0")  # delay from decision
    
    @property
    def total_cost_bps(self) -> Decimal:
        """Total cost in basis points."""
        if self.arrival_price == 0:
            return Decimal("0")
        return (self.implementation_shortfall / self.arrival_price) * Decimal("10000")


class TCAEngine:
    """Real-time execution quality tracking."""
    
    def __init__(self) -> None:
        self._arrival_prices: dict[str, tuple[Decimal, datetime]] = {}
        self._metrics: list[TCAMetrics] = []
        self._window_size = 1000  # Keep last N trades
    
    def record_decision(self, order_id: str, symbol: str, price: Decimal) -> None:
        """Record decision-time price."""
        self._arrival_prices[order_id] = (price, datetime.utcnow())
    
    def analyze_fill(self, order: Order, fill: Fill) -> TCAMetrics:
        """Analyze completed order."""
        arrival = self._arrival_prices.get(order.id, (order.price or fill.price, fill.timestamp))
        arrival_price, decision_time = arrival
        
        # Calculate fill stats
        total_qty = sum(f.quantity for f in [fill])  # Extend for partials
        avg_price = fill.price  # Weighted avg for partials
        
        # Implementation shortfall
        if order.side == Side.BUY:
            isf = avg_price - arrival_price
        else:
            isf = arrival_price - avg_price
        
        metrics = TCAMetrics(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=fill.quantity,
            arrival_price=arrival_price,
            decision_time=decision_time,
            fills=[fill],
            avg_fill_price=avg_price,
            total_commission=fill.commission,
            total_slippage=fill.slippage or Decimal("0"),
            implementation_shortfall=isf,
            timing_cost=Decimal("0")  # Calculate from timestamps
        )
        
        self._metrics.append(metrics)
        if len(self._metrics) > self._window_size:
            self._metrics.pop(0)
        
        # Log if expensive
        if metrics.total_cost_bps > Decimal("10"):
            logger.warning(
                f"High execution cost: {metrics.total_cost_bps:.2f} bps",
                order_id=order.id,
                isf=float(isf),
                slippage=float(fill.slippage or 0)
            )
        
        return metrics
    
    def get_stats(self, n: int = 100) -> dict[str, Any]:
        """Rolling statistics."""
        recent = self._metrics[-n:]
        if not recent:
            return {}
        
        costs = [m.total_cost_bps for m in recent]
        
        return {
            "count": len(recent),
            "mean_cost_bps": float(sum(costs) / len(costs)),
            "median_cost_bps": float(sorted(costs)[len(costs)//2]),
            "p90_cost_bps": float(sorted(costs)[int(len(costs)*0.9)]),
            "win_rate": len([c for c in costs if c < Decimal("5")]) / len(costs),
        }
