"""
Real-Time Streaming Service

Event-driven, WebSocket-capable data streaming infrastructure with:
- Multi-symbol subscription management
- Tick aggregation into bars
- Reconnection logic
- Pluggable data source adapters
- Thread-safe publish/subscribe event bus
"""

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StreamStatus(Enum):
    """Connection/stream status."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class Tick:
    """A single market tick."""

    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume: float = 0.0
    trade_id: Optional[str] = None

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2, 5)

    @property
    def spread(self) -> float:
        return round(self.ask - self.bid, 5)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "volume": self.volume,
            "trade_id": self.trade_id,
            "mid": self.mid,
            "spread": self.spread,
        }


@dataclass
class AggregatedBar:
    """OHLCV bar aggregated from ticks."""

    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    buy_volume: float = 0.0
    sell_volume: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
        }


@dataclass
class StreamEvent:
    """An event published on the stream event bus."""

    event_type: str  # 'tick', 'bar', 'connected', 'disconnected', 'error'
    symbol: Optional[str]
    timestamp: datetime
    data: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "event_type": self.event_type,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


class TickAggregator:
    """
    Aggregates ticks into OHLCV bars for a given timeframe.

    Supports multiple timeframes per symbol.
    """

    def __init__(self, timeframe_minutes: int = 1):
        self._tf_minutes = timeframe_minutes
        self._open_bars: Dict[str, Dict] = {}

    def _bar_key(self, ts: datetime) -> datetime:
        mins = (ts.minute // self._tf_minutes) * self._tf_minutes
        return ts.replace(minute=mins, second=0, microsecond=0)

    def add_tick(self, tick: Tick) -> Optional[AggregatedBar]:
        """
        Add a tick and return a completed bar if the bar period has closed.

        Args:
            tick: Incoming tick

        Returns:
            Completed AggregatedBar or None
        """
        bar_ts = self._bar_key(tick.timestamp)
        key = tick.symbol

        completed: Optional[AggregatedBar] = None

        if key in self._open_bars and self._open_bars[key]["ts"] != bar_ts:
            # Close the current bar
            b = self._open_bars[key]
            completed = AggregatedBar(
                symbol=tick.symbol,
                timeframe=f"{self._tf_minutes}m",
                timestamp=b["ts"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=b["volume"],
                tick_count=b["count"],
                buy_volume=b.get("buy_volume", 0.0),
                sell_volume=b.get("sell_volume", 0.0),
            )
            del self._open_bars[key]

        if key not in self._open_bars:
            self._open_bars[key] = {
                "ts": bar_ts,
                "open": tick.last,
                "high": tick.last,
                "low": tick.last,
                "close": tick.last,
                "volume": tick.volume,
                "buy_volume": 0.0,
                "sell_volume": 0.0,
                "count": 1,
            }
        else:
            b = self._open_bars[key]
            b["high"] = max(b["high"], tick.last)
            b["low"] = min(b["low"], tick.last)
            b["close"] = tick.last
            b["volume"] += tick.volume
            b["count"] += 1

        return completed

    def get_open_bar(self, symbol: str) -> Optional[Dict]:
        """Get the currently open bar for a symbol."""
        return self._open_bars.get(symbol)


class StreamingService:
    """
    Real-time data streaming service.

    Supports:
    - Multi-symbol subscriptions
    - Tick aggregation into configurable bars
    - Event-driven publish/subscribe
    - Reconnection logic with exponential backoff
    - Thread-safe operation

    Usage:
        service = StreamingService()

        # Subscribe to events
        service.subscribe('XAUUSD', handler_fn)

        # Simulate/inject a tick (for testing or adapters)
        service.publish_tick(Tick('XAUUSD', datetime.utcnow(), 1950.0, 1950.1, 1950.05))
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize streaming service.

        Args:
            config: Configuration options:
                - max_ticks_buffer: Tick buffer size per symbol (default 10000)
                - default_timeframes: Bar timeframes in minutes (default [1, 5, 15])
                - reconnect_max_attempts: Max reconnection attempts (default 5)
                - reconnect_base_delay: Base delay for backoff in seconds (default 2)
        """
        self.config = config or {}
        self._max_ticks = self.config.get("max_ticks_buffer", 10000)
        self._timeframes = self.config.get("default_timeframes", [1, 5, 15])
        self._reconnect_max = self.config.get("reconnect_max_attempts", 5)
        self._reconnect_base = self.config.get("reconnect_base_delay", 2)

        # State
        self._status = StreamStatus.DISCONNECTED
        self._subscriptions: Dict[str, Set] = defaultdict(set)
        self._global_listeners: List[Callable] = []

        # Tick buffers per symbol
        self._tick_buffers: Dict[str, deque] = {}

        # Bar aggregators per timeframe
        self._aggregators: Dict[int, TickAggregator] = {
            tf: TickAggregator(tf) for tf in self._timeframes
        }

        # Completed bars per symbol per timeframe
        self._bars: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=500))
        )

        # Thread safety
        self._lock = threading.RLock()

        logger.info("Streaming Service initialized, timeframes=%s", self._timeframes)

    # ================================================================
    # SUBSCRIPTION MANAGEMENT
    # ================================================================

    def subscribe(
        self,
        symbol: str,
        callback: Callable[[StreamEvent], None],
    ) -> None:
        """
        Subscribe to stream events for a symbol.

        Args:
            symbol: Trading symbol ('*' for all symbols)
            callback: Callable receiving StreamEvent objects
        """
        with self._lock:
            if symbol == "*":
                self._global_listeners.append(callback)
            else:
                self._subscriptions[symbol].add(callback)
        logger.debug("Subscribed to %s", symbol)

    def unsubscribe(
        self,
        symbol: str,
        callback: Callable[[StreamEvent], None],
    ) -> None:
        """Unsubscribe a callback from a symbol."""
        with self._lock:
            if symbol == "*":
                self._global_listeners = [
                    c for c in self._global_listeners if c is not callback
                ]
            else:
                self._subscriptions[symbol].discard(callback)

    def get_subscriptions(self) -> List[str]:
        """Get list of subscribed symbols."""
        with self._lock:
            return list(self._subscriptions.keys())

    # ================================================================
    # TICK PUBLISHING
    # ================================================================

    def publish_tick(self, tick: Tick) -> None:
        """
        Publish a tick to all subscribers and run aggregation.

        Args:
            tick: Tick to publish
        """
        with self._lock:
            if tick.symbol not in self._tick_buffers:
                self._tick_buffers[tick.symbol] = deque(maxlen=self._max_ticks)
            self._tick_buffers[tick.symbol].append(tick)

            # Aggregate into bars
            completed_bars = []
            for tf, aggregator in self._aggregators.items():
                bar = aggregator.add_tick(tick)
                if bar is not None:
                    self._bars[tick.symbol][bar.timeframe].append(bar)
                    completed_bars.append(bar)

        # Publish tick event
        tick_event = StreamEvent(
            event_type="tick",
            symbol=tick.symbol,
            timestamp=tick.timestamp,
            data=tick.to_dict(),
        )
        self._dispatch(tick_event)

        # Publish bar events
        for bar in completed_bars:
            bar_event = StreamEvent(
                event_type="bar",
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                data=bar.to_dict(),
            )
            self._dispatch(bar_event)

    def _dispatch(self, event: StreamEvent) -> None:
        """Dispatch an event to all relevant subscribers."""
        listeners: List[Callable] = []
        with self._lock:
            if event.symbol:
                listeners = list(self._subscriptions.get(event.symbol, set()))
            listeners.extend(self._global_listeners)

        for cb in listeners:
            try:
                cb(event)
            except Exception as exc:  # pragma: no cover
                logger.error("Stream callback error: %s", exc)

    # ================================================================
    # DATA RETRIEVAL
    # ================================================================

    def get_recent_ticks(self, symbol: str, n: int = 100) -> List[Tick]:
        """Get the most recent N ticks for a symbol."""
        with self._lock:
            buf = self._tick_buffers.get(symbol)
            if buf is None:
                return []
            ticks = list(buf)
        return ticks[-n:]

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
    ) -> List[AggregatedBar]:
        """
        Get aggregated bars for a symbol.

        Args:
            symbol: Trading symbol
            timeframe: Bar timeframe string (e.g. '1m', '5m', '15m')
            limit: Maximum bars to return

        Returns:
            List of AggregatedBar objects (oldest first)
        """
        with self._lock:
            bars = list(self._bars.get(symbol, {}).get(timeframe, []))
        return bars[-limit:]

    def get_latest_tick(self, symbol: str) -> Optional[Tick]:
        """Get the most recent tick for a symbol."""
        with self._lock:
            buf = self._tick_buffers.get(symbol)
            if not buf:
                return None
            return buf[-1]

    # ================================================================
    # CONNECTION STATUS
    # ================================================================

    @property
    def status(self) -> StreamStatus:
        return self._status

    def connect(self) -> None:
        """Mark the service as connected."""
        self._status = StreamStatus.CONNECTED
        event = StreamEvent(
            event_type="connected",
            symbol=None,
            timestamp=datetime.utcnow(),
        )
        self._dispatch(event)
        logger.info("Streaming Service connected")

    def disconnect(self) -> None:
        """Mark the service as disconnected."""
        self._status = StreamStatus.DISCONNECTED
        event = StreamEvent(
            event_type="disconnected",
            symbol=None,
            timestamp=datetime.utcnow(),
        )
        self._dispatch(event)
        logger.info("Streaming Service disconnected")

    def reconnect_with_backoff(
        self,
        connect_fn: Callable,
        max_attempts: Optional[int] = None,
    ) -> bool:
        """
        Attempt to reconnect with exponential backoff.

        Args:
            connect_fn: Callable that attempts the connection; should return True on success
            max_attempts: Override max reconnection attempts

        Returns:
            True if reconnection succeeded
        """
        attempts = max_attempts or self._reconnect_max
        self._status = StreamStatus.RECONNECTING

        for attempt in range(1, attempts + 1):
            delay = self._reconnect_base * (2 ** (attempt - 1))
            logger.info(
                "Reconnection attempt %d/%d in %ds", attempt, attempts, delay
            )
            time.sleep(delay)
            try:
                if connect_fn():
                    self._status = StreamStatus.CONNECTED
                    logger.info("Reconnected successfully on attempt %d", attempt)
                    return True
            except Exception as exc:
                logger.warning("Reconnection attempt %d failed: %s", attempt, exc)

        self._status = StreamStatus.ERROR
        logger.error("All %d reconnection attempts failed", attempts)
        return False

    # ================================================================
    # UTILITY
    # ================================================================

    def get_stats(self) -> Dict:
        """Get streaming service statistics."""
        with self._lock:
            return {
                "status": self._status.value,
                "subscribed_symbols": list(self._subscriptions.keys()),
                "global_listeners": len(self._global_listeners),
                "tick_buffer_sizes": {
                    s: len(b) for s, b in self._tick_buffers.items()
                },
                "available_timeframes": [f"{tf}m" for tf in self._timeframes],
            }

    def clear_symbol(self, symbol: str) -> None:
        """Clear buffered data for a symbol."""
        with self._lock:
            self._tick_buffers.pop(symbol, None)
            self._bars.pop(symbol, None)

    def clear_all(self) -> None:
        """Clear all buffered data."""
        with self._lock:
            self._tick_buffers.clear()
            self._bars.clear()


# ================================================================
# FASTAPI / WEBSOCKET INTEGRATION
# ================================================================


def create_streaming_router(service: StreamingService):
    """
    Create FastAPI router with streaming endpoints and WebSocket support.

    Args:
        service: StreamingService instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
    import json

    router = APIRouter(prefix="/api/stream", tags=["Streaming"])

    @router.get("/stats")
    async def get_stats():
        """Get streaming service statistics."""
        return service.get_stats()

    @router.get("/{symbol}/ticks")
    async def get_recent_ticks(symbol: str, n: int = 100):
        """Get recent ticks for a symbol."""
        ticks = service.get_recent_ticks(symbol, n=n)
        return [t.to_dict() for t in ticks]

    @router.get("/{symbol}/bars/{timeframe}")
    async def get_bars(symbol: str, timeframe: str = "1m", limit: int = 100):
        """Get aggregated bars for a symbol."""
        bars = service.get_bars(symbol, timeframe=timeframe, limit=limit)
        return [b.to_dict() for b in bars]

    @router.websocket("/{symbol}/ws")
    async def websocket_stream(websocket: WebSocket, symbol: str):
        """WebSocket endpoint for real-time tick streaming."""
        await websocket.accept()
        queue = []

        def on_event(event: StreamEvent) -> None:
            queue.append(event.to_dict())

        service.subscribe(symbol, on_event)
        try:
            while True:
                # Drain queue
                while queue:
                    await websocket.send_text(json.dumps(queue.pop(0)))
                # Small sleep to avoid busy-wait
                import asyncio
                await asyncio.sleep(0.01)
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            service.unsubscribe(symbol, on_event)

    return router


# Global instance
_streaming_service: Optional[StreamingService] = None


def get_streaming_service() -> StreamingService:
    """Get the global streaming service instance."""
    global _streaming_service
    if _streaming_service is None:
        _streaming_service = StreamingService()
    return _streaming_service
