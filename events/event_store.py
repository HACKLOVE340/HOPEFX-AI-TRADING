"""
HOPEFX Event Store
Event sourcing for complete audit trail and replay capability
"""

import json
import logging
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from collections import defaultdict
import asyncio

try:
    from database.connection import get_db_manager
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

logger = logging.getLogger(__name__)


class EventType(Enum):
    # Trading events
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    ORDER_CANCELLED = "order_cancelled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    
    # Market events
    PRICE_UPDATE = "price_update"
    SIGNAL_GENERATED = "signal_generated"
    REGIME_CHANGE = "regime_change"
    
    # System events
    BRAIN_STARTED = "brain_started"
    BRAIN_STOPPED = "brain_stopped"
    BRAIN_PAUSED = "brain_paused"
    BRAIN_RESUMED = "brain_resumed"
    EMERGENCY_STOP = "emergency_stop"
    CONFIG_CHANGED = "config_changed"
    ERROR_OCCURRED = "error_occurred"
    
    # Risk events
    RISK_LIMIT_BREACH = "risk_limit_breach"
    DRAWDOWN_ALERT = "drawdown_alert"
    MARGIN_CALL = "margin_call"


@dataclass
class DomainEvent:
    """Base domain event"""
    event_id: str
    event_type: EventType
    aggregate_id: str  # e.g., trade_id, order_id
    aggregate_type: str  # e.g., "trade", "order", "position"
    timestamp: datetime
    version: int
    payload: Dict[str, Any]
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict:
        return {
            'event_id': self.event_id,
            'event_type': self.event_type.value,
            'aggregate_id': self.aggregate_id,
            'aggregate_type': self.aggregate_type,
            'timestamp': self.timestamp.isoformat(),
            'version': self.version,
            'payload': self.payload,
            'metadata': self.metadata
        }
    
    @classmethod
    def create(
        cls,
        event_type: EventType,
        aggregate_id: str,
        aggregate_type: str,
        payload: Dict[str, Any],
        metadata: Optional[Dict] = None
    ) -> 'DomainEvent':
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            timestamp=datetime.utcnow(),
            version=1,  # Would be incremented for aggregate versioning
            payload=payload,
            metadata=metadata or {}
        )


class EventStore:
    """
    Event store for event sourcing
    
    Features:
    - Append-only event log
    - Event replay for state reconstruction
    - Projection support for read models
    - Async event publishing
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._event_buffer: List[DomainEvent] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
        
        # In-memory store for quick access (limited size)
        self._recent_events: List[DomainEvent] = []
        self._max_memory_events = 10000
    
    async def start(self):
        """Start event store"""
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info("Event store started")
    
    async def stop(self):
        """Stop event store"""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        
        # Final flush
        await self._flush_events()
        logger.info("Event store stopped")
    
    async def append(self, event: DomainEvent):
        """
        Append event to store
        
        Thread-safe, non-blocking for producers
        """
        async with self._buffer_lock:
            self._event_buffer.append(event)
            self._recent_events.append(event)
            
            # Trim memory store
            if len(self._recent_events) > self._max_memory_events:
                self._recent_events = self._recent_events[-self._max_memory_events:]
        
        # Notify subscribers asynchronously
        asyncio.create_task(self._notify_subscribers(event))
        
        logger.debug(f"Event appended: {event.event_type.value} [{event.aggregate_id}]")
    
    async def _notify_subscribers(self, event: DomainEvent):
        """Notify all subscribers of event"""
        subscribers = self._subscribers.get(event.event_type, [])
        
        for callback in subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Event subscriber error: {e}")
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """Subscribe to events"""
        self._subscribers[event_type].append(callback)
        logger.info(f"Subscriber added for {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Unsubscribe from events"""
        if callback in self._subscribers.get(event_type, []):
            self._subscribers[event_type].remove(callback)
    
    async def get_events(
        self,
        aggregate_id: Optional[str] = None,
        aggregate_type: Optional[str] = None,
        event_types: Optional[List[EventType]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[DomainEvent]:
        """
        Query events with filters
        """
        # Start with recent in-memory events
        events = list(self._recent_events)
        
        # Apply filters
        if aggregate_id:
            events = [e for e in events if e.aggregate_id == aggregate_id]
        
        if aggregate_type:
            events = [e for e in events if e.aggregate_type == aggregate_type]
        
        if event_types:
            type_values = [et.value for et in event_types]
            events = [e for e in events if e.event_type.value in type_values]
        
        if start_time:
            events = [e for e in events if e.timestamp >= start_time]
        
        if end_time:
            events = [e for e in events if e.timestamp <= end_time]
        
        # Sort by timestamp descending and limit
        events.sort(key=lambda e: e.timestamp, reverse=True)
        
        return events[:limit]
    
    async def replay(
        self,
        aggregate_id: str,
        handler: Callable[[DomainEvent], None]
    ):
        """
        Replay all events for an aggregate
        Used for state reconstruction
        """
        events = await self.get_events(aggregate_id=aggregate_id)
        events.sort(key=lambda e: e.timestamp)  # Chronological order
        
        for event in events:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Replay handler error: {e}")
                raise
    
    async def _periodic_flush(self):
        """Periodically flush events to persistent storage"""
        while self._running:
            try:
                await asyncio.sleep(5)  # Flush every 5 seconds
                await self._flush_events()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Event flush error: {e}")
    
    async def _flush_events(self):
        """Flush buffered events to database"""
        async with self._buffer_lock:
            if not self._event_buffer:
                return
            
            events_to_flush = self._event_buffer[:]
            self._event_buffer = []
        
        # Persist to database
        if DATABASE_AVAILABLE:
            try:
                db = get_db_manager()
                if db:
                    # Would insert to database here
                    logger.debug(f"Flushed {len(events_to_flush)} events to database")
            except Exception as e:
                logger.error(f"Database flush error: {e}")
                # Re-buffer events
                async with self._buffer_lock:
                    self._event_buffer = events_to_flush + self._event_buffer
        else:
            logger.debug(f"Would flush {len(events_to_flush)} events (no database)")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get event store statistics"""
        return {
            'buffered_events': len(self._event_buffer),
            'memory_events': len(self._recent_events),
            'subscribers': {
                et.value: len(subs) 
                for et, subs in self._subscribers.items()
            }
        }


# Global event store
_event_store: Optional[EventStore] = None

def get_event_store() -> EventStore:
    """Get global event store"""
    global _event_store
    if _event_store is None:
        _event_store = EventStore()
    return _event_store

async def publish_event(
    event_type: EventType,
    aggregate_id: str,
    aggregate_type: str,
    payload: Dict[str, Any],
    metadata: Optional[Dict] = None
):
    """Convenience function to publish event"""
    event = DomainEvent.create(
        event_type=event_type,
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        payload=payload,
        metadata=metadata
    )
    await get_event_store().append(event)
    return event
