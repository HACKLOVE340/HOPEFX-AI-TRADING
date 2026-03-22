"""
Polygon.io data feed implementation.
"""

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

import aiohttp
import websockets

from src.core.config import settings
from src.core.exceptions import FeedError
from src.core.logging_config import get_logger
from src.data.feeds.base import DataFeed
from src.data.validators import TickValidator
from src.domain.models import OHLCV, TickData

logger = get_logger(__name__)


class PolygonDataFeed(DataFeed):
    """
    Polygon.io WebSocket and REST API implementation.
    """
    
    def __init__(
        self,
        symbols: list[str],
        api_key: str | None = None,
        use_websocket: bool = True
    ):
        self.symbols = symbols
        self.api_key = api_key or settings.data.polygon_api_key
        self.use_websocket = use_websocket
        
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._running = False
        self._callbacks: list[Callable[[TickData], None]] = []
        self._validator = TickValidator()
        self._rest_session: aiohttp.ClientSession | None = None
    
    async def start(self) -> None:
        """Start data feed."""
        self._running = True
        
        if self.use_websocket:
            await self._connect_websocket()
        else:
            await self._start_polling()
        
        logger.info(f"Polygon feed started for {self.symbols}")
    
    async def stop(self) -> None:
        """Stop data feed."""
        self._running = False
        
        if self._ws:
            await self._ws.close()
        
        if self._rest_session:
            await self._rest_session.close()
        
        logger.info("Polygon feed stopped")
    
    async def subscribe(self, callback: Callable[[TickData], None]) -> None:
        """Subscribe to tick updates."""
        self._callbacks.append(callback)
    
    async def _connect_websocket(self) -> None:
        """Connect to Polygon WebSocket."""
        uri = f"wss://socket.polygon.io/forex?apiKey={self.api_key}"
        
        try:
            self._ws = await websockets.connect(uri)
            
            # Subscribe to symbols
            subscribe_msg = {
                "action": "subscribe",
                "params": ",".join([f"C.{s}" for s in self.symbols])
            }
            await self._ws.send(json.dumps(subscribe_msg))
            
            # Start message handler
            asyncio.create_task(self._handle_messages())
            
        except Exception as e:
            raise FeedError(f"WebSocket connection failed: {e}")
    
    async def _handle_messages(self) -> None:
        """Handle incoming WebSocket messages."""
        while self._running and self._ws:
            try:
                message = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=30.0
                )
                
                data = json.loads(message)
                
                # Parse tick
                if data.get("ev") == "C":  # Forex quote
                    tick = TickData(
                        symbol=data["p"].replace("C:", ""),
                        timestamp=datetime.fromtimestamp(
                            data["t"] / 1000,
                            tz=timezone.utc
                        ),
                        bid=Decimal(str(data.get("b", 0))),
                        ask=Decimal(str(data.get("a", 0))),
                        mid=(Decimal(str(data.get("b", 0))) + 
                             Decimal(str(data.get("a", 0)))) / 2,
                        volume=data.get("v", 0),
                        source="POLYGON"
                    )
                    
                    # Validate
                    is_valid, error = self._validator.validate(tick)
                    if is_valid:
                        for callback in self._callbacks:
                            try:
                                await callback(tick)
                            except Exception as e:
                                logger.error(f"Callback error: {e}")
                    else:
                        logger.warning(f"Invalid tick: {error}")
                        
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                if self._ws:
                    await self._ws.send(json.dumps({"action": "ping"}))
            except Exception as e:
                logger.error(f"Message handling error: {e}")
                await asyncio.sleep(5)
                await self._reconnect()
    
    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        for attempt in range(5):
            try:
                await self._connect_websocket()
                return
            except Exception as e:
                wait = min(2 ** attempt, 60)
                logger.warning(f"Reconnect failed, retrying in {wait}s: {e}")
                await asyncio.sleep(wait)
        
        raise FeedError("Failed to reconnect after 5 attempts")
    
    async def _start_polling(self) -> None:
        """Start REST API polling fallback."""
        self._rest_session = aiohttp.ClientSession()
        
        while self._running:
            try:
                for symbol in self.symbols:
                    tick = await self._fetch_quote(symbol)
                    if tick:
                        for callback in self._callbacks:
                            await callback(tick)
                
                await asyncio.sleep(1)  # Rate limit
                
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(5)
    
    async def _fetch_quote(self, symbol: str) -> TickData | None:
        """Fetch quote via REST API."""
        url = (
            f"https://api.polygon.io/v1/last_quote/currencies/{symbol}"
            f"?apiKey={self.api_key}"
        )
        
        async with self._rest_session.get(url) as response:
            if response.status != 200:
                return None
            
            data = await response.json()
            last = data.get("last", {})
            
            return TickData(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                bid=Decimal(str(last.get("bid", 0))),
                ask=Decimal(str(last.get("ask", 0))),
                mid=(Decimal(str(last.get("bid", 0))) + 
                     Decimal(str(last.get("ask", 0)))) / 2,
                volume=0,
                source="POLYGON_REST"
            )
    
    async def get_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "minute"
    ) -> list[OHLCV]:
        """Fetch historical bars."""
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/"
            f"{timeframe}/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
            f"?apiKey={self.api_key}"
        )
        
        if not self._rest_session:
            self._rest_session = aiohttp.ClientSession()
        
        async with self._rest_session.get(url) as response:
            data = await response.json()
            results = data.get("results", [])
            
            bars = []
            for r in results:
                bars.append(OHLCV(
                    symbol=symbol,
                    timestamp=datetime.fromtimestamp(
                        r["t"] / 1000,
                        tz=timezone.utc
                    ),
                    open=Decimal(str(r["o"])),
                    high=Decimal(str(r["h"])),
                    low=Decimal(str(r["l"])),
                    close=Decimal(str(r["c"])),
                    volume=r["v"],
                    frequency="1M"
                ))
            
            return bars
