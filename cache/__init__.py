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
    MarketDataCache,
    Timeframe,
    OHLCVData,
    CachedTickData,
    CacheStatistics,
)

__all__ = [
    'MarketDataCache',
    'Timeframe',
    'OHLCVData',
    'CachedTickData',
    'CacheStatistics',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Redis-based market data caching with multi-timeframe support'
