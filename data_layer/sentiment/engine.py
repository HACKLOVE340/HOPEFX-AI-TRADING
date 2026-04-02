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
import hashlib
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

from data_layer.feeds.news.alpha_vantage import AlphaVantageNewsFeed
from data_layer.feeds.news.base import NewsFeedBase
from data_layer.feeds.news.finnhub import FinnhubFeed
from data_layer.feeds.news.fmp import FMPFeed
import os

from data_layer.feeds.news.newsapi import NewsAPIFeed
from data_layer.feeds.news.newsdata import NewsDataFeed
from data_layer.sentiment.scorer import GoldSentimentScorer, gold_sentiment_scorer
from data_layer.types import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

_SENTIMENT_EMA_ALPHA = float(os.getenv("SENT_EMA_ALPHA", "0.15"))
_ARTICLE_WINDOW_H = float(os.getenv("SENT_WINDOW_H", "1.0"))
_MAX_ARTICLE_HISTORY = int(os.getenv("SENT_MAX_HISTORY", "500"))
_MIN_RELEVANCE = float(os.getenv("SENT_MIN_RELEVANCE", "0.10"))
# Articles older than this are not ingested into the EMA (stale news)
_MAX_ARTICLE_AGE_H = float(os.getenv("SENT_MAX_ARTICLE_AGE_H", "24.0"))
# Cross-feed dedup window: articles with the same URL fingerprint within
# this many hours are treated as duplicates regardless of source
_DEDUP_WINDOW_H = float(os.getenv("SENT_DEDUP_WINDOW_H", "6.0"))

