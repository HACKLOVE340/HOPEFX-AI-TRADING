from __future__ import annotations

import asyncio
import json
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import AsyncIterator, Callable, Optional, Dict, List

import aiohttp
import aioredis
import structlog
import websockets
from tenacity import retry, stop_after_attempt, wait_exponential

from hopefx.config.settings import settings
from hopefx.events.bus import event_bus
from hopefx.events.schemas import Event, EventType, TickData

logger = structlog.get_logger()


@dataclass
class FeedConfig:
    symbol: str
    ws_endpoint: Optional[str] = None
    rest_endpoint: Optional[str] = None
    api_key: Optional[str] = None
    reconnect_interval: int = 5
    heartbeat_interval: int = 30
    max_spread: Decimal = Decimal("0.1")


class PriceFeed(ABC):
    """Abstract base for real-time price feeds."""

    def __init__(self, config: FeedConfig) -> None:
        self.config = config
        self._running = False
        self._callbacks: List[Callable[[TickData], None]] = []
        self._last_tick: Optional[TickData] = None
        self._connection_task: Optional[asyncio.Task] = None
        self._latency_ms: float = 0.0
        self._reconnect_count: int = 0

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to feed source."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from feed source."""
        pass

    @abstractmethod
    async def _parse_message(self, data: str | bytes) -> Optional[TickData]:
        """Parse raw message into TickData."""
        pass

    def on_tick(self, callback: Callable[[TickData], None]) -> None:
        """Register tick callback."""
        self._callbacks.append(callback)

    def _emit_tick(self, tick: TickData) -> None:
        """Emit tick to all callbacks and event bus."""
        self._last_tick = tick

        # Validation
        if tick.bid <= 0 or tick.ask <= 0:
            logger.warning("feed.invalid_prices", bid=tick.bid, ask=tick.ask)
            return

        if tick.spread < 0:
            logger.warning("feed.negative_spread", spread=tick.spread)
            return

        # XAUUSD specific validation
        if tick.symbol == "XAUUSD" and tick.spread > settings.xauusd_spread_threshold:
            logger.warning(
                "feed.high_spread_alert",
                spread=tick.spread,
                threshold=settings.xauusd_spread_threshold
            )

        # Emit to callbacks
        for callback in self._callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.exception("feed.callback_error", error=str(e))

        # Publish to event bus
        asyncio.create_task(
            event_bus.publish(
                Event(
                    type=EventType.TICK,
                    payload=tick,
                    source=self.__class__.__name__,
                    priority=2  # High priority
                )
            )
        )


