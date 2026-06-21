# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/news/fmp.py
=============================
Financial Modeling Prep (FMP) news adapter — https://financialmodelingprep.com/

Free tier: 250 requests/day
Endpoints used:
  - GET /v3/stock_news?tickers=GLD,IAU,XAUUSD&limit=50&apikey=KEY
  - GET /v4/general_news?page=0&apikey=KEY  (broader macro news)

FMP provides structured news with ticker tagging — very useful for
filtering gold-specific articles without keyword matching.
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

_BASE = "https://financialmodelingprep.com/api"


class FMPFeed(NewsFeedBase):
    """Financial Modeling Prep news adapter."""

    name = NewsSource.FMP
    _api_key_env = "FMP_API_KEY"  # pragma: allowlist secret
    _min_interval_s = 30.0  # 250 req/day ≈ 1 req/5.8min; use 30s for bursts

    async def fetch_articles(self, limit: int = 50) -> list[NewsArticle]:
        if not self.is_configured:
            return []

        articles: ClassVar[list[NewsArticle]] = []
        try:
            # Gold-specific ticker news
            data = await self._get(
                f"{_BASE}/v3/stock_news",
                params={
                    "tickers": "GLD,IAU,XAUUSD,GOLD",
                    "limit": min(limit, 50),
                    "apikey": self._api_key,
                },
            )
            if not isinstance(data, list):
                data = []

            for item in data:
                headline = item.get("title", "")
                summary = item.get("text", "")
                raw_id = item.get("url", headline)
                article_id = self._dedup_id(raw_id)
                if not self._is_new(article_id):
                    continue

                pub_str = item.get("publishedDate", "")
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
                        keywords=[item.get("symbol", "")],
                        lineage_id=str(uuid.uuid4()),
                    )
                )
                self._total_fetched += 1

        except Exception as exc:
            logger.log(logging.DEBUG if any(s in str(exc).lower() for s in ("connect", "dns", "ssl", "timeout")) else logging.WARNING, "FMP fetch_articles error: %s", exc)

        return articles
