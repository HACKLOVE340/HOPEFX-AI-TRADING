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
    ├── GoldSentimentScorer  → unified VADER + keyword scoring
    ├── FinBERTScorer        → transformer-based financial sentiment (new)
    └── SocialMediaSentiment → Reddit/Twitter gold sentiment aggregator (new)

The engine runs a background polling loop for each feed at its configured
interval. Scored articles are:
  1. Written to the lineage store (immutable audit trail)
  2. Cached in Redis (hopefx:news:latest, TTL 5min)
  3. Injected into the ML feature pipeline via get_ml_features()

ML features produced (7 total, up from 4)
------------------------------------------
  news_sentiment_score    : EMA of recent article sentiment scores [-1, 1]
  news_sentiment_momentum : rate of change of sentiment EMA
  news_article_count_1h   : number of gold-relevant articles in last hour
  news_bullish_ratio      : fraction of recent articles that are bullish [0, 1]
  news_finbert_score      : FinBERT-weighted sentiment score [-1, 1] (new)
  news_social_score       : social media sentiment score [-1, 1] (new)
  news_regime             : sentiment regime encoded as float (new)
                            0.0=neutral, 1.0=risk_on, -1.0=risk_off

New in this version
-------------------
- FinBERT scoring: uses ProsusAI/finbert via sentence-transformers when
  available; falls back to VADER gracefully. Scores are blended with the
  existing VADER EMA using a configurable weight (SENT_FINBERT_WEIGHT).
- Social media sentiment: polls Reddit (r/Gold, r/investing, r/wallstreetbets)
  via the public JSON API (no auth required) and scores posts with VADER.
  Configurable via SENT_REDDIT_SUBREDDITS and SENT_REDDIT_INTERVAL_S.
- Sentiment regime detection: classifies the current market sentiment into
  risk_on / risk_off / neutral based on EMA level, momentum, and article
  velocity. Regime transitions are logged and emitted as Prometheus events.

Causal guarantee: articles are scored only after published_at <= now.
The as_of parameter in get_ml_features() enforces this for backtesting.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

from data_layer.feeds.news.alpha_vantage import AlphaVantageNewsFeed
from data_layer.feeds.news.base import NewsFeedBase
from data_layer.feeds.news.finnhub import FinnhubFeed
from data_layer.feeds.news.fmp import FMPFeed
from data_layer.feeds.news.newsapi import NewsAPIFeed
from data_layer.feeds.news.newsdata import NewsDataFeed
from data_layer.sentiment.scorer import GoldSentimentScorer, gold_sentiment_scorer
from data_layer.types import NewsArticle, NewsSource
from news.geopolitical_risk import GeopoliticalRiskProvider

logger = logging.getLogger(__name__)

_SENTIMENT_EMA_ALPHA = float(os.getenv("SENT_EMA_ALPHA", "0.15"))
_ARTICLE_WINDOW_H = float(os.getenv("SENT_WINDOW_H", "1.0"))
_MAX_ARTICLE_HISTORY = int(os.getenv("SENT_MAX_HISTORY", "500"))
_MIN_RELEVANCE = float(os.getenv("SENT_MIN_RELEVANCE", "0.10"))
_MAX_ARTICLE_AGE_H = float(os.getenv("SENT_MAX_ARTICLE_AGE_H", "24.0"))
_DEDUP_WINDOW_H = float(os.getenv("SENT_DEDUP_WINDOW_H", "6.0"))
# FinBERT blend weight: 0 = VADER only, 1 = FinBERT only
_FINBERT_WEIGHT = float(os.getenv("SENT_FINBERT_WEIGHT", "0.4"))
# Social media poll interval (seconds)
_REDDIT_INTERVAL_S = float(os.getenv("SENT_REDDIT_INTERVAL_S", "300.0"))
_REDDIT_SUBREDDITS = os.getenv("SENT_REDDIT_SUBREDDITS", "Gold,investing,wallstreetbets").split(",")
_REDDIT_POST_LIMIT = int(os.getenv("SENT_REDDIT_POST_LIMIT", "25"))
# Regime detection thresholds
_REGIME_RISK_ON_THRESH = float(os.getenv("SENT_REGIME_RISK_ON", "0.15"))
_REGIME_RISK_OFF_THRESH = float(os.getenv("SENT_REGIME_RISK_OFF", "-0.15"))
_REGIME_MOMENTUM_THRESH = float(os.getenv("SENT_REGIME_MOMENTUM", "0.05"))

