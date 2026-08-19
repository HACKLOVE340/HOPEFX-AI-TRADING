# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/feeds/news — News feed adapters for gold sentiment.

Public API
----------
    NewsFeedBase        Abstract base class for all news feed adapters.
                        Implements retry, rate limiting, and deduplication.

Individual adapters (internal — use NewsSentimentEngine, not these directly)
-----------------------------------------------------------------------------
    FinnhubFeed     Finnhub company news + native sentiment scores
    FMPFeed         Financial Modeling Prep gold-ticker articles
    NewsDataFeed        NewsData.io full-text gold search
    AlphaVantageNewsFeed  Alpha Vantage pre-scored news sentiment
    NewsAPIFeed         NewsAPI.org broad coverage with keyword filter
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.feeds.news.base import NewsFeedBase
except Exception as _exc:
    logger.debug("data_layer.feeds.news: NewsFeedBase unavailable: %s", _exc)
    NewsFeedBase = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.news.finnhub import FinnhubFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.news: FinnhubFeed unavailable: %s", _exc)
    FinnhubFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.news.fmp import FMPFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.news: FMPFeed unavailable: %s", _exc)
    FMPFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.news.newsdata import NewsDataFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.news: NewsDataFeed unavailable: %s", _exc)
    NewsDataFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.news.alpha_vantage import AlphaVantageNewsFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.news: AlphaVantageNewsFeed unavailable: %s", _exc)
    AlphaVantageNewsFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.news.newsapi import NewsAPIFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.news: NewsAPIFeed unavailable: %s", _exc)
    NewsAPIFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.news.manager import NewsFeedManager
except Exception as _exc:
    logger.debug("data_layer.feeds.news: NewsFeedManager unavailable: %s", _exc)
    NewsFeedManager = None  # type: ignore[assignment,misc]

__all__ = [
    "AlphaVantageNewsFeed",
    "NewsFeedManager",
    "FMPFeed",
    "FinnhubFeed",
    "NewsAPIFeed",
    "NewsFeedBase",
    "NewsDataFeed",
]
