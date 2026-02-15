"""
Data Module

This module provides data management and market data functionality:
- Depth of Market (DOM) / Level 2 order book management
- Real-time data streaming
- Historical data handling
- Data normalization and caching
"""

from .depth_of_market import (
    DepthOfMarketService,
    OrderBook,
    OrderBookLevel,
    OrderBookAnalysis,
    OrderBookSide,
    get_dom_service,
    create_dom_router,
)

__all__ = [
    # Depth of Market
    'DepthOfMarketService',
    'OrderBook',
    'OrderBookLevel',
    'OrderBookAnalysis',
    'OrderBookSide',
    'get_dom_service',
    'create_dom_router',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Market data management including Depth of Market (DOM) and real-time data streaming'
