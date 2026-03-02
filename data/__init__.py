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

from .time_and_sales import (
    TimeAndSalesService,
    ExecutedTrade,
    TradeVelocity,
    AggressorStats,
    get_time_and_sales_service,
    create_time_and_sales_router,
)

from .streaming import (
    StreamingService,
    Tick,
    AggregatedBar,
    StreamEvent,
    StreamStatus,
    TickAggregator,
    get_streaming_service,
    create_streaming_router,
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
    # Time & Sales
    'TimeAndSalesService',
    'ExecutedTrade',
    'TradeVelocity',
    'AggressorStats',
    'get_time_and_sales_service',
    'create_time_and_sales_router',
    # Streaming
    'StreamingService',
    'Tick',
    'AggregatedBar',
    'StreamEvent',
    'StreamStatus',
    'TickAggregator',
    'get_streaming_service',
    'create_streaming_router',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Market data management including Depth of Market (DOM) and real-time data streaming'
