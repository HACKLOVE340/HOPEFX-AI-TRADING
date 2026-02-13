"""
Broker Integration Module

This module provides integration with various trading brokers and exchanges.

Supported brokers:
- OANDA
- MetaTrader 5 (MT5)
- Interactive Brokers (IB)
- Binance
- Alpaca
- And more via CCXT

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

__all__ = [
    'BrokerConnector',
    'Order',
    'Position',
    'AccountInfo',
    'OrderType',
    'OrderSide',
    'OrderStatus',
    'PaperTradingBroker',
]
