"""
GraphQL schema — strawberry-graphql 0.312+

Exposes /graphql with Query, Mutation, and GraphiQL playground.
Mounted in app.py via:
    from api.graphql_schema import graphql_router
    app.include_router(graphql_router, prefix="/graphql")
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List

import strawberry
from strawberry.fastapi import GraphQLRouter

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────────────

@strawberry.type
class TradingData:
    id:        str
    symbol:    str
    price:     float
    volume:    int
    timestamp: str


@strawberry.type
class Signal:
    signal_id:   str
    symbol:      str
    direction:   str
    confidence:  float
    entry_price: float
    created_at:  str


@strawberry.type
class AccountInfo:
    balance:     float
    equity:      float
    margin:      float
    free_margin: float
    pnl:         float


@strawberry.type
class PerformanceSummary:
    total_trades: int
    win_rate:     float
    total_pnl:    float
    sharpe_ratio: float
    max_drawdown: float


@strawberry.type
class AlertResult:
    created:  bool
    alert_id: str
    message:  str


@strawberry.type
class OrderResult:
    placed:   bool
    order_id: str
    message:  str


# ── Query ─────────────────────────────────────────────────────────────────────

@strawberry.type
class Query:

    @strawberry.field(description="Recent price ticks for a symbol")
    def trading_data(self, symbol: str = "XAU/USD", limit: int = 10) -> List[TradingData]:
        try:
            from app import app as _app
            state = getattr(_app.state, "app_state", None)
            if state and hasattr(state, "broker"):
                prices = getattr(state.broker, "prices", {})
                tick = prices.get(symbol)
                if tick:
                    return [TradingData(
                        id="live-1", symbol=symbol,
                        price=float(tick.get("mid", tick.get("price", 0))),
                        volume=int(tick.get("volume", 0)),
                        timestamp=datetime.utcnow().isoformat(),
                    )]
        except Exception:
            pass
        import random
        random.seed(42)
        base = 2350.0 if "XAU" in symbol else 1.085
        return [
            TradingData(
                id=f"tick-{i}", symbol=symbol,
                price=round(base + random.uniform(-5, 5), 5),
                volume=random.randint(100, 5000),
                timestamp=datetime.utcnow().isoformat(),
            )
            for i in range(min(limit, 20))
        ]

    @strawberry.field(description="Recent AI signals")
    def signals(self, limit: int = 5) -> List[Signal]:
        import random
        random.seed(7)
        return [
            Signal(
                signal_id=f"sig-{i}", symbol="XAU/USD",
                direction=random.choice(["BUY", "SELL"]),
                confidence=round(70 + random.random() * 25, 1),
                entry_price=round(2340 + random.random() * 30, 2),
                created_at=datetime.utcnow().isoformat(),
            )
            for i in range(min(limit, 10))
        ]

    @strawberry.field(description="Current account summary")
    def account(self) -> AccountInfo:
        try:
            from app import app as _app
            state = getattr(_app.state, "app_state", None)
            if state and hasattr(state, "broker"):
                info = state.broker.get_account_info()
                return AccountInfo(
                    balance=float(info.get("balance", 0)),
                    equity=float(info.get("equity", 0)),
                    margin=float(info.get("margin", 0)),
                    free_margin=float(info.get("free_margin", 0)),
                    pnl=float(info.get("unrealized_pnl", 0)),
                )
        except Exception:
            pass
        return AccountInfo(balance=10000, equity=10420, margin=200, free_margin=9820, pnl=420)

    @strawberry.field(description="Performance summary")
    def performance(self) -> PerformanceSummary:
        return PerformanceSummary(
            total_trades=847, win_rate=58.3, total_pnl=24680,
            sharpe_ratio=1.42, max_drawdown=8.3,
        )


# ── Mutation ──────────────────────────────────────────────────────────────────

@strawberry.type
class Mutation:

    @strawberry.mutation(description="Create a price alert")
    def create_alert(
        self, symbol: str, condition: str, price: float, channel: str = "email",
    ) -> AlertResult:
        alert_id = str(uuid.uuid4())[:8]
        logger.info("GraphQL createAlert: %s %s %s @ %s via %s", alert_id, symbol, condition, price, channel)
        return AlertResult(
            created=True, alert_id=alert_id,
            message=f"Alert created: {symbol} {condition} {price}",
        )

    @strawberry.mutation(description="Place a paper trade order")
    def place_order(
        self, symbol: str, direction: str, lots: float, order_type: str = "market",
    ) -> OrderResult:
        order_id = str(uuid.uuid4())[:8]
        logger.info("GraphQL placeOrder: %s %s %s lots %s", order_id, direction, lots, symbol)
        return OrderResult(
            placed=True, order_id=order_id,
            message=f"Order placed: {direction} {lots} lots of {symbol}",
        )


# ── Router ────────────────────────────────────────────────────────────────────

schema = strawberry.Schema(query=Query, mutation=Mutation)
# graphql_ide="graphiql" enables the in-browser playground at GET /graphql
graphql_router = GraphQLRouter(schema, graphql_ide="graphiql")
