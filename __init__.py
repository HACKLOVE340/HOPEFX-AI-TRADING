"""
HOPEFX AI Trading Framework
Advanced AI-powered trading framework with machine learning, real-time analysis,
multi-broker integration, and intelligent trade execution.
"""

__version__ = '1.0.0'
__author__ = 'HOPEFX Team'
__license__ = 'MIT'

# Import main components
from config import ConfigManager, initialize_config
from cache import MarketDataCache, Timeframe
from database import Base

# Import trading components
from strategies import (
    BaseStrategy, Signal, SignalType, StrategyStatus,
    StrategyManager, MovingAverageCrossover
)
from risk import RiskManager, RiskConfig, PositionSize, PositionSizeMethod
from brokers import (
    BrokerConnector, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus, PaperTradingBroker
)
from notifications import NotificationManager, NotificationLevel, NotificationChannel

__all__ = [
    # Version info
    '__version__',
    '__author__',
    '__license__',

    # Configuration
    'ConfigManager',
    'initialize_config',

    # Cache
    'MarketDataCache',
    'Timeframe',

    # Database
    'Base',

    # Strategies
    'BaseStrategy',
    'Signal',
    'SignalType',
    'StrategyStatus',
    'StrategyManager',
    'MovingAverageCrossover',

    # Risk Management
    'RiskManager',
    'RiskConfig',
    'PositionSize',
    'PositionSizeMethod',

    # Brokers
    'BrokerConnector',
    'Order',
    'Position',
    'AccountInfo',
    'OrderType',
    'OrderSide',
    'OrderStatus',
    'PaperTradingBroker',

    # Notifications
    'NotificationManager',
    'NotificationLevel',
    'NotificationChannel',
]
