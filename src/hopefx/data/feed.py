import asyncio
import json
from decimal import Decimal

import aiohttp
import structlog
import websockets

from hopefx.core.bus import EventBus
from hopefx.core.events import EventType, TickData

logger = structlog.get_logger()


class RealTimePriceEngine:
    """Multi-source WebSocket feed with automatic failover."""
    
    def __init__(self, bus: EventBus, symbols: list[str]) -> None:
        self.bus = bus
        self.symbols = symbols
        self._sources: dict[str, Callable] = {
            "oanda": self._oanda_feed,
            "binance": self._binance_feed,
        }
        self._active_tasks: set[asyncio.Task] = set()
        self._shutdown = False
    
    async def start(self) -> None:
        async with asyncio.TaskGroup() as tg:
            for name, coro in self._sources.items():
                tg.create_task(self._run_source(name, coro))
    
    async def _run_source(self, name: str, coro: Callable) -> None:
        while not self._shutdown:
            try:
                await coro()
            except Exception as e:
                logger.error("feed.source_error", source=name, error=str(e))
                await asyncio.sleep(5)  # Backoff
    
    async def _oanda_feed(self) -> None:
        """OANDA WebSocket implementation."""
        url = "wss://stream-fxpractice.oanda.com/v3/prices/stream"
        # Auth headers would go here
        
        async with websockets.connect(url) as ws:
            async for message in ws:
                if self._shutdown:
                    break
                data = json.loads(message)
                tick = self._parse_oanda(data)
                if tick:
                    await self.bus.publish(EventType.TICK, tick)
    
    async def _binance_feed(self) -> None:
        """Binance XAUUSD (GOLD) futures feed."""
        streams = "/".join([f"{s.lower()}@bookTicker" for s in self.symbols])
        url = f"wss://fstream.binance.com/stream?streams={streams}"
        
        async with websockets.connect(url) as ws:
            async for message in ws:
                if self._shutdown:
                    break
                data = json.loads(message)
                tick = self._parse_binance(data)
                if tick:
                    await self.bus.publish(EventType.TICK, tick)
    
    def _parse_oanda(self, data: dict) -> TickData | None:
        try:
            return TickData(
                symbol=data["instrument"],
                bid=Decimal(str(data["bids"][0]["price"])),
                ask=Decimal(str(data["asks"][0]["price"])),
                volume=int(data.get("volume", 0)),
                source="oanda"
            )
        except (KeyError, IndexError) as e:
            logger.warning("feed.parse_error", source="oanda", error=str(e))
            return None
    
    def _parse_binance(self, data: dict) -> TickData | None:
        try:
            d = data["data"]
            return TickData(
                symbol=d["s"],
                bid=Decimal(d["b"]),
                ask=Decimal(d["a"]),
                volume=int(float(d.get("v", 0))),
                source="binance"
            )
        except (KeyError, ValueError) as e:
            logger.warning("feed.parse_error", source="binance", error=str(e))
            return None
    
    def stop(self) -> None:
        self._shutdown = True
        for task in self._active_tasks:
            task.cancel()
