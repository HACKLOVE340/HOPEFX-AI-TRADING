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

try:
    import defusedxml.ElementTree as _ET  # type: ignore[import-untyped]

    ET = _ET
except ImportError:
    # defusedxml not installed — fall back to stdlib; input is validated upstream
    import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

UTC = timezone.utc

import requests

try:
    import feedparser as _fp_module

    _ = _fp_module.parse  # verify parse() is accessible (import may succeed but be broken)
    _FEEDPARSER_AVAILABLE = True
    feedparser = _fp_module
except Exception:
    feedparser = None  # type: ignore[assignment]
    _FEEDPARSER_AVAILABLE = False

logger = logging.getLogger(__name__)

if not _FEEDPARSER_AVAILABLE:
    logger.info("feedparser unavailable — using built-in XML RSS parser")


# ── Minimal RSS/Atom parser (stdlib only, no feedparser dependency) ───────────

_ATOM_NS = "http://www.w3.org/2005/Atom"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _parse_date(text: str | None) -> datetime:
    """Parse RFC 2822 or ISO 8601 date strings, fallback to now."""
    if not text:
        return datetime.now(UTC)
    try:
        return parsedate_to_datetime(text).astimezone(UTC)
    except Exception:  # nosec B110
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[: len(fmt) + 5], fmt)
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
        except Exception:
            continue
    return datetime.now(UTC)


def _xml_text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_rss_feed(xml_bytes: bytes, source_name: str) -> list[dict]:
    """Parse RSS 2.0 or Atom feed XML bytes into a list of entry dicts."""
    try:
        root = ET.fromstring(xml_bytes)  # noqa: S314  # nosec B314 — defusedxml used when available (see import block above)
    except ET.ParseError:
        return []

    entries: list[dict] = []

    # Atom feed
    if root.tag == f"{{{_ATOM_NS}}}feed" or root.tag.endswith("}feed"):
        ns = {"a": _ATOM_NS}
        for entry in root.findall("a:entry", ns) or root.findall("entry"):
            title_el = entry.find("a:title", ns) or entry.find("title")
            summary_el = entry.find("a:summary", ns) or entry.find("summary")
            link_el = entry.find("a:link", ns) or entry.find("link")
            updated_el = entry.find("a:updated", ns) or entry.find("updated")
            author_el = entry.find("a:author/a:name", ns) or entry.find("author/name")
            link_href = ""
            if link_el is not None:
                link_href = link_el.get("href", "") or _xml_text(link_el)
            entries.append(
                {
                    "title": _xml_text(title_el),
                    "summary": _xml_text(summary_el),
                    "link": link_href,
                    "published": _xml_text(updated_el),
                    "author": _xml_text(author_el),
                    "source": source_name,
                }
            )
        return entries

    # RSS 2.0
    channel = root.find("channel") or root
    for item in channel.findall("item"):
        pub_el = item.find("pubDate") or item.find(f"{{{_DC_NS}}}date")
        desc_el = item.find("description")
        entries.append(
            {
                "title": _xml_text(item.find("title")),
                "summary": _xml_text(desc_el),
                "link": _xml_text(item.find("link")),
                "published": _xml_text(pub_el),
                "author": _xml_text(item.find(f"{{{_DC_NS}}}creator") or item.find("author")),
                "source": source_name,
            }
        )
    return entries


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
    def get_news(self, **kwargs) -> list[NewsArticle]:
        """Fetch and return a list of NewsArticle objects."""

    @abc.abstractmethod
    def format_article(self, raw_article: Any, **kwargs) -> NewsArticle:
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
        **kwargs,
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
                self.logger.error("NewsAPI error: %s", data.get("message"))

                return []

            articles = []
            for article in data.get("articles", []):
                try:
                    articles.append(self.format_article(article))
                except Exception as e:
                    self.logger.warning("Error formatting article: %s", e)

                    continue

            self.logger.info("Retrieved %s articles from NewsAPI", len(articles))

            return articles

        except requests.exceptions.RequestException as e:
            self.logger.error("NewsAPI request failed: %s", e)

            return []
        except Exception as e:
            self.logger.error("NewsAPI error: %s", e)

            return []

    def format_article(self, raw_article: Any, **kwargs) -> NewsArticle:
        """Format NewsAPI article"""
        return NewsArticle(
            title=raw_article.get("title", ""),
            description=raw_article.get("description", ""),
            source=raw_article.get("source", {}).get("name", "Unknown"),
            published_at=datetime.fromisoformat(raw_article.get("publishedAt", "")),
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
        **kwargs,
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
                self.logger.error("Alpha Vantage error: %s", data["Error Message"])

                return []

            articles = []
            for item in data.get("feed", []):
                try:
                    articles.append(self.format_article(item))
                except Exception as e:
                    self.logger.warning("Error formatting article: %s", e)

                    continue

            self.logger.info("Retrieved %s articles from Alpha Vantage", len(articles))

            return articles

        except requests.exceptions.RequestException as e:
            self.logger.error("Alpha Vantage request failed: %s", e)

            return []
        except Exception as e:
            self.logger.error("Alpha Vantage error: %s", e)

            return []

    def format_article(self, raw_article: Any, **kwargs) -> NewsArticle:
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
            symbols=symbols or None,
        )


