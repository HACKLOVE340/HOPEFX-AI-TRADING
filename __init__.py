"""
HOPEFX AI Trading Framework
Advanced AI-powered trading framework with machine learning, real-time analysis,
multi-broker integration, and intelligent trade execution.
"""

__version__ = '1.0.0'
__author__ = 'HOPEFX Team'
__license__ = 'MIT'

# Import main components — wrapped so partial installs don't break the package
try:
    from config import ConfigManager, initialize_config
except Exception:  # pragma: no cover
    pass

try:
    from cache import MarketDataCache, Timeframe
except Exception:  # pragma: no cover
    pass

try:
    from database import Base
except Exception:  # pragma: no cover
    pass

# Import trading components — wrapped so partial installs don't break the package
try:
    from strategies import (
        BaseStrategy, Signal, SignalType, StrategyStatus,
        StrategyManager, MovingAverageCrossover
    )
except Exception:  # pragma: no cover
    pass

try:
    from risk import RiskManager, RiskConfig, PositionSize, PositionSizeMethod
except Exception:  # pragma: no cover
    pass

try:
    from brokers import (
        BrokerConnector, Order, Position, AccountInfo,
        OrderType, OrderSide, OrderStatus, PaperTradingBroker
    )
except Exception:  # pragma: no cover
    pass

try:
    from notifications import NotificationManager, NotificationLevel, NotificationChannel
except Exception:  # pragma: no cover
    pass

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
