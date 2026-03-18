"""
Smart Order Router (SOR) with venue selection.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.core.logging_config import get_logger
from src.domain.enums import OrderType, TradeDirection
from src.domain.models import Order

logger = get_logger(__name__)


@dataclass
class VenueScore:
    """Venue routing score."""
    venue: str
    latency_ms: float
    fill_probability: float
    cost_bps: float
    composite_score: float


class SmartOrderRouter:
    """
    Intelligent order routing across multiple venues.
    """
    
    def __init__(self):
        self._venues: dict[str, Any] = {}
        self._venue_stats: dict[str, dict] = {}
    
    def register_venue(self, name: str, venue: Any) -> None:
        """Register trading venue."""
        self._venues[name] = venue
        self._venue_stats[name] = {
            "orders_sent": 0,
            "orders_filled": 0,
            "avg_latency_ms": 0,
            "avg_slippage_bps": 0,
        }
    
    async def route_order(
        self,
        order: Order,
        preferences: dict[str, Any] | None = None
    ) -> tuple[str, Any]:
        """
        Select best venue for order.
        
        Routing logic:
        1. Urgent orders -> lowest latency
        2. Large orders -> best depth/lowest market impact
        3. Cost-sensitive -> lowest fees
        4. Fill-critical -> highest fill probability
        """
        if not self._venues:
            raise RuntimeError("No venues registered")
        
        # Score each venue
        scores = []
        for name, venue in self._venues.items():
            score = await self._score_venue(name, venue, order)
            scores.append(score)
        
        # Sort by composite score (higher is better)
        scores.sort(key=lambda x: x.composite_score, reverse=True)
        
        best = scores[0]
        logger.info(
            f"Routing {order.symbol} {order.direction.value} to {best.venue} "
            f"(score: {best.composite_score:.2f})"
        )
        
        return best.venue, self._venues[best.venue]
    
    async def _score_venue(
        self,
        name: str,
        venue: Any,
        order: Order
    ) -> VenueScore:
        """Calculate venue score."""
        stats = self._venue_stats[name]
        
        # Base metrics
        latency = stats["avg_latency_ms"]
        fill_prob = self._estimate_fill_probability(venue, order)
        cost = self._estimate_cost(venue, order)
        
        # Weight factors
        urgency_weight = 0.4 if order.order_type == OrderType.MARKET else 0.2
        fill_weight = 0.4
        cost_weight = 0.2
        
        # Normalize and score
        latency_score = max(0, 100 - latency) / 100
        fill_score = fill_prob
        cost_score = max(0, 1 - (cost / 10))  # Assume 10bps max
        
        composite = (
            latency_score * urgency_weight +
            fill_score * fill_weight +
            cost_score * cost_weight
        )
        
        return VenueScore(
            venue=name,
            latency_ms=latency,
            fill_probability=fill_prob,
            cost_bps=cost,
            composite_score=composite
        )
    
    def _estimate_fill_probability(self, venue: Any, order: Order) -> float:
        """Estimate probability of fill."""
        # Simplified - would use order book depth
        return 0.95 if order.order_type == OrderType.MARKET else 0.7
    
    def _estimate_cost(self, venue: Any, order: Order) -> float:
        """Estimate trading cost in bps."""
        # Base fee + spread + market impact
        base_fee = 2.0  # 2bps
        spread = 1.0    # 1bp
        impact = 0.5 if order.quantity > 10 else 0.1  # Market impact
        
        return base_fee + spread + impact
    
    def update_venue_stats(
        self,
        venue: str,
        latency_ms: float,
        filled: bool,
        slippage_bps: float
    ) -> None:
        """Update venue performance statistics."""
        stats = self._venue_stats[venue]
        
        # Exponential moving average
        alpha = 0.1
        stats["avg_latency_ms"] = (
            (1 - alpha) * stats["avg_latency_ms"] + alpha * latency_ms
        )
        stats["avg_slippage_bps"] = (
            (1 - alpha) * stats["avg_slippage_bps"] + alpha * slippage_bps
        )
        
        stats["orders_sent"] += 1
        if filled:
            stats["orders_filled"] += 1
