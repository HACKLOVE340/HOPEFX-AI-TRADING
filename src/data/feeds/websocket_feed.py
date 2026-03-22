"""
Generic WebSocket data feed with reconnection logic.
"""

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Literal

import websockets
from websockets.exceptions import ConnectionClosed

from src.core.exceptions import FeedError
from src.core.logging_config import get_logger
from src.data.feeds.base import DataFeed
from src.data.validators import TickValidator
from src.domain.models import OHLCV, TickData

logger = get_logger(__name__)


class WebSocketFeed(DataFeed):
    """
    Generic WebSocket data feed for crypto exchanges.
    """
    
    def __init__(
        self,
        symbols: list[str],
        url: str,
        exchange: Literal["binance", "coinbase", "kraken"] = "binance",
        api_key: str | None = None
    ):
        self.symbols = symbols
        self.url = url
        self.exchange = exchange
        self.api_key = api_key
        
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._running = False
        self._callbacks: list[Callable[[TickData], None]] = []
        self._validator = TickValidator()
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
    
    async def start(self) -> None:
        """Start WebSocket connection."""
        self._running = True
        await self._connect()
    
    async def stop(self) -> None:
        """Stop connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
    
    async def subscribe(self, callback: Callable[[TickData], None]) -> None:
        """Subscribe to ticks."""
        self._callbacks.append(callback)
    
    async def _connect(self) -> None:
        """Connect with exponential backoff."""
        while self._running:
            try:
                self._ws = await websockets.connect(self.url)
                self._reconnect_delay = 1  # Reset on success
                
                # Subscribe to channels
                await self._subscribe_channels()
                
                # Handle messages
                await self._handle_messages()
                
            except ConnectionClosed:
                logger.warning("WebSocket closed, reconnecting...")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            
            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay
                )
    
    async def _subscribe_channels(self) -> None:
        """Send subscription message."""
        if self.exchange == "binance":
            # Binance combined stream
            streams = "/".join([f"{s.lower()}@bookTicker" for s in self.symbols])
            # Already in URL for Binance
        elif self.exchange == "coinbase":
            msg = {
                "type": "subscribe",
                "product_ids": self.symbols,
                "channels": ["ticker"]
            }
            await self._ws.send(json.dumps(msg))
    
    async def _handle_messages(self) -> None:
        """Process incoming messages."""
        async for message in self._ws:
            try:
                data = json.loads(message)
                tick = self._parse_message(data)
                
                if tick:
                    is_valid, error = self._validator.validate(tick)
                    if is_valid:
                        for callback in self._callbacks:
                            try:
                                await callback(tick)
                            except Exception as e:
                                logger.error(f"Callback error: {e}")
                    else:
                        logger.warning(f"Invalid tick: {error}")
                        
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"Message handling error: {e}")
    
    def _parse_message(self, data: dict) -> TickData | None:
        """Parse exchange-specific message format."""
        try:
            if self.exchange == "binance":
                return TickData(
                    symbol=data["s"].replace("/", ""),
                    timestamp=datetime.now(timezone.utc),
                    bid=Decimal(data["b"]),
                    ask=Decimal(data["a"]),
                    mid=(Decimal(data["b"]) + Decimal(data["a"])) / 2,
                    volume=0,
                    source="BINANCE_WS"
                )
            elif self.exchange == "coinbase":
                if data.get("type") != "ticker":
                    return None
                return TickData(
                    symbol=data["product_id"],
                    timestamp=datetime.fromisoformat(data["time"].replace("Z", "+00:00")),
                    bid=Decimal(data["best_bid"]),
                    ask=Decimal(data["best_ask"]),
                    mid=(Decimal(data["best_bid"]) + Decimal(data["best_ask"])) / 2,
                    volume=int(float(data["volume_24h"])),
                    source="COINBASE_WS"
                )
        except (KeyError, ValueError) as e:
            logger.warning(f"Parse error: {e}")
            return None
        
        return None
    
    async def get_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1m"
    ) -> list[OHLCV]:
        """Historical data not available via WebSocket."""
        raise NotImplementedError("Use REST API for historical data")
