"""
MetaTrader 5 ZeroMQ bridge for data and execution.
"""

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

import zmq
import zmq.asyncio

from src.core.config import settings
from src.core.exceptions import FeedError
from src.core.logging_config import get_logger
from src.data.feeds.base import DataFeed
from src.domain.models import TickData

logger = get_logger(__name__)


class MT5Bridge(DataFeed):
    """
    ZeroMQ bridge to MetaTrader 5.
    Requires MT5 with ZeroMQ EA running.
    """
    
    def __init__(
        self,
        symbols: list[str],
        host: str = "localhost",
        data_port: int = 15555,
        control_port: int = 15556
    ):
        self.symbols = symbols
        self.host = host
        self.data_port = data_port
        self.control_port = control_port
        
        self._ctx: zmq.asyncio.Context | None = None
        self._data_socket: zmq.asyncio.Socket | None = None
        self._control_socket: zmq.asyncio.Socket | None = None
        self._running = False
        self._callbacks: list[Callable[[TickData], None]] = []
    
    async def start(self) -> None:
        """Start ZeroMQ connections."""
        self._ctx = zmq.asyncio.Context()
        
        # Data socket (SUB)
        self._data_socket = self._ctx.socket(zmq.SUB)
        self._data_socket.connect(f"tcp://{self.host}:{self.data_port}")
        
        # Subscribe to symbols
        for symbol in self.symbols:
            self._data_socket.setsockopt_string(zmq.SUBSCRIBE, symbol)
        
        # Control socket (REQ)
        self._control_socket = self._ctx.socket(zmq.REQ)
        self._control_socket.connect(f"tcp://{self.host}:{self.control_port}")
        
        self._running = True
        
        # Start listener
        asyncio.create_task(self._listen())
        
        # Subscribe to market data
        await self._send_command("SUBSCRIBE", {"symbols": self.symbols})
        
        logger.info(f"MT5 bridge connected to {self.host}")
    
    async def stop(self) -> None:
        """Stop connections."""
        self._running = False
        
        if self._data_socket:
            self._data_socket.close()
        if self._control_socket:
            self._control_socket.close()
        if self._ctx:
            self._ctx.term()
    
    async def subscribe(self, callback: Callable[[TickData], None]) -> None:
        """Subscribe to ticks."""
        self._callbacks.append(callback)
    
    async def _listen(self) -> None:
        """Listen for incoming data."""
        while self._running:
            try:
                msg = await self._data_socket.recv_string()
                data = json.loads(msg)
                
                tick = TickData(
                    symbol=data["symbol"],
                    timestamp=datetime.now(timezone.utc),
                    bid=Decimal(str(data["bid"])),
                    ask=Decimal(str(data["ask"])),
                    mid=(Decimal(str(data["bid"])) + Decimal(str(data["ask"]))) / 2,
                    volume=int(data.get("volume", 0)),
                    source="MT5"
                )
                
                for callback in self._callbacks:
                    try:
                        await callback(tick)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
                        
            except Exception as e:
                logger.error(f"MT5 listen error: {e}")
                await asyncio.sleep(1)
    
    async def _send_command(self, command: str, params: dict) -> dict:
        """Send command to MT5."""
        request = {
            "command": command,
            "params": params
        }
        
        await self._control_socket.send_string(json.dumps(request))
        response = await self._control_socket.recv_string()
        return json.loads(response)
    
    async def get_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "M1"
    ) -> list:
        """Request historical data from MT5."""
        response = await self._send_command("GET_HISTORICAL", {
            "symbol": symbol,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "timeframe": timeframe
        })
        
        # Parse response
        candles = response.get("candles", [])
        from src.domain.models import OHLCV
        
        bars = []
        for c in candles:
            bars.append(OHLCV(
                symbol=symbol,
                timestamp=datetime.fromisoformat(c["time"]),
                open=Decimal(str(c["open"])),
                high=Decimal(str(c["high"])),
                low=Decimal(str(c["low"])),
                close=Decimal(str(c["close"])),
                volume=c["volume"],
                frequency=timeframe
            ))
        
        return bars
