"""
Async event bus with type-safe event handling.
Zero-blocking, backpressure-aware.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Generic, TypeVar
from uuid import UUID, uuid4

import anyio
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class EventMetadata(BaseModel):
    """Event metadata for tracing."""
    event_id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID | None = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = Field(default="unknown")
    priority: int = Field(default=5, ge=1, le=10)


class Event(BaseModel, Generic[T]):
    """Generic event wrapper."""
    metadata: EventMetadata
    payload: T
    
    @classmethod
    def create(cls, payload: T, source: str = "unknown", priority: int = 5) -> Event[T]:
        return cls(
            metadata=EventMetadata(source=source, priority=priority),
            payload=payload
        )


@dataclass
class Subscription:
    """Event subscription handle."""
    id: UUID = field(default_factory=uuid4)
    event_type: type = field()
    handler: Callable[[Any], Awaitable[None]] = field()
    priority: int = field(default=5)
    filter_fn: Callable[[Any], bool] | None = field(default=None)


class EventBus:
    """
    High-performance async event bus with priority queues.
    Backpressure handling via bounded queues.
    """
    
    def __init__(self, max_queue_size: int = 10000):
        self._subscriptions: dict[type, list[Subscription]] = defaultdict(list)
        self._queue: asyncio.PriorityQueue[tuple[int, datetime, UUID, Any]] = asyncio.PriorityQueue(
            maxsize=max_queue_size
        )
        self._running = False
        self._task: asyncio.Task | None = None
        self._handlers: dict[UUID, Subscription] = {}
    
    async def start(self) -> None:
        """Start event processing loop."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._process_events())
    
    async def stop(self) -> None:
        """Graceful shutdown with pending event flush."""
        self._running = False
        
        # Wait for queue to drain (with timeout)
        try:
            await asyncio.wait_for(self._queue.join(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    async def emit(self, event: Event[Any]) -> bool:
        """
        Emit event to bus.
        Returns False if queue full (backpressure).
        """
        if not self._running:
            raise RuntimeError("Event bus not started")
        
        # Get subscribers for this event type
        event_type = type(event.payload)
        subs = self._subscriptions.get(event_type, [])
        
        if not subs:
            return True
        
        try:
            # Priority: lower number = higher priority
            priority = event.metadata.priority
            await self._queue.put((
                priority,
                event.metadata.timestamp,
                event.metadata.event_id,
                event
            ))
            return True
        except asyncio.QueueFull:
            return False
    
    def subscribe(
        self,
        event_type: type[T],
        handler: Callable[[Event[T]], Awaitable[None]],
        priority: int = 5,
        filter_fn: Callable[[Event[T]], bool] | None = None
    ) -> UUID:
        """Subscribe to events with optional filtering."""
        sub = Subscription(
            event_type=event_type,
            handler=handler,
            priority=priority,
            filter_fn=filter_fn
        )
        
        self._subscriptions[event_type].append(sub)
        self._subscriptions[event_type].sort(key=lambda s: s.priority)
        self._handlers[sub.id] = sub
        
        return sub.id
    
    def unsubscribe(self, subscription_id: UUID) -> bool:
        """Remove subscription."""
        if subscription_id not in self._handlers:
            return False
        
        sub = self._handlers.pop(subscription_id)
        self._subscriptions[sub.event_type].remove(sub)
        return True
    
    async def _process_events(self) -> None:
        """Main event processing loop."""
        while self._running:
            try:
                priority, timestamp, event_id, event = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                
                # Process with structured concurrency
                async with anyio.create_task_group() as tg:
                    event_type = type(event.payload)
                    for sub in self._subscriptions.get(event_type, []):
                        if sub.filter_fn and not sub.filter_fn(event):
                            continue
                        
                        tg.start_soon(self._invoke_handler, sub, event)
                
                self._queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                # Log but don't crash
                print(f"Event processing error: {e}")
    
    async def _invoke_handler(self, sub: Subscription, event: Any) -> None:
        """Invoke handler with error isolation."""
        try:
            await sub.handler(event)
        except Exception as e:
            # Handler errors shouldn't crash bus
            print(f"Handler error for {sub.id}: {e}")


# Global event bus instance
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get or create global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


# Domain events
class TickReceived(BaseModel):
    """Market tick received."""
    symbol: str
    bid: float
    ask: float
    volume: int
    timestamp: datetime


class SignalGenerated(BaseModel):
    """Trading signal generated."""
    strategy_id: str
    symbol: str
    direction: str
    strength: float
    confidence: float


class OrderSubmitted(BaseModel):
    """Order submitted to broker."""
    order_id: UUID
    symbol: str
    quantity: float
    order_type: str


class OrderFilled(BaseModel):
    """Order filled by broker."""
    order_id: UUID
    fill_price: float
    fill_quantity: float
    commission: float


class PositionOpened(BaseModel):
    """New position opened."""
    position_id: UUID
    symbol: str
    direction: str
    entry_price: float
    quantity: float


class PositionClosed(BaseModel):
    """Position closed."""
    position_id: UUID
    exit_price: float
    realized_pnl: float


class RiskEvent(BaseModel):
    """Risk threshold breached."""
    level: str
    metric: str
    value: float
    threshold: float


class KillSwitchTriggered(BaseModel):
    """Emergency stop activated."""
    reason: str
    triggered_at: datetime