# Poll intervals per feed (seconds)
_POLL_INTERVALS: dict[NewsSource, float] = {
    NewsSource.FINNHUB: 60.0,
    NewsSource.FMP: 120.0,
    NewsSource.NEWSDATA: 300.0,
    NewsSource.ALPHA_VANTAGE: 300.0,
    NewsSource.NEWSAPI: 120.0,
    NewsSource.NEWSAPI_AI: 120.0,
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
        self._feeds: dict[NewsSource, NewsFeedBase] = {
            NewsSource.FINNHUB: FinnhubFeed(),
            NewsSource.FMP: FMPFeed(),
            NewsSource.NEWSDATA: NewsDataFeed(),
            NewsSource.ALPHA_VANTAGE: AlphaVantageNewsFeed(),
            NewsSource.NEWSAPI: NewsAPIFeed(),
        }
        self._scorer: GoldSentimentScorer = gold_sentiment_scorer
        self._articles: deque = deque(maxlen=_MAX_ARTICLE_HISTORY)
        self._sentiment_ema: float = 0.0
        self._prev_ema: float = 0.0
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._redis = None
        self._lineage = None
        self._lock = asyncio.Lock()
        self._article_count: int = 0
        self._last_fetch_at: dict[NewsSource, float] = {}
        # Cross-feed deduplication: URL fingerprint → ingested_at epoch.
        # Prevents the same article appearing in Finnhub + FMP + NewsAPI
        # from being scored 3× and inflating the sentiment EMA.
        self._seen_urls: dict[str, float] = {}

        # Prometheus
        self._prom_sentiment = None
        self._prom_art_count = None
        self._prom_bull_ratio = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import Counter, Gauge, REGISTRY

            def _gauge(name: str, doc: str):
                try:
                    return Gauge(name, doc)
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            def _counter(name: str, doc: str, labels=None):
                try:
                    return Counter(name, doc, labels or [])
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            self._prom_sentiment = _gauge(
                "hopefx_news_sentiment_ema",
                "EMA of gold news sentiment score [-1, 1]",
            )
            self._prom_art_count = _counter(
                "hopefx_news_articles_scored_total",
                "Total gold-relevant articles scored",
                ["source"],
            )
            self._prom_bull_ratio = _gauge(
                "hopefx_news_bullish_ratio",
                "Fraction of recent articles that are bullish",
            )
        except Exception as _exc:
            logger.debug("NewsSentimentEngine: Prometheus init skipped: %s", _exc)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start background polling loops for all configured feeds."""
        self._running = True
        configured = [(src, feed) for src, feed in self._feeds.items() if feed.is_configured]
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
                logger.warning("NewsSentimentEngine poll error source=%s: %s", src.value, exc)

            self._last_fetch_at[src] = time.time()
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.1, interval - elapsed))

    # ── Article ingestion ─────────────────────────────────────────────────────

    def _url_fingerprint(self, article: NewsArticle) -> str:
        """
        Stable cross-feed fingerprint for deduplication.

        Uses URL when available (most reliable), falls back to
        SHA-256 of (headline[:80] + date) for articles without URLs.
        """
        if article.url:
            # Normalise URL: strip query params and trailing slashes
            url = article.url.split("?")[0].rstrip("/").lower()
            return hashlib.sha256(url.encode()).hexdigest()[:20]
        key = f"{article.headline[:80]}|{article.published_at.date()}"
        return hashlib.sha256(key.encode()).hexdigest()[:20]

    async def _ingest_articles(self, articles: list[NewsArticle], src: NewsSource) -> None:
        """Update EMA, cache, and lineage for a batch of scored articles."""
        now = datetime.now(UTC)
        max_age_cutoff = now - timedelta(hours=_MAX_ARTICLE_AGE_H)
        dedup_cutoff_epoch = time.time() - _DEDUP_WINDOW_H * 3600.0

        # Prune stale dedup entries to bound memory
        self._seen_urls = {fp: ts for fp, ts in self._seen_urls.items() if ts > dedup_cutoff_epoch}

        for article in articles:
            # Causal check: reject future-dated articles
            if article.published_at > now + timedelta(minutes=5):
                logger.debug(
                    "NewsSentimentEngine: future-dated article rejected: %s",
                    article.published_at.isoformat(),
                )
                continue

            # Age gate: ignore articles older than MAX_ARTICLE_AGE_H
            if article.published_at < max_age_cutoff:
                logger.debug(
                    "NewsSentimentEngine: article too old (age=%.1fh) — skipped",
                    (now - article.published_at).total_seconds() / 3600.0,
                )
                continue

            if article.gold_relevance < _MIN_RELEVANCE:
                continue

            # Cross-feed deduplication: same URL from multiple sources
            fp = self._url_fingerprint(article)
            if fp in self._seen_urls:
                logger.debug(
                    "NewsSentimentEngine: duplicate article skipped (source=%s fp=%s)",
                    src.value,
                    fp,
                )
                continue
            self._seen_urls[fp] = time.time()

            self._articles.append(article)
            self._article_count += 1

            # Update sentiment EMA
            self._prev_ema = self._sentiment_ema
            self._sentiment_ema = (
                _SENTIMENT_EMA_ALPHA * article.sentiment_score + (1.0 - _SENTIMENT_EMA_ALPHA) * self._sentiment_ema
            )

            # Prometheus
            if self._prom_art_count:
                try:
                    self._prom_art_count.labels(source=src.value).inc()
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)

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
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        bull_ratio = self._compute_bullish_ratio()
        if self._prom_bull_ratio:
            try:
                self._prom_bull_ratio.set(bull_ratio)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        # Cache to Redis
        await self._cache_to_redis()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_ml_features(self, as_of: datetime | None = None) -> dict[str, float]:
        """
        Return 4 sentiment ML features.

        as_of: causal cutoff — only use articles published before this time.

        When no articles are in memory (cold start), attempts to read the
        last cached features from Redis before returning neutral defaults.
        """
        now = as_of or datetime.now(UTC)
        cutoff_1h = now - timedelta(hours=_ARTICLE_WINDOW_H)

        # Filter causally
        recent = [a for a in self._articles if a.published_at <= now and a.published_at >= cutoff_1h]

        if not recent:
            # Try Redis cache on cold start (no as_of = live mode only)
            if as_of is None and self._redis:
                try:
                    import json

                    raw = self._redis.get("hopefx:dl:sentiment")
                    if raw:
                        cached = json.loads(raw)
                        return {
                            "news_sentiment_score": float(cached.get("news_sentiment_score", self._sentiment_ema)),
                            "news_sentiment_momentum": float(cached.get("news_sentiment_momentum", 0.0)),
                            "news_article_count_1h": float(cached.get("news_article_count_1h", 0.0)),
                            "news_bullish_ratio": float(cached.get("news_bullish_ratio", 0.5)),
                        }
                except Exception as exc:
                    logger.debug("NewsSentimentEngine Redis read error: %s", exc)
            return {
                "news_sentiment_score": round(self._sentiment_ema, 4),
                "news_sentiment_momentum": 0.0,
                "news_article_count_1h": 0.0,
                "news_bullish_ratio": 0.5,
            }

        # Recompute EMA over causal window
        ema = 0.0
        for a in sorted(recent, key=lambda x: x.published_at):
            ema = _SENTIMENT_EMA_ALPHA * a.sentiment_score + (1.0 - _SENTIMENT_EMA_ALPHA) * ema

        # Momentum: current EMA vs previous EMA
        momentum = ema - self._prev_ema

        # Bullish ratio
        bullish = sum(1 for a in recent if a.sentiment_label == "bullish")
        bull_ratio = bullish / len(recent) if recent else 0.5

        return {
            "news_sentiment_score": round(ema, 4),
            "news_sentiment_momentum": round(momentum, 4),
            "news_article_count_1h": float(len(recent)),
            "news_bullish_ratio": round(bull_ratio, 4),
        }

    def get_recent_articles(self, hours: float = 1.0, min_relevance: float = 0.1) -> list[NewsArticle]:
        """Return recent gold-relevant articles."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        return [a for a in self._articles if a.published_at >= cutoff and a.gold_relevance >= min_relevance]

    def get_articles_since(
        self,
        since: datetime,
        min_relevance: float = 0.0,
        source: Any | None = None,
    ) -> list[NewsArticle]:
        """
        Return all articles published at or after `since`.

        Parameters
        ----------
        since         : UTC datetime lower bound (inclusive)
        min_relevance : Minimum gold_relevance score to include
        source        : Optional NewsSource filter

        Returns articles in chronological order (oldest first).
        """
        results = [
            a
            for a in self._articles
            if a.published_at >= since and a.gold_relevance >= min_relevance and (source is None or a.source == source)
        ]
        return sorted(results, key=lambda a: a.published_at)

    def get_sentiment_snapshot(self) -> dict[str, Any]:
        """
        Return a point-in-time sentiment snapshot for caching and health checks.

        Includes the current EMA, momentum, article counts, and per-source
        article counts over the last hour.
        """
        now = datetime.now(UTC)
        cutoff_1h = now - timedelta(hours=1.0)
        recent_1h = [a for a in self._articles if a.published_at >= cutoff_1h]

        per_source: dict[str, int] = {}
        for a in recent_1h:
            per_source[a.source.value] = per_source.get(a.source.value, 0) + 1

        bullish = sum(1 for a in recent_1h if a.sentiment_label == "bullish")
        bearish = sum(1 for a in recent_1h if a.sentiment_label == "bearish")

        return {
            "sentiment_ema": round(self._sentiment_ema, 4),
            "sentiment_momentum": round(self._sentiment_ema - self._prev_ema, 4),
            "article_count_1h": len(recent_1h),
            "bullish_count_1h": bullish,
            "bearish_count_1h": bearish,
            "bullish_ratio_1h": round(bullish / max(len(recent_1h), 1), 4),
            "per_source_1h": per_source,
            "total_articles": self._article_count,
            "timestamp": now.isoformat(),
        }

    def flush_cache(self) -> None:
        """
        Clear the in-memory article deque and reset EMA state.

        Used in testing and when a feed produces a large batch of
        back-dated articles that would corrupt the rolling EMA.
        Does NOT affect the lineage store — articles already written
        there are permanent.
        """
        self._articles.clear()
        self._sentiment_ema = 0.0
        self._prev_ema = 0.0
        self._article_count = 0
        logger.info("NewsSentimentEngine: in-memory cache flushed")

    def health(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "article_count": self._article_count,
            "sentiment_ema": round(self._sentiment_ema, 4),
            "active_feeds": [src.value for src, feed in self._feeds.items() if feed.is_configured],
            "last_fetch": {src.value: round(time.time() - ts, 1) for src, ts in self._last_fetch_at.items()},
            "feed_health": {src.value: feed.health_summary() for src, feed in self._feeds.items()},
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compute_bullish_ratio(self, hours: float = 1.0) -> float:
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
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
            payload = json.dumps(features)
            loop = asyncio.get_running_loop()
            # Primary key used by orchestrator and get_ml_features() cold-start read
            await loop.run_in_executor(
                None,
                lambda: self._redis.setex("hopefx:dl:sentiment", 300, payload),
            )
            # Legacy key kept for backwards compatibility with any existing consumers
            await loop.run_in_executor(
                None,
                lambda: self._redis.setex("hopefx:news:sentiment", 300, payload),
            )
        except Exception as exc:
            logger.debug("NewsSentimentEngine Redis cache error: %s", exc)


# Module-level singleton
news_sentiment_engine = NewsSentimentEngine()
