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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

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
    """Retrieve the nuclear wordmap scorer."""
    try:
        from core.app_state import app_state
        scorer = getattr(app_state, "nuclear_scorer", None)
        if scorer is None:
            from news.nuclear_wordmap_scorer import NuclearWordmapScorer
            scorer = NuclearWordmapScorer()
            app_state.nuclear_scorer = scorer
        return scorer
    except Exception as e:
        logger.warning(f"Nuclear scorer init failed: {e}")
        return None


@router.get("/feed")
async def get_news_feed(
    limit: int = Query(50, ge=1, le=200),
    symbol: Optional[str] = Query(None),
    impact: Optional[str] = Query(None, regex="^(high|medium|low)$"),
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
                    try:
                        nuclear_score = scorer.score_text(
                            article.get("title", "") + " " + article.get("summary", "")
                        )
                    except Exception:
                        pass

                articles.append({
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
                })
        except Exception as e:
            logger.error(f"News feed fetch failed: {e}")

    # Apply impact filter
    if impact:
        articles = [a for a in articles if a.get("impact") == impact]

    return {"articles": articles[:limit], "total": len(articles)}


@router.get("/nuclear-score")
async def get_nuclear_score(
    symbol: Optional[str] = Query("XAUUSD"),
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
        try:
            articles = await mgr.get_latest(limit=20, symbol=symbol)
        except Exception:
            pass

    # Aggregate nuclear score
    scores = []
    for article in articles:
        try:
            text = article.get("title", "") + " " + article.get("summary", "")
            score = scorer.score_text(text)
            scores.append(score)
        except Exception:
            continue

    avg_score = sum(scores) / len(scores) if scores else 0
    max_score = max(scores) if scores else 0

    return {
        "symbol": symbol,
        "score": round(avg_score, 2),
        "max_score": round(max_score, 2),
        "alert": abs(avg_score) > 50 or abs(max_score) > 75,
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
    symbol: Optional[str] = Query("XAUUSD"),
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
        try:
            articles = await mgr.get_latest(limit=50, symbol=symbol)
        except Exception:
            pass

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
            try:
                text = article.get("title", "") + " " + article.get("summary", "")
                score = scorer.score_text(text)
                scores.append(score)
            except Exception:
                continue
        if scores:
            overall_score = sum(scores) / len(scores)
            nuclear_alert = abs(overall_score) > 50

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
