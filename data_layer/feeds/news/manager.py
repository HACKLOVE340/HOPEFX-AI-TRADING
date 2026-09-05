# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/feeds/news/manager.py
================================
Fan-out across the news feed adapters and merge their results.

``api/news_feed.py`` imported ``NewsFeedManager`` from
``data_layer.feeds.news.base``. That module defines ``NewsFeedBase``, an
abstract class whose one abstract method is ``fetch_articles`` — there is no
manager in it, and there was none anywhere else either. The import raised on
every call, ``_get_news_manager()`` returned ``None``, and all three
``/api/news-feed/*`` endpoints skipped their work entirely and answered
``{"articles": [], "total": 0}``. There is no fallback path in them.

The five adapters all exist and all implement ``fetch_articles(limit)``:
``FinnhubFeed``, ``FMPFeed``, ``NewsDataFeed``, ``AlphaVantageNewsFeed`` and
``NewsAPIFeed``. What was missing is the piece that queries them together and
hands the API the shape it reads.

Two translations matter here:

* The adapters return ``NewsArticle`` dataclasses — ``article_id``,
  ``headline``, ``sentiment_label``, ``impact_score``. The endpoints read
  dictionaries with different names — ``id``, ``title``, ``sentiment``,
  ``impact``. Mapping between them is this module's job; getting it wrong would
  hand back articles whose fields are all quietly empty.
* ``impact_score`` is a 0-1 float, but ``GET /articles`` filters on
  ``impact == "low" | "medium" | "high"``, so the score is bucketed.

Feeds without an API key are skipped rather than called and failed: an
unconfigured provider is a deployment state, and it should read as an empty
feed rather than an error.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

logger = logging.getLogger(__name__)

# impact_score (0-1) -> the bucket GET /articles filters on.
_IMPACT_MEDIUM = 0.34
_IMPACT_HIGH = 0.67

# Every adapter in this package, in the order results are gathered.
_FEED_CLASS_NAMES = (
    "FinnhubFeed",
    "FMPFeed",
    "NewsDataFeed",
    "AlphaVantageNewsFeed",
    "NewsAPIFeed",
)


def _bucket_impact(score: float) -> str:
    """Map a 0-1 impact score onto the endpoint's three-value filter."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "low"
    if value >= _IMPACT_HIGH:
        return "high"
    if value >= _IMPACT_MEDIUM:
        return "medium"
    return "low"


def _build_default_feeds() -> list[Any]:
    """Instantiate every adapter that imports cleanly.

    Import failures are tolerated: an adapter whose optional dependency is
    absent should cost that one provider, not the whole news surface.
    """
    feeds: list[Any] = []
    for name in _FEED_CLASS_NAMES:
        try:
            module = __import__("data_layer.feeds.news", fromlist=[name])
            cls = getattr(module, name, None)
            if cls is None:
                logger.debug("NewsFeedManager: %s not available", name)
                continue
            feeds.append(cls())
        except Exception as exc:
            logger.debug("NewsFeedManager: %s could not be constructed: %s", name, exc)
    return feeds


class NewsFeedManager:
    """Aggregates the configured news adapters behind one ``get_latest``."""

    def __init__(self, feeds: list[Any] | None = None) -> None:
        self.feeds: list[Any] = _build_default_feeds() if feeds is None else list(feeds)

    # ── Public API ───────────────────────────────────────────────────────────

    async def get_latest(self, limit: int = 50, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return up to ``limit`` articles, newest first, as endpoint dicts.

        ``symbol`` is accepted because the endpoints pass it. The adapters are
        gold-only today and none of them filter by instrument, so it is carried
        onto each article's ``symbols`` rather than used to narrow the query —
        stating that plainly beats silently ignoring the argument.

        Never raises: a news outage must not take an endpoint down.
        """
        active = [f for f in self.feeds if self._is_configured(f)]
        if not active:
            logger.debug("NewsFeedManager: no configured news feeds — returning empty")
            return []

        results = await asyncio.gather(
            *(self._fetch_one(feed, limit) for feed in active),
            return_exceptions=True,
        )

        merged: dict[str, Any] = {}
        for feed, result in zip(active, results, strict=False):
            if isinstance(result, BaseException):
                logger.warning("NewsFeedManager: %s failed: %s", type(feed).__name__, result)
                continue
            for article in result:
                article_id = getattr(article, "article_id", None)
                if not article_id or article_id in merged:
                    continue
                merged[article_id] = article

        ordered = sorted(merged.values(), key=self._published_sort_key, reverse=True)
        return [self._to_dict(a, symbol) for a in ordered[:limit]]

    async def close(self) -> None:
        """Release every adapter's HTTP session."""
        for feed in self.feeds:
            closer = getattr(feed, "close", None)
            if closer is None:
                continue
            try:
                await closer()
            except Exception as exc:
                logger.debug("NewsFeedManager: closing %s failed: %s", type(feed).__name__, exc)

    def health_summary(self) -> dict[str, Any]:
        """Per-adapter health, for the news health endpoint."""
        summary: dict[str, Any] = {}
        for feed in self.feeds:
            name = type(feed).__name__
            try:
                reporter = getattr(feed, "health_summary", None)
                summary[name] = reporter() if reporter else {"configured": self._is_configured(feed)}
            except Exception as exc:
                summary[name] = {"error": str(exc)[:200]}
        return summary

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _is_configured(feed: Any) -> bool:
        """An adapter with no API key is skipped, not called and failed.

        ``NewsFeedBase.is_configured`` is a **property**, so reading it already
        yields a bool. Calling it raised ``TypeError: 'bool' object is not
        callable``, which the surrounding ``except`` reported as "not
        configured" — so every adapter was skipped and ``get_latest`` returned
        ``[]`` for every request, leaving ``/api/news-feed/*`` exactly as empty
        as before this manager existed.

        Both shapes are accepted: a subclass or a test double may legitimately
        expose it as a method.
        """
        if not hasattr(feed, "is_configured"):
            return True
        value = feed.is_configured
        if callable(value):
            try:
                value = value()
            except Exception as exc:
                logger.debug("NewsFeedManager: %s.is_configured() failed: %s", type(feed).__name__, exc)
                return False
        return bool(value)

    @staticmethod
    async def _fetch_one(feed: Any, limit: int) -> list[Any]:
        articles = await feed.fetch_articles(limit=limit)
        return list(articles or [])

    @staticmethod
    def _published_sort_key(article: Any):
        """Order by publication time across adapters that disagree about tzinfo.

        FMP and NewsData return naive datetimes; Finnhub, AlphaVantage and
        NewsAPI return aware ones. ``sorted`` raises "can't compare
        offset-naive and offset-aware datetimes" the moment both kinds are in
        one merged list, which the endpoint reports as a fetch failure — an
        outage decided purely by which two providers happen to be configured.

        A naive timestamp is read as UTC, which is what every one of these
        providers actually means. A feed that omits the field sorts last rather
        than crashing the merge.
        """
        published = getattr(article, "published_at", None)
        if published is None or not hasattr(published, "tzinfo"):
            return (False, datetime.min.replace(tzinfo=UTC))
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        return (True, published)

    @staticmethod
    def _to_dict(article: Any, symbol: str | None) -> dict[str, Any]:
        """Translate a NewsArticle onto the keys api/news_feed.py reads."""
        published = getattr(article, "published_at", None)
        source = getattr(article, "source", "")

        return {
            "id": getattr(article, "article_id", ""),
            "title": getattr(article, "headline", ""),
            "source": str(getattr(source, "value", source) or ""),
            "published_at": published.isoformat() if hasattr(published, "isoformat") else "",
            "url": getattr(article, "url", ""),
            "sentiment": getattr(article, "sentiment_label", "neutral"),
            "impact": _bucket_impact(getattr(article, "impact_score", 0.0)),
            "symbols": [symbol] if symbol else [],
            "summary": getattr(article, "summary", ""),
        }
