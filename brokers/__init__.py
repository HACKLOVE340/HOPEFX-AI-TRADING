"""
Broker Integration Module

This module provides integration with various trading brokers and exchanges.

Supported brokers:
- OANDA (Forex)
- Binance (Crypto)
- Alpaca (US Stocks)
- MT5 (Universal - ANY MT5 broker)
- Interactive Brokers (Multi-asset)
- Paper Trading (Simulation)

Supported prop firms:
- FTMO
- TopstepTrader
- The5ers
- MyForexFunds

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
from .mt5 import MT5Connector
from .interactive_brokers import InteractiveBrokersConnector
from .factory import BrokerFactory

# Prop firms
from .prop_firms.ftmo import FTMOConnector
from .prop_firms.topstep import TopstepTraderConnector
from .prop_firms.the5ers import The5ersConnector
from .prop_firms.myforexfunds import MyForexFundsConnector

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
    'MT5Connector',
    'InteractiveBrokersConnector',
    # Prop firms
    'FTMOConnector',
    'TopstepTraderConnector',
    'The5ersConnector',
    'MyForexFundsConnector',
    # Factory
    'BrokerFactory',
]
