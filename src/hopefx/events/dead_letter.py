"""Dead letter queue for failed event processing."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, List

from hopefx.events.schemas import Event


class DeadLetterQueue:
    """Store and retry failed events."""

    def __init__(self, max_retries: int = 3, retry_delays: List[int] = None) -> None:
        self.max_retries = max_retries
        self.retry_delays = retry_delays or [60, 300, 900]  # 1min, 5min, 15min
        self._failed_events: Dict[str, dict] = {}
        self._retry_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start retry processor."""
        self._retry_task = asyncio.create_task(self._retry_loop())

    async def enqueue(self, event: Event, error: str, handler: callable) -> None:
        """Add failed event to DLQ."""
        event_id = event.id
        attempt = self._failed_events.get(event_id, {}).get('attempts', 0) + 1

        if attempt > self.max_retries:
            await self._permanent_failure(event, error)
            return

        self._failed_events[event_id] = {
            'event': event,
            'error': error,
            'handler': handler,
            'attempts': attempt,
            'next_retry': datetime.utcnow().timestamp() + self.retry_delays[attempt - 1]
        }

    async def _retry_loop(self) -> None:
        """Process retry queue."""
        while True:
            now = datetime.utcnow().timestamp()
            ready = [
                (eid, data) for eid, data in self._failed_events.items()
                if data['next_retry'] <= now
            ]

            for event_id, data in ready:
                try:
                    await data['handler'](data['event'])
                    del self._failed_events[event_id]
                except Exception as e:
                    await self.enqueue(data['event'], str(e), data['handler'])

            await asyncio.sleep(10)

    async def _permanent_failure(self, event: Event, error: str) -> None:
        """Handle permanent failure - alert ops team."""
        # Send to monitoring
        # Create incident ticket
        # Archive for analysis
        pass
