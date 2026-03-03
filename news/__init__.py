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
- REST API Router: FastAPI endpoints for all news/geopolitical intelligence

Author: HOPEFX Development Team
Version: 1.2.0
"""

import logging
from typing import Optional

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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton risk provider (lazy-initialised)
# ---------------------------------------------------------------------------
_risk_provider: Optional[GeopoliticalRiskProvider] = None


def _get_risk_provider() -> GeopoliticalRiskProvider:
    """Return (or create) the module-level GeopoliticalRiskProvider singleton."""
    global _risk_provider
    if _risk_provider is None:
        _risk_provider = GeopoliticalRiskProvider()
    return _risk_provider


# ---------------------------------------------------------------------------
# FastAPI Router factory
# ---------------------------------------------------------------------------

def create_news_router():
    """
    Build and return a FastAPI APIRouter with news, sentiment, and
    geopolitical intelligence endpoints.

    Register in app.py startup::

        from news import create_news_router
        app.include_router(create_news_router())

    Endpoints
    ---------
    GET  /api/news/geopolitical/signal        — Gold trading signal from geopolitical events
    GET  /api/news/geopolitical/events        — Current geopolitical events list
    GET  /api/news/geopolitical/assessment    — Full risk assessment report
    GET  /api/news/geopolitical/world-monitor — World Monitor integration URLs
    GET  /api/news/economic/upcoming          — Upcoming high-impact economic events
    GET  /api/news/sentiment/{symbol}         — Market sentiment for a symbol
    """
    try:
        from fastapi import APIRouter, HTTPException, Query
    except ImportError:
        logger.warning("FastAPI not available; news router not created.")
        return None

    news_router = APIRouter(prefix="/api/news", tags=["News & Geopolitical Intelligence"])

    # ── Geopolitical endpoints ──────────────────────────────────────────────

    @news_router.get("/geopolitical/signal")
    async def get_gold_signal():
        """
        Return a gold trading signal derived from live geopolitical intelligence.

        Uses the GeopoliticalRiskProvider (World Monitor layer + internal risk model).
        Falls back gracefully when no live data source is configured.

        The ``direction`` field is always returned in uppercase: BUY, SELL, or HOLD.
        """
        try:
            provider = _get_risk_provider()
            signal = provider.get_gold_trading_signal()
            # Normalize direction to uppercase for consistent API contract
            if "direction" in signal and isinstance(signal["direction"], str):
                signal = dict(signal)
                signal["direction"] = signal["direction"].upper()
            return signal
        except Exception as exc:
            logger.error(f"Geopolitical signal error: {exc}")
            raise HTTPException(status_code=500, detail=f"Geopolitical signal unavailable: {exc}")

    @news_router.get("/geopolitical/events")
    async def get_geopolitical_events(force_refresh: bool = Query(False)):
        """
        Return current geopolitical events tracked by the risk provider.

        Pass ``force_refresh=true`` to bypass the TTL cache and fetch fresh data.

        **Cache behaviour**: The provider caches events for a configurable TTL
        (default 5 minutes). When ``force_refresh=true`` the cache is ignored and
        a fresh fetch is performed. If the underlying data source is unavailable
        the provider returns an empty list rather than raising an error.
        """
        try:
            provider = _get_risk_provider()
            events = provider.get_current_events(force_refresh=force_refresh)
            return {
                "events": [e.to_dict() for e in events],
                "count": len(events),
            }
        except Exception as exc:
            logger.error(f"Geopolitical events error: {exc}")
            raise HTTPException(status_code=500, detail=f"Events unavailable: {exc}")

    @news_router.get("/geopolitical/assessment")
    async def get_risk_assessment():
        """
        Return a full GeopoliticalRiskAssessment including global risk score,
        gold outlook, high-risk regions, country risks, and trading recommendations.
        """
        try:
            provider = _get_risk_provider()
            assessment = provider.get_risk_assessment()
            return assessment.to_dict()
        except Exception as exc:
            logger.error(f"Risk assessment error: {exc}")
            raise HTTPException(status_code=500, detail=f"Assessment unavailable: {exc}")

    @news_router.get("/geopolitical/world-monitor")
    async def get_world_monitor_urls():
        """
        Return curated World Monitor dashboard URLs relevant to XAU/USD trading.

        These deep-links open specific intelligence views on https://worldmonitor.app/
        """
        try:
            wm = WorldMonitorIntegration()
            return {
                "gold_relevant_views": wm.get_gold_relevant_views(),
                "base_url": "https://worldmonitor.app",
            }
        except Exception as exc:
            logger.error(f"World Monitor URLs error: {exc}")
            raise HTTPException(status_code=500, detail=f"World Monitor integration error: {exc}")

    # ── Economic calendar endpoint ─────────────────────────────────────────

    @news_router.get("/economic/upcoming")
    async def get_upcoming_events(hours_ahead: int = Query(24, ge=1, le=168)):
        """
        Return upcoming high-impact economic events within the next N hours (1-168).

        Defaults to 24 hours. Only CRITICAL and HIGH importance events are returned.
        """
        try:
            from datetime import datetime, timezone, timedelta
            calendar = EconomicCalendar()
            now = datetime.now(timezone.utc)
            cutoff = now + timedelta(hours=hours_ahead)
            events = calendar.get_upcoming_events()
            upcoming = []
            for evt in events:
                try:
                    evt_time = evt.scheduled_time
                    if evt_time.tzinfo is None:
                        evt_time = evt_time.replace(tzinfo=timezone.utc)
                    if now <= evt_time <= cutoff:
                        upcoming.append({
                            "title": evt.title,
                            "time": evt_time.isoformat(),
                            "country": evt.country,
                            "importance": evt.importance.value if hasattr(evt.importance, "value") else str(evt.importance),
                            "forecast": evt.forecast,
                            "previous": evt.previous,
                        })
                except Exception:
                    pass
            return {"events": upcoming, "count": len(upcoming), "hours_ahead": hours_ahead}
        except Exception as exc:
            logger.error(f"Economic calendar error: {exc}")
            raise HTTPException(status_code=500, detail=f"Economic calendar unavailable: {exc}")

    # ── Sentiment endpoint ──────────────────────────────────────────────────

    @news_router.get("/sentiment/{symbol}")
    async def get_symbol_sentiment(symbol: str):
        """
        Return aggregated news sentiment for a trading symbol (e.g. XAUUSD, BTCUSD).

        The sentiment score ranges from -1.0 (very bearish) to +1.0 (very bullish).
        Returns neutral (0.0) when no recent news is found.
        """
        try:
            analyzer = FinancialSentimentAnalyzer()
            # Map common symbol names to search terms
            search_terms = {
                "XAUUSD": ["gold", "XAU", "XAUUSD"],
                "BTCUSD": ["bitcoin", "BTC", "crypto"],
                "EURUSD": ["euro", "EUR", "EURUSD"],
                "GBPUSD": ["pound", "GBP", "sterling"],
                "USDJPY": ["yen", "JPY", "Japan"],
            }
            terms = search_terms.get(symbol.upper(), [symbol.upper()])
            score = analyzer.analyze_batch(terms)
            return {
                "symbol": symbol.upper(),
                "sentiment_score": score.score if hasattr(score, "score") else float(score),
                "label": score.label if hasattr(score, "label") else ("bullish" if score > 0 else "bearish" if score < 0 else "neutral"),
            }
        except Exception as exc:
            logger.error(f"Sentiment analysis error for {symbol}: {exc}")
            raise HTTPException(status_code=500, detail=f"Sentiment unavailable: {exc}")

    return news_router


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

    # Router factory
    'create_news_router',
]

# Module metadata
__version__ = '1.2.0'
__author__ = 'HOPEFX Development Team'

