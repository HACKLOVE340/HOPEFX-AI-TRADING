async def _process_message(self, venue: Venue, message: str):
    from src.risk.kill_switch import kill_switch
    if kill_switch.is_killed:
        return None
    # ... your existing code

"""Real-time tick feed engine with asyncio."""
from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

import aiohttp
import aioredis
import structlog
import websockets
from anyio import create_task_group

from src.core.events import TickEvent, Event
from src.core.types import Tick, Venue, Symbol
from src.data.validation import TickValidator
from configs.settings import get_settings

logger = structlog.get_logger()


@dataclass
class FeedConfig:
    """Feed configuration."""
    venue: Venue
    symbols: list[Symbol]
    ws_url: str | None = None
    rest_url: str | None = None
    api_key: str | None = None
    reconnect_interval: float = 5.0
    heartbeat_interval: float = 30.0


class RealTimePriceEngine:
    """Multi-venue real-time price engine."""
    
    def __init__(self) -> None:
        self.validator = TickValidator()
        self.redis: aioredis.Redis | None = None
        self._feeds: dict[Venue, FeedConfig] = {}
        self._handlers: list[Callable[[TickEvent], asyncio.Future[Any]]] = []
        self._running = False
        self._tasks: set[asyncio.Task] = set()
    
    async def initialize(self) -> None:
        """Initialize Redis connection."""
        settings = get_settings()
        self.redis = aioredis.from_url(
            settings.redis.url.get_secret_value(),
            decode_responses=True
        )
        await self.redis.ping()
        logger.info("Redis connected for price feed")
    
    def register_feed(self, config: FeedConfig) -> None:
        """Register a new feed configuration."""
        self._feeds[config.venue] = config
        logger.info(f"Registered feed for {config.venue}")
    
    def add_handler(self, handler: Callable[[TickEvent], asyncio.Future[Any]]) -> None:
        """Add tick handler."""
        self._handlers.append(handler)
    
    async def start(self) -> None:
        """Start all feeds."""
        self._running = True
        
        async with create_task_group() as tg:
            for venue, config in self._feeds.items():
                tg.start_soon(self._run_feed, venue, config)
        
        logger.info("All feeds started")
    
    async def stop(self) -> None:
        """Stop all feeds."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.redis:
            await self.redis.close()
        logger.info("All feeds stopped")
    
    async def _run_feed(self, venue: Venue, config: FeedConfig) -> None:
        """Run feed with auto-reconnect."""
        while self._running:
            try:
                if config.ws_url:
                    await self._websocket_feed(venue, config)
                else:
                    await self._rest_poll_feed(venue, config)
            except Exception as e:
                logger.error(f"Feed {venue} error: {e}")
                await asyncio.sleep(config.reconnect_interval)
    
    async def _websocket_feed(self, venue: Venue, config: FeedConfig) -> None:
        """WebSocket feed implementation."""
        if not config.ws_url:
            return
        
        async with websockets.connect(config.ws_url) as ws:
            # Subscribe to symbols
            subscribe_msg = self._build_subscribe_message(venue, config)
            await ws.send(json.dumps(subscribe_msg))
            
            # Start heartbeat
            heartbeat_task = asyncio.create_task(
                self._heartbeat(ws, config.heartbeat_interval)
            )
            self._tasks.add(heartbeat_task)
            
            async for message in ws:
                if not self._running:
                    break
                
                try:
                    tick = self._parse_message(venue, message)
                    if tick:
                        validated = await self.validator.validate(tick)
                        event = TickEvent(tick=validated)
                        
                        # Persist to Redis
                        await self._persist_tick(validated)
                        
                        # Fan out to handlers
                        await asyncio.gather(
                            *[handler(event) for handler in self._handlers],
                            return_exceptions=True
                        )
                        
                except Exception as e:
                    logger.error(f"Error processing message from {venue}: {e}")
            
            heartbeat_task.cancel()
    
    async def _rest_poll_feed(self, venue: Venue, config: FeedConfig) -> None:
        """REST polling fallback."""
        if not config.rest_url:
            return
        
        async with aiohttp.ClientSession() as session:
            while self._running:
                try:
                    async with session.get(config.rest_url) as resp:
                        data = await resp.json()
                        tick = self._parse_rest_message(venue, data)
                        if tick:
                            validated = await self.validator.validate(tick)
                            event = TickEvent(tick=validated)
                            await self._persist_tick(validated)
                            await asyncio.gather(
                                *[handler(event) for handler in self._handlers],
                                return_exceptions=True
                            )
                except Exception as e:
                    logger.error(f"REST poll error for {venue}: {e}")
                
                await asyncio.sleep(1.0)  # 1 second poll interval
    
    async def _heartbeat(self, ws, interval: float) -> None:
        """Send heartbeat pings."""
        while True:
            try:
                await asyncio.sleep(interval)
                await ws.ping()
            except Exception:
                break
    
    async def _persist_tick(self, tick: Tick) -> None:
        """Persist tick to Redis time-series."""
        if not self.redis:
            return
        
        key = f"ticks:{tick.venue.value}:{tick.symbol}"
        pipeline = self.redis.pipeline()
        
        # Add to sorted set by timestamp
        pipeline.zadd(key, {tick.model_dump_json(): tick.timestamp.timestamp()})
        
        # Trim to last 10k ticks
        pipeline.zremrangebyrank(key, 0, -10001)
        
        # Set TTL
        pipeline.expire(key, 86400)  # 24 hours
        
        await pipeline.execute()
    
    def _build_subscribe_message(self, venue: Venue, config: FeedConfig) -> dict:
        """Build venue-specific subscribe message."""
        if venue == Venue.OANDA:
            return {
                "type": "SUBSCRIBE",
                "instruments": [f"{s}_XAU" for s in config.symbols]
            }
        elif venue == Venue.BINANCE:
            streams = [f"{s.lower()}@ticker" for s in config.symbols]
            return {"method": "SUBSCRIBE", "params": streams, "id": 1}
        return {}
    
    def _parse_message(self, venue: Venue, message: str) -> Tick | None:
        """Parse WebSocket message to Tick."""
        try:
            data = json.loads(message)
            
            if venue == Venue.OANDA:
                return Tick(
                    symbol=Symbol(data["instrument"].replace("_XAU", "")),
                    timestamp=data["time"],
                    bid=Decimal(str(data["bids"][0]["price"])),
                    ask=Decimal(str(data["asks"][0]["price"])),
                    volume=Decimal(str(data.get("volume", 0))),
                    venue=venue
                )
            elif venue == Venue.BINANCE:
                return Tick(
                    symbol=Symbol(data["s"]),
                    timestamp=data["E"],
                    bid=Decimal(str(data["b"])),
                    ask=Decimal(str(data["a"])),
                    volume=Decimal(str(data["v"])),
                    venue=venue
                )
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Parse error for {venue}: {e}")
        
        return None
    
    def _parse_rest_message(self, venue: Venue, data: dict) -> Tick | None:
        """Parse REST response to Tick."""
        # Implementation similar to _parse_message
        return None
    
    async def get_latest(self, symbol: Symbol, venue: Venue) -> Tick | None:
        """Get latest tick from Redis."""
        if not self.redis:
            return None
        
        key = f"ticks:{venue.value}:{symbol}"
        data = await self.redis.zrange(key, -1, -1)
        if data:
            return Tick.model_validate_json(data[0])
        return None
