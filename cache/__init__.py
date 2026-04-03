# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Market Data Cache Module

This module provides Redis-based caching for market data with multi-timeframe support.

Main components:
- MarketDataCache: High-performance Redis cache for market data
- Timeframe: Supported timeframe enumerations
- OHLCVData: OHLCV data structure
- CachedTickData: Tick-level data structure
- CacheStatistics: Cache performance metrics
"""

from .market_data_cache import (
    CacheStatistics,
    MarketDataCache,
    OHLCVData,
    Timeframe,
)
from .market_data_cache import (
    TickData as CachedTickData,
)

__all__ = [
    "CacheStatistics",
    "CachedTickData",
    "MarketDataCache",
    "OHLCVData",
    "Timeframe",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Redis-based market data caching with multi-timeframe support"
