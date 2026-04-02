# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
News Providers Module

Integrates multiple news sources to provide comprehensive financial news coverage.

Providers:
- NewsAPI.org: Global news coverage
- Alpha Vantage: Market-specific news
- RSS Feeds: Real-time updates from major sources
- Multi-source aggregator: Combines all sources

Author: HOPEFX Development Team
"""

import abc
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

import requests

try:
    import feedparser

    _FEEDPARSER_AVAILABLE = True
except ImportError:
    feedparser = None  # type: ignore[assignment]
    _FEEDPARSER_AVAILABLE = False

logger = logging.getLogger(__name__)

if not _FEEDPARSER_AVAILABLE:
    logger.warning("feedparser not installed — RSS news feed disabled. Install with: pip install feedparser")


@dataclass
class NewsArticle:
    """Represents a news article"""

    title: str
    description: str
    source: str
    published_at: datetime
    url: str
    author: str | None = None
    content: str | None = None
    symbols: list[str] | None = None
    sentiment: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "published_at": self.published_at.isoformat(),
            "url": self.url,
            "author": self.author,
            "content": self.content,
            "symbols": self.symbols,
            "sentiment": self.sentiment,
        }


class NewsProvider(abc.ABC):
    """Abstract base class for news data providers."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.logger = logging.getLogger(self.__class__.__name__)

    @abc.abstractmethod
    def get_news(self, *args, **kwargs) -> list[NewsArticle]:
        """Fetch and return a list of NewsArticle objects."""

    @abc.abstractmethod
    def format_article(self, *args, **kwargs) -> NewsArticle:
        """Convert a raw provider response dict into a NewsArticle."""


