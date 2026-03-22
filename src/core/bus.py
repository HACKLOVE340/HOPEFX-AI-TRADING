"""AnyIO-based event bus with bounded queues and task groups."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import anyio
import structlog
from anyio import TASK_STATUS_IGNORED, CancelScope, create_task_group
from anyio.abc import TaskGroup, TaskStatus

from src.core.events import Event, TradingEvent
from src.core.exceptions import EventBusError

logger = structlog.get_logger()
T = TypeVar("T", bound=Event)


class BoundedEventQueue:
    """Bounded queue with backpressure handling."""
    
    def __init__(self, maxsize: int = 10000, name: str = "default") -> None:
        self._queue: asyncio.Queue[TradingEvent] = asyncio.Queue(maxsize=maxsize)
        self._name = name
        self._dropped = 0
        self._processed = 0
    
    async def put(self, event: TradingEvent, block: bool = True, timeout: float = 1.0) -> bool:
        """Put event with backpressure."""
        try:
            if block:
                await asyncio.wait_for(self._queue.put(event), timeout=timeout)
            else:
                self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 100 == 1:
                logger.warning(f"Queue {self._name} full, dropped {self._dropped} events")
            return False
        except asyncio.TimeoutError:
            self._dropped += 1
            return False
    
    async def get(self) -> TradingEvent:
        """Get event."""
        event = await self._queue.get()
        self._processed += 1
        return event
    
    def task_done(self) -> None:
        self._queue.task_done()
    
    @property
    def size(self) -> int:
        return self._queue.qsize()
    
    @property
    def stats(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "size": self.size,
            "maxsize": self._queue.maxsize,
            "processed": self._processed,
            "dropped": self._dropped,
        }


class EventBus:
    """Central event bus with typed subscribers."""
    
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Any], Coroutine[Any, Any, None]]]] = {}
        self._queues: dict[str, BoundedEventQueue] = {}
        self._task_group: TaskGroup | None = None
        self._running = False
        self._lock = asyncio.Lock()
    
    async def start(self, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        """Start the event bus."""
        async with self._lock:
            if self._running:
                return
            
            self._task_group = create_task_group()
            await self._task_group.__aenter__()
            self._running = True
            task_status.started()
            logger.info("Event bus started")
    
    async def stop(self) -> None:
        """Stop the event bus."""
        async with self._lock:
            if not self._running or not self._task_group:
                return
            
            self._task_group.cancel_scope.cancel()
            await self._task_group.__aexit__(None, None, None)
            self._running = False
            logger.info("Event bus stopped")
    
    def subscribe(
        self, 
        event_type: type[T], 
        handler: Callable[[T], Coroutine[Any, Any, None]],
        queue_size: int = 1000
    ) -> None:
        """Subscribe to event type."""
        type_name = event_type.__name__
        
        if type_name not in self._subscribers:
            self._subscribers[type_name] = []
            self._queues[type_name] = BoundedEventQueue(maxsize=queue_size, name=type_name)
        
        self._subscribers[type_name].append(handler)
        
        # Start consumer task if running
        if self._running and self._task_group:
            self._task_group.start_soon(self._consume, type_name)
        
        logger.debug(f"Subscribed handler to {type_name}")
    
    async def publish(self, event: TradingEvent) -> bool:
        """Publish event to all subscribers."""
        type_name = type(event).__name__
        
        if type_name not in self._queues:
            # No subscribers, drop silently
            return False
        
        queue = self._queues[type_name]
        return await queue.put(event)
    
    async def _consume(self, type_name: str) -> None:
        """Consume events from queue."""
        queue = self._queues[type_name]
        handlers = self._subscribers[type_name]
        
        with CancelScope() as scope:
            while True:
                try:
                    event = await queue.get()
                    
                    # Fan out to all handlers concurrently
                    async with create_task_group() as tg:
                        for handler in handlers:
                            tg.start_soon(self._safe_handler, handler, event)
                    
                    queue.task_done()
                    
                except anyio.get_cancelled_exc_class():
                    break
                except Exception as e:
                    logger.error(f"Error consuming {type_name}: {e}")
    
    async def _safe_handler(
        self, 
        handler: Callable[[Any], Coroutine[Any, Any, None]], 
        event: TradingEvent
    ) -> None:
        """Wrap handler with error handling."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Handler failed for {type(event).__name__}: {e}", exc_info=True)
    
    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        return {name: queue.stats for name, queue in self._queues.items()}


# Global event bus instance
event_bus = EventBus()
