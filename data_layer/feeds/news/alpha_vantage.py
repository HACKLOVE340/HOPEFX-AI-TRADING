# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/news/alpha_vantage.py
=======================================
Alpha Vantage News & Sentiment adapter — https://www.alphavantage.co/

Free tier: 25 requests/day
Endpoint: GET https://www.alphavantage.co/query?function=NEWS_SENTIMENT
          &tickers=FOREX:XAUUSD&topics=economy_macro,finance&apikey=KEY

Alpha Vantage provides per-article sentiment scores (overall_sentiment_score,
overall_sentiment_label) and per-ticker relevance scores — extremely useful
for gold-specific sentiment without running our own NLP.
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

_BASE = "https://www.alphavantage.co/query"


class AlphaVantageNewsFeed(NewsFeedBase):
    """Alpha Vantage News & Sentiment adapter."""

    name = NewsSource.ALPHA_VANTAGE
    _api_key_env = "ALPHA_VANTAGE_KEY"
    _min_interval_s = 300.0  # 25 req/day ≈ 1 req/58min; use 5min for bursts

    async def fetch_articles(self, limit: int = 50) -> list[NewsArticle]:
        if not self.is_configured:
            return []

        articles: ClassVar[list[NewsArticle]] = []
        try:
            data = await self._get(
                _BASE,
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": "FOREX:XAUUSD,GLD,IAU",
                    "topics": "economy_macro,finance,economy_monetary",
                    "limit": min(limit, 50),
                    "apikey": self._api_key,
                },
            )

            feed_items = data.get("feed", [])
            for item in feed_items:
                headline = item.get("title", "")
                summary = item.get("summary", "")
                raw_id = item.get("url", headline)
                article_id = self._dedup_id(raw_id)
                if not self._is_new(article_id):
                    continue

                # Alpha Vantage time format: "20240115T143000"
                time_str = item.get("time_published", "")
                try:
                    published = datetime.strptime(time_str, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
                except Exception:
                    published = datetime.now(UTC)

                # Native sentiment score: -1 to +1
                raw_score = float(item.get("overall_sentiment_score", 0.0))
                label = item.get("overall_sentiment_label", "Neutral")

                # Gold relevance from ticker sentiment list
                gold_relevance = 0.0
                for ts in item.get("ticker_sentiment", []):
                    if ts.get("ticker", "").upper() in ("FOREX:XAUUSD", "GLD", "IAU"):
                        gold_relevance = max(
                            gold_relevance,
                            float(ts.get("relevance_score", 0.0)),
                        )

                articles.append(
                    NewsArticle(
                        article_id=article_id,
                        source=self.name,
                        headline=headline,
                        summary=summary,
                        url=item.get("url", ""),
                        published_at=published,
                        fetched_at=datetime.now(UTC),
                        sentiment_score=raw_score,
                        sentiment_label=label.lower(),
                        gold_relevance=gold_relevance,
                        keywords=[t.get("ticker", "") for t in item.get("ticker_sentiment", [])],
                        lineage_id=str(uuid.uuid4()),
                    )
                )
                self._total_fetched += 1

        except Exception as exc:
            logger.warning("AlphaVantage news error: %s", exc)

        return articles