class OandaFeed(PriceFeed):
    """OANDA v20 streaming price feed."""

    def __init__(self, config: FeedConfig) -> None:
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60))
    async def connect(self) -> None:
        """Connect to OANDA streaming API."""
        if not self.config.api_key:
            raise ValueError("OANDA API key required")

        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        url = f"{self.config.ws_endpoint}/v3/prices/stream?instruments={self.config.symbol}"

        try:
            self._ws = await websockets.connect(url, extra_headers=headers)
            self._running = True
            self._connection_task = asyncio.create_task(self._receive_loop())
            self._reconnect_count = 0
            logger.info("oanda_feed.connected", symbol=self.config.symbol)
        except Exception as e:
            self._reconnect_count += 1
            logger.exception("oanda_feed.connection_failed", error=str(e), attempt=self._reconnect_count)
            raise

    async def disconnect(self) -> None:
        """Disconnect from OANDA."""
        self._running = False
        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        logger.info("oanda_feed.disconnected")

    async def _receive_loop(self) -> None:
        """Main receive loop with automatic reconnection."""
        while self._running:
            try:
                if not self._ws:
                    await self.connect()
                    continue

                import time
                start = time.time()
                
                message = await self._ws.recv()
                
                self._latency_ms = (time.time() - start) * 1000
                
                tick = await self._parse_message(message)

                if tick:
                    self._emit_tick(tick)

            except websockets.ConnectionClosed:
                logger.warning("oanda_feed.connection_closed")
                self._ws = None
                await asyncio.sleep(self.config.reconnect_interval)
            except Exception as e:
                logger.exception("oanda_feed.receive_error", error=str(e))
                await asyncio.sleep(1)

    async def _parse_message(self, data: str | bytes) -> Optional[TickData]:
        """Parse OANDA price message."""
        try:
            msg = json.loads(data)
            if msg.get("type") != "PRICE":
                return None

            price_data = msg.get("price", {})
            return TickData(
                symbol=price_data.get("instrument", self.config.symbol),
                timestamp=datetime.utcnow(),
                bid=Decimal(str(price_data.get("bids", [{}])[0].get("price", 0))),
                ask=Decimal(str(price_data.get("asks", [{}])[0].get("price", 0))),
                volume=Decimal(str(price_data.get("tradeableUnits", 0))),
                source="oanda",
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("oanda_feed.parse_error", error=str(e), data=str(data)[:200])
            return None


class MT5Feed(PriceFeed):
    """MetaTrader 5 zeroMQ feed with heartbeat."""

    def __init__(self, config: FeedConfig) -> None:
        super().__init__(config)
        self._zmq_context: Optional[Any] = None
        self._socket: Optional[Any] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_heartbeat: float = 0

    async def connect(self) -> None:
        """Connect to MT5 via ZeroMQ with reconnection."""
        import zmq.asyncio

        self._zmq_context = zmq.asyncio.Context()
        
        while not self._connected:
            try:
                self._socket = self._zmq_context.socket(zmq.SUB)
                self._socket.connect(self.config.ws_endpoint or "tcp://localhost:5555")
                self._socket.setsockopt_string(zmq.SUBSCRIBE, "")
                
                self._running = True
                self._connected = True
                self._connection_task = asyncio.create_task(self._receive_loop())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                
                logger.info("mt5_feed.connected")
                break
                
            except Exception as e:
                logger.error("mt5_feed.connect_error", error=str(e))
                await asyncio.sleep(5)

    async def disconnect(self) -> None:
        """Disconnect from MT5."""
        self._running = False
        self._connected = False
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        
        if self._socket:
            self._socket.close()
        if self._zmq_context:
            self._zmq_context.term()

    async def _receive_loop(self) -> None:
        """Receive loop for MT5 ticks."""
        while self._running:
            try:
                msg = await self._socket.recv_json()
                tick = await self._parse_message(json.dumps(msg))
                
                if tick:
                    self._emit_tick(tick)
                    self._last_heartbeat = asyncio.get_event_loop().time()
                    
            except Exception as e:
                logger.exception("mt5_feed.receive_error", error=str(e))
                await asyncio.sleep(0.1)

    async def _heartbeat_loop(self) -> None:
        """Monitor connection health."""
        while self._running:
            await asyncio.sleep(10)
            
            if asyncio.get_event_loop().time() - self._last_heartbeat > 30:
                logger.warning("mt5_feed.heartbeat_timeout")
                self._connected = False
                # Trigger reconnection
                asyncio.create_task(self.connect())

    async def _parse_message(self, data: str | bytes) -> Optional[TickData]:
        """Parse MT5 tick."""
        try:
            msg = json.loads(data)
            return TickData(
                symbol=msg.get("symbol", self.config.symbol),
                timestamp=datetime.utcnow(),
                bid=Decimal(str(msg.get("bid", 0))),
                ask=Decimal(str(msg.get("ask", 0))),
                volume=Decimal(str(msg.get("volume", 0))),
                source="mt5",
            )
        except Exception as e:
            logger.warning("mt5_feed.parse_error", error=str(e))
            return None


class BinanceFeed(PriceFeed):
    """Binance WebSocket feed."""

    def __init__(self, config: FeedConfig) -> None:
        super().__init__(config)
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def connect(self) -> None:
        """Connect to Binance WebSocket."""
        symbol = self.config.symbol.replace("/", "").lower()
        url = f"wss://stream.binance.com:9443/ws/{symbol}@aggTrade"

        self._ws = await websockets.connect(url)
        self._running = True
        self._connected = True
        self._connection_task = asyncio.create_task(self._receive_loop())
        
        logger.info("binance_feed.connected")

    async def disconnect(self) -> None:
        """Disconnect."""
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _receive_loop(self) -> None:
        """Receive trades."""
        while self._running:
            try:
                msg = await self._ws.recv()
                data = json.loads(msg)
                
                # Convert trade to tick-like format
                tick = TickData(
                    symbol=self.config.symbol,
                    timestamp=datetime.utcfromtimestamp(data['T'] / 1000),
                    bid=Decimal(str(data['p'])),
                    ask=Decimal(str(data['p'])),  # Trade price as both
                    volume=Decimal(str(data['q'])),
                    source="binance"
                )
                
                self._emit_tick(tick)
                
            except Exception as e:
                logger.exception("binance_feed.error", error=str(e))
                await asyncio.sleep(1)

    async def _parse_message(self, data: str | bytes) -> Optional[TickData]:
        """Not used - parsed in receive loop."""
        return None


class PriceFeedManager:
    """Manages multiple price feeds with failover and aggregation."""

    def __init__(self) -> None:
        self._feeds: Dict[str, List[PriceFeed]] = {}
        self._primary_feed: Dict[str, PriceFeed] = {}
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._health_check_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize Redis cache."""
        try:
            self._redis = aioredis.from_url(
                settings.redis_url,
                max_connections=settings.redis_max_connections,
            )
            await self._redis.ping()
            logger.info("feed_manager.redis_connected")
        except Exception as e:
            logger.warning("feed_manager.redis_unavailable", error=str(e))
            self._redis = None

    def add_feed(self, feed: PriceFeed, symbol: str, primary: bool = False) -> None:
        """Add price feed to manager."""
        if symbol not in self._feeds:
            self._feeds[symbol] = []
        
        self._feeds[symbol].append(feed)
        
        if primary:
            self._primary_feed[symbol] = feed
        
        feed.on_tick(self._cache_tick)

    def _cache_tick(self, tick: TickData) -> None:
        """Cache tick to Redis."""
        if not self._redis:
            return

        asyncio.create_task(self._redis.setex(
            f"tick:{tick.symbol}",
            60,
            tick.model_dump_json(),
        ))

    async def start(self) -> None:
        """Start all feeds and health monitoring."""
        self._running = True
        
        for symbol_feeds in self._feeds.values():
            for feed in symbol_feeds:
                await feed.connect()
        
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("feed_manager.started")

    async def stop(self) -> None:
        """Stop all feeds."""
        self._running = False
        
        if self._health_check_task:
            self._health_check_task.cancel()
        
        for symbol_feeds in self._feeds.values():
            for feed in symbol_feeds:
                await feed.disconnect()

        if self._redis:
            await self._redis.close()

    async def _health_check_loop(self) -> None:
        """Monitor feed health."""
        while self._running:
            for symbol, feeds in self._feeds.items():
                for feed in feeds:
                    # Check if feed is stale
                    if feed._last_tick:
                        age = (datetime.utcnow() - feed._last_tick.timestamp).total_seconds()
                        if age > 60:
                            logger.warning(
                                "feed_manager.stale_feed",
                                source=feed.__class__.__name__,
                                symbol=symbol,
                                age_seconds=age
                            )
                            # Attempt reconnection
                            asyncio.create_task(self._reconnect_feed(feed))
            
            await asyncio.sleep(30)

    async def _reconnect_feed(self, feed: PriceFeed) -> None:
        """Reconnect a specific feed."""
        try:
            await feed.disconnect()
            await asyncio.sleep(1)
            await feed.connect()
        except Exception as e:
            logger.error("feed_manager.reconnect_failed", error=str(e))

    def get_best_price(self, symbol: str) -> Optional[TickData]:
        """Get best available price from any feed (lowest spread)."""
        best_tick: Optional[TickData] = None
        best_spread = Decimal("999")

        for feed in self._feeds.get(symbol, []):
            if feed._last_tick and feed._connected:
                if feed._last_tick.spread < best_spread:
                    best_spread = feed._last_tick.spread
                    best_tick = feed._last_tick

        return best_tick

    def get_aggregated_price(self, symbol: str) -> Optional[TickData]:
        """Aggregate prices from multiple feeds (VWAP)."""
        ticks = [f._last_tick for f in self._feeds.get(symbol, []) if f._last_tick and f._connected]
        
        if not ticks:
            return None
        
        # Calculate VWAP
        total_bid_volume = sum(t.volume for t in ticks)
        total_ask_volume = sum(t.volume for t in ticks)
        
        if total_bid_volume == 0 or total_ask_volume == 0:
            return ticks[0]  # Fallback to first
        
        vwap_bid = sum(t.bid * t.volume for t in ticks) / total_bid_volume
        vwap_ask = sum(t.ask * t.volume for t in ticks) / total_ask_volume
        
        return TickData(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            bid=vwap_bid,
            ask=vwap_ask,
            volume=sum(t.volume for t in ticks),
            source="aggregated"
        )

    def get_feed_stats(self) -> dict:
        """Get feed statistics."""
        stats = {}
        for symbol, feeds in self._feeds.items():
            stats[symbol] = {
                "feed_count": len(feeds),
                "connected": sum(1 for f in feeds if f._connected),
                "primary_latency_ms": self._primary_feed.get(symbol, type('obj', (object,), {'_latency_ms': 0}))._latency_ms,
                "best_spread": min((f._last_tick.spread for f in feeds if f._last_tick), default=None)
            }
        return stats


# Global feed manager
feed_manager = PriceFeedManager()
