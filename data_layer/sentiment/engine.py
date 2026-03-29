# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/sentiment/engine.py
================================
NewsSentimentEngine — orchestrates all news feeds and sentiment scoring.

Architecture
------------
  NewsSentimentEngine
    ├── FinnhubFeed          → articles + native sentiment
    ├── FMPFeed              → gold-ticker-tagged articles
    ├── NewsDataFeed         → full-text gold search
    ├── AlphaVantageNewsFeed → pre-scored articles
    ├── NewsAPIFeed          → broad coverage
    └── GoldSentimentScorer  → unified scoring + EMA signal

The engine runs a background polling loop for each feed at its configured
interval. Scored articles are:
  1. Written to the lineage store (immutable audit trail)
  2. Cached in Redis (hopefx:news:latest, TTL 5min)
  3. Injected into the ML feature pipeline via get_ml_features()

Causal guarantee: articles are scored in published_at order. The ML pipeline
receives only articles published BEFORE the current bar's close_time.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

from data_layer.feeds.news.alpha_vantage import AlphaVantageNewsFeed
from data_layer.feeds.news.finnhub import FinnhubFeed
from data_layer.feeds.news.fmp import FMPFeed
from data_layer.feeds.news.newsapi import NewsAPIFeed
from data_layer.feeds.news.newsdata import NewsDataFeed
from data_layer.sentiment.scorer import GoldSentimentScorer, gold_sentiment_scorer
from data_layer.types import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

# Polling intervals per feed (seconds)
_POLL_INTERVALS: Dict[NewsSource, float] = {
    NewsSource.FINNHUB:       60.0,
    NewsSource.FMP:           120.0,
    NewsSource.NEWSDATA:      300.0,
    NewsSource.ALPHA_VANTAGE: 300.0,
    NewsSource.NEWSAPI:       120.0,
}

_ARTICLE_CACHE_SIZE = 2000   # rolling in-memory article store


