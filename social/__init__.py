"""
Social Trading Module

Provides copy trading, strategy marketplace, and community features.
"""

from .copy_trading import CopyTradingEngine
from .marketplace import StrategyMarketplace
from .profiles import ProfileManager
from .leaderboards import LeaderboardManager
from .performance import PerformanceTracker

copy_trading_engine = CopyTradingEngine()
marketplace = StrategyMarketplace()
profile_manager = ProfileManager()
leaderboard_manager = LeaderboardManager()
performance_tracker = PerformanceTracker()

__all__ = [
    'CopyTradingEngine',
    'StrategyMarketplace',
    'ProfileManager',
    'LeaderboardManager',
    'PerformanceTracker',
    'copy_trading_engine',
    'marketplace',
    'profile_manager',
    'leaderboard_manager',
    'performance_tracker',
]
