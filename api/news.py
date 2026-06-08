# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
News API helpers — thin async wrappers over the news package.

Provides the two functions imported by api/signals.py:
  get_sentiment_for_symbol(symbol)        — aggregated news sentiment dict
  get_news_for_symbol(symbol, limit)      — recent news items list

Both functions are async and designed for FastAPI dependency injection or
direct await calls from endpoint handlers.  They delegate to the news
package (news/sentiment.py, news/providers.py) and return normalised dicts
that match the shape expected by the signals endpoint.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ── Symbol → search-term mapping ─────────────────────────────────────────────

_SYMBOL_TERMS: dict[str, list[str]] = {
    "XAUUSD": ["gold", "XAU", "XAUUSD", "precious metals"],
    "XAGUSD": ["silver", "XAG", "precious metals"],
    "XPTUSD": ["platinum", "XPT"],
    "EURUSD": ["euro", "EUR", "European Central Bank", "ECB"],
    "GBPUSD": ["pound sterling", "GBP", "Bank of England", "BoE"],
    "USDJPY": ["yen", "JPY", "Bank of Japan", "BoJ"],
    "AUDUSD": ["Australian dollar", "AUD", "Reserve Bank of Australia"],
    "USDCAD": ["Canadian dollar", "CAD", "Bank of Canada"],
    "USDCHF": ["Swiss franc", "CHF", "SNB"],
    "NZDUSD": ["New Zealand dollar", "NZD"],
    "BTCUSD": ["bitcoin", "BTC", "crypto", "cryptocurrency"],
    "ETHUSD": ["ethereum", "ETH", "crypto"],
}

_IMPACT_MAP: dict[str, str] = {
    "XAUUSD": "gold",
    "XAGUSD": "silver",
    "EURUSD": "fx",
    "GBPUSD": "fx",
}


def _get_search_terms(symbol: str) -> list[str]:
    from utils.symbol import canonical as _canonical

    sym = _canonical(symbol)
    return _SYMBOL_TERMS.get(sym, [sym])


# ── Public async API ──────────────────────────────────────────────────────────


async def get_sentiment_for_symbol(symbol: str) -> dict[str, Any]:
    """
    Return aggregated news sentiment for a trading symbol.

    Tries the following sources in order:
    1. news.FinancialSentimentAnalyzer.analyze_batch()
    2. news/providers.py RSS feeds (no API key required)
    3. Neutral fallback

    Returns a dict with:
      sentiment_score  : float -1.0 (bearish) to +1.0 (bullish)
      label            : "very_bearish" / "bearish" / "neutral" / "bullish" / "very_bullish"
      confidence       : float 0–1
      sources          : int (number of articles analysed)
      gold_score       : float (gold-specific score for XAU)
      usd_score        : float
      geopolitical_score : float
      updated_at       : int (ms timestamp)
    """
    terms = _get_search_terms(symbol)
    ts = int(datetime.now(UTC).timestamp() * 1000)

    # ── Primary: FinancialSentimentAnalyzer ───────────────────────────────
    try:
        from news.sentiment import FinancialSentimentAnalyzer

        analyzer = FinancialSentimentAnalyzer()
        score_obj = analyzer.analyze_batch(terms)

        # score_obj is a SentimentScore dataclass
        polarity = float(getattr(score_obj, "polarity", 0.0))
        confidence = float(getattr(score_obj, "confidence", 0.0))
        label_raw = getattr(score_obj, "label", None)

        if hasattr(label_raw, "value"):
            label = str(label_raw.value)
        elif label_raw is not None:
            label = str(label_raw)
        elif polarity >= 0.5:
            label = "very_bullish"
        elif polarity >= 0.1:
            label = "bullish"
        elif polarity <= -0.5:
            label = "very_bearish"
        elif polarity <= -0.1:
            label = "bearish"
        else:
            label = "neutral"

        # Gold-specific score from geopolitical risk module
        gold_score = 0.0
        geo_score = 0.0
        from utils.symbol import canonical as _canonical

        _sym_canonical = _canonical(symbol)
        if "XAU" in _sym_canonical:
            try:
                from news.geopolitical_risk import get_geopolitical_provider

                provider = get_geopolitical_provider()
                risk = await provider.get_risk_assessment()
                # global_risk_score is 0–100; normalise to 0–1
                raw_risk = float(getattr(risk, "global_risk_score", 0.0))
                geo_score = round(raw_risk / 100.0, 4)
                # High geopolitical risk → bullish gold
                gold_score = min(geo_score * 0.8, 1.0)
            except Exception:  # nosec B110  # noqa: S110
                pass

        return {
            "sentiment_score": round(polarity, 4),
            "label": label,
            "confidence": round(confidence, 4),
            "sources": len(terms),  # min proxy when provider count unavailable
            "gold_score": round(gold_score, 4),
            "usd_score": round(-polarity * 0.6, 4) if "XAU" in _sym_canonical else round(polarity, 4),
            "geopolitical_score": round(geo_score, 4),
            "updated_at": ts,
        }

    except Exception as exc:
        logger.debug("get_sentiment_for_symbol primary failed: %s", exc)

    # ── Secondary: RSS provider (free, no key) ────────────────────────────
    try:
        from news.providers import RSSFeedProvider
        from news.sentiment import FinancialSentimentAnalyzer

        provider = RSSFeedProvider()
        articles = provider.get_news(hours_back=4)

        from utils.symbol import canonical as _canonical

        _canonical(symbol)
        relevant = [
            a for a in articles if any(t.lower() in (a.title + " " + (a.description or "")).lower() for t in terms)
        ]

        if relevant:
            analyzer = FinancialSentimentAnalyzer()
            texts = [f"{a.title} {a.description or ''}" for a in relevant]
            score_obj = analyzer.analyze_batch(texts)
            polarity = float(getattr(score_obj, "polarity", 0.0))

            return {
                "sentiment_score": round(polarity, 4),
                "label": "bullish" if polarity > 0.1 else ("bearish" if polarity < -0.1 else "neutral"),
                "confidence": round(min(len(relevant) / 10, 1.0), 4),
                "sources": len(relevant),
                "gold_score": 0.0,
                "usd_score": 0.0,
                "geopolitical_score": 0.0,
                "updated_at": ts,
            }
    except Exception as exc:
        logger.debug("get_sentiment_for_symbol RSS fallback failed: %s", exc)

    # ── Neutral fallback ──────────────────────────────────────────────────
    return {
        "sentiment_score": 0.0,
        "label": "neutral",
        "confidence": 0.0,
        "sources": 0,
        "gold_score": 0.0,
        "usd_score": 0.0,
        "geopolitical_score": 0.0,
        "updated_at": ts,
    }