class RSSFeedProvider(NewsProvider):
    """
    RSS Feed provider for real-time news updates

    Supports: Forex Factory, Trading Economics, Reuters, Bloomberg, etc.
    """

    # Publicly accessible RSS feeds for financial/forex news.
    # Feeds are tried in order; failures are logged and skipped gracefully.
    # Override individual feeds via RSS_FEED_<NAME>=<url> env vars, e.g.:
    #   RSS_FEED_REUTERS=https://feeds.reuters.com/reuters/businessNews
    DEFAULT_FEEDS = {
        "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
        "reuters_markets": "https://feeds.reuters.com/reuters/UKmarkets",
        "investing_com": "https://www.investing.com/rss/news.rss",
        "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
        "ft_markets": "https://www.ft.com/markets?format=rss",
        "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
        "cnbc_finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        "seeking_alpha": "https://seekingalpha.com/market_currents.xml",
    }

    def __init__(self):
        super().__init__()
        # Allow per-feed URL overrides via environment variables.
        # RSS_FEED_REUTERS=https://... overrides the "reuters_business" feed, etc.
        self.feeds = self.DEFAULT_FEEDS.copy()
        import os as _os

        for name in list(self.feeds.keys()):
            env_key = f"RSS_FEED_{name.upper()}"
            override = _os.getenv(env_key, "")
            if override:
                self.feeds[name] = override
                logger.info("RSS feed '%s' overridden via %s", name, env_key)
        # Allow adding entirely new feeds via RSS_FEED_EXTRA_<NAME>=<url>
        for key, val in _os.environ.items():
            if key.startswith("RSS_FEED_EXTRA_") and val:
                feed_name = key[len("RSS_FEED_EXTRA_") :].lower()
                self.feeds[feed_name] = val
                logger.info("RSS feed '%s' added via %s", feed_name, key)

    def add_feed(self, name: str, url: str):
        """Add a custom RSS feed"""
        self.feeds[name] = url

    def get_news(self, feeds: list[str] | None = None, hours_back: int = 24, **kwargs) -> list[NewsArticle]:
        """
        Get news from RSS feeds.

        Uses feedparser when available; falls back to a stdlib XML parser
        (xml.etree.ElementTree) so RSS feeds work even without feedparser.
        """
        if feeds is None:
            feeds = list(self.feeds.keys())

        cutoff_time = datetime.now(UTC) - timedelta(hours=hours_back)
        all_articles = []

        for feed_name in feeds:
            if feed_name not in self.feeds:
                self.logger.warning("Feed '%s' not found", feed_name)
                continue

            feed_url = self.feeds[feed_name]
            try:
                if _FEEDPARSER_AVAILABLE:
                    # ── feedparser path ───────────────────────────────────────
                    feed = feedparser.parse(feed_url)
                    for entry in feed.entries:
                        try:
                            article = self.format_article(entry, feed_name)
                            if article.published_at >= cutoff_time:
                                all_articles.append(article)
                        except Exception as e:
                            self.logger.warning("Error formatting RSS entry: %s", e)
                else:
                    # ── stdlib XML fallback path ──────────────────────────────
                    resp = requests.get(feed_url, timeout=8, headers={"User-Agent": "HopeFX/1.0 (+https://hopefx.ai)"})
                    resp.raise_for_status()
                    entries = _parse_rss_feed(resp.content, feed_name)
                    for entry in entries:
                        try:
                            pub = _parse_date(entry.get("published"))
                            if pub.tzinfo is None:
                                pub = pub.replace(tzinfo=UTC)
                            if pub < cutoff_time:
                                continue
                            all_articles.append(
                                NewsArticle(
                                    title=entry.get("title", ""),
                                    description=entry.get("summary", ""),
                                    source=entry.get("source", feed_name),
                                    published_at=pub,
                                    url=entry.get("link", ""),
                                    author=entry.get("author") or None,
                                )
                            )
                        except Exception as e:
                            self.logger.warning("Error formatting XML entry from %s: %s", feed_name, e)

                self.logger.info("Retrieved articles from %s", feed_name)

            except Exception as e:
                self.logger.debug("Error parsing RSS feed %s: %s", feed_name, e)
                continue

        self.logger.info("Retrieved %s articles from RSS feeds", len(all_articles))

        return all_articles

    def format_article(self, raw_article: Any, source: str = "", **kwargs) -> NewsArticle:
        entry = raw_article
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
                self.logger.error("Error fetching from %s: %s", provider.__class__.__name__, e)

                continue

        if deduplicate:
            all_articles = self._deduplicate(all_articles)

        # Sort by published date (newest first)
        all_articles.sort(key=lambda x: x.published_at, reverse=True)

        self.logger.info("Aggregated %s unique articles", len(all_articles))

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
