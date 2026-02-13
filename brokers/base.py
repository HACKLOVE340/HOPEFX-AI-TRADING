"""
Base Broker Connector

Abstract base class for all broker integrations.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Order types"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(Enum):
    """Order side"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order status"""
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """Order data structure"""
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_price: Optional[float] = None
    timestamp: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class Position:
    """Position data structure"""
    symbol: str
    side: str  # "LONG" or "SHORT"
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0
    timestamp: Optional[datetime] = None


@dataclass
class AccountInfo:
    """Account information"""
    balance: float
    equity: float
    margin_used: float
    margin_available: float
    positions_count: int
    timestamp: Optional[datetime] = None


class BrokerConnector(ABC):
    """
    Abstract base class for broker connectors.
    
    All broker integrations must implement:
    - connect() / disconnect()
    - place_order() / cancel_order()
    - get_positions() / close_position()
    - get_account_info()
    - get_market_data()
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize broker connector.
        
        Args:
            config: Broker configuration dictionary
        """
        self.config = config
        self.connected = False
        self.name = self.__class__.__name__
        
        logger.info(f"Initialized {self.name} broker connector")
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to broker.
        
        Returns:
            True if connection successful
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """
        Disconnect from broker.
        
        Returns:
            True if disconnection successful
        """
        pass
    
    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        **kwargs
    ) -> Order:
        """
        Place an order.
        
        Args:
            symbol: Trading symbol
            side: Buy or sell
            order_type: Market, limit, etc.
            quantity: Order quantity
            price: Limit price (for limit orders)
            stop_price: Stop price (for stop orders)
            **kwargs: Additional broker-specific parameters
            
        Returns:
            Order object
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order identifier
            
        Returns:
            True if cancellation successful
        """
        pass
    
    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """
        Get order by ID.
        
        Args:
            order_id: Order identifier
            
        Returns:
            Order object or None
        """
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Position]:
        """
        Get all open positions.
        
        Returns:
            List of Position objects
        """
        pass
    
    @abstractmethod
    def close_position(self, symbol: str) -> bool:
        """
        Close a position.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if closure successful
        """
        pass
    
    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """
        Get account information.
        
        Returns:
            AccountInfo object
        """
        pass
    
    @abstractmethod
    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get market data (OHLCV).
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., "1h", "1d")
            limit: Number of candles
            
        Returns:
            List of OHLCV dictionaries
        """
        pass
    
    def is_connected(self) -> bool:
        """
        Check if connected to broker.
        
        Returns:
            Connection status
        """
        return self.connected
    
    def __repr__(self) -> str:
        return f"{self.name}(connected={self.connected})"