async def get_news_for_symbol(symbol: str, limit: int = 15) -> list[dict[str, Any]]:
    """
    Return recent news articles relevant to a trading symbol.

    Tries the following sources in order:
    1. news/providers.py RSS feeds (no API key required)
    2. NewsAPI provider (requires NEWSAPI_ORG_KEY env var)
    3. Empty list fallback

    Returns a list of dicts with:
      id          : str
      headline    : str
      source      : str
      url         : str
      sentiment   : float
      publishedAt : str (ISO 8601)
      impact      : str ("high" / "medium" / "low")
    """
    terms = _get_search_terms(symbol)
    items: list[dict[str, Any]] = []

    # ── Primary: RSS (free) ───────────────────────────────────────────────
    try:
        from news.providers import RSSFeedProvider
        from news.sentiment import FinancialSentimentAnalyzer

        provider = RSSFeedProvider()
        articles = provider.get_news(hours_back=24)
        analyzer = FinancialSentimentAnalyzer()

        relevant = [
            a for a in articles if any(t.lower() in (a.title + " " + (a.description or "")).lower() for t in terms)
        ]

        for i, art in enumerate(relevant[:limit]):
            sentiment_score = 0.0
            try:
                s = analyzer.analyze(f"{art.title} {art.description or ''}")
                sentiment_score = round(float(getattr(s, "polarity", 0.0)), 4)
            except Exception:  # nosec B110  # noqa: S110
                pass

            items.append(
                {
                    "id": str(i),
                    "headline": art.title,
                    "source": art.source,
                    "url": art.url,
                    "sentiment": sentiment_score,
                    "publishedAt": art.published_at.isoformat()
                    if hasattr(art.published_at, "isoformat")
                    else str(art.published_at),
                    "impact": "high"
                    if abs(sentiment_score) > 0.5
                    else ("medium" if abs(sentiment_score) > 0.2 else "low"),
                }
            )

        if items:
            return items
    except Exception as exc:
        logger.debug("get_news_for_symbol RSS: %s", exc)

    # ── Secondary: NewsAPI provider ───────────────────────────────────────
    try:
        import os

        api_key = os.getenv("NEWSAPI_ORG_KEY", "")
        if api_key:
            from news.providers import NewsAPIProvider
            from news.sentiment import FinancialSentimentAnalyzer

            provider = NewsAPIProvider(api_key=api_key)
            articles = provider.get_news(query=" OR ".join(terms[:2]), hours_back=24, page_size=limit)
            analyzer = FinancialSentimentAnalyzer()

            for i, art in enumerate(articles[:limit]):
                sentiment_score = 0.0
                try:
                    s = analyzer.analyze(f"{art.title} {art.description or ''}")
                    sentiment_score = round(float(getattr(s, "polarity", 0.0)), 4)
                except Exception:  # nosec B110  # noqa: S110
                    pass

                items.append(
                    {
                        "id": str(i),
                        "headline": art.title,
                        "source": art.source,
                        "url": art.url,
                        "sentiment": sentiment_score,
                        "publishedAt": art.published_at.isoformat()
                        if hasattr(art.published_at, "isoformat")
                        else str(art.published_at),
                        "impact": "high" if abs(sentiment_score) > 0.5 else "medium",
                    }
                )
    except Exception as exc:
        logger.debug("get_news_for_symbol NewsAPI: %s", exc)

    return items
