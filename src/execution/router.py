"""Smart order router."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from src.core.types import Order, Venue, Side, Symbol
from src.execution.brokers.base import Broker

logger = structlog.get_logger()


class SmartRouter:
    """Route orders to best venue."""
    
    def __init__(self) -> None:
        self.brokers: dict[Venue, Broker] = {}
        self._venue_latency: dict[Venue, float] = {}
        self._venue_fees: dict[Venue, Decimal] = {
            Venue.OANDA: Decimal("0.0001"),
            Venue.BINANCE: Decimal("0.0004"),
            Venue.PAPER: Decimal("0"),
        }
    
    def register_broker(self, venue: Venue, broker: Broker) -> None:
        """Register broker for venue."""
        self.brokers[venue] = broker
        logger.info(f"Registered broker for {venue}")
    
    async def route_order(
        self, 
        symbol: Symbol, 
        side: Side, 
        quantity: Decimal,
        preference: Venue | None = None
    ) -> tuple[Venue, Broker]:
        """Determine best venue for order."""
        if preference and preference in self.brokers:
            return preference, self.brokers[preference]
        
        # Score venues
        scores = {}
        for venue, broker in self.brokers.items():
            score = await self._score_venue(venue, symbol, side, quantity)
            scores[venue] = score
        
        best_venue = max(scores, key=scores.get)
        return best_venue, self.brokers[best_venue]
    
    async def _score_venue(
        self, 
        venue: Venue, 
        symbol: Symbol, 
        side: Side, 
        quantity: Decimal
    ) -> float:
        """Score venue for order."""
        scores = []
        
        # Latency score (lower is better)
        latency = self._venue_latency.get(venue, 100.0)
        latency_score = max(0, 100 - latency)
        scores.append(latency_score * 0.3)  # 30% weight
        
        # Fee score (lower is better)
        fee = self._venue_fees.get(venue, Decimal("0.001"))
        fee_score = float(Decimal("1") / (fee * 1000 + Decimal("0.0001")))
        scores.append(fee_score * 0.2)  # 20% weight
        
        # Liquidity score (would query order book depth)
        liquidity_score = 50.0  # Placeholder
        scores.append(liquidity_score * 0.5)  # 50% weight
        
        return sum(scores)
    
    async def update_latency(self, venue: Venue, latency_ms: float) -> None:
        """Update venue latency measurement."""
        self._venue_latency[venue] = latency_ms
