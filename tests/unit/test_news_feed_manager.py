# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_news_feed_manager.py
====================================
`/api/news-feed/*` has always returned an empty list.

`api/news_feed.py::_get_news_manager` did:

    from data_layer.feeds.news.base import NewsFeedManager
    mgr = NewsFeedManager()

`data_layer/feeds/news/base.py` defines `NewsFeedBase`, an abstract class whose
one abstract method is `fetch_articles`. There is no manager in it, and no
`NewsFeedManager` anywhere in the repository. The import raised on every call,
the handler logged "News manager init failed" at WARNING and returned `None`,
and all three endpoints then skipped their `if mgr:` block entirely:

    articles = []
    if mgr:
        ...
    return {"articles": articles[:limit], "total": len(articles)}

There is no fallback path — the response is `{"articles": [], "total": 0}`
regardless of what the five configured feed adapters could have returned.

The five adapters all exist and all implement `fetch_articles(limit)`:
`FinnhubFeed`, `FMPFeed`, `NewsDataFeed`, `AlphaVantageNewsFeed`,
`NewsAPIFeed`. What was missing is the thing that fans out across them,
merges the results and hands the API the shape it reads.

`data_layer/feeds/news/manager.py` is that. Note what it must translate: the
adapters return `NewsArticle` dataclasses (`article_id`, `headline`,
`sentiment_label`, `impact_score`, …) while the endpoints read dictionaries
with different key names (`id`, `title`, `sentiment`, `impact`, …). That
mapping is the manager's job, and getting it wrong would produce articles whose
fields are all silently empty — the same class of failure as the original bug.

Feeds with no API key are skipped rather than failed: "no key configured" is a
deployment state and should read as an empty feed, not an error.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

UTC = timezone.utc


def _article(article_id: str, headline: str, minutes_ago: int = 0, **overrides):
    from data_layer.types import NewsArticle, NewsSource

    now = datetime.now(UTC)
    kwargs = {
        "article_id": article_id,
        "source": NewsSource.FINNHUB,
        "headline": headline,
        "summary": f"summary of {headline}",
        "url": f"https://example.test/{article_id}",
        "published_at": now - timedelta(minutes=minutes_ago),
        "fetched_at": now,
        "sentiment_score": 0.0,
        "sentiment_label": "neutral",
        "gold_relevance": 0.9,
        "impact_score": 0.1,
    }
    kwargs.update(overrides)
    return NewsArticle(**kwargs)


class _StubFeed:
    """A feed adapter with the real NewsFeedBase surface."""

    def __init__(self, articles, configured=True, raises=False):
        self._articles = articles
        self._configured = configured
        self._raises = raises
        self.closed = False
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    async def fetch_articles(self, limit: int = 50):
        self.calls += 1
        if self._raises:
            raise RuntimeError("upstream 503")
        return self._articles[:limit]

    async def close(self) -> None:
        self.closed = True


class TestTheManagerExists:
    def test_it_is_importable(self):
        from data_layer.feeds.news.manager import NewsFeedManager

        assert NewsFeedManager is not None

    def test_it_is_exported_from_the_package(self):
        import data_layer.feeds.news as pkg

        assert "NewsFeedManager" in pkg.__all__
        assert getattr(pkg, "NewsFeedManager", None) is not None

    def test_the_endpoint_no_longer_imports_it_from_base(self):
        import inspect

        from api.news_feed import _get_news_manager

        source = inspect.getsource(_get_news_manager)
        assert "from data_layer.feeds.news.base import NewsFeedManager" not in source
        assert "NewsFeedManager" in source


