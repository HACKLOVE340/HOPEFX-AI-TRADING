# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
    OrderBookAnalysis,
    OrderBookLevel,
    OrderBookSide,
    create_dom_router,
    get_dom_service,
)
from .streaming import (
    AggregatedBar,
    StreamEvent,
    StreamingService,
    StreamStatus,
    Tick,
    TickAggregator,
    create_streaming_router,
    get_streaming_service,
)
from .time_and_sales import (
    AggressorStats,
    ExecutedTrade,
    TimeAndSalesService,
    TradeVelocity,
    create_time_and_sales_router,
    get_time_and_sales_service,
)

__all__ = [
    "AggregatedBar",
    "AggressorStats",
    # Depth of Market
    "DepthOfMarketService",
    "ExecutedTrade",
    "OrderBook",
    "OrderBookAnalysis",
    "OrderBookLevel",
    "OrderBookSide",
    "StreamEvent",
    "StreamStatus",
    # Streaming
    "StreamingService",
    "Tick",
    "TickAggregator",
    # Time & Sales
    "TimeAndSalesService",
    "TradeVelocity",
    "create_dom_router",
    "create_streaming_router",
    "create_time_and_sales_router",
    "get_dom_service",
    "get_streaming_service",
    "get_time_and_sales_service",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Market data management including Depth of Market (DOM) and real-time data streaming"
