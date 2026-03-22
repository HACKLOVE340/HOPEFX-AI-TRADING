"""Abstract broker interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from src.core.types import Order, Fill, Position, Side, OrderType, Symbol


class Broker(ABC):
    """Abstract broker interface."""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Connect to broker."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from broker."""
        pass
    
    @abstractmethod
    async def place_order(self, order: Order) -> Order:
        """Place order."""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        pass
    
    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get open positions."""
        pass
    
    @abstractmethod
    async def get_account(self) -> dict[str, Any]:
        """Get account info."""
        pass
    
    @abstractmethod
    async def stream_quotes(self, symbols: list[Symbol], callback: callable) -> None:
        """Stream quotes."""
        pass
