"""Pydantic-based event definitions for the event bus."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Any

from pydantic import BaseModel, Field

from src.core.types import (
    Tick, Order, Fill, Position, 
    SignalType, OrderId, PositionId, Symbol
)


class Event(BaseModel):
    """Base event."""
    event_id: str = Field(default_factory=lambda: f"evt_{datetime.utcnow().timestamp()}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_type: str
    
    class Config:
        frozen = True


class TickEvent(Event):
    """New market tick."""
    event_type: Literal["TICK"] = "TICK"
    tick: Tick


class SignalEvent(Event):
    """Trading signal from brain."""
    event_type: Literal["SIGNAL"] = "SIGNAL"
    symbol: Symbol
    signal: SignalType
    confidence: float = Field(..., ge=0.0, le=1.0)
    predicted_price: Decimal | None = None
    features: dict[str, float] = Field(default_factory=dict)


class OrderEvent(Event):
    """Order state change."""
    event_type: Literal["ORDER"] = "ORDER"
    order: Order
    previous_status: str | None = None


class FillEvent(Event):
    """Order fill/execution."""
    event_type: Literal["FILL"] = "FILL"
    fill: Fill


class PositionEvent(Event):
    """Position update."""
    event_type: Literal["POSITION"] = "POSITION"
    position: Position
    action: Literal["OPENED", "UPDATED", "CLOSED"]


class RiskEvent(Event):
    """Risk limit breach."""
    event_type: Literal["RISK"] = "RISK"
    risk_type: Literal["VAR_LIMIT", "POSITION_LIMIT", "DAILY_LOSS", "CIRCUIT_BREAKER"]
    severity: Literal["WARNING", "CRITICAL", "FATAL"]
    message: str
    metrics: dict[str, Any]


class DriftEvent(Event):
    """Model drift detected."""
    event_type: Literal["DRIFT"] = "DRIFT"
    model_id: str
    drift_score: float
    metric: Literal["KS", "PSI", "AD"]
    threshold: float


class HealthEvent(Event):
    """Component health status."""
    event_type: Literal["HEALTH"] = "HEALTH"
    component: str
    status: Literal["HEALTHY", "DEGRADED", "UNHEALTHY"]
    latency_ms: float | None = None
    error_count: int = 0


# Union type for type hints
TradingEvent = TickEvent | SignalEvent | OrderEvent | FillEvent | PositionEvent | RiskEvent | DriftEvent | HealthEvent
