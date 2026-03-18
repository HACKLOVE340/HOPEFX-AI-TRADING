"""Event sourcing and persistence for audit trails."""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

import asyncpg
from hopefx.config.settings import settings
from hopefx.events.schemas import Event


class EventStore:
    """PostgreSQL-backed event store for replay and audit."""

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    async def initialize(self) -> None:
        """Create connection pool."""
        self._pool = await asyncpg.create_pool(settings.database_url)

    async def append(self, event: Event) -> None:
        """Persist event to store."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_store (id, type, timestamp, payload, source, priority)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                event.id,
                event.type.value,
                event.timestamp,
                json.dumps(event.payload),
                event.source,
                event.priority
            )

    async def get_stream(
        self,
        event_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Event]:
        """Query event stream with filters."""
        # Implementation for replay
        pass

    async def replay(
        self,
        start_time: datetime,
        handler: callable
    ) -> None:
        """Replay events from point in time."""
        events = await self.get_stream(start_time=start_time)
        for event in events:
            await handler(event)
