from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Callable, Coroutine, Any, Optional

import structlog
from anyio import create_task_group

from hopefx.events.schemas import Event, EventType

logger = structlog.get_logger()


class EventBus:
    """Async event bus with bounded queues and backpressure handling."""

    def __init__(self, max_queue_size: int = 100000) -> None:
        self._subscribers: dict[EventType, list[Callable[[Event], Coroutine[Any, Any, None]]]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._metrics: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._dlq: Optional[Any] = None  # Dead letter queue
        self._persistence: Optional[Any] = None  # Event store

    def set_dlq(self, dlq: Any) -> None:
        """Set dead letter queue for failed events."""
        self._dlq = dlq

    def set_persistence(self, persistence: Any) -> None:
        """Set event store for persistence."""
        self._persistence = persistence

    async def start(self) -> None:
        """Start the event processor."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("event_bus.started", max_queue=max_queue_size)

    async def stop(self) -> None:
        """Stop the event processor gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Drain remaining events
        remaining = []
        while not self._queue.empty():
            try:
                remaining.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if remaining:
            logger.warning("event_bus.drain_remaining", count=len(remaining))
            if self._persistence:
                for event in remaining:
                    await self._persistence.append(event)

        logger.info("event_bus.stopped")

    async def publish(self, event: Event) -> bool:
        """Publish event to bus. Returns False if queue full (backpressure)."""
        # Add trace ID if not present
        if not event.trace_id:
            event.trace_id = str(uuid.uuid4())

        try:
            self._queue.put_nowait(event)
            self._metrics[f"published_{event.type.value}"] += 1
            
            # Persist if configured
            if self._persistence and event.priority <= 3:
                asyncio.create_task(self._persistence.append(event))
            
            return True
        except asyncio.QueueFull:
            logger.error("event_bus.queue_full", event_type=event.type.value)
            self._metrics["dropped_events"] += 1
            return False

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[Event], Coroutine[Any, Any, None]],
    ) -> Callable[[], None]:
        """Subscribe to event type. Returns unsubscribe function."""
        self._subscribers[event_type].append(handler)
        logger.debug("event_bus.subscribed", event_type=event_type.value)

        def unsubscribe() -> None:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)

        return unsubscribe

    async def _process_loop(self) -> None:
        """Main processing loop with structured concurrency."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                
                # Process based on priority
                if event.priority <= 2:
                    # Critical: process immediately
                    await self._dispatch(event)
                else:
                    # Normal: can batch
                    asyncio.create_task(self._dispatch(event))
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.exception("event_bus.process_error", error=str(e))

    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to all subscribers."""
        handlers = self._subscribers.get(event.type, [])

        if not handlers:
            return

        async with create_task_group() as tg:
            for handler in handlers:
                tg.start_soon(self._execute_handler, handler, event)

    async def _execute_handler(
        self,
        handler: Callable[[Event], Coroutine[Any, Any, None]],
        event: Event,
    ) -> None:
        """Execute handler with error isolation and retry logic."""
        max_retries = 3 if event.priority <= 5 else 1
        
        for attempt in range(max_retries):
            try:
                await handler(event)
                self._metrics[f"handled_{event.type.value}"] += 1
                return
            except Exception as e:
                logger.exception(
                    "event_bus.handler_error",
                    handler=handler.__name__,
                    event_type=event.type.value,
                    attempt=attempt + 1,
                    error=str(e),
                )
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (2 ** attempt))  # Exponential backoff
                else:
                    # Max retries reached
                    self._metrics["handler_errors"] += 1
                    
                    if self._dlq:
                        await self._dlq.enqueue(event, str(e), handler)

    def get_metrics(self) -> dict[str, int]:
        """Return current metrics snapshot."""
        return {
            **dict(self._metrics),
            "queue_size": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "subscriber_count": sum(len(h) for h in self._subscribers.values())
        }


# Global event bus instance
event_bus = EventBus(max_queue_size=200000)
