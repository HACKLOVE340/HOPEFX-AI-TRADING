# src/hopefx/core/events.py
"""
Production-grade event bus with pydantic events, asyncio.Queue,
and anyio task groups. Zero blocking in hot paths.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Generic, TypeVar

import anyio
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

T = TypeVar("T", bound="Event")


class EventPriority(Enum):
    """Event processing priority."""
    CRITICAL = 0   # Risk events, circuit breakers
    HIGH = 1       # Order fills, position updates
    NORMAL = 2     # Market data, signals
    LOW = 3        # Analytics, logging
    BACKGROUND = 4 # ML training, reports


class Event(BaseModel):
    """Base event with metadata."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    priority: EventPriority = EventPriority.NORMAL
    source: str = "unknown"
    trace_id: str | None = None
    
    class Config:
        frozen = True


class TickEvent(Event):
    """Market tick data."""
    symbol: str
    bid: float
    ask: float
    volume: float = 0.0
    timestamp_exchange: float | None = None


class BarEvent(Event):
    """OHLCV bar completion."""
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class SignalEvent(Event):
    """Trading signal generated."""
    symbol: str
    direction: Literal["LONG", "SHORT", "FLAT"]
    confidence: float
    strategy: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderEvent(Event):
    """Order lifecycle event."""
    order_id: str
    action: Literal["SUBMITTED", "FILLED", "PARTIAL", "CANCELLED", "REJECTED"]
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: float | None = None
    slippage: float = 0.0


class RiskEvent(Event):
    """Risk threshold breach."""
    event_type: Literal["POSITION_LIMIT", "DRAWDOWN", "VAR_LIMIT", "LATENCY"]
    severity: Literal["WARNING", "CRITICAL", "EMERGENCY"]
    current_value: float
    threshold: float
    action_taken: str | None = None


class EventHandler(ABC, Generic[T]):
    """Abstract event handler."""
    
    @property
    @abstractmethod
    def event_type(self) -> type[T]:
        """Event type this handler processes."""
        pass
    
    @abstractmethod
    async def handle(self, event: T) -> None:
        """Process the event."""
        pass
    
    async def on_error(self, event: T, error: Exception) -> None:
        """Handle processing errors."""
        logger.error(
            "event_handler_error",
            event_type=event.__class__.__name__,
            event_id=event.event_id,
            error=str(error),
            handler=self.__class__.__name__
        )


class EventBus:
    """
    High-performance async event bus with priority queues,
    back-pressure handling, and circuit breaker integration.
    """
    
    def __init__(
        self,
        max_queue_size: int = 10000,
        max_handlers_per_event: int = 100
    ) -> None:
        self._queues: dict[EventPriority, asyncio.Queue[Event]] = {
            priority: asyncio.Queue(maxsize=max_queue_size)
            for priority in EventPriority
        }
        self._handlers: dict[type[Event], list[EventHandler]] = defaultdict(list)
        self._running = False
        self._task_group: anyio.TaskGroup | None = None
        self._metrics = {
            "events_published": 0,
            "events_processed": 0,
            "events_dropped": 0,
            "errors": 0,
        }
        self._max_handlers = max_handlers_per_event
    
    def subscribe(self, handler: EventHandler) -> None:
        """Register an event handler."""
        event_type = handler.event_type
        if len(self._handlers[event_type]) >= self._max_handlers:
            raise RuntimeError(f"Max handlers reached for {event_type.__name__}")
        self._handlers[event_type].append(handler)
        logger.info(
            "handler_subscribed",
            event_type=event_type.__name__,
            handler=handler.__class__.__name__
        )
    
    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove an event handler."""
        event_type = handler.event_type
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)
    
    async def publish(self, event: Event) -> bool:
        """
        Publish event to appropriate priority queue.
        Returns False if queue is full (back-pressure).
        """
        queue = self._queues[event.priority]
        try:
            queue.put_nowait(event)
            self._metrics["events_published"] += 1
            return True
        except asyncio.QueueFull:
            self._metrics["events_dropped"] += 1
            logger.warning(
                "event_dropped_queue_full",
                event_type=event.__class__.__name__,
                priority=event.priority.name
            )
            return False
    
    async def start(self) -> None:
        """Start event processing loops."""
        self._running = True
        async with anyio.create_task_group() as tg:
            self._task_group = tg
            for priority in EventPriority:
                tg.start_soon(self._process_queue, priority)
            logger.info("event_bus_started")
    
    async def stop(self) -> None:
        """Graceful shutdown with drain."""
        self._running = False
        
        # Drain queues with timeout
        for priority in EventPriority:
            queue = self._queues[priority]
            try:
                await asyncio.wait_for(queue.join(), timeout=5.0)
            except asyncio.TimeoutError:
                remaining = queue.qsize()
                logger.warning(
                    "queue_drain_timeout",
                    priority=priority.name,
                    remaining=remaining
                )
        
        if self._task_group:
            self._task_group.cancel_scope.cancel()
        
        logger.info("event_bus_stopped", metrics=self._metrics)
    
    async def _process_queue(self, priority: EventPriority) -> None:
        """Process events from a priority queue."""
        queue = self._queues[priority]
        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                await self._dispatch(event)
                queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._metrics["errors"] += 1
                logger.error("queue_processing_error", error=str(e))
    
    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to all registered handlers."""
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        
        if not handlers:
            return
        
        # Execute handlers concurrently with error isolation
        async with anyio.create_task_group() as tg:
            for handler in handlers:
                tg.start_soon(self._execute_handler, handler, event)
        
        self._metrics["events_processed"] += 1
    
    async def _execute_handler(self, handler: EventHandler, event: Event) -> None:
        """Execute single handler with error handling."""
        try:
            await handler.handle(event)
        except Exception as e:
            self._metrics["errors"] += 1
            await handler.on_error(event, e)


# Global event bus instance
_event_bus: EventBus | None = None


async def get_event_bus() -> EventBus:
    """Get or create global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """Reset event bus (for testing)."""
    global _event_bus
    _event_bus = None
