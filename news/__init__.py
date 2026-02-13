"""
News Integration Module for HOPEFX AI Trading Platform

This module provides news data collection, sentiment analysis, and market impact prediction
to enhance trading decisions with fundamental analysis.

Components:
- News Providers: NewsAPI, Alpha Vantage, RSS feeds
- Sentiment Analysis: TextBlob, VADER, custom financial sentiment
- Impact Prediction: News-to-price correlation, event scoring
- Economic Calendar: Major economic events tracking

Author: HOPEFX Development Team
Version: 1.0.0
"""

from .providers import (
    NewsProvider,
    NewsAPIProvider,
    AlphaVantageNewsProvider,
    RSSFeedProvider,
    MultiSourceAggregator
)

from .sentiment import (
    SentimentAnalyzer,
    FinancialSentimentAnalyzer,
    SentimentScore
)

from .impact_predictor import (
    ImpactPredictor,
    ImpactLevel,
    MarketImpact
)

from .economic_calendar import (
    EconomicCalendar,
    EconomicEvent,
    EventImportance
)

__all__ = [
    # Providers
    'NewsProvider',
    'NewsAPIProvider',
    'AlphaVantageNewsProvider',
    'RSSFeedProvider',
    'MultiSourceAggregator',

    # Sentiment
    'SentimentAnalyzer',
    'FinancialSentimentAnalyzer',
    'SentimentScore',

    # Impact Prediction
    'ImpactPredictor',
    'ImpactLevel',
    'MarketImpact',

    # Economic Calendar
    'EconomicCalendar',
    'EconomicEvent',
    'EventImportance',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
