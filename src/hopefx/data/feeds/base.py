# src/hopefx/data/feeds/base.py
"""
Abstract base for all market data feeds.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import AsyncIterator, Callable, Coroutine, Literal

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class TickData:
    """Normalized tick data."""
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal | None = None
    volume: Decimal = Decimal("0")
    timestamp: float = 0.0
    timestamp_exchange: float | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class BarData:
    """Normalized OHLCV bar."""
    symbol: str
    timeframe: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timestamp: float


class DataFeed(ABC):
    """Abstract market data feed."""
    
    def __init__(self, name: str) -> None:
        self.name = name
        self._connected = False
        self._callbacks: list[Callable[[TickData], Coroutine[None, None, None]]] = []
        self.logger = logger.bind(feed=name)
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        pass
    
    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to symbols."""
        pass
    
    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""
        pass
    
    def on_tick(self, callback: Callable[[TickData], Coroutine[None, None, None]]) -> None:
        """Register tick callback."""
        self._callbacks.append(callback)
    
    async def _emit_tick(self, tick: TickData) -> None:
        """Emit tick to all callbacks."""
        for cb in self._callbacks:
            try:
                await cb(tick)
            except Exception as e:
                self.logger.error("callback_error", error=str(e))
    
    @property
    def is_connected(self) -> bool:
        return self._connected
