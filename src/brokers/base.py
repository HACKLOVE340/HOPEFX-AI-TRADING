"""
Abstract broker interface.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from src.domain.enums import BrokerType
from src.domain.models import Account, Order, Position, TickData


class Broker(ABC):
    """
    Base class for all broker integrations.
    """
    
    def __init__(self, broker_type: BrokerType, credentials: dict[str, Any]):
        self.broker_type = broker_type
        self.credentials = credentials
        self._connected = False
        self._account: Account | None = None
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        pass
    
    @abstractmethod
    async def get_account(self) -> Account:
        """Fetch account information."""
        pass
    
    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """Submit order."""
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
    async def get_quote(self, symbol: str) -> TickData:
        """Get current quote."""
        pass
    
    @abstractmethod
    async def stream_quotes(self, symbols: list[str], callback: callable) -> None:
        """Stream real-time quotes."""
        pass
    
    @property
    def is_connected(self) -> bool:
        return self._connected
