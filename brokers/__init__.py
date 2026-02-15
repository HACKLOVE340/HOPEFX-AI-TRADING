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

Advanced order types:
- OCO (One-Cancels-Other)
- Bracket orders
- Trailing stops
- Conditional orders
- Scaled orders

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
from .advanced_orders import (
    AdvancedOrderManager,
    OCOOrder,
    BracketOrder,
    TrailingStopOrder,
    ConditionalOrder,
    ScaledOrder,
    TimeInForce,
)

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
    # Advanced orders
    'AdvancedOrderManager',
    'OCOOrder',
    'BracketOrder',
    'TrailingStopOrder',
    'ConditionalOrder',
    'ScaledOrder',
    'TimeInForce',
    # Prop firms
    'FTMOConnector',
    'TopstepTraderConnector',
    'The5ersConnector',
    'MyForexFundsConnector',
    # Factory
    'BrokerFactory',
]

# Module metadata
__version__ = '2.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Multi-broker integration with prop firm support and advanced order types'
