# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/news/newsdata.py
==================================
NewsData.io adapter — https://newsdata.io/

Free tier: 200 credits/day (1 credit = 1 article)
Endpoint: GET https://newsdata.io/api/1/news?apikey=KEY&q=gold+XAU&language=en&category=business

NewsData.io supports full-text search queries — we query specifically for
gold/XAU/bullion to maximise relevance without post-filtering.
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

_BASE = "https://newsdata.io/api/1"


class NewsDataFeed(NewsFeedBase):
    """NewsData.io adapter."""

    name = NewsSource.NEWSDATA
    _api_key_env = "NEWSDATA_IO_KEY"
    _min_interval_s = 300.0  # 200 credits/day ≈ 1 req/7.2min; use 5min

    async def fetch_articles(self, limit: int = 50) -> list[NewsArticle]:
        if not self.is_configured:
            return []

        articles: ClassVar[list[NewsArticle]] = []
        try:
            data = await self._get(
                f"{_BASE}/news",
                params={
                    "apikey": self._api_key,
                    "q": 'gold OR XAU OR bullion OR "precious metal"',
                    "language": "en",
                    "category": "business,top",
                    "size": min(limit, 50),
                },
            )

            results = data.get("results", [])
            for item in results:
                headline = item.get("title", "")
                summary = item.get("description", "") or item.get("content", "")
                raw_id = item.get("article_id", item.get("link", headline))
                article_id = self._dedup_id(raw_id)
                if not self._is_new(article_id):
                    continue

                pub_str = item.get("pubDate", "")
                try:
                    published = datetime.fromisoformat(pub_str)
                except Exception:
                    published = datetime.now(UTC)

                keywords = item.get("keywords") or []

                articles.append(
                    NewsArticle(
                        article_id=article_id,
                        source=self.name,
                        headline=headline,
                        summary=summary,
                        url=item.get("link", ""),
                        published_at=published,
                        fetched_at=datetime.now(UTC),
                        keywords=keywords if isinstance(keywords, list) else [],
                        lineage_id=str(uuid.uuid4()),
                    )
                )
                self._total_fetched += 1

        except Exception as exc:
            logger.warning("NewsData.io fetch_articles error: %s", exc)

        return articles
