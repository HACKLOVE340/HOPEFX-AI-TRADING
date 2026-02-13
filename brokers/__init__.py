"""
Broker Integration Module

This module provides integration with various trading brokers and exchanges.

Supported brokers:
- OANDA (Forex)
- Binance (Crypto)
- Alpaca (US Stocks)
- Paper Trading (Simulation)

Each broker module provides:
- Connection management
- Order execution
- Account management
- Market data streaming
"""

from .base import (
    BrokerConnector,
    Order,
    Position,
    AccountInfo,
    OrderType,
    OrderSide,
    OrderStatus,
)
from .paper_trading import PaperTradingBroker
from .oanda import OANDAConnector
from .binance import BinanceConnector
from .alpaca import AlpacaConnector
from .factory import BrokerFactory

__all__ = [
    # Base classes and enums
    'BrokerConnector',
    'Order',
    'Position',
    'AccountInfo',
    'OrderType',
    'OrderSide',
    'OrderStatus',
    # Broker implementations
    'PaperTradingBroker',
    'OANDAConnector',
    'BinanceConnector',
    'AlpacaConnector',
    # Factory
    'BrokerFactory',
]