class NewsSentimentEngine:
    """
    Manages all news feeds, scores articles, and exposes ML features.

    Usage:
        engine = NewsSentimentEngine(redis_client=redis)
        await engine.start()
        features = engine.get_ml_features()
        # features = {
        #   "news_sentiment_score": 0.23,
        #   "news_sentiment_momentum": 0.05,
        #   "news_article_count_1h": 12.0,
        #   "news_bullish_ratio": 0.67,
        # }
    """

    def __init__(self, redis_client=None, lineage_store=None) -> None:
        self._feeds = {
            NewsSource.FINNHUB:       FinnhubFeed(),
            NewsSource.FMP:           FMPFeed(),
            NewsSource.NEWSDATA:      NewsDataFeed(),
            NewsSource.ALPHA_VANTAGE: AlphaVantageNewsFeed(),
            NewsSource.NEWSAPI:       NewsAPIFeed(),
        }
        self._scorer: GoldSentimentScorer = gold_sentiment_scorer
        self._redis = redis_client
        self._lineage = lineage_store
        self._articles: deque = deque(maxlen=_ARTICLE_CACHE_SIZE)
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._finnhub_feed: FinnhubFeed = self._feeds[NewsSource.FINNHUB]  # type: ignore

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        configured = [
            (src, feed) for src, feed in self._feeds.items()
            if feed.is_configured
        ]
        if not configured:
            logger.warning(
                "NewsSentimentEngine: no news API keys configured. "
                "Set FINNHUB_API_KEY, FMP_API_KEY, NEWSDATA_IO_KEY, "
                "ALPHA_VANTAGE_KEY, or NEWSAPI_ORG_KEY."
            )
            return

        for src, feed in configured:
            task = asyncio.create_task(
                self._poll_loop(src, feed),
                name=f"news_feed_{src.value}",
            )
            self._tasks.append(task)
            logger.info("NewsSentimentEngine: started feed %s", src.value)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for feed in self._feeds.values():
            await feed.close()

    # ── Polling loop ──────────────────────────────────────────────────────────

    async def _poll_loop(self, src: NewsSource, feed) -> None:
        interval = _POLL_INTERVALS.get(src, 120.0)
        while self._running:
            t0 = time.monotonic()
            try:
                articles = await feed.fetch_articles(limit=50)
                if articles:
                    scored = self._scorer.score_batch(articles)
                    for article in scored:
                        self._articles.append(article)
                        await self._persist(article)
                    logger.debug(
                        "NewsSentimentEngine: %s fetched %d articles",
                        src.value, len(scored),
                    )
            except Exception as exc:
                logger.warning("NewsSentimentEngine poll error %s: %s", src.value, exc)

            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    # ── ML feature injection ──────────────────────────────────────────────────

    def get_ml_features(self, as_of: Optional[datetime] = None) -> Dict[str, float]:
        """
        Return sentiment features for ML pipeline injection.

        as_of: if provided, only articles published before this timestamp
               are included (causal guarantee for backtesting).
        """
        if as_of is not None:
            # Causal filter — only past articles
            relevant = [
                a for a in self._articles
                if a.published_at <= as_of and a.gold_relevance > 0.05
            ]
            # Recompute signal from filtered articles
            from data_layer.sentiment.scorer import GoldSentimentScorer
            temp_scorer = GoldSentimentScorer()
            for a in sorted(relevant, key=lambda x: x.published_at):
                temp_scorer.score_article(a)
            return temp_scorer.get_aggregate_signal()

        return self._scorer.get_aggregate_signal()

    def get_recent_articles(
        self,
        limit: int = 20,
        min_relevance: float = 0.1,
        as_of: Optional[datetime] = None,
    ) -> List[NewsArticle]:
        """Return recent gold-relevant articles, newest first."""
        cutoff = as_of or datetime.now(timezone.utc)
        filtered = [
            a for a in reversed(self._articles)
            if a.gold_relevance >= min_relevance and a.published_at <= cutoff
        ]
        return filtered[:limit]

    def get_finnhub_sentiment(self) -> dict:
        """Return Finnhub's native market sentiment (async wrapper)."""
        # Called synchronously from sync contexts — returns cached value
        return getattr(self, "_finnhub_sentiment_cache", {})

    async def refresh_finnhub_sentiment(self) -> None:
        """Refresh Finnhub native sentiment score."""
        try:
            result = await self._finnhub_feed.fetch_sentiment()
            self._finnhub_sentiment_cache = result
        except Exception as exc:
            logger.debug("Finnhub sentiment refresh error: %s", exc)

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist(self, article: NewsArticle) -> None:
        """Write article to Redis cache and lineage store."""
        # Redis cache
        if self._redis:
            try:
                import json
                payload = {
                    "article_id":     article.article_id,
                    "source":         article.source.value,
                    "headline":       article.headline,
                    "published_at":   article.published_at.isoformat(),
                    "sentiment_score": article.sentiment_score,
                    "sentiment_label": article.sentiment_label,
                    "gold_relevance": article.gold_relevance,
                    "impact_score":   article.impact_score,
                    "lineage_id":     article.lineage_id,
                }
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._redis.lpush(
                        "hopefx:news:latest",
                        json.dumps(payload),
                    ),
                )
                # Keep only last 200 articles in Redis list
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._redis.ltrim("hopefx:news:latest", 0, 199),
                )
            except Exception as exc:
                logger.debug("NewsSentimentEngine Redis persist error: %s", exc)

        # Lineage store
        if self._lineage:
            try:
                self._lineage.record_news(article)
            except Exception as exc:
                logger.debug("NewsSentimentEngine lineage error: %s", exc)

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        signal = self._scorer.get_aggregate_signal()
        return {
            "running":          self._running,
            "total_articles":   len(self._articles),
            "active_feeds":     [
                src.value for src, feed in self._feeds.items()
                if feed.is_configured
            ],
            "sentiment_signal": signal,
            "feed_health":      {
                src.value: feed.health_summary()
                for src, feed in self._feeds.items()
            },
        }


# Module-level singleton
news_sentiment_engine = NewsSentimentEngine()
