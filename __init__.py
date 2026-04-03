import logging

logger = logging.getLogger(__name__)
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX AI Trading Framework
Advanced AI-powered trading framework with machine learning, real-time analysis,
multi-broker integration, and intelligent trade execution.
"""

__version__ = "1.0.0"
__author__ = "HOPEFX Team"
__license__ = "MIT"

# Import main components — wrapped so partial installs don't break the package
try:
    from config import ConfigManager, initialize_config
except Exception as _exc:  # pragma: no cover
    logger.debug("Suppressed exception: %s", _exc)

try:
    from cache import MarketDataCache, Timeframe
except Exception as _exc:  # pragma: no cover
    logger.debug("Suppressed exception: %s", _exc)

try:
    from database import Base
except Exception as _exc:  # pragma: no cover
    logger.debug("Suppressed exception: %s", _exc)

# Import trading components — wrapped so partial installs don't break the package
try:
    from strategies import (
        BaseStrategy,
        MovingAverageCrossover,
        Signal,
        SignalType,
        StrategyManager,
        StrategyStatus,
    )
except Exception as _exc:  # pragma: no cover
    logger.debug("Suppressed exception: %s", _exc)

try:
    from risk import PositionSize, PositionSizeMethod, RiskConfig, RiskManager
except Exception as _exc:  # pragma: no cover
    logger.debug("Suppressed exception: %s", _exc)

try:
    from brokers import (
        AccountInfo,
        BrokerConnector,
        Order,
        OrderSide,
        OrderStatus,
        OrderType,
        PaperTradingBroker,
        Position,
    )
except Exception as _exc:  # pragma: no cover
    logger.debug("Suppressed exception: %s", _exc)

try:
    from notifications import (
        NotificationChannel,
        NotificationLevel,
        NotificationManager,
    )
except Exception as _exc:  # pragma: no cover
    logger.debug("Suppressed exception: %s", _exc)

__all__ = [
    "AccountInfo",
    # Database
    "Base",
    # Strategies
    "BaseStrategy",
    # Brokers
    "BrokerConnector",
    # Configuration
    "ConfigManager",
    # Cache
    "MarketDataCache",
    "MovingAverageCrossover",
    "NotificationChannel",
    "NotificationLevel",
    # Notifications
    "NotificationManager",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperTradingBroker",
    "Position",
    "PositionSize",
    "PositionSizeMethod",
    "RiskConfig",
    # Risk Management
    "RiskManager",
    "Signal",
    "SignalType",
    "StrategyManager",
    "StrategyStatus",
    "Timeframe",
    "__author__",
    "__license__",
    # Version info
    "__version__",
    "initialize_config",
]
