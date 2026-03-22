"""
Abstract data feed interface.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable

from src.domain.models import OHLCV, TickData


class DataFeed(ABC):
    """
    Abstract base for all market data feeds.
    """
    
    @abstractmethod
    async def start(self) -> None:
        """Start receiving data."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop receiving data."""
        pass
    
    @abstractmethod
    async def subscribe(self, callback: Callable[[TickData], None]) -> None:
        """Subscribe to tick updates."""
        pass
    
    @abstractmethod
    async def get_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "minute"
    ) -> list[OHLCV]:
        """Fetch historical data."""
        pass
