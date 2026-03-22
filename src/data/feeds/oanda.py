"""
OANDA v20 streaming data feed.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

import aiohttp

from src.core.config import settings
from src.core.exceptions import FeedError
from src.core.logging_config import get_logger
from src.data.feeds.base import DataFeed
from src.data.validators import TickValidator
from src.domain.models import OHLCV, TickData

logger = get_logger(__name__)


class OandaDataFeed(DataFeed):
    """
    OANDA v20 REST API streaming implementation.
    """
    
    def __init__(
        self,
        symbols: list[str],
        api_key: str | None = None,
        account_id: str | None = None,
        environment: str = "practice"
    ):
        self.symbols = [s.replace("/", "_") for s in symbols]
        self.api_key = api_key or settings.broker.oanda_api_key
        self.account_id = account_id or settings.broker.oanda_account_id
        self.environment = environment
        
        self._base_url = (
            "https://stream-fxpractice.oanda.com"
            if environment == "practice"
            else "https://stream-fxtrade.oanda.com"
        )
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._callbacks: list[Callable[[TickData], None]] = []
        self._validator = TickValidator()
    
    async def start(self) -> None:
        """Start streaming."""
        self._running = True
        self._session = aiohttp.ClientSession()
        
        # Start streaming for all symbols
        tasks = [self._stream_symbol(s) for s in self.symbols]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def stop(self) -> None:
        """Stop streaming."""
        self._running = False
        if self._session:
            await self._session.close()
    
    async def subscribe(self, callback: Callable[[TickData], None]) -> None:
        """Subscribe to ticks."""
        self._callbacks.append(callback)
    
    async def _stream_symbol(self, symbol: str) -> None:
        """Stream prices for single symbol."""
        url = f"{self._base_url}/v3/accounts/{self.account_id}/pricing/stream"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"instruments": symbol}
        
        while self._running:
            try:
                async with self._session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=None)
                ) as response:
                    async for line in response.content:
                        if not line:
                            continue
                        
                        data = line.decode("utf-8").strip()
                        if not data:
                            continue
                        
                        try:
                            import json
                            msg = json.loads(data)
                            
                            if msg.get("type") == "PRICE":
                                tick = self._parse_tick(msg)
                                
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
                                    
                        except json.JSONDecodeError:
                            continue
                            
            except Exception as e:
                logger.error(f"OANDA stream error for {symbol}: {e}")
                await asyncio.sleep(5)
    
    def _parse_tick(self, data: dict) -> TickData:
        """Parse OANDA price message."""
        symbol = data["instrument"].replace("_", "/")
        
        # Get best bid/ask
        bids = sorted(data.get("bids", []), key=lambda x: float(x["price"]), reverse=True)
        asks = sorted(data.get("asks", []), key=lambda x: float(x["price"]))
        
        bid = Decimal(bids[0]["price"]) if bids else Decimal("0")
        ask = Decimal(asks[0]["price"]) if asks else Decimal("0")
        mid = (bid + ask) / 2 if bid and ask else Decimal("0")
        
        return TickData(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            bid=bid,
            ask=ask,
            mid=mid,
            volume=0,
            source="OANDA"
        )
    
    async def get_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "M1"
    ) -> list[OHLCV]:
        """Fetch historical candles."""
        url = f"https://api-fx{'practice' if self.environment == 'practice' else 'trade'}.oanda.com/v3/instruments/{symbol}/candles"
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "granularity": timeframe,
            "price": "M"  # Midpoint
        }
        
        async with self._session.get(url, headers=headers, params=params) as response:
            data = await response.json()
            candles = data.get("candles", [])
            
            bars = []
            for c in candles:
                if not c["complete"]:
                    continue
                
                bar = OHLCV(
                    symbol=symbol.replace("_", "/"),
                    timestamp=datetime.fromisoformat(c["time"].replace("Z", "+00:00")),
                    open=Decimal(c["mid"]["o"]),
                    high=Decimal(c["mid"]["h"]),
                    low=Decimal(c["mid"]["l"]),
                    close=Decimal(c["mid"]["c"]),
                    volume=int(c["volume"]),
                    frequency=timeframe
                )
                bars.append(bar)
            
            return bars
