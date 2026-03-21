"""Pydantic-based event definitions for the event bus."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Any, Generic, TypeVar

from pydantic import BaseModel, Field

_T = TypeVar("_T")

from src.core.types import (
    Tick, Order, Fill, Position, 
    SignalType, OrderId, PositionId, Symbol
)


class Event(BaseModel, Generic[_T]):
    """Base event — supports Event[PayloadType] generic syntax."""
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


# ── Aliases expected by tests ─────────────────────────────────────────────────
import asyncio as _asyncio
import logging as _logging
from typing import Callable as _Callable, Dict as _Dict, List as _List

_ebus_logger = _logging.getLogger(__name__)


class EventBus:
    """
    Simple async pub/sub event bus.
    Subscribers register handlers per event_type string.
    """

    def __init__(self):
        self._handlers: _Dict[str, _List[_Callable]] = {}

    def subscribe(self, event_type: str, handler: _Callable):
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: _Callable):
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h is not handler
            ]

    async def publish(self, event: "Event"):
        event_type = getattr(event, "event_type", type(event).__name__)
        handlers = self._handlers.get(event_type, []) + self._handlers.get("*", [])
        for handler in handlers:
            try:
                if _asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as exc:
                _ebus_logger.error("EventBus handler error for %s: %s", event_type, exc)

    def publish_sync(self, event: "Event"):
        """Fire-and-forget from sync context."""
        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.publish(event))
            else:
                loop.run_until_complete(self.publish(event))
        except Exception as exc:
            _ebus_logger.error("EventBus publish_sync error: %s", exc)


# Module-level singleton
_default_bus = EventBus()


def get_event_bus() -> EventBus:
    """Return the module-level EventBus singleton."""
    return _default_bus


# TickReceived is an alias for TickEvent
TickReceived = TickEvent

# Additional aliases
KillSwitchTriggered = RiskEvent
PositionClosed = PositionEvent
PositionOpened = PositionEvent
SignalGenerated = SignalEvent
OrderPlaced = OrderEvent
OrderFilled = FillEvent
