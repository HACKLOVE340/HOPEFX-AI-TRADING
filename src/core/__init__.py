"""
Core infrastructure module.
"""

from src.core.config import Settings, get_settings, settings
from src.core.events import Event, EventBus, get_event_bus
from src.core.exceptions import HopeFXError
from src.core.logging_config import configure_logging, get_logger
from src.core.trading_engine import TradingEngine
from src.core.lifecycle import LifecycleManager, LifecycleState

__all__ = [
    "Settings",
    "get_settings",
    "settings",
    "Event",
    "EventBus",
    "get_event_bus",
    "HopeFXError",
    "configure_logging",
    "get_logger",
    "TradingEngine",
    "LifecycleManager",
    "LifecycleState",
]
