"""Immutable event sourcing for audit."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import aioredis


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    event_type: str
    aggregate_id: str
    sequence: int
    timestamp: datetime
    payload: dict[str, Any]
    previous_hash: str
    
    def compute_hash(self) -> str:
        """Compute SHA256 of event."""
        data = f"{self.event_id}:{self.sequence}:{self.timestamp.isoformat()}:{json.dumps(self.payload, sort_keys=True)}:{self.previous_hash}"
        return hashlib.sha256(data.encode()).hexdigest()


class EventStore:
    """Append-only event store with integrity checks."""
    
    def __init__(self, redis_url: str):
        self.redis: aioredis.Redis | None = None
        self._url = redis_url
        self._current_hash = "0" * 64  # Genesis
    
    async def initialize(self):
        self.redis = aioredis.from_url(self._url, decode_responses=True)
        # Recover last hash
        last = await self.redis.lindex("events", -1)
        if last:
            event = json.loads(last)
            self._current_hash = event["hash"]
    
    async def append(self, event: DomainEvent) -> str:
        """Append event with chain hash."""
        event_hash = event.compute_hash()
        chain_hash = hashlib.sha256(
            f"{self._current_hash}:{event_hash}".encode()
        ).hexdigest()
        
        stored = {
            **asdict(event),
            "hash": chain_hash,
            "verified": True
        }
        
        # Atomic append
        pipe = self.redis.pipeline()
        pipe.rpush("events", json.dumps(stored))
        pipe.rpush(f"events:{event.aggregate_id}", json.dumps(stored))
        await pipe.execute()
        
        self._current_hash = chain_hash
        return chain_hash
    
    async def get_stream(self, aggregate_id: str) -> list[DomainEvent]:
        """Get event stream for aggregate."""
        events = await self.redis.lrange(f"events:{aggregate_id}", 0, -1)
        return [json.loads(e) for e in events]
    
    async def verify_integrity(self) -> bool:
        """Verify chain integrity."""
        all_events = await self.redis.lrange("events", 0, -1)
        prev_hash = "0" * 64
        
        for event_json in all_events:
            event = json.loads(event_json)
            computed = hashlib.sha256(
                f"{prev_hash}:{DomainEvent(**{k:v for k,v in event.items() if k not in ['hash', 'verified']}).compute_hash()}"
            ).hexdigest()
            
            if computed != event["hash"]:
                return False
            prev_hash = event["hash"]
        
        return True
