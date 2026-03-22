import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import anyio
import structlog
from pydantic import BaseModel

from .events import EventType

logger = structlog.get_logger()
Handler = Callable[[BaseModel], Coroutine[Any, Any, None]]


class EventBus:
    """AnyIO task group with bounded queues. No silent fails."""
    
    def __init__(self, maxsize: int = 10000) -> None:
        self._queues: dict[EventType, asyncio.Queue[BaseModel]] = {
            et: asyncio.Queue(maxsize=maxsize) for et in EventType
        }
        self._handlers: dict[EventType, list[Handler]] = {et: [] for et in EventType}
        self._tg: anyio.TaskGroup | None = None
        self._shutdown_event = asyncio.Event()
    
    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers[event_type].append(handler)
    
    async def publish(self, event_type: EventType, event: BaseModel) -> None:
        queue = self._queues[event_type]
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.error("event_bus.queue_full", event_type=event_type.value, event=event)
            raise RuntimeError(f"Queue full for {event_type}")
    
    async def _process_queue(self, event_type: EventType) -> None:
        queue = self._queues[event_type]
        while not self._shutdown_event.is_set():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                handlers = self._handlers[event_type]
                async with anyio.create_task_group() as tg:
                    for handler in handlers:
                        tg.start_soon(self._wrap_handler, handler, event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.exception("event_bus.process_error", error=str(e))
    
    async def _wrap_handler(self, handler: Handler, event: BaseModel) -> None:
        try:
            await handler(event)
        except Exception as e:
            logger.exception("event_bus.handler_error", 
                           handler=handler.__name__, 
                           error=str(e))
    
    async def start(self) -> None:
        async with anyio.create_task_group() as tg:
            self._tg = tg
            for event_type in EventType:
                tg.start_soon(self._process_queue, event_type)
            await self._shutdown_event.wait()
    
    def shutdown(self) -> None:
        self._shutdown_event.set()
