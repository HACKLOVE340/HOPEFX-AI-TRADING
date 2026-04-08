# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/news/finnhub.py
=================================
Finnhub news + sentiment adapter — https://finnhub.io/

Free tier: 60 API calls/minute
Endpoints used:
  - GET /news?category=general          (market news)
  - GET /news-sentiment?symbol=OANDA:XAU_USD  (sentiment score)

Finnhub provides a native sentiment score (bullishPercent, bearishPercent)
which we use directly rather than running our own NLP on every article.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
from typing import ClassVar

from data_layer.feeds.news.base import NewsFeedBase
from data_layer.types import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"


class FinnhubFeed(NewsFeedBase):
    """Finnhub news + native sentiment scores."""

    name = NewsSource.FINNHUB
    _api_key_env = "FINNHUB_API_KEY"
    _min_interval_s = 5.0  # free tier: 60 req/min

    async def fetch_articles(self, limit: int = 50) -> list[NewsArticle]:
        if not self.is_configured:
            return []

        articles: ClassVar[list[NewsArticle]] = []
        try:
            data = await self._get(
                f"{_BASE}/news",
                params={"category": "general", "token": self._api_key},
            )
            if not isinstance(data, list):
                return []

            for item in data[:limit]:
                headline = item.get("headline", "")
                summary = item.get("summary", "")
                text = f"{headline} {summary}"

                if not self._is_gold_relevant(text):
                    continue

                raw_id = str(item.get("id", item.get("url", headline)))
                article_id = self._dedup_id(raw_id)
                if not self._is_new(article_id):
                    continue

                ts = item.get("datetime", 0)
                published = datetime.fromtimestamp(ts, tz=UTC) if ts else datetime.now(UTC)

                articles.append(
                    NewsArticle(
                        article_id=article_id,
                        source=self.name,
                        headline=headline,
                        summary=summary,
                        url=item.get("url", ""),
                        published_at=published,
                        fetched_at=datetime.now(UTC),
                        gold_relevance=0.0,  # scored by SentimentEngine
                        lineage_id=str(uuid.uuid4()),
                    )
                )
                self._total_fetched += 1

        except Exception as exc:
            logger.warning("Finnhub fetch_articles error: %s", exc)

        return articles

    async def fetch_sentiment(self) -> dict:
        """
        Fetch Finnhub's native market sentiment for gold.

        Returns dict with keys: bullishPercent, bearishPercent, buzz.
        Falls back to empty dict on error.
        """
        if not self.is_configured:
            return {}
        try:
            data = await self._get(
                f"{_BASE}/news-sentiment",
                params={"symbol": "OANDA:XAU_USD", "token": self._api_key},
            )
            return {
                "bullish_pct": float(data.get("bullishPercent", 0.5)),
                "bearish_pct": float(data.get("bearishPercent", 0.5)),
                "buzz": float(data.get("buzz", {}).get("articlesInLastWeek", 0)),
                "source": "finnhub",
            }
        except Exception as exc:
            logger.debug("Finnhub sentiment error: %s", exc)
            return {}
