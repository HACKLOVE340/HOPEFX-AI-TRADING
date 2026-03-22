from __future__ import annotations

import json
import zlib
from datetime import datetime, timedelta
from typing import List, Optional, Any, Callable

import asyncpg
import structlog

from hopefx.config.settings import settings
from hopefx.events.schemas import Event, EventType

logger = structlog.get_logger()


class EventStore:
    """PostgreSQL-backed event store with compression and archival."""

    def __init__(self, compression: bool = True) -> None:
        self._pool: Optional[asyncpg.Pool] = None
        self._compression = compression
        self._snapshot_interval = 1000
        self._archival_threshold_days = 90

    async def initialize(self) -> None:
        """Create connection pool and tables."""
        self._pool = await asyncpg.create_pool(
            settings.async_database_url,
            min_size=5,
            max_size=20
        )
        
        # Create tables if not exist
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS event_store (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    payload BYTEA NOT NULL,
                    source TEXT,
                    priority INTEGER,
                    trace_id TEXT,
                    correlation_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_event_type_time 
                ON event_store(type, timestamp);
                
                CREATE INDEX IF NOT EXISTS idx_event_trace 
                ON event_store(trace_id);
                
                CREATE TABLE IF NOT EXISTS event_snapshots (
                    aggregate_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL,
                    state BYTEA NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                
                CREATE TABLE IF NOT EXISTS event_archive (
                    LIKE event_store INCLUDING ALL,
                    archived_at TIMESTAMPTZ DEFAULT NOW()
                ) PARTITION BY RANGE (timestamp);
            """)

    async def append(self, event: Event) -> None:
        """Persist event to store with optional compression."""
        payload = json.dumps(event.payload, default=str).encode()
        
        if self._compression:
            payload = zlib.compress(payload)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_store 
                (id, type, timestamp, payload, source, priority, trace_id, correlation_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                event.id,
                event.type.value,
                event.timestamp,
                payload,
                event.source,
                event.priority,
                event.trace_id,
                event.correlation_id
            )

    async def get_stream(
        self,
        event_type: Optional[EventType] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        trace_id: Optional[str] = None,
        limit: int = 1000,
        decompress: bool = True
    ) -> List[Event]:
        """Query event stream with filters."""
        conditions = []
        params = []
        param_idx = 1

        if event_type:
            conditions.append(f"type = ${param_idx}")
            params.append(event_type.value)
            param_idx += 1

        if start_time:
            conditions.append(f"timestamp >= ${param_idx}")
            params.append(start_time)
            param_idx += 1

        if end_time:
            conditions.append(f"timestamp <= ${param_idx}")
            params.append(end_time)
            param_idx += 1

        if trace_id:
            conditions.append(f"trace_id = ${param_idx}")
            params.append(trace_id)
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        
        query = f"""
            SELECT id, type, timestamp, payload, source, priority, trace_id, correlation_id
            FROM event_store
            WHERE {where_clause}
            ORDER BY timestamp
            LIMIT ${param_idx}
        """
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        events = []
        for row in rows:
            payload = row['payload']
            if decompress and self._compression:
                payload = zlib.decompress(payload)
            
            events.append(Event(
                id=row['id'],
                type=EventType(row['type']),
                timestamp=row['timestamp'],
                payload=json.loads(payload),
                source=row['source'],
                priority=row['priority'],
                trace_id=row['trace_id'],
                correlation_id=row['correlation_id']
            ))

        return events

    async def create_snapshot(self, aggregate_id: str, sequence: int, state: Any) -> None:
        """Create snapshot for fast replay."""
        state_bytes = json.dumps(state, default=str).encode()
        if self._compression:
            state_bytes = zlib.compress(state_bytes)

        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO event_snapshots (aggregate_id, sequence, state)
                VALUES ($1, $2, $3)
                ON CONFLICT (aggregate_id) 
                DO UPDATE SET sequence = $2, state = $3, created_at = NOW()
            """, aggregate_id, sequence, state_bytes)

    async def get_latest_snapshot(self, aggregate_id: str) -> Optional[dict]:
        """Get latest snapshot for aggregate."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT sequence, state FROM event_snapshots WHERE aggregate_id = $1",
                aggregate_id
            )

        if not row:
            return None

        state = row['state']
        if self._compression:
            state = zlib.decompress(state)

        return {
            "sequence": row['sequence'],
            "state": json.loads(state)
        }

    async def replay_from_snapshot(
        self,
        aggregate_id: str,
        handler: Callable[[Event], Any]
    ) -> Any:
        """Fast replay using snapshot + delta."""
        # Get snapshot
        snapshot = await self.get_latest_snapshot(aggregate_id)
        
        if snapshot:
            # Apply snapshot
            state = await handler.apply_snapshot(snapshot["state"])
            start_sequence = snapshot["sequence"]
        else:
            state = None
            start_sequence = 0

        # Get events after snapshot
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, type, timestamp, payload, source, priority, trace_id, correlation_id
                FROM event_store
                WHERE id LIKE $1 AND CAST(SUBSTRING(id FROM '[0-9]+') AS INTEGER) > $2
                ORDER BY timestamp
            """, f"{aggregate_id}%", start_sequence)

        # Replay events
        for row in rows:
            payload = row['payload']
            if self._compression:
                payload = zlib.decompress(payload)

            event = Event(
                id=row['id'],
                type=EventType(row['type']),
                timestamp=row['timestamp'],
                payload=json.loads(payload),
                source=row['source'],
                priority=row['priority'],
                trace_id=row['trace_id'],
                correlation_id=row['correlation_id']
            )
            
            state = await handler(event)

        return state

    async def compact_events(self, before_date: datetime) -> int:
        """Archive old events to cold storage."""
        async with self._pool.acquire() as conn:
            # Move to archive table
            result = await conn.execute("""
                WITH moved AS (
                    DELETE FROM event_store
                    WHERE timestamp < $1
                    RETURNING *
                )
                INSERT INTO event_archive
                SELECT *, NOW() FROM moved
            """, before_date)

        # Also upload to S3/Glacier for long-term
        # Implementation depends on cloud provider
        
        return int(result.split()[-1]) if result else 0

    async def get_event_statistics(self, days: int = 7) -> dict:
        """Get event statistics for monitoring."""
        start = datetime.utcnow() - timedelta(days=days)
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT type, COUNT(*) as count, 
                       AVG(EXTRACT(EPOCH FROM (timestamp - LAG(timestamp) OVER (ORDER BY timestamp)))) as avg_interval
                FROM event_store
                WHERE timestamp > $1
                GROUP BY type
            """, start)

        return {
            row['type']: {
                'count': row['count'],
                'avg_interval_seconds': row['avg_interval']
            }
            for row in rows
        }


# Global instance
event_store = EventStore()
