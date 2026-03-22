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
    payload: Any = None
    source: str = ""

    class Config:
        frozen = True

    @classmethod
    def create(cls, payload: Any, source: str = "") -> "Event":
        """Wrap an arbitrary payload in an Event."""
        return cls(
            event_type=type(payload).__name__,
            payload=payload,
            source=source,
        )


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
    Subscribers register handlers per event_type string or class.
    """

    def __init__(self):
        self._handlers: _Dict[str, _List[_Callable]] = {}
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    @staticmethod
    def _key(event_type) -> str:
        """Normalise event_type: accept string or class."""
        if isinstance(event_type, str):
            return event_type
        return getattr(event_type, "__name__", str(event_type))

    def subscribe(self, event_type, handler: _Callable):
        self._handlers.setdefault(self._key(event_type), []).append(handler)

    def unsubscribe(self, event_type, handler: _Callable):
        key = self._key(event_type)
        if key in self._handlers:
            self._handlers[key] = [
                h for h in self._handlers[key] if h is not handler
            ]

    async def publish(self, event: "Event"):
        # Match by event_type field, class name, or parent class names
        keys = set()
        et = getattr(event, "event_type", None)
        if et:
            keys.add(str(et))
        keys.add(type(event).__name__)
        for base in type(event).__mro__:
            keys.add(base.__name__)
        keys.add("*")

        handlers = []
        for k in keys:
            handlers.extend(self._handlers.get(k, []))

        for handler in handlers:
            try:
                if _asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as exc:
                _ebus_logger.error("EventBus handler error: %s", exc)

    async def emit(self, event: "Event"):
        """Alias for publish."""
        await self.publish(event)

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


class TickReceived(BaseModel):
    """Lightweight tick payload used by tests and simple consumers."""
    symbol: str
    bid: float
    ask: float
    volume: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# Additional aliases
KillSwitchTriggered = RiskEvent
PositionClosed = PositionEvent
PositionOpened = PositionEvent
SignalGenerated = SignalEvent
OrderPlaced = OrderEvent
OrderFilled = FillEvent
