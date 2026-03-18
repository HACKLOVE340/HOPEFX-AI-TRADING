from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

import structlog

from hopefx.config.settings import settings
from hopefx.events.bus import event_bus
from hopefx.events.schemas import Event, EventType, OrderFill, TickData
from hopefx.execution.brokers.base import BaseBroker, Order, OrderResult, OrderStatus, OrderType
from hopefx.risk.circuit_breaker import multi_breaker

logger = structlog.get_logger()


@dataclass
class RouteRule:
    broker: str
    weight: float = 1.0
    min_latency: float = 0.0
    max_spread: float = 999.0


class SmartRouter:
    """Intelligent order routing across multiple brokers."""

    def __init__(self) -> None:
        self.brokers: dict[str, BaseBroker] = {}
        self._rules: dict[str, list[RouteRule]] = {
            "XAUUSD": [
                RouteRule("oanda", weight=0.5, max_spread=0.05),
                RouteRule("mt5", weight=0.3),
                RouteRule("binance", weight=0.2),
            ],
        }
        self._price_feeds: dict[str, TickData] = {}
        self._broker_stats: dict[str, dict] = {}

    def register_broker(self, name: str, broker: BaseBroker) -> None:
        """Register broker with router."""
        self.brokers[name] = broker
        self._broker_stats[name] = {
            "orders": 0,
            "fills": 0,
            "rejections": 0,
            "avg_latency": 0.0,
            "total_slippage": Decimal("0"),
        }
        logger.info("router.broker_registered", broker=name)

    async def route_order(self, order: Order) -> OrderResult:
        """Route order to best available broker."""
        # Check circuit breakers
        if not await multi_breaker.check_all():
            return OrderResult(
                order_id="rejected",
                status=OrderStatus.REJECTED,
                filled_qty=Decimal("0"),
                filled_price=Decimal("0"),
                remaining_qty=order.quantity,
                commission=Decimal("0"),
                slippage=Decimal("0"),
                timestamp="",
                raw_response="Circuit breaker open",
            )

        # Select broker
        broker_name = self._select_broker(order.symbol)
        if not broker_name or broker_name not in self.brokers:
            return OrderResult(
                order_id="rejected",
                status=OrderStatus.REJECTED,
                filled_qty=Decimal("0"),
                filled_price=Decimal("0"),
                remaining_qty=order.quantity,
                commission=Decimal("0"),
                slippage=Decimal("0"),
                timestamp="",
                raw_response="No available broker",
            )

        broker = self.brokers[broker_name]

        # Execute
        try:
            result = await broker.place_order(order)

            # Update stats
            self._broker_stats[broker_name]["orders"] += 1
            if result.status == OrderStatus.FILLED:
                self._broker_stats[broker_name]["fills"] += 1
                self._broker_stats[broker_name]["total_slippage"] += result.slippage

                # Record latency
                multi_breaker.record_latency(broker.latency_ms)
                # Record slippage
                multi_breaker.record_slippage(float(result.slippage))

                # Publish fill event
                await event_bus.publish(
                    Event(
                        type=EventType.ORDER_FILL,
                        payload=OrderFill(
                            order_id=result.order_id,
                            symbol=order.symbol,
                            timestamp=result.timestamp,
                            side=order.side,
                            filled_qty=result.filled_qty,
                            filled_price=result.filled_price,
                            commission=result.commission,
                            slippage=result.slippage,
                        ),
                        source="smart_router",
                    )
                )

            elif result.status == OrderStatus.REJECTED:
                self._broker_stats[broker_name]["rejections"] += 1

            return result

        except Exception as e:
            logger.exception("router.execution_error", broker=broker_name, error=str(e))
            # Try failover broker
            return await self._failover(order, exclude=[broker_name])

    def _select_broker(self, symbol: str) -> str | None:
        """Select best broker for symbol."""
        rules = self._rules.get(symbol, [])
        if not rules:
            return None

        # Filter by spread if we have price data
        valid_brokers = []
        for rule in rules:
            if rule.broker not in self.brokers:
                continue
            if not self.brokers[rule.broker].connected:
                continue
            valid_brokers.append((rule.broker, rule.weight))

        if not valid_brokers:
            return None

        # Weighted random selection
        total_weight = sum(w for _, w in valid_brokers)
        r = random.uniform(0, total_weight)
        cumulative = 0
        for broker, weight in valid_brokers:
            cumulative += weight
            if r <= cumulative:
                return broker

        return valid_brokers[-1][0]

    async def _failover(self, order: Order, exclude: list[str]) -> OrderResult:
        """Try alternative brokers."""
        for name, broker in self.brokers.items():
            if name in exclude:
                continue
            if not broker.connected:
                continue

            try:
                return await broker.place_order(order)
            except Exception as e:
                logger.warning("router.failover_failed", broker=name, error=str(e))
                continue

        return OrderResult(
            order_id="failed",
            status=OrderStatus.REJECTED,
            filled_qty=Decimal("0"),
            filled_price=Decimal("0"),
            remaining_qty=order.quantity,
            commission=Decimal("0"),
            slippage=Decimal("0"),
            timestamp="",
            raw_response="All brokers failed",
        )

    def update_price(self, symbol: str, tick: TickData) -> None:
        """Update price feed for routing decisions."""
        self._price_feeds[symbol] = tick

    def get_stats(self) -> dict:
        """Get routing statistics."""
        return {
            "brokers": self._broker_stats,
            "active_feeds": list(self._price_feeds.keys()),
        }


# Global router
smart_router = SmartRouter()
