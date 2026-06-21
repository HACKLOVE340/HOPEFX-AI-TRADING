# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/news/newsapi.py
=================================
NewsAPI.org adapter — https://newsapi.org/

Free tier: 100 requests/day, developer plan
Endpoint: GET https://newsapi.org/v2/everything
          ?q=gold+XAU+bullion&language=en&sortBy=publishedAt&apiKey=KEY

Also supports NewsAPI.ai (https://newsapi.ai/) which uses the same
response schema but with richer entity extraction. The adapter auto-detects
which endpoint to use based on which key is configured.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
from typing import ClassVar

from data_layer.feeds.news.base import NewsFeedBase
from data_layer.types import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

_NEWSAPI_ORG_BASE = "https://newsapi.org/v2"
_NEWSAPI_AI_BASE = "https://eventregistry.org/api/v1"


class NewsAPIFeed(NewsFeedBase):
    """
    NewsAPI.org / NewsAPI.ai adapter.

    Prefers NewsAPI.ai (richer entity data) when NEWSAPI_AI_KEY is set,
    falls back to NewsAPI.org when NEWSAPI_ORG_KEY is set.
    """

    name = NewsSource.NEWSAPI
    _api_key_env = "NEWSAPI_ORG_KEY"  # primary  # pragma: allowlist secret
    _min_interval_s = 60.0

    def __init__(self) -> None:
        super().__init__()
        # NewsAPI.ai key takes priority
        self._ai_key = os.getenv("NEWSAPI_AI_KEY", "")

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key or self._ai_key)

    async def fetch_articles(self, limit: int = 50) -> list[NewsArticle]:
        if not self.is_configured:
            return []

        if self._ai_key:
            return await self._fetch_newsapi_ai(limit)
        return await self._fetch_newsapi_org(limit)

    async def _fetch_newsapi_org(self, limit: int) -> list[NewsArticle]:
        articles: ClassVar[list[NewsArticle]] = []
        try:
            data = await self._get(
                f"{_NEWSAPI_ORG_BASE}/everything",
                params={
                    "q": 'gold OR XAU OR bullion OR "gold price"',
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": min(limit, 100),
                    "apiKey": self._api_key,
                },
            )

            for item in data.get("articles", []):
                headline = item.get("title", "")
                summary = item.get("description", "") or item.get("content", "")
                raw_id = item.get("url", headline)
                article_id = self._dedup_id(raw_id)
                if not self._is_new(article_id):
                    continue

                pub_str = item.get("publishedAt", "")
                try:
                    published = datetime.fromisoformat(pub_str)
                except Exception:
                    published = datetime.now(UTC)

                articles.append(
                    NewsArticle(
                        article_id=article_id,
                        source=self.name,
                        headline=headline,
                        summary=summary,
                        url=item.get("url", ""),
                        published_at=published,
                        fetched_at=datetime.now(UTC),
                        lineage_id=str(uuid.uuid4()),
                    )
                )
                self._total_fetched += 1

        except Exception as exc:
            logger.log(logging.DEBUG if any(s in str(exc).lower() for s in ("connect", "dns", "ssl", "timeout")) else logging.WARNING, "NewsAPI.org error: %s", exc)

        return articles

    async def _fetch_newsapi_ai(self, limit: int) -> list[NewsArticle]:
        """NewsAPI.ai uses EventRegistry API with richer entity extraction."""
        articles: ClassVar[list[NewsArticle]] = []
        try:
            data = await self._get(
                f"{_NEWSAPI_AI_BASE}/article/getArticles",
                params={
                    "apiKey": self._ai_key,
                    "keyword": "gold XAU bullion",
                    "keywordOper": "or",
                    "lang": "eng",
                    "articlesSortBy": "date",
                    "articlesSortByAsc": "false",
                    "articlesCount": min(limit, 100),
                    "resultType": "articles",
                    "dataType": ["news", "blog"],
                    "forceMaxDataTimeWindow": 2,
                },
            )

            for item in data.get("articles", {}).get("results", []):
                headline = item.get("title", "")
                summary = item.get("body", "")[:500]
                raw_id = item.get("uri", item.get("url", headline))
                article_id = self._dedup_id(raw_id)
                if not self._is_new(article_id):
                    continue

                pub_str = item.get("dateTime", item.get("date", ""))
                try:
                    published = datetime.fromisoformat(pub_str)
                except Exception:
                    published = datetime.now(UTC)

                # NewsAPI.ai provides sentiment
                sentiment = item.get("sentiment", 0.0) or 0.0

                articles.append(
                    NewsArticle(
                        article_id=article_id,
                        source=NewsSource.NEWSAPI_AI,
                        headline=headline,
                        summary=summary,
                        url=item.get("url", ""),
                        published_at=published,
                        fetched_at=datetime.now(UTC),
                        sentiment_score=float(sentiment),
                        lineage_id=str(uuid.uuid4()),
                    )
                )
                self._total_fetched += 1

        except Exception as exc:
            logger.log(logging.DEBUG if any(s in str(exc).lower() for s in ("connect", "dns", "ssl", "timeout")) else logging.WARNING, "NewsAPI.ai error: %s", exc)

        return articles
