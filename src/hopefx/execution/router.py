# src/hopefx/execution/router.py
"""
Smart Order Router (SOR) with latency scoring, cost optimization,
and fill probability modeling.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import numpy as np
import structlog

from hopefx.brokers.base import BaseBroker
from hopefx.execution.oms import Order, OrderManager, OrderStatus, OrderType

logger = structlog.get_logger()


@dataclass
class RouteScore:
    """Broker routing score."""
    broker_name: str
    latency_ms: float
    cost_bps: float
    fill_probability: float
    available_liquidity: Decimal
    composite_score: float


class SmartRouter:
    """
    Institutional-grade smart router with multi-factor scoring.
    Routes orders to optimal venue based on:
    - Latency (real-time measurement)
    - Cost (spread + commission)
    - Fill probability (historical + market conditions)
    - Liquidity (depth at price level)
    """
    
    def __init__(self, order_manager: OrderManager) -> None:
        self._brokers: dict[str, BaseBroker] = {}
        self._oms = order_manager
        self._latency_history: dict[str, list[float]] = {}
        self._fill_history: dict[str, dict] = {}
        self._lock = asyncio.Lock()
    
    def register_broker(self, name: str, broker: BaseBroker) -> None:
        """Register execution venue."""
        self._brokers[name] = broker
        self._latency_history[name] = []
        self._fill_history[name] = {"attempts": 0, "fills": 0}
        logger.info("broker_registered", name=name, broker_type=broker.__class__.__name__)
    
    async def route_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        urgency: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"
    ) -> tuple[str, Order]:
        """
        Route order to optimal broker.
        Returns (broker_name, order).
        """
        # Score all venues
        scores = await self._score_venues(symbol, side, quantity, order_type)
        
        if not scores:
            raise RuntimeError("No available brokers for routing")
        
        # Sort by composite score (higher is better)
        scores.sort(key=lambda x: x.composite_score, reverse=True)
        
        # Select top venue
        selected = scores[0]
        
        # Submit order
        broker = self._brokers[selected.broker_name]
        
        start_time = time.perf_counter()
        
        order = await self._oms.submit_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price
        )
        
        # Route to broker
        try:
            broker_order_id = await broker.place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type.name,
                price=price
            )
            
            # Update order with broker reference
            order.client_order_id = broker_order_id
            
            latency = (time.perf_counter() - start_time) * 1000
            self._latency_history[selected.broker_name].append(latency)
            
            # Keep only last 100 measurements
            self._latency_history[selected.broker_name] = \
                self._latency_history[selected.broker_name][-100:]
            
            logger.info(
                "order_routed",
                broker=selected.broker_name,
                order_id=order.order_id,
                latency_ms=latency,
                score=selected.composite_score
            )
            
            return selected.broker_name, order
            
        except Exception as e:
            logger.error("routing_failed", broker=selected.broker_name, error=str(e))
            # Try next best venue
            if len(scores) > 1:
                logger.info("failing_over", to_broker=scores[1].broker_name)
                return await self._route_to_specific(scores[1].broker_name, order)
            raise
    
    async def _score_venues(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: Decimal,
        order_type: OrderType
    ) -> list[RouteScore]:
        """Calculate routing scores for all venues."""
        scores = []
        
        for name, broker in self._brokers.items():
            if not broker.is_connected:
                continue
            
            # Measure latency
            latency = await self._measure_latency(name, broker)
            
            # Get cost estimate
            cost = await self._estimate_cost(name, symbol, side, quantity)
            
            # Calculate fill probability
            fill_prob = await self._estimate_fill_probability(name, symbol, quantity, order_type)
            
            # Get available liquidity
            liquidity = await broker.get_available_liquidity(symbol, side)
            
            # Calculate composite score (0-100)
            # Lower latency = higher score (exponential decay)
            latency_score = 100 * np.exp(-latency / 50)  # 50ms half-life
            
            # Lower cost = higher score
            cost_score = max(0, 100 - cost * 10)  # 10bps = 0 score
            
            # Higher fill prob = higher score
            fill_score = fill_prob * 100
            
            # Higher liquidity = higher score (log scale)
            liquidity_score = min(100, 20 * np.log10(float(liquidity) + 1))
            
            # Weighted composite
            composite = (
                0.3 * latency_score +
                0.2 * cost_score +
                0.3 * fill_score +
                0.2 * liquidity_score
            )
            
            scores.append(RouteScore(
                broker_name=name,
                latency_ms=latency,
                cost_bps=cost,
                fill_probability=fill_prob,
                available_liquidity=liquidity,
                composite_score=composite
            ))
        
        return scores
    
    async def _measure_latency(self, name: str, broker: BaseBroker) -> float:
        """Measure round-trip latency to broker."""
        start = time.perf_counter()
        await broker.ping()
        latency = (time.perf_counter() - start) * 1000
        
        # Blend with historical average (EMA)
        history = self._latency_history.get(name, [])
        if history:
            ema = history[-1] * 0.7 + latency * 0.3
            return ema
        return latency
    
    async def _estimate_cost(
        self,
        name: str,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: Decimal
    ) -> float:
        """Estimate total cost in basis points."""
        broker = self._brokers[name]
        
        # Get spread
        tick = await broker.get_current_tick(symbol)
        if tick and tick.bid and tick.ask:
            mid = (float(tick.bid) + float(tick.ask)) / 2
            spread_bps = (float(tick.ask) - float(tick.bid)) / mid * 10000
        else:
            spread_bps = 10  # Default 10bps
        
        # Commission
        commission_bps = broker.get_commission_bps(symbol)
        
        # Market impact estimate (square root model)
        avg_daily_volume = await broker.get_adv(symbol)
        if avg_daily_volume > 0:
            participation = float(quantity) / avg_daily_volume
            impact_bps = 10 * np.sqrt(participation)  # Simplified square root model
        else:
            impact_bps = 5
        
        return spread_bps + commission_bps + impact_bps
    
    async def _estimate_fill_probability(
        self,
        name: str,
        symbol: str,
        quantity: Decimal,
        order_type: OrderType
    ) -> float:
        """Estimate probability of complete fill."""
        broker = self._brokers[name]
        
        # Market orders have high fill probability
        if order_type == OrderType.MARKET:
            return 0.98
        
        # Check historical fill rate
        history = self._fill_history.get(name, {})
        if history["attempts"] > 0:
            historical = history["fills"] / history["attempts"]
        else:
            historical = 0.95  # Default optimistic
        
        # Check current liquidity
        liquidity = await broker.get_available_liquidity(symbol, "BUY")
        if liquidity >= quantity * Decimal("2"):
            liquidity_factor = 1.0
        elif liquidity >= quantity:
            liquidity_factor = 0.9
        else:
            liquidity_factor = float(liquidity / quantity) * 0.8
        
        # Volatility adjustment (higher vol = lower fill prob for limits)
        volatility = await broker.get_current_volatility(symbol)
        vol_factor = max(0.5, 1.0 - volatility * 2)
        
        return historical * liquidity_factor * vol_factor
    
    async def _route_to_specific(self, broker_name: str, order: Order) -> tuple[str, Order]:
        """Route to specific broker (failover)."""
        broker = self._brokers[broker_name]
        
        broker_order_id = await broker.place_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            order_type=order.order_type.name,
            price=order.price
        )
        
        order.client_order_id = broker_order_id
        
        return broker_name, order
    
    def get_routing_stats(self) -> dict:
        """Get router performance statistics."""
        stats = {}
        for name, latencies in self._latency_history.items():
            if latencies:
                stats[name] = {
                    "avg_latency_ms": sum(latencies) / len(latencies),
                    "p99_latency_ms": sorted(latencies)[int(len(latencies) * 0.99)],
                    "samples": len(latencies)
                }
        return stats