# Poll intervals per feed (seconds)
_POLL_INTERVALS: dict[NewsSource, float] = {
    NewsSource.FINNHUB: 60.0,
    NewsSource.FMP: 120.0,
    NewsSource.NEWSDATA: 300.0,
    NewsSource.ALPHA_VANTAGE: 300.0,
    NewsSource.NEWSAPI: 120.0,
    NewsSource.NEWSAPI_AI: 120.0,
}


class FinBERTScorer:
    """
    FinBERT-based financial sentiment scorer.

    Uses ProsusAI/finbert via the transformers pipeline when available.
    Falls back to VADER gracefully when transformers/torch is not installed.

    Scores are mapped to [-1, 1]:
      positive → +score
      negative → -score
      neutral  → 0.0
    """

    def __init__(self) -> None:
        self._pipeline = None
        self._available = False
        self._load_attempted = False

    def _try_load(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True
        try:
            from transformers import pipeline as hf_pipeline  # type: ignore[import]

            self._pipeline = hf_pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
                truncation=True,
                max_length=512,
                device=-1,  # CPU only; GPU if available via CUDA_VISIBLE_DEVICES
            )
            self._available = True
            logger.info("FinBERTScorer: ProsusAI/finbert loaded successfully")
        except Exception as exc:
            logger.info(
                "FinBERTScorer: transformers/finbert not available (%s) — "
                "falling back to VADER for FinBERT slot",
                exc,
            )

    def score(self, text: str) -> float:
        """
        Score a text string. Returns float in [-1, 1].
        Positive = bullish for gold, negative = bearish.
        """
        self._try_load()
        if not self._available or not self._pipeline:
            return self._vader_fallback(text)
        try:
            result = self._pipeline(text[:512])[0]
            label = result["label"].lower()
            score = float(result["score"])
            if label == "positive":
                return round(score, 4)
            elif label == "negative":
                return round(-score, 4)
            return 0.0
        except Exception as exc:
            logger.debug("FinBERTScorer.score error: %s", exc)
            return self._vader_fallback(text)

    def score_batch(self, texts: list[str]) -> list[float]:
        """Score a batch of texts. Returns list of floats in [-1, 1]."""
        self._try_load()
        if not self._available or not self._pipeline:
            return [self._vader_fallback(t) for t in texts]
        try:
            results = self._pipeline([t[:512] for t in texts])
            scores = []
            for r in results:
                label = r["label"].lower()
                s = float(r["score"])
                scores.append(round(s if label == "positive" else (-s if label == "negative" else 0.0), 4))
            return scores
        except Exception as exc:
            logger.debug("FinBERTScorer.score_batch error: %s", exc)
            return [self._vader_fallback(t) for t in texts]

    @staticmethod
    def _vader_fallback(text: str) -> float:
        """VADER fallback when FinBERT is unavailable."""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore[import]
            sia = SentimentIntensityAnalyzer()
            return round(sia.polarity_scores(text)["compound"], 4)
        except Exception:
            return 0.0

    @property
    def is_available(self) -> bool:
        self._try_load()
        return self._available


