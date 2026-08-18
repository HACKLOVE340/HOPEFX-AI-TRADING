# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
market_data — Real-time market data feeds and order book management.

Public API
----------
    OrderBookFeed       L2 order book feed with bid/ask depth tracking.
                        Supports IBKR, MT5, and simulated feeds.
    IBKRMarketDataFeed            Interactive Brokers real-time market data feed.
    MT5LiveFeed         MetaTrader 5 live price and tick feed.
    MarketDataValidator Validates incoming tick and OHLCV data quality.

Usage
-----
    from market_data import get_order_book_feed
    feed = get_order_book_feed()
    await feed.start(["XAU_USD", "EUR_USD"])
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

try:
    from market_data.order_book import OrderBookFeed, get_order_book_feed
except Exception as _exc:
    logger.debug("market_data.order_book unavailable: %s", _exc)
    OrderBookFeed = None  # type: ignore[assignment,misc]
    get_order_book_feed = None  # type: ignore[assignment]

try:
    from market_data.ibkr_feed import IBKRMarketDataFeed
except Exception as _exc:
    logger.debug("market_data.ibkr_feed unavailable: %s", _exc)
    IBKRMarketDataFeed = None  # type: ignore[assignment,misc]

try:
    from market_data.mt5_live_feed import MT5LiveFeed
except Exception as _exc:
    logger.debug("market_data.mt5_live_feed unavailable: %s", _exc)
    MT5LiveFeed = None  # type: ignore[assignment,misc]

try:
    from market_data.validation import MarketDataValidator
except Exception as _exc:
    logger.debug("market_data.validation unavailable: %s", _exc)
    MarketDataValidator = None  # type: ignore[assignment,misc]

__all__ = [
    "IBKRMarketDataFeed",
    "MT5LiveFeed",
    "MarketDataValidator",
    "OrderBookFeed",
    "get_order_book_feed",
]
