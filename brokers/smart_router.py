# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# brokers/smart_router.py
"""
HOPEFX Smart Order Router
Intelligent order routing across multiple brokers with best execution
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BrokerScore:
    """Real-time broker quality score"""

    broker_id: str
    latency_ms: float
    fill_rate: float
    avg_slippage_bps: float
    cost_score: float  # Combined fees + slippage
    reliability_score: float
    overall_score: float

    def calculate(self, weights: dict[str, float]):
        """Calculate weighted overall score"""
        self.overall_score = (
            weights.get("latency", 0.25) * (1 / (1 + self.latency_ms / 100))
            + weights.get("fill_rate", 0.25) * self.fill_rate
            + weights.get("cost", 0.25) * (1 / (1 + self.cost_score))
            + weights.get("reliability", 0.25) * self.reliability_score
        )


class SmartOrderRouter:
    """
    Routes orders to optimal broker based on real-time quality metrics.
    Implements best execution obligations.
    """

    def __init__(self):
        self.brokers: dict[str, BrokerConnector] = {}
        self.scores: dict[str, BrokerScore] = {}
        self.order_history: list[dict] = []
        self.routing_rules = {
            "latency_weight": 0.25,
            "fill_rate_weight": 0.25,
            "cost_weight": 0.30,
            "reliability_weight": 0.20,
        }
        self.last_route_decision: str | None = None

    def add_broker(self, broker_id: str, connector: "BrokerConnector"):
        """Add broker to routing pool"""
        self.brokers[broker_id] = connector
        self.scores[broker_id] = BrokerScore(
            broker_id=broker_id,
            latency_ms=100,
            fill_rate=0.95,
            avg_slippage_bps=5.0,
            cost_score=10.0,
            reliability_score=0.99,
            overall_score=0.0,
        )

    async def route_order(self, order: dict) -> tuple[str, dict]:
        """
        Determine optimal broker for order.
        Returns: (broker_id, routing_decision_metadata)
        """
        # Update scores with latest data
        await self._update_broker_scores()

        # Score all brokers
        for score in self.scores.values():
            score.calculate(self.routing_rules)

        # Rank brokers
        ranked = sorted(
            self.scores.values(),
            key=lambda x: x.overall_score,
            reverse=True,
        )

        # Select best available
        best_broker = ranked[0].broker_id

        # Smart routing logic
        decision = {
            "selected_broker": best_broker,
            "alternative_brokers": [r.broker_id for r in ranked[1:3]],
            "selection_reason": self._explain_selection(ranked[0]),
            "timestamp": datetime.now(UTC).isoformat(),
            "expected_latency_ms": ranked[0].latency_ms,
            "expected_cost_bps": ranked[0].cost_score,
        }

        self.last_route_decision = best_broker

        # Emit routing event
        # await event_bus.publish(...)

        return best_broker, decision

    async def _update_broker_scores(self):
        """Update broker scores with real-time metrics"""
        for broker_id, connector in self.brokers.items():
            try:
                # Ping latency
                start = datetime.now(UTC)
                await connector.ping()
                latency = (datetime.now(UTC) - start).total_seconds() * 1000

                score = self.scores[broker_id]
                score.latency_ms = 0.7 * score.latency_ms + 0.3 * latency  # EMA

                # Get recent performance
                recent_fills = await connector.get_recent_fills(hours=1)
                if recent_fills:
                    score.fill_rate = len(
                        [f for f in recent_fills if f["filled"]],
                    ) / len(recent_fills)
                    score.avg_slippage_bps = np.mean(
                        [f.get("slippage_bps", 0) for f in recent_fills],
                    )

            except Exception as e:
                logger.warning(
                    "Broker score update failed for %s, degrading reliability: %s",
                    broker_id,
                    e,
                )
                self.scores[broker_id].reliability_score *= 0.9

    def _explain_selection(self, score: BrokerScore) -> str:
        """Generate human-readable explanation"""
        reasons = []
        if score.latency_ms < 50:
            reasons.append("low_latency")
        if score.fill_rate > 0.98:
            reasons.append("high_fill_rate")
        if score.cost_score < 5:
            reasons.append("low_cost")
        if score.reliability_score > 0.99:
            reasons.append("high_reliability")

        return ", ".join(reasons) if reasons else "balanced_score"

    async def execute_with_fallback(self, order: dict) -> dict:
        """
        Execute order with automatic fallback to next best broker.
        Ensures execution even if primary broker fails.
        """
        primary_broker, decision = await self.route_order(order)

        try:
            result = await self._execute_with_timeout(primary_broker, order)
            return {**result, "routing": decision}

        except Exception as e:
            logger.error(
                "Primary broker %s failed: %s",
                primary_broker,
                e,
                exc_info=True,
            )

            # Try alternatives
            for fallback in decision["alternative_brokers"]:
                try:
                    logger.warning("Trying fallback broker: %s", fallback)
                    result = await self._execute_with_timeout(fallback, order)
                    return {
                        **result,
                        "routing": {
                            **decision,
                            "fallback_used": fallback,
                            "fallback_reason": str(e),
                        },
                    }
                except Exception as e2:
                    logger.error(
                        "Fallback broker %s also failed: %s",
                        fallback,
                        e2,
                        exc_info=True,
                    )
                    continue

            # All failed
            raise RuntimeError("All brokers failed to execute order") from None

    async def _execute_with_timeout(
        self,
        broker_id: str,
        order: dict,
        timeout_ms: int = 5000,
    ):
        """Execute with strict timeout"""
        return await asyncio.wait_for(
            self.brokers[broker_id].place_order(order),
            timeout=timeout_ms / 1000,
        )


class BrokerConnector:
    """Enhanced broker connector with performance tracking"""

    def __init__(self, name: str, client):
        self.name = name
        self.client = client
        self.latency_history: list[float] = []
        self.fill_history: list[dict] = []

    async def ping(self) -> float:
        """Measure round-trip latency"""
        start = datetime.now(UTC)
        await self.client.get_server_time()
        latency = (datetime.now(UTC) - start).total_seconds() * 1000
        self.latency_history.append(latency)
        if len(self.latency_history) > 1000:
            self.latency_history.pop(0)
        return latency

    async def place_order(self, order: dict) -> dict:
        """Place order with full tracking"""
        start = datetime.now(UTC)

        result = await self.client.place_order(
            symbol=order["symbol"],
            side=order["side"],
            type=order["type"],
            size=order["size"],
            price=order.get("price"),
        )

        latency = (datetime.now(UTC) - start).total_seconds() * 1000

        # Track fill
        fill_record = {
            "timestamp": datetime.now(UTC),
            "order_id": result.get("id"),
            "filled": result.get("status") == "FILLED",
            "slippage_bps": self._calculate_slippage(order, result),
            "latency_ms": latency,
        }
        self.fill_history.append(fill_record)

        return result

    def _calculate_slippage(self, order: dict, result: dict) -> float:
        """Calculate execution slippage"""
        if "price" not in order or "avg_price" not in result:
            return 0

        expected = Decimal(str(order["price"]))
        actual = Decimal(str(result["avg_price"]))

        if order["side"] == "buy":
            slippage = (actual - expected) / expected * 10000  # bps
        else:
            slippage = (expected - actual) / expected * 10000

        return float(slippage)

    async def get_recent_fills(self, hours: int = 1) -> list[dict]:
        """Get recent fill history"""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        return [f for f in self.fill_history if f["timestamp"] > cutoff]
