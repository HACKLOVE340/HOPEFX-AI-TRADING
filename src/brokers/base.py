"""
Abstract base broker interface with strict typing.
"""
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class TickData:
    """Immutable tick data structure."""
    symbol: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    volume: int
    source: str


@dataclass
class Order:
    """Order request structure."""
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: str = "MARKET"
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: str = "GTC"
    client_order_id: Optional[str] = None


@dataclass
class Position:
    """Position structure."""
    symbol: str
    quantity: Decimal
    avg_entry_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    open_time: datetime


class BaseBroker(ABC):
    """Abstract base class for all broker implementations."""
    
    def __init__(self, name: str, paper_mode: bool = False):
        self.name = name
        self.paper_mode = paper_mode
        self._connected = False
        self._last_ping: Optional[datetime] = None
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to broker."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close broker connection."""
        pass
    
    @abstractmethod
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account balance and margin info."""
        pass
    
    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Get all open positions."""
        pass
    
    @abstractmethod
    async def place_order(self, order: Order) -> Dict[str, Any]:
        """Execute order."""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        pass
    
    @abstractmethod
    async def get_quote(self, symbol: str) -> TickData:
        """Get current market quote."""
        pass
    
    async def health_check(self) -> bool:
        """Verify broker connectivity."""
        try:
            await self.get_account_info()
            self._last_ping = datetime.utcnow()
            return True
        except Exception:
            self._connected = False
            return False
