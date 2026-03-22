"""
Institutional Event-Driven Architecture
All communication flows through immutable events
"""

from __future__ import annotations
import asyncio
import json
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto
from typing import (
    Any, Callable, Coroutine, Dict, Generic, List, 
    Optional, Protocol, Set, TypeVar, Union, runtime_checkable
)
import numpy as np
from prometheus_client import Counter, Histogram, Gauge

# ============================================================================
# EVENT TYPES — Every system action is an event
# ============================================================================

class EventType(Enum):
    # Market Data
    MARKET_TICK = auto()           # L1/L2 tick data
    MARKET_BAR = auto()            # OHLCV bar close
    MARKET_DEPTH = auto()          # Full order book
    
    # Trading
    SIGNAL_GENERATED = auto()      # Strategy signal
    ORDER_NEW = auto()             # Order created
    ORDER_PENDING = auto()         # Sent to broker
    ORDER_ACK = auto()             # Broker acknowledged
    ORDER_REJECT = auto()          # Broker rejected
    ORDER_FILL = auto()            # Partial/complete fill
    ORDER_CANCEL = auto()          # Cancel requested
    ORDER_CANCELLED = auto()       # Cancel confirmed
    
    # Position Management
    POSITION_OPEN = auto()         # New position
    POSITION_MODIFY = auto()        # SL/TP updated
    POSITION_CLOSE = auto()         # Position closed
    
    # Risk
    RISK_CHECK_PASS = auto()        # Pre-trade approved
    RISK_CHECK_FAIL = auto()        # Pre-trade blocked
    RISK_BREACH = auto()            # Limit exceeded
    MARGIN_CALL = auto()            # Margin warning
    LIQUIDATION = auto()            # Forced close
    
    # Portfolio
    PORTFOLIO_REBALANCE = auto()    # Allocation change
    PORTFOLIO_SNAPSHOT = auto()     # EOD valuation
    
    # Compliance
    AUDIT_RECORD = auto()           # Immutable log entry
    COMPLIANCE_ALERT = auto()       # Regulatory alert
    
    # System
    SYSTEM_START = auto()
    SYSTEM_HEARTBEAT = auto()
    SYSTEM_SHUTDOWN = auto()

# ============================================================================
# CORE EVENT CLASS — Immutable, auditable, traceable
# ============================================================================

@dataclass(frozen=True, slots=True)
class DomainEvent:
    """
    Immutable domain event — the atomic unit of the system.
    
    All state changes happen through events. No direct method calls
    between modules. Everything is event-driven for:
    - Complete audit trail
    - Replay capability
    - Distributed system support
    - Regulatory compliance
    """
    
    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    source: str = "system"  # Component that emitted
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_json(self) -> str:
        """Serialize for storage/transmission."""
        return json.dumps(asdict(self), default=str, separators=(',', ':'))
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        """Deserialize from storage."""
        data = json.loads(json_str)
        data['event_type'] = EventType[data['event_type']]
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)

# ============================================================================
# EVENT BUS — Central nervous system
# ============================================================================