class NewsAPIProvider(NewsProvider):
    """
    NewsAPI.org provider for general financial news

    API Documentation: https://newsapi.org/docs
    """

    BASE_URL = "https://newsapi.org/v2"

    def __init__(self, api_key: str):
        super().__init__(api_key)
        if not api_key:
            raise ValueError("NewsAPI requires an API key")

    def get_news(
        self,
        query: str = "forex OR trading OR stocks",
        language: str = "en",
        sort_by: str = "publishedAt",
        page_size: int = 20,
        from_date: datetime | None = None,
    ) -> list[NewsArticle]:
        """
        Get news from NewsAPI

        Args:
            query: Search query
            language: Language code
            sort_by: Sort order (publishedAt, relevancy, popularity)
            page_size: Number of articles (max 100)
            from_date: Get articles from this date onwards

        Returns:
            List of NewsArticle objects
        """
        try:
            # Set default from_date to last 24 hours
            if from_date is None:
                from_date = datetime.now(UTC) - timedelta(days=1)

            params = {
                "q": query,
                "language": language,
                "sortBy": sort_by,
                "pageSize": min(page_size, 100),
                "from": from_date.isoformat(),
                "apiKey": self.api_key,
            }

            response = requests.get(f"{self.BASE_URL}/everything", params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data.get("status") != "ok":
                self.logger.error(f"NewsAPI error: {data.get('message')}")
                return []

            articles = []
            for article in data.get("articles", []):
                try:
                    articles.append(self.format_article(article))
                except Exception as e:
                    self.logger.warning(f"Error formatting article: {e}")
                    continue

            self.logger.info(f"Retrieved {len(articles)} articles from NewsAPI")
            return articles

        except requests.exceptions.RequestException as e:
            self.logger.error(f"NewsAPI request failed: {e}")
            return []
        except Exception as e:
            self.logger.error(f"NewsAPI error: {e}")
            return []

    def format_article(self, raw_article: dict[str, Any]) -> NewsArticle:
        """Format NewsAPI article"""
        return NewsArticle(
            title=raw_article.get("title", ""),
            description=raw_article.get("description", ""),
            source=raw_article.get("source", {}).get("name", "Unknown"),
            published_at=datetime.fromisoformat(raw_article.get("publishedAt", "").replace("Z", "+00:00")),
            url=raw_article.get("url", ""),
            author=raw_article.get("author"),
            content=raw_article.get("content"),
        )


class AlphaVantageNewsProvider(NewsProvider):
    """
    Alpha Vantage News & Sentiment provider

    API Documentation: https://www.alphavantage.co/documentation/#news-sentiment
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str):
        super().__init__(api_key)
        if not api_key:
            raise ValueError("Alpha Vantage requires an API key")

    def get_news(
        self,
        tickers: str | None = None,
        topics: str = "financial_markets",
        limit: int = 50,
    ) -> list[NewsArticle]:
        """
        Get news from Alpha Vantage

        Args:
            tickers: Comma-separated ticker symbols
            topics: News topics filter
            limit: Number of articles

        Returns:
            List of NewsArticle objects
        """
        try:
            params = {
                "function": "NEWS_SENTIMENT",
                "topics": topics,
                "limit": limit,
                "apikey": self.api_key,
            }

            if tickers:
                params["tickers"] = tickers

            response = requests.get(self.BASE_URL, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if "Error Message" in data:
                self.logger.error(f"Alpha Vantage error: {data['Error Message']}")
                return []

            articles = []
            for item in data.get("feed", []):
                try:
                    articles.append(self.format_article(item))
                except Exception as e:
                    self.logger.warning(f"Error formatting article: {e}")
                    continue

            self.logger.info(f"Retrieved {len(articles)} articles from Alpha Vantage")
            return articles

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Alpha Vantage request failed: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Alpha Vantage error: {e}")
            return []

    def format_article(self, raw_article: dict[str, Any]) -> NewsArticle:
        """Format Alpha Vantage article"""
        # Extract overall sentiment score
        sentiment_score = float(raw_article.get("overall_sentiment_score", 0))

        # Extract symbols
        symbols = [ticker["ticker"] for ticker in raw_article.get("ticker_sentiment", [])]

        return NewsArticle(
            title=raw_article.get("title", ""),
            description=raw_article.get("summary", ""),
            source=raw_article.get("source", "Unknown"),
            published_at=datetime.strptime(raw_article.get("time_published", ""), "%Y%m%dT%H%M%S"),
            url=raw_article.get("url", ""),
            author=", ".join(raw_article.get("authors", [])),
            sentiment=sentiment_score,
            symbols=symbols if symbols else None,
        )


class RSSFeedProvider(NewsProvider):
    """
    RSS Feed provider for real-time news updates

    Supports: Forex Factory, Trading Economics, Reuters, Bloomberg, etc.
    """

    DEFAULT_FEEDS = {
        "forex_factory": "https://www.forexfactory.com/feed",
        "trading_economics": "https://tradingeconomics.com/rss/news.aspx",
        "reuters": "https://www.reutersagency.com/feed/",
        "bloomberg": "https://www.bloomberg.com/feed/podcast/etf-report.xml",
    }

    def __init__(self):
        super().__init__()
        self.feeds = self.DEFAULT_FEEDS.copy()

    def add_feed(self, name: str, url: str):
        """Add a custom RSS feed"""
        self.feeds[name] = url

    def get_news(self, feeds: list[str] | None = None, hours_back: int = 24) -> list[NewsArticle]:
        """
        Get news from RSS feeds

        Args:
            feeds: List of feed names (defaults to all)
            hours_back: Get articles from last N hours

        Returns:
            List of NewsArticle objects
        """
        if feeds is None:
            feeds = list(self.feeds.keys())

        cutoff_time = datetime.now(UTC) - timedelta(hours=hours_back)
        all_articles = []

        for feed_name in feeds:
            if feed_name not in self.feeds:
                self.logger.warning(f"Feed '{feed_name}' not found")
                continue

            try:
                if not _FEEDPARSER_AVAILABLE:
                    self.logger.warning("feedparser not installed — skipping RSS feed '%s'", feed_name)
                    continue
                feed_url = self.feeds[feed_name]
                feed = feedparser.parse(feed_url)

                for entry in feed.entries:
                    try:
                        article = self.format_article(entry, feed_name)
                        if article.published_at >= cutoff_time:
                            all_articles.append(article)
                    except Exception as e:
                        self.logger.warning(f"Error formatting RSS entry: {e}")
                        continue

                self.logger.info(f"Retrieved articles from {feed_name}")

            except Exception as e:
                self.logger.error(f"Error parsing RSS feed {feed_name}: {e}")
                continue

        self.logger.info(f"Retrieved {len(all_articles)} articles from RSS feeds")
        return all_articles

    def format_article(self, entry: Any, source: str) -> NewsArticle:
        """Format RSS feed entry"""
        # Parse published date
        published_at = datetime.now(UTC)
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published_at = datetime(*entry.published_parsed[:6])
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            published_at = datetime(*entry.updated_parsed[:6])

        return NewsArticle(
            title=entry.get("title", ""),
            description=entry.get("summary", ""),
            source=source,
            published_at=published_at,
            url=entry.get("link", ""),
            author=entry.get("author"),
            content=entry.get("content", [{}])[0].get("value") if hasattr(entry, "content") else None,
        )


class MultiSourceAggregator:
    """
    Aggregates news from multiple sources and deduplicates
    """

    def __init__(
        self,
        newsapi_key: str | None = None,
        alphavantage_key: str | None = None,
        use_rss: bool = True,
    ):
        self.providers = []

        if newsapi_key:
            self.providers.append(NewsAPIProvider(newsapi_key))

        if alphavantage_key:
            self.providers.append(AlphaVantageNewsProvider(alphavantage_key))

        if use_rss:
            self.providers.append(RSSFeedProvider())

        self.logger = logging.getLogger(self.__class__.__name__)

    def get_aggregated_news(
        self,
        query: str | None = None,
        symbols: list[str] | None = None,
        hours_back: int = 24,
        deduplicate: bool = True,
    ) -> list[NewsArticle]:
        """
        Get news from all configured providers

        Args:
            query: Search query (for NewsAPI)
            symbols: Stock symbols (for Alpha Vantage)
            hours_back: Time window in hours
            deduplicate: Remove duplicate articles

        Returns:
            Combined list of NewsArticle objects
        """
        all_articles = []

        for provider in self.providers:
            try:
                if isinstance(provider, NewsAPIProvider) and query:
                    articles = provider.get_news(query=query)
                elif isinstance(provider, AlphaVantageNewsProvider) and symbols:
                    articles = provider.get_news(tickers=",".join(symbols))
                elif isinstance(provider, RSSFeedProvider):
                    articles = provider.get_news(hours_back=hours_back)
                else:
                    continue

                all_articles.extend(articles)

            except Exception as e:
                self.logger.error(f"Error fetching from {provider.__class__.__name__}: {e}")
                continue

        if deduplicate:
            all_articles = self._deduplicate(all_articles)

        # Sort by published date (newest first)
        all_articles.sort(key=lambda x: x.published_at, reverse=True)

        self.logger.info(f"Aggregated {len(all_articles)} unique articles")
        return all_articles

    def _deduplicate(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        """Remove duplicate articles based on title similarity"""
        seen_titles = set()
        unique_articles = []

        for article in articles:
            # Normalize title for comparison
            normalized_title = article.title.lower().strip()

            if normalized_title not in seen_titles:
                seen_titles.add(normalized_title)
                unique_articles.append(article)

        return unique_articles


# Global aggregator instance (to be configured with API keys)
news_aggregator = None


def initialize_aggregator(newsapi_key=None, alphavantage_key=None):
    """Initialize the global news aggregator"""
    global news_aggregator
    news_aggregator = MultiSourceAggregator(newsapi_key=newsapi_key, alphavantage_key=alphavantage_key)
    return news_aggregator
