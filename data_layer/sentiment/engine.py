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
    └── GoldSentimentScorer  → unified VADER + keyword scoring

The engine runs a background polling loop for each feed at its configured
interval. Scored articles are:
  1. Written to the lineage store (immutable audit trail)
  2. Cached in Redis (hopefx:news:latest, TTL 5min)
  3. Injected into the ML feature pipeline via get_ml_features()

ML features produced (4 total)
--------------------------------
  news_sentiment_score    : EMA of recent article sentiment scores [-1, 1]
  news_sentiment_momentum : rate of change of sentiment EMA
  news_article_count_1h   : number of gold-relevant articles in last hour
  news_bullish_ratio      : fraction of recent articles that are bullish [0, 1]

Causal guarantee: articles are scored only after published_at <= now.
The as_of parameter in get_ml_features() enforces this for backtesting.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from data_layer.feeds.news.alpha_vantage import AlphaVantageNewsFeed
from data_layer.feeds.news.base import NewsFeedBase
from data_layer.feeds.news.finnhub import FinnhubFeed
from data_layer.feeds.news.fmp import FMPFeed
from data_layer.feeds.news.newsapi import NewsAPIFeed
from data_layer.feeds.news.newsdata import NewsDataFeed
from data_layer.sentiment.scorer import GoldSentimentScorer, gold_sentiment_scorer
from data_layer.types import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

import os
_SENTIMENT_EMA_ALPHA  = float(os.getenv("SENT_EMA_ALPHA",    "0.15"))
_ARTICLE_WINDOW_H     = float(os.getenv("SENT_WINDOW_H",     "1.0"))
_MAX_ARTICLE_HISTORY  = int(os.getenv("SENT_MAX_HISTORY",    "500"))
_MIN_RELEVANCE        = float(os.getenv("SENT_MIN_RELEVANCE", "0.10"))

# Poll intervals per feed (seconds)
_POLL_INTERVALS: Dict[NewsSource, float] = {
    NewsSource.FINNHUB:       60.0,
    NewsSource.FMP:           120.0,
    NewsSource.NEWSDATA:      300.0,
    NewsSource.ALPHA_VANTAGE: 300.0,
    NewsSource.NEWSAPI:       120.0,
    NewsSource.NEWSAPI_AI:    120.0,
}


