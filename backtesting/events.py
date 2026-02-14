"""
Event System for Backtesting

Defines events used in event-driven backtesting architecture.
"""

from enum import Enum
from typing import Optional
from datetime import datetime


class EventType(Enum):
    """Types of events in backtesting."""
    MARKET = "MARKET"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"


class Event:
    """Base event class."""

    def __init__(self, event_type: EventType):
        self.type = event_type
        self.timestamp = datetime.now()


class MarketEvent(Event):
    """Market data update event."""

    def __init__(self):
        super().__init__(EventType.MARKET)


class SignalEvent(Event):
    """Trading signal from strategy."""

    def __init__(self, symbol: str, signal_type: str, strength: float = 1.0, metadata: dict = None):
        """
        Initialize signal event.

        Args:
            symbol: Trading symbol
            signal_type: 'BUY' or 'SELL'
            strength: Signal strength (0-1)
            metadata: Additional signal information
        """
        super().__init__(EventType.SIGNAL)
        self.symbol = symbol
        self.signal_type = signal_type
        self.strength = strength
        self.metadata = metadata or {}


class OrderEvent(Event):
    """Order to be executed."""

    def __init__(self, symbol: str, order_type: str, quantity: float, direction: str,
                 price: Optional[float] = None):
        """
        Initialize order event.

        Args:
            symbol: Trading symbol
            order_type: 'MARKET', 'LIMIT', 'STOP'
            quantity: Order quantity
            direction: 'BUY' or 'SELL'
            price: Limit/stop price (optional for market orders)
        """
        super().__init__(EventType.ORDER)
        self.symbol = symbol
        self.order_type = order_type
        self.quantity = quantity
        self.direction = direction
        self.price = price


class FillEvent(Event):
    """Order fill confirmation."""

    def __init__(self, symbol: str, quantity: float, direction: str, fill_price: float,
                 commission: float = 0.0):
        """
        Initialize fill event.

        Args:
            symbol: Trading symbol
            quantity: Filled quantity
            direction: 'BUY' or 'SELL'
            fill_price: Execution price
            commission: Commission paid
        """
        super().__init__(EventType.FILL)
        self.symbol = symbol
        self.quantity = quantity
        self.direction = direction
        self.fill_price = fill_price
        self.commission = commission