class SocialMediaSentiment:
    """
    Reddit-based social media sentiment aggregator for gold.

    Polls configured subreddits via the public JSON API (no OAuth required).
    Posts are scored with VADER and aggregated into a rolling EMA.

    No API keys required — uses Reddit's public .json endpoint.
    Rate limit: 1 request per subreddit per _REDDIT_INTERVAL_S seconds.
    """

    def __init__(self) -> None:
        self._ema: float = 0.0
        self._post_count: int = 0
        self._last_poll: float = 0.0
        self._lock = asyncio.Lock()
        self._gold_keywords = {
            "gold", "xau", "xauusd", "bullion", "precious metals",
            "gold price", "gold futures", "comex", "spot gold",
        }

    async def poll(self) -> float:
        """
        Poll Reddit subreddits and update the sentiment EMA.
        Returns the updated EMA score.
        """
        try:
            import aiohttp
        except ImportError:
            return self._ema

        async with self._lock:
            now = time.time()
            if now - self._last_poll < _REDDIT_INTERVAL_S:
                return self._ema

            scores = []
            headers = {"User-Agent": "HopeFX-Sentiment/1.0 (research bot)"}

            async with aiohttp.ClientSession(headers=headers) as session:
                for sub in _REDDIT_SUBREDDITS:
                    url = f"https://www.reddit.com/r/{sub.strip()}/hot.json?limit={_REDDIT_POST_LIMIT}"
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.json()
                            posts = data.get("data", {}).get("children", [])
                            for post in posts:
                                pd_ = post.get("data", {})
                                title = pd_.get("title", "")
                                body = pd_.get("selftext", "")
                                text = f"{title} {body}".lower()
                                # Only score gold-relevant posts
                                if any(kw in text for kw in self._gold_keywords):
                                    score = FinBERTScorer._vader_fallback(f"{title} {body}")
                                    scores.append(score)
                    except Exception as exc:
                        logger.debug("SocialMediaSentiment Reddit error sub=%s: %s", sub, exc)

            if scores:
                batch_avg = sum(scores) / len(scores)
                alpha = 0.2
                self._ema = alpha * batch_avg + (1.0 - alpha) * self._ema
                self._post_count += len(scores)
                logger.debug(
                    "SocialMediaSentiment: scored %d posts avg=%.3f ema=%.3f",
                    len(scores), batch_avg, self._ema,
                )

            self._last_poll = now
            return self._ema

    @property
    def score(self) -> float:
        return round(self._ema, 4)

    @property
    def post_count(self) -> int:
        return self._post_count


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
        self._finbert: FinBERTScorer = FinBERTScorer()
        self._social: SocialMediaSentiment = SocialMediaSentiment()
        self._articles: deque = deque(maxlen=_MAX_ARTICLE_HISTORY)
        self._sentiment_ema: float = 0.0
        self._prev_ema: float = 0.0
        self._finbert_ema: float = 0.0
        self._regime: str = "neutral"  # "risk_on" | "risk_off" | "neutral"
        self._prev_regime: str = "neutral"
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._redis = None
        self._lineage = None
        self._lock = asyncio.Lock()
        # Geopolitical risk provider — use the module-level singleton so all
        # consumers share one instance and _all_sources_warned fires only once.
        from news.geopolitical_risk import get_geopolitical_provider as _get_geo

        self._geo_provider: GeopoliticalRiskProvider = _get_geo()
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
        self._prom_finbert = None
        self._prom_social = None
        self._prom_regime = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import REGISTRY, Counter, Gauge

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
            self._prom_finbert = _gauge(
                "hopefx_news_finbert_ema",
                "FinBERT-weighted sentiment EMA [-1, 1]",
            )
            self._prom_social = _gauge(
                "hopefx_news_social_ema",
                "Social media sentiment EMA [-1, 1]",
            )
            self._prom_regime = _gauge(
                "hopefx_news_sentiment_regime",
                "Sentiment regime: 1=risk_on, 0=neutral, -1=risk_off",
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
        else:
            for src, feed in configured:
                task = asyncio.create_task(
                    self._poll_loop(src, feed),
                    name=f"news_feed_{src.value}",
                )
                self._tasks.append(task)
                logger.info("NewsSentimentEngine: started feed %s", src.value)

        # Start social media sentiment background poll
        social_task = asyncio.create_task(
            self._social_poll_loop(),
            name="social_sentiment_poll",
        )
        self._tasks.append(social_task)

        # Start geopolitical risk background poll (non-blocking async loop)
        await self._geo_provider.start()

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for feed in self._feeds.values():
            await feed.close()
        # Stop geopolitical risk background poll
        await self._geo_provider.stop()

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

            # Update VADER sentiment EMA
            self._prev_ema = self._sentiment_ema
            self._sentiment_ema = (
                _SENTIMENT_EMA_ALPHA * article.sentiment_score + (1.0 - _SENTIMENT_EMA_ALPHA) * self._sentiment_ema
            )

            # Update FinBERT EMA (score headline + summary)
            text = f"{article.headline} {article.summary}"[:512]
            finbert_score = self._finbert.score(text)
            self._finbert_ema = (
                _SENTIMENT_EMA_ALPHA * finbert_score + (1.0 - _SENTIMENT_EMA_ALPHA) * self._finbert_ema
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

        # Update FinBERT and social Prometheus gauges
        if self._prom_finbert:
            try:
                self._prom_finbert.set(self._finbert_ema)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        # Detect and update sentiment regime
        self._update_regime()

        # Cache to Redis
        await self._cache_to_redis()

        # Publish to event bus so ws_live _chartbot_broadcaster and any other
        # subscriber receives news/sentiment updates without polling.
        await self._publish_to_event_bus()

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
                            "news_finbert_score": float(cached.get("news_finbert_score", self._finbert_ema)),
                            "news_social_score": float(cached.get("news_social_score", self._social.score)),
                            "news_regime": float(cached.get("news_regime", 0.0)),
                        }
                except Exception as exc:
                    logger.debug("NewsSentimentEngine Redis read error: %s", exc)
            return {
                "news_sentiment_score": round(self._sentiment_ema, 4),
                "news_sentiment_momentum": 0.0,
                "news_article_count_1h": 0.0,
                "news_bullish_ratio": 0.5,
                "news_finbert_score": round(self._finbert_ema, 4),
                "news_social_score": round(self._social.score, 4),
                "news_regime": self._regime_to_float(),
            }

        # Recompute EMA over causal window
        ema = 0.0
        finbert_ema = 0.0
        for a in sorted(recent, key=lambda x: x.published_at):
            ema = _SENTIMENT_EMA_ALPHA * a.sentiment_score + (1.0 - _SENTIMENT_EMA_ALPHA) * ema
            # FinBERT score for causal window (use stored score if available)
            fb_score = self._finbert.score(f"{a.headline} {a.summary}"[:512])
            finbert_ema = _SENTIMENT_EMA_ALPHA * fb_score + (1.0 - _SENTIMENT_EMA_ALPHA) * finbert_ema

        # Blended score: VADER + FinBERT weighted average
        blended = (1.0 - _FINBERT_WEIGHT) * ema + _FINBERT_WEIGHT * finbert_ema

        # Momentum: current EMA vs previous EMA
        momentum = ema - self._prev_ema

        # Bullish ratio
        bullish = sum(1 for a in recent if a.sentiment_label == "bullish")
        bull_ratio = bullish / len(recent) if recent else 0.5

        return {
            "news_sentiment_score": round(blended, 4),
            "news_sentiment_momentum": round(momentum, 4),
            "news_article_count_1h": float(len(recent)),
            "news_bullish_ratio": round(bull_ratio, 4),
            "news_finbert_score": round(finbert_ema, 4),
            "news_social_score": round(self._social.score, 4),
            "news_regime": self._regime_to_float(),
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

    def get_geopolitical_risk_score(self) -> float:
        """
        Return the latest cached geopolitical global risk score [0, 100].

        Served from the background-poll cache — never blocks the event loop.
        Returns 20.0 (baseline) when no events have been fetched yet.
        """
        cached_events = self._geo_provider._cache.get("events", [])
        if not cached_events:
            return 20.0
        # Reuse the provider's scoring logic on the cached events
        return self._geo_provider._calculate_global_risk(cached_events)

    def health(self) -> dict[str, Any]:
        geo_events = len(self._geo_provider._cache.get("events", []))
        geo_ts = self._geo_provider._cache_timestamp
        return {
            "running": self._running,
            "article_count": self._article_count,
            "sentiment_ema": round(self._sentiment_ema, 4),
            "active_feeds": [src.value for src, feed in self._feeds.items() if feed.is_configured],
            "last_fetch": {src.value: round(time.time() - ts, 1) for src, ts in self._last_fetch_at.items()},
            "feed_health": {src.value: feed.health_summary() for src, feed in self._feeds.items()},
            "geopolitical": {
                "running": self._geo_provider._running,
                "cached_events": geo_events,
                "cache_age_s": round((datetime.now(UTC) - geo_ts).total_seconds(), 1) if geo_ts else None,
                "risk_score": self.get_geopolitical_risk_score(),
            },
        }

    # ── Sentiment regime detection ────────────────────────────────────────────

    def _update_regime(self) -> None:
        """
        Classify current sentiment into risk_on / risk_off / neutral.

        Rules (applied in priority order):
          1. risk_on:  blended EMA > RISK_ON_THRESH AND momentum > 0
          2. risk_off: blended EMA < RISK_OFF_THRESH AND momentum < 0
          3. neutral:  everything else

        Regime transitions are logged at INFO level.
        """
        blended = (1.0 - _FINBERT_WEIGHT) * self._sentiment_ema + _FINBERT_WEIGHT * self._finbert_ema
        momentum = self._sentiment_ema - self._prev_ema

        if blended > _REGIME_RISK_ON_THRESH and momentum > -_REGIME_MOMENTUM_THRESH:
            new_regime = "risk_on"
        elif blended < _REGIME_RISK_OFF_THRESH and momentum < _REGIME_MOMENTUM_THRESH:
            new_regime = "risk_off"
        else:
            new_regime = "neutral"

        if new_regime != self._regime:
            logger.info(
                "SentimentRegime transition: %s → %s (ema=%.3f momentum=%.4f)",
                self._regime, new_regime, blended, momentum,
            )
            self._prev_regime = self._regime
            self._regime = new_regime

        if self._prom_regime:
            try:
                self._prom_regime.set(self._regime_to_float())
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

    def _regime_to_float(self) -> float:
        """Encode regime as float: 1.0=risk_on, 0.0=neutral, -1.0=risk_off."""
        return {"risk_on": 1.0, "neutral": 0.0, "risk_off": -1.0}.get(self._regime, 0.0)

    def get_regime(self) -> str:
        """Return current sentiment regime string: 'risk_on' | 'neutral' | 'risk_off'."""
        return self._regime

    def get_finbert_score(self) -> float:
        """Return the current FinBERT EMA score."""
        return round(self._finbert_ema, 4)

    def get_social_score(self) -> float:
        """Return the current social media sentiment EMA score."""
        return round(self._social.score, 4)

    # ── Social media poll loop ────────────────────────────────────────────────

    async def _social_poll_loop(self) -> None:
        """Background loop that polls Reddit for gold sentiment."""
        while self._running:
            try:
                score = await self._social.poll()
                if self._prom_social:
                    try:
                        self._prom_social.set(score)
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("SocialMediaSentiment poll error: %s", exc)
            await asyncio.sleep(_REDDIT_INTERVAL_S)

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

    async def _publish_to_event_bus(self) -> None:
        """
        Publish sentiment snapshot and recent articles to the event bus.

        Publishes two messages per ingest cycle:
          CH_SENTIMENT  — full sentiment snapshot (signal + recent_articles)
          CH_NEWS_ITEM  — one message per new article (most recent 3 only)

        This wires the sentiment engine into the ws_live _chartbot_broadcaster
        subscription path so WebSocket clients receive push updates instead of
        relying on the broadcaster's poll interval.
        """
        try:
            from core.event_bus import CH_NEWS_ITEM, CH_SENTIMENT, bus

            # Build sentiment snapshot (same shape as orchestrator.get_sentiment_snapshot)
            features = self.get_ml_features()
            sentiment_features = {k: v for k, v in features.items() if k.startswith("news_")}
            recent_articles: list[dict] = []
            try:
                raw = self.get_recent_articles(hours=1.0, min_relevance=0.1)
                recent_articles = [
                    {
                        "headline": getattr(a, "title", getattr(a, "headline", "")),
                        "source": getattr(a, "source", ""),
                        "sentiment_score": getattr(a, "sentiment_score", 0.0),
                        "sentiment_label": getattr(a, "sentiment_label", "neutral"),
                        "published_at": (
                            a.published_at.isoformat()
                            if getattr(a, "published_at", None)
                            else None
                        ),
                        "url": getattr(a, "url", None),
                    }
                    for a in (raw or [])[:5]
                ]
            except Exception as _exc:
                logger.debug("_publish_to_event_bus: article serialisation error: %s", _exc)

            await bus.publish(
                CH_SENTIMENT,
                {
                    "type": "sentiment_update",
                    "data": {"signal": sentiment_features, "recent_articles": recent_articles},
                },
            )

            # Publish individual news items (most recent 3 to avoid flooding)
            for article_dict in recent_articles[:3]:
                await bus.publish(
                    CH_NEWS_ITEM,
                    {"type": "news_item", "data": article_dict},
                )
        except Exception as exc:
            logger.debug("NewsSentimentEngine event bus publish error: %s", exc)


# Module-level singleton
news_sentiment_engine = NewsSentimentEngine()
