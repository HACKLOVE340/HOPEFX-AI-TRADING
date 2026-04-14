# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Social Trading Module

Provides copy trading, strategy marketplace, and community features.
"""

from .copy_trading import CopyTradingEngine
from .leaderboards import PerformanceLeaderboard as LeaderboardManager
from .marketplace import StrategyMarketplace
from .performance import PerformanceTracker
from .profiles import TraderProfileManager as ProfileManager

# broker=None at module load time; injected by core/startup_factories.init_social()
# after the broker is initialised.  Do not pass a broker here.
copy_trading_engine = CopyTradingEngine(broker=None)
marketplace = StrategyMarketplace()
profile_manager = ProfileManager()
leaderboard_manager = LeaderboardManager()
performance_tracker = PerformanceTracker()

__all__ = [
    "CopyTradingEngine",
    "LeaderboardManager",
    "PerformanceTracker",
    "ProfileManager",
    "StrategyMarketplace",
    "copy_trading_engine",
    "leaderboard_manager",
    "marketplace",
    "performance_tracker",
    "profile_manager",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Social trading with copy trading, marketplace, and leaderboards"
