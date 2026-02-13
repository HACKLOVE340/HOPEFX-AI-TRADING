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

__all__ = [
    '__version__',
    '__author__',
    '__license__',
    'ConfigManager',
    'initialize_config',
    'MarketDataCache',
    'Timeframe',
    'Base',
]
