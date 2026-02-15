"""
News Integration Module for HOPEFX AI Trading Platform

This module provides news data collection, sentiment analysis, and market impact prediction
to enhance trading decisions with fundamental analysis.

Components:
- News Providers: NewsAPI, Alpha Vantage, RSS feeds
- Sentiment Analysis: TextBlob, VADER, custom financial sentiment
- Impact Prediction: News-to-price correlation, event scoring
- Economic Calendar: Major economic events tracking
- Geopolitical Risk: World Monitor integration for conflict/sanctions/risk intelligence
  - Direct API access to World Monitor endpoints
  - Self-hosting support for custom deployments
  - Customizable data layers for trading strategies

Author: HOPEFX Development Team
Version: 1.2.0
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

from .geopolitical_risk import (
    # Core Classes
    GeopoliticalRiskProvider,
    GeopoliticalEvent,
    GeopoliticalRiskAssessment,
    GeopoliticalEventType,
    RiskSeverity,
    GoldImpact,
    CountryRisk,
    
    # World Monitor Integration
    WorldMonitorIntegration,
    WorldMonitorAPIClient,
    WorldMonitorSelfHostConfig,
    CustomDataLayerConfig,
    
    # Convenience Functions
    get_geopolitical_provider,
    get_gold_geopolitical_signal,
    get_api_client,
    get_gold_signal_from_api,
    create_self_hosted_setup,
    get_custom_layer_config,
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

    # Geopolitical Risk (World Monitor Integration)
    'GeopoliticalRiskProvider',
    'GeopoliticalEvent',
    'GeopoliticalRiskAssessment',
    'GeopoliticalEventType',
    'RiskSeverity',
    'GoldImpact',
    'CountryRisk',
    'WorldMonitorIntegration',
    'WorldMonitorAPIClient',
    'WorldMonitorSelfHostConfig',
    'CustomDataLayerConfig',
    'get_geopolitical_provider',
    'get_gold_geopolitical_signal',
    'get_api_client',
    'get_gold_signal_from_api',
    'create_self_hosted_setup',
    'get_custom_layer_config',
]

# Module metadata
__version__ = '1.2.0'
__author__ = 'HOPEFX Development Team'