class EventBus:
    """
    Institutional-grade event bus with:
    - Persistent event store (regulatory requirement)
    - Multiple subscriber patterns
    - Backpressure handling
    - Metrics integration
    - Dead letter queue for failed handlers
    """
    
    _instance: Optional[EventBus] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers: Dict[
                EventType, 
                List[Callable[[DomainEvent], Coroutine]]
            ] = defaultdict(list)
            cls._instance._persistent_store: List[DomainEvent] = []
            cls._instance._event_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
            cls._instance._running = False
            cls._instance._metrics = {
                'published': Counter('hopefx_events_published_total', 'Events published', ['type']),
                'processed': Counter('hopefx_events_processed_total', 'Events processed', ['type']),
                'dropped': Counter('hopefx_events_dropped_total', 'Events dropped'),
                'latency': Histogram('hopefx_event_latency_seconds', 'Processing latency'),
                'queue_depth': Gauge('hopefx_event_queue_depth', 'Current queue size'),
                'handler_errors': Counter('hopefx_handler_errors_total', 'Handler exceptions'),
            }
            cls._instance._dead_letter_queue: List[DomainEvent] = []
        return cls._instance
    
    def subscribe(
        self, 
        event_type: EventType,
        handler: Callable[[DomainEvent], Coroutine],
        priority: int = 5
    ) -> Callable[[], None]:
        """
        Subscribe to events with priority (1=highest, 10=lowest).
        
        Risk handlers should use priority 1.
        Logging handlers should use priority 10.
        """
        # Store with priority for ordered execution
        entry = (priority, handler)
        self._handlers[event_type].append(entry)
        # Sort by priority
        self._handlers[event_type].sort(key=lambda x: x[0])
        
        # Return unsubscribe function
        def unsubscribe():
            self._handlers[event_type] = [
                e for e in self._handlers[event_type] 
                if e[1] != handler
            ]
        return unsubscribe
    
    async def publish(self, event: DomainEvent) -> bool:
        """
        Publish event to all subscribers.
        
        Returns True if queued successfully, False if backpressure.
        """
        try:
            self._event_queue.put_nowait(event)
            self._metrics['published'].labels(type=event.event_type.name).inc()
            self._metrics['queue_depth'].set(self._event_queue.qsize())
            return True
        except asyncio.QueueFull:
            self._metrics['dropped'].inc()
            # Critical: log to emergency file
            await self._emergency_log(event)
            return False
    
    async def _emergency_log(self, event: DomainEvent):
        """Write to disk when memory queue is full."""
        import aiofiles
        async with aiofiles.open('outputs/logs/emergency_events.jsonl', 'a') as f:
            await f.write(event.to_json() + '\n')
    
    async def start(self):
        """Start event processing loop."""
        self._running = True
        
        while self._running:
            try:
                # Wait for event with timeout for health checks
                event = await asyncio.wait_for(
                    self._event_queue.get(), 
                    timeout=1.0
                )
                
                # Persist for audit (regulatory requirement)
                self._persistent_store.append(event)
                
                # Process through handlers
                await self._process_event(event)
                
                self._event_queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logging.critical(f"Event loop error: {e}", exc_info=True)
    
    async def _process_event(self, event: DomainEvent):
        """Execute all handlers for event type."""
        import time
        start = time.time()
        
        handlers = self._handlers.get(event.event_type, [])
        
        for priority, handler in handlers:
            try:
                await handler(event)
                self._metrics['processed'].labels(type=event.event_type.name).inc()
            except Exception as e:
                self._metrics['handler_errors'].inc()
                # Add to dead letter for retry
                self._dead_letter_queue.append(event)
                logging.error(
                    f"Handler failed for {event.event_type.name}: {e}",
                    extra={'trace_id': event.trace_id, 'handler': handler.__name__}
                )
        
        # Record latency
        self._metrics['latency'].observe(time.time() - start)
    
    def stop(self):
        """Graceful shutdown."""
        self._running = False
    
    def get_event_store(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        event_types: Optional[List[EventType]] = None
    ) -> List[DomainEvent]:
        """
        Query event store for replay/audit.
        """
        events = self._persistent_store
        
        if start:
            events = [e for e in events if e.timestamp >= start]
        if end:
            events = [e for e in events if e.timestamp <= end]
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        
        return events
    
    async def replay(
        self,
        start: datetime,
        end: Optional[datetime] = None,
        speed: float = 1.0
    ):
        """
        Replay events for backtesting or disaster recovery.
        """
        events = self.get_event_store(start, end)
        
        if not events:
            return
        
        last_time = events[0].timestamp
        
        for event in events:
            # Calculate delay
            if speed > 0:
                delay = (event.timestamp - last_time).total_seconds() / speed
                if delay > 0:
                    await asyncio.sleep(delay)
            
            # Re-publish (handlers will process)
            await self.publish(event)
            last_time = event.timestamp

# Global instance
event_bus = EventBus()