class TestGetLatest:
    def test_it_returns_the_dict_shape_the_endpoints_read(self):
        from data_layer.feeds.news.manager import NewsFeedManager

        mgr = NewsFeedManager(feeds=[_StubFeed([_article("a1", "Gold rallies")])])
        articles = asyncio.run(mgr.get_latest(limit=10))

        assert len(articles) == 1
        got = articles[0]
        # Exactly the keys api/news_feed.py reads off each article.
        for key in ("id", "title", "source", "published_at", "url", "sentiment", "impact", "symbols", "summary"):
            assert key in got, f"endpoint reads {key!r} and the manager did not supply it"

    def test_it_maps_dataclass_fields_onto_the_endpoint_names(self):
        """article_id->id, headline->title, sentiment_label->sentiment."""
        from data_layer.feeds.news.manager import NewsFeedManager

        mgr = NewsFeedManager(feeds=[_StubFeed([_article("a1", "Gold rallies", sentiment_label="bullish")])])
        got = asyncio.run(mgr.get_latest(limit=10))[0]

        assert got["id"] == "a1"
        assert got["title"] == "Gold rallies"
        assert got["sentiment"] == "bullish"
        assert got["summary"] == "summary of Gold rallies"
        assert got["url"].endswith("/a1")
        assert got["published_at"], "published_at must be serialisable, not empty"

    def test_impact_score_is_bucketed_for_the_impact_filter(self):
        """The endpoint filters on impact == 'low'|'medium'|'high'."""
        from data_layer.feeds.news.manager import NewsFeedManager

        feed = _StubFeed(
            [
                _article("low", "Minor note", impact_score=0.1),
                _article("med", "Notable", impact_score=0.5),
                _article("high", "Major", impact_score=0.9),
            ]
        )
        got = {a["id"]: a["impact"] for a in asyncio.run(NewsFeedManager(feeds=[feed]).get_latest(limit=10))}

        assert got["low"] == "low"
        assert got["med"] == "medium"
        assert got["high"] == "high"

    def test_results_are_newest_first(self):
        from data_layer.feeds.news.manager import NewsFeedManager

        feed = _StubFeed(
            [
                _article("old", "Older", minutes_ago=120),
                _article("new", "Newer", minutes_ago=1),
                _article("mid", "Middle", minutes_ago=30),
            ]
        )
        ids = [a["id"] for a in asyncio.run(NewsFeedManager(feeds=[feed]).get_latest(limit=10))]

        assert ids == ["new", "mid", "old"]

    def test_the_limit_is_respected(self):
        from data_layer.feeds.news.manager import NewsFeedManager

        feed = _StubFeed([_article(f"a{i}", f"Story {i}", minutes_ago=i) for i in range(20)])
        got = asyncio.run(NewsFeedManager(feeds=[feed]).get_latest(limit=5))

        assert len(got) == 5

    def test_duplicate_articles_across_feeds_are_merged(self):
        """Two providers carrying the same wire story must not double-count."""
        from data_layer.feeds.news.manager import NewsFeedManager

        shared = _article("wire-1", "Fed holds rates")
        mgr = NewsFeedManager(feeds=[_StubFeed([shared]), _StubFeed([shared])])
        got = asyncio.run(mgr.get_latest(limit=10))

        assert len(got) == 1


class TestDegradation:
    def test_unconfigured_feeds_are_skipped_not_called(self):
        """No API key is a deployment state, not an error."""
        from data_layer.feeds.news.manager import NewsFeedManager

        unconfigured = _StubFeed([_article("x", "Never returned")], configured=False)
        configured = _StubFeed([_article("a1", "Real story")])

        got = asyncio.run(NewsFeedManager(feeds=[unconfigured, configured]).get_latest(limit=10))

        assert unconfigured.calls == 0
        assert [a["id"] for a in got] == ["a1"]

    def test_one_failing_feed_does_not_lose_the_others(self):
        from data_layer.feeds.news.manager import NewsFeedManager

        mgr = NewsFeedManager(feeds=[_StubFeed([], raises=True), _StubFeed([_article("a1", "Survivor")])])
        got = asyncio.run(mgr.get_latest(limit=10))

        assert [a["id"] for a in got] == ["a1"]

    def test_no_feeds_at_all_returns_empty_without_raising(self):
        from data_layer.feeds.news.manager import NewsFeedManager

        assert asyncio.run(NewsFeedManager(feeds=[]).get_latest(limit=10)) == []

    def test_every_feed_failing_returns_empty_without_raising(self):
        from data_layer.feeds.news.manager import NewsFeedManager

        mgr = NewsFeedManager(feeds=[_StubFeed([], raises=True), _StubFeed([], raises=True)])
        assert asyncio.run(mgr.get_latest(limit=10)) == []

    def test_close_releases_every_feed(self):
        from data_layer.feeds.news.manager import NewsFeedManager

        feeds = [_StubFeed([]), _StubFeed([])]
        asyncio.run(NewsFeedManager(feeds=feeds).close())

        assert all(f.closed for f in feeds)


class TestDefaultConstruction:
    def test_it_builds_its_own_feeds_when_none_are_supplied(self):
        """The endpoint constructs it with no arguments."""
        from data_layer.feeds.news.manager import NewsFeedManager

        mgr = NewsFeedManager()
        assert isinstance(mgr.feeds, list)

    def test_it_does_not_raise_with_no_api_keys_configured(self):
        """The state this repository is actually in — must degrade, not crash."""
        from data_layer.feeds.news.manager import NewsFeedManager

        assert asyncio.run(NewsFeedManager().get_latest(limit=5)) is not None
