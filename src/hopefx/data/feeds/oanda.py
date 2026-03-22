# src/hopefx/data/feeds/oanda.py
"""
OANDA v20 REST and WebSocket feed implementation.
Production-grade with auto-reconnect, backoff, and validation.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

import aiohttp
import tenacity
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from hopefx.config.settings import settings
from hopefx.core.events import EventBus, TickEvent, get_event_bus
from hopefx.data.feeds.base import BarData, DataFeed, TickData
from hopefx.data.validation import TickValidator

import structlog

logger = structlog.get_logger()


class OandaFeed(DataFeed):
    """
    OANDA v20 streaming feed with institutional-grade reliability.
    """
    
    REST_URL = {
        "practice": "https://api-fxpractice.oanda.com/v3",
        "live": "https://api-fxtrade.oanda.com/v3",
    }
    
    STREAM_URL = {
        "practice": "https://stream-fxpractice.oanda.com/v3",
        "live": "https://stream-fxtrade.oanda.com/v3",
    }
    
    def __init__(self) -> None:
        super().__init__("oanda")
        self._api_key = settings.broker.oanda_api_key
        self._account_id = settings.broker.oanda_account_id
        self._environment = settings.broker.oanda_environment
        self._session: aiohttp.ClientSession | None = None
        self._stream_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._validator = TickValidator()
        self._event_bus: EventBus | None = None
        self._subscribed_symbols: set[str] = set()
        self._last_heartbeat: float = 0.0
    
    async def connect(self) -> bool:
        """Establish connection with retry logic."""
        if not self._api_key or not self._account_id:
            logger.error("oanda_credentials_missing")
            return False
        
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self._session = aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            raise_for_status=True,
        )
        
        # Verify connectivity
        try:
            async with self._session.get(
                f"{self.REST_URL[self._environment]}/accounts/{self._account_id}"
            ) as resp:
                data = await resp.json()
                logger.info(
                    "oanda_connected",
                    account=data["account"]["id"],
                    currency=data["account"]["currency"],
                    balance=data["account"]["balance"]
                )
                self._connected = True
                self._event_bus = await get_event_bus()
                
                # Start heartbeat
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                return True
                
        except Exception as e:
            logger.error("oanda_connection_failed", error=str(e))
            await self.disconnect()
            return False
    
    async def disconnect(self) -> None:
        """Graceful disconnection."""
        self._connected = False
        
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._session:
            await self._session.close()
            self._session = None
        
        logger.info("oanda_disconnected")
    
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to price stream."""
        # Normalize symbols to OANDA format (XAUUSD -> XAU_USD)
        oanda_symbols = [s.replace("/", "_") for s in symbols]
        self._subscribed_symbols.update(oanda_symbols)
        
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = asyncio.create_task(self._price_stream())
        
        logger.info("oanda_subscribed", symbols=symbols)
    
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        oanda_symbols = [s.replace("/", "_") for s in symbols]
        self._subscribed_symbols.difference_update(oanda_symbols)
        logger.info("oanda_unsubscribed", symbols=symbols)
    
    @retry(
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        reraise=True
    )
    async def _price_stream(self) -> None:
        """Maintain persistent price streaming connection."""
        while self._connected and self._subscribed_symbols:
            try:
                instruments = ",".join(self._subscribed_symbols)
                url = (
                    f"{self.STREAM_URL[self._environment]}/accounts/"
                    f"{self._account_id}/pricing/stream"
                )
                
                params = {"instruments": instruments}
                
                async with self._session.get(url, params=params) as resp:
                    async for line in resp.content:
                        if not line:
                            continue
                        
                        try:
                            data = json.loads(line)
                            await self._process_message(data)
                        except json.JSONDecodeError:
                            continue
                            
            except aiohttp.ClientPayloadError:
                logger.warning("oanda_stream_reset")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("oanda_stream_error", error=str(e))
                await asyncio.sleep(5)
    
    async def _process_message(self, data: dict[str, Any]) -> None:
        """Process streaming message."""
        msg_type = data.get("type")
        
        if msg_type == "PRICE":
            await self._handle_price(data)
        elif msg_type == "HEARTBEAT":
            self._last_heartbeat = asyncio.get_event_loop().time()
    
    async def _handle_price(self, data: dict[str, Any]) -> None:
        """Handle price tick."""
        try:
            symbol = data["instrument"].replace("_", "/")
            bid = Decimal(str(data["bids"][0]["price"]))
            ask = Decimal(str(data["asks"][0]["price"]))
            
            tick = TickData(
                symbol=symbol,
                bid=bid,
                ask=ask,
                timestamp=asyncio.get_event_loop().time(),
                source="oanda"
            )
            
            # Validate tick
            if not self._validator.validate(tick):
                return
            
            # Emit to local callbacks
            await self._emit_tick(tick)
            
            # Publish to event bus
            if self._event_bus:
                event = TickEvent(
                    symbol=symbol,
                    bid=float(bid),
                    ask=float(ask),
                    timestamp_exchange=data.get("time"),
                    source="oanda"
                )
                await self._event_bus.publish(event)
                
        except (KeyError, ValueError) as e:
            logger.error("oanda_price_parse_error", error=str(e))
    
    async def _heartbeat_loop(self) -> None:
        """Monitor connection health."""
        while self._connected:
            await asyncio.sleep(30)
            if asyncio.get_event_loop().time() - self._last_heartbeat > 60:
                logger.warning("oanda_heartbeat_timeout")
