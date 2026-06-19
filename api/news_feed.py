# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/news_feed.py
=================
News Feed & Sentiment API — serves the frontend News & Sentiment page.
Provides: /api/news/feed, /api/news/nuclear-score, /api/news/calendar
Connected to: news/nuclear_wordmap_scorer.py, data_layer/feeds/news/
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query
import contextlib

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["News Feed"])


def _get_news_manager():
    """Retrieve the news feed manager from app state."""
    try:
        from core.app_state import app_state

        mgr = getattr(app_state, "news_feed_manager", None)
        if mgr is None:
            from data_layer.feeds.news.base import NewsFeedManager

            mgr = NewsFeedManager()
            app_state.news_feed_manager = mgr
        return mgr
    except Exception as e:
        logger.warning(f"News manager init failed: {e}")
        return None


def _get_nuclear_scorer():
    """Retrieve the geopolitical risk scorer (WORDMAP + optional LLM).

    Returns an LLMGeopoliticalScorer, which wraps the deterministic
    NuclearWordMapScorer and adds an optional LLM extraction path (gated by
    GEOPOLITICAL_LLM_EXTRACTION). The wrapper is always safe: with the flag off
    it scores via the WORDMAP exactly as before.
    """
    try:
        from core.app_state import app_state

        scorer = getattr(app_state, "nuclear_scorer", None)
        if scorer is None:
            from news.geopolitical_llm import LLMGeopoliticalScorer

            scorer = LLMGeopoliticalScorer()
            app_state.nuclear_scorer = scorer
        return scorer
    except Exception as e:
        logger.warning(f"Nuclear scorer init failed: {e}")
        return None


async def _severity(scorer, text: str) -> int:
    """Return the 0–10 geopolitical severity for a text.

    Uses the scorer's async LLM path when available (falls back to WORDMAP
    internally). Previously this module called a non-existent ``score_text``
    method, so every Exception was swallowed and the score was always 0 — this
    restores real scoring and adds the LLM upgrade.
    """
    try:
        severity, _action, _score, _meta = await scorer.score_event_llm(text)
        return int(severity)
    except Exception as exc:
        logger.debug("severity scoring failed: %s", exc)
        return 0


@router.get("/feed")
async def get_news_feed(
    limit: int = Query(50, ge=1, le=200),
    symbol: str | None = Query(None),
    impact: str | None = Query(None, pattern="^(high|medium|low)$"),
):
    """
    Retrieve the latest news articles with sentiment scoring.
    Each article includes: title, source, published_at, url, sentiment,
    impact level, nuclear_score, and related symbols.
    """
    mgr = _get_news_manager()
    scorer = _get_nuclear_scorer()

    articles = []
    if mgr:
        try:
            raw_articles = await mgr.get_latest(limit=limit, symbol=symbol)
            for article in raw_articles:
                # Score each article with nuclear wordmap
                nuclear_score = 0
                if scorer and article.get("title"):
                    nuclear_score = await _severity(
                        scorer, article.get("title", "") + " " + article.get("summary", "")
                    )

                articles.append(
                    {
                        "id": article.get("id", ""),
                        "title": article.get("title", ""),
                        "source": article.get("source", ""),
                        "published_at": article.get("published_at", ""),
                        "url": article.get("url", ""),
                        "sentiment": article.get("sentiment", "neutral"),
                        "impact": article.get("impact", "low"),
                        "nuclear_score": nuclear_score,
                        "symbols": article.get("symbols", []),
                        "summary": article.get("summary", ""),
                    }
                )
        except Exception as e:
            logger.error(f"News feed fetch failed: {e}")

    # Apply impact filter
    if impact:
        articles = [a for a in articles if a.get("impact") == impact]

    return {"articles": articles[:limit], "total": len(articles)}


@router.get("/nuclear-score")
async def get_nuclear_score(
    symbol: str | None = Query("XAUUSD"),
):
    """
    Get the current nuclear wordmap score for a symbol.
    Returns the aggregate sentiment danger level based on recent news.
    """
    scorer = _get_nuclear_scorer()
    mgr = _get_news_manager()

    if not scorer:
        return {"symbol": symbol, "score": 0, "alert": False, "articles_analyzed": 0}

    # Get recent articles for scoring
    articles = []
    if mgr:
        with contextlib.suppress(Exception):
            articles = await mgr.get_latest(limit=20, symbol=symbol)

    # Aggregate nuclear score (severity 0–10 per article)
    scores = []
    for article in articles:
        text = article.get("title", "") + " " + article.get("summary", "")
        scores.append(await _severity(scorer, text))

    avg_score = sum(scores) / len(scores) if scores else 0
    max_score = max(scores) if scores else 0

    return {
        "symbol": symbol,
        "score": round(avg_score, 2),
        "max_score": round(max_score, 2),
        # Severity scale 0–10: ≥7 = hedge/nuclear, ≥5 = pause new entries.
        "alert": max_score >= 7 or avg_score >= 5,
        "articles_analyzed": len(scores),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/calendar")
async def get_economic_calendar(
    days_ahead: int = Query(7, ge=1, le=30),
):
    """
    Get upcoming economic events that may impact trading.
    """
    try:
        from core.app_state import app_state

        calendar = getattr(app_state, "economic_calendar", None)
        if calendar:
            events = await calendar.get_upcoming(days_ahead=days_ahead)
            return {"events": events}
    except Exception as e:
        logger.warning(f"Calendar fetch failed: {e}")

    return {"events": []}


# ── Sentiment sub-router ──────────────────────────────────────────────────────

sentiment_router = APIRouter(prefix="/api/sentiment", tags=["Sentiment"])


@sentiment_router.get("/latest")
async def get_sentiment_latest(
    symbol: str | None = Query("XAUUSD"),
):
    """
    Get the latest aggregated sentiment overview for a symbol.
    Returns: overall_score, bullish/bearish/neutral percentages, nuclear_alert.
    """
    mgr = _get_news_manager()
    scorer = _get_nuclear_scorer()

    # Fetch recent articles
    articles = []
    if mgr:
        with contextlib.suppress(Exception):
            articles = await mgr.get_latest(limit=50, symbol=symbol)

    # Calculate sentiment distribution
    bullish = sum(1 for a in articles if a.get("sentiment") == "bullish")
    bearish = sum(1 for a in articles if a.get("sentiment") == "bearish")
    neutral = sum(1 for a in articles if a.get("sentiment") == "neutral")
    total = bullish + bearish + neutral or 1

    # Calculate nuclear score
    nuclear_alert = False
    overall_score = 0
    if scorer and articles:
        scores = []
        for article in articles:
            text = article.get("title", "") + " " + article.get("summary", "")
            scores.append(await _severity(scorer, text))
        if scores:
            overall_score = sum(scores) / len(scores)
            # Severity scale 0–10: ≥5 means at least "pause new entries".
            nuclear_alert = overall_score >= 5

    return {
        "symbol": symbol or "XAUUSD",
        "overall_score": round(overall_score, 1),
        "news_count": total,
        "bullish_pct": round(bullish / total * 100, 1),
        "bearish_pct": round(bearish / total * 100, 1),
        "neutral_pct": round(neutral / total * 100, 1),
        "nuclear_alert": nuclear_alert,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