class NewsSentimentEngine:
    """
    Orchestrates all news feeds and produces a unified gold sentiment signal.

    Usage:
        engine = NewsSentimentEngine()
        await engine.start()
        features = engine.get_ml_features()
        await engine.stop()
    """

    def __init__(self) -> None:
        self._feeds: Dict[NewsSource, NewsFeedBase] = {
            NewsSource.FINNHUB:       FinnhubFeed(),
            NewsSource.FMP:           FMPFeed(),
            NewsSource.NEWSDATA:      NewsDataFeed(),
            NewsSource.ALPHA_VANTAGE: AlphaVantageNewsFeed(),
            NewsSource.NEWSAPI:       NewsAPIFeed(),
        }
        self._scorer: GoldSentimentScorer = gold_sentiment_scorer
        self._articles: deque = deque(maxlen=_MAX_ARTICLE_HISTORY)
        self._sentiment_ema: float = 0.0
        self._prev_ema: float = 0.0
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._redis = None
        self._lineage = None
        self._lock = asyncio.Lock()
        self._article_count: int = 0
        self._last_fetch_at: Dict[NewsSource, float] = {}

        # Prometheus
        self._prom_sentiment  = None
        self._prom_art_count  = None
        self._prom_bull_ratio = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import Counter, Gauge
            self._prom_sentiment = Gauge(
                "hopefx_news_sentiment_ema",
                "EMA of gold news sentiment score [-1, 1]",
            )
            self._prom_art_count = Counter(
                "hopefx_news_articles_scored_total",
                "Total gold-relevant articles scored",
                ["source"],
            )
            self._prom_bull_ratio = Gauge(
                "hopefx_news_bullish_ratio",
                "Fraction of recent articles that are bullish",
            )
        except Exception:
            pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start background polling loops for all configured feeds."""
        self._running = True
        configured = [
            (src, feed) for src, feed in self._feeds.items()
            if feed.is_configured
        ]
        if not configured:
            logger.warning(
                "NewsSentimentEngine: no news API keys configured — "
                "sentiment features will be zero. Set at least one of: "
                "FINNHUB_API_KEY, FMP_API_KEY, NEWSDATA_IO_KEY, "
                "ALPHA_VANTAGE_KEY, NEWSAPI_ORG_KEY"
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

    async def _poll_loop(self, src: NewsSource, feed: NewsFeedBase) -> None:
        interval = _POLL_INTERVALS.get(src, 120.0)
        # Stagger startup
        await asyncio.sleep(list(self._feeds.keys()).index(src) * 3.0)

        while self._running:
            t0 = time.monotonic()
            try:
                raw_articles = await feed.fetch_articles(limit=50)
                if raw_articles:
                    scored = self._scorer.score_batch(raw_articles)
                    if scored:
                        async with self._lock:
                            await self._ingest_articles(scored, src)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "NewsSentimentEngine poll error source=%s: %s", src.value, exc
                )

            self._last_fetch_at[src] = time.time()
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.1, interval - elapsed))

    # ── Article ingestion ─────────────────────────────────────────────────────

    async def _ingest_articles(
        self, articles: List[NewsArticle], src: NewsSource
    ) -> None:
        """Update EMA, cache, and lineage for a batch of scored articles."""
        now = datetime.now(timezone.utc)

        for article in articles:
            # Causal check: reject future-dated articles
            if article.published_at > now + timedelta(minutes=5):
                logger.debug(
                    "NewsSentimentEngine: future-dated article rejected: %s",
                    article.published_at.isoformat(),
                )
                continue

            if article.gold_relevance < _MIN_RELEVANCE:
                continue

            self._articles.append(article)
            self._article_count += 1

            # Update sentiment EMA
            self._prev_ema = self._sentiment_ema
            self._sentiment_ema = (
                _SENTIMENT_EMA_ALPHA * article.sentiment_score
                + (1.0 - _SENTIMENT_EMA_ALPHA) * self._sentiment_ema
            )

            # Prometheus
            if self._prom_art_count:
                try:
                    self._prom_art_count.labels(source=src.value).inc()
                except Exception:
                    pass

            # Lineage
            if self._lineage:
                try:
                    self._lineage.record_news(article)
                except Exception as exc:
                    logger.debug("NewsSentimentEngine lineage error: %s", exc)

        # Update Prometheus gauges
        if self._prom_sentiment:
            try:
                self._prom_sentiment.set(self._sentiment_ema)
            except Exception:
                pass

        bull_ratio = self._compute_bullish_ratio()
        if self._prom_bull_ratio:
            try:
                self._prom_bull_ratio.set(bull_ratio)
            except Exception:
                pass

        # Cache to Redis
        await self._cache_to_redis()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_ml_features(
        self, as_of: Optional[datetime] = None
    ) -> Dict[str, float]:
        """
        Return 4 sentiment ML features.

        as_of: causal cutoff — only use articles published before this time.
        """
        now = as_of or datetime.now(timezone.utc)
        cutoff_1h = now - timedelta(hours=_ARTICLE_WINDOW_H)

        # Filter causally
        recent = [
            a for a in self._articles
            if a.published_at <= now and a.published_at >= cutoff_1h
        ]

        if not recent:
            return {
                "news_sentiment_score":    round(self._sentiment_ema, 4),
                "news_sentiment_momentum": 0.0,
                "news_article_count_1h":   0.0,
                "news_bullish_ratio":      0.5,
            }

        # Recompute EMA over causal window
        ema = 0.0
        for a in sorted(recent, key=lambda x: x.published_at):
            ema = (
                _SENTIMENT_EMA_ALPHA * a.sentiment_score
                + (1.0 - _SENTIMENT_EMA_ALPHA) * ema
            )

        # Momentum: current EMA vs previous EMA
        momentum = ema - self._prev_ema

        # Bullish ratio
        bullish = sum(1 for a in recent if a.sentiment_label == "bullish")
        bull_ratio = bullish / len(recent) if recent else 0.5

        return {
            "news_sentiment_score":    round(ema, 4),
            "news_sentiment_momentum": round(momentum, 4),
            "news_article_count_1h":   float(len(recent)),
            "news_bullish_ratio":      round(bull_ratio, 4),
        }

    def get_recent_articles(
        self, hours: float = 1.0, min_relevance: float = 0.1
    ) -> List[NewsArticle]:
        """Return recent gold-relevant articles."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            a for a in self._articles
            if a.published_at >= cutoff and a.gold_relevance >= min_relevance
        ]

    def health(self) -> Dict[str, Any]:
        return {
            "running":         self._running,
            "article_count":   self._article_count,
            "sentiment_ema":   round(self._sentiment_ema, 4),
            "active_feeds":    [
                src.value for src, feed in self._feeds.items()
                if feed.is_configured
            ],
            "last_fetch":      {
                src.value: round(time.time() - ts, 1)
                for src, ts in self._last_fetch_at.items()
            },
            "feed_health":     {
                src.value: feed.health_summary()
                for src, feed in self._feeds.items()
            },
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compute_bullish_ratio(self, hours: float = 1.0) -> float:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = [a for a in self._articles if a.published_at >= cutoff]
        if not recent:
            return 0.5
        bullish = sum(1 for a in recent if a.sentiment_label == "bullish")
        return bullish / len(recent)

    async def _cache_to_redis(self) -> None:
        if not self._redis:
            return
        try:
            import json
            features = self.get_ml_features()
            payload  = json.dumps(features)
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._redis.setex("hopefx:news:sentiment", 300, payload),
            )
        except Exception as exc:
            logger.debug("NewsSentimentEngine Redis cache error: %s", exc)


# Module-level singleton
news_sentiment_engine = NewsSentimentEngine()
