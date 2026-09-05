# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_news_providers.py
=================================
`news/providers.py` was 276 statements at 47.78 %.

This is the ingestion edge: four third-party sources, each with its own date
encoding, its own error shape, and its own way of returning garbage. The
module's whole design is that any one of them can fail without taking the
others down — every `get_news` swallows its exceptions and returns `[]`. That
contract was almost entirely unverified, which is the worst combination: code
whose only job is to be robust, and no test that it is.

The stdlib RSS parser is the part most worth pinning. It exists so the platform
does not need `feedparser`, and it has to handle RSS 2.0, Atom, Dublin Core
date/creator elements, and malformed XML — by hand, with `ElementTree`. Nothing
exercised the Atom branch at all.

No test here touches the network: `requests.get` and `feedparser.parse` are
both substituted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import news.providers as providers_mod
from news.providers import (
    AlphaVantageNewsProvider,
    MultiSourceAggregator,
    NewsAPIProvider,
    NewsArticle,
    RSSFeedProvider,
    _as_utc,
    _parse_date,
    _parse_rss_feed,
    _xml_text,
    initialize_aggregator,
)

pytestmark = pytest.mark.unit

UTC = timezone.utc


def _article(title="Gold rallies", when=None, source="test"):
    return NewsArticle(
        title=title,
        description="d",
        source=source,
        published_at=when or datetime.now(UTC),
        url="https://example.test/1",
    )


def _response(payload=None, content=b"", status_ok=True):
    resp = MagicMock()
    resp.json.return_value = payload if payload is not None else {}
    resp.content = content
    if not status_ok:
        import requests

        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    return resp


# ── date handling ─────────────────────────────────────────────────────────────


class TestParseDate:
    def test_an_empty_value_falls_back_to_now(self):
        assert (datetime.now(UTC) - _parse_date(None)).total_seconds() < 5

    def test_an_rfc_2822_date_is_parsed(self):
        parsed = _parse_date("Tue, 01 Dec 2026 13:30:00 +0000")

        assert (parsed.year, parsed.month, parsed.day) == (2026, 12, 1)
        assert parsed.tzinfo is not None

    def test_an_iso_date_with_a_zone_is_parsed(self):
        parsed = _parse_date("2026-12-01T13:30:00+0000")

        assert parsed.year == 2026

    def test_a_bare_date_is_parsed_as_utc(self):
        parsed = _parse_date("2026-12-01")

        assert parsed.tzinfo is not None
        assert parsed.year == 2026

    def test_unparseable_text_falls_back_to_now_rather_than_raising(self):
        """A malformed pubDate from one feed must not abort the fetch."""
        assert (datetime.now(UTC) - _parse_date("last Tuesday-ish")).total_seconds() < 5

    def test_the_result_is_always_timezone_aware(self):
        for text in (None, "", "2026-12-01", "Tue, 01 Dec 2026 13:30:00 +0000", "nonsense"):
            assert _parse_date(text).tzinfo is not None


class TestAsUtc:
    def test_none_becomes_now(self):
        assert (datetime.now(UTC) - _as_utc(None)).total_seconds() < 5

    def test_a_naive_datetime_is_labelled_utc(self):
        """feedparser yields naive datetimes; comparing them to aware cutoffs raises."""
        result = _as_utc(datetime(2026, 12, 1, 13, 30))

        assert result.tzinfo is not None
        assert result.hour == 13

    def test_an_aware_datetime_is_converted_not_relabelled(self):
        other = timezone(timedelta(hours=5))
        result = _as_utc(datetime(2026, 12, 1, 13, 30, tzinfo=other))

        assert result.hour == 8

    def test_an_already_utc_datetime_is_unchanged(self):
        original = datetime(2026, 12, 1, 13, 30, tzinfo=UTC)

        assert _as_utc(original) == original


class TestXmlText:
    def test_a_missing_element_is_the_empty_string(self):
        assert _xml_text(None) == ""

    def test_text_is_stripped(self):
        import xml.etree.ElementTree as ET

        assert _xml_text(ET.fromstring("<t>  hi  </t>")) == "hi"  # noqa: S314 - literal test input

    def test_an_empty_element_is_the_empty_string(self):
        import xml.etree.ElementTree as ET

        assert _xml_text(ET.fromstring("<t/>")) == ""  # noqa: S314 - literal test input


# ── the hand-rolled feed parser ───────────────────────────────────────────────


_RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Feed</title>
    <item>
      <title>Gold hits record</title>
      <description>Bullion rallies.</description>
      <link>https://example.test/gold</link>
      <pubDate>Tue, 01 Dec 2026 13:30:00 +0000</pubDate>
      <author>A Reporter</author>
    </item>
    <item>
      <title>Second story</title>
      <description>More.</description>
      <link>https://example.test/two</link>
      <dc:date>2026-12-01T14:00:00Z</dc:date>
      <dc:creator>DC Reporter</dc:creator>
    </item>
  </channel>
</rss>"""

_ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Atom story</title>
    <summary>Summary text.</summary>
    <link href="https://example.test/atom"/>
    <updated>2026-12-01T13:30:00Z</updated>
    <author><name>Atom Author</name></author>
  </entry>
</feed>"""


class TestParseRssFeed:
    def test_rss_items_are_extracted(self):
        entries = _parse_rss_feed(_RSS, "src")

        assert len(entries) == 2
        assert entries[0]["title"] == "Gold hits record"
        assert entries[0]["link"] == "https://example.test/gold"
        assert entries[0]["source"] == "src"

    def test_an_rss_author_element_is_read(self):
        assert _parse_rss_feed(_RSS, "src")[0]["author"] == "A Reporter"

    def test_a_dublin_core_date_is_read_when_pubdate_is_absent(self):
        assert _parse_rss_feed(_RSS, "src")[1]["published"] == "2026-12-01T14:00:00Z"

    def test_a_dublin_core_creator_is_read(self):
        assert _parse_rss_feed(_RSS, "src")[1]["author"] == "DC Reporter"

    def test_atom_entries_are_extracted(self):
        """The Atom branch was entirely unreached."""
        entries = _parse_rss_feed(_ATOM, "src")

        assert len(entries) == 1
        assert entries[0]["title"] == "Atom story"
        assert entries[0]["summary"] == "Summary text."

    def test_an_atom_link_is_read_from_its_href_attribute(self):
        assert _parse_rss_feed(_ATOM, "src")[0]["link"] == "https://example.test/atom"

    def test_an_atom_author_name_is_read_from_the_nested_element(self):
        assert _parse_rss_feed(_ATOM, "src")[0]["author"] == "Atom Author"

    def test_malformed_xml_is_an_empty_list_not_an_exception(self):
        assert _parse_rss_feed(b"<rss><channel><item>", "src") == []

    def test_empty_bytes_are_an_empty_list(self):
        assert _parse_rss_feed(b"", "src") == []

    def test_a_feed_with_no_items_is_an_empty_list(self):
        assert _parse_rss_feed(b'<rss version="2.0"><channel><title>x</title></channel></rss>', "src") == []


# ── the article record ────────────────────────────────────────────────────────


class TestNewsArticle:
    def test_to_dict_iso_formats_the_timestamp(self):
        payload = _article(when=datetime(2026, 12, 1, 13, 30, tzinfo=UTC)).to_dict()

        assert payload["published_at"] == "2026-12-01T13:30:00+00:00"

    def test_optional_fields_default_to_none(self):
        payload = _article().to_dict()

        assert payload["author"] is None
        assert payload["symbols"] is None
        assert payload["sentiment"] is None


# ── NewsAPI ───────────────────────────────────────────────────────────────────


_NEWSAPI_ARTICLE = {
    "title": "Gold up",
    "description": "Bullion rallies",
    "source": {"name": "Reuters"},
    "publishedAt": "2026-12-01T13:30:00+00:00",
    "url": "https://example.test/g",
    "author": "A Reporter",
    "content": "body",
}


class TestNewsApiProvider:
    def test_it_refuses_to_construct_without_a_key(self):
        with pytest.raises(ValueError, match="requires an API key"):
            NewsAPIProvider("")

    def test_a_successful_fetch_returns_articles(self):
        payload = {"status": "ok", "articles": [_NEWSAPI_ARTICLE]}

        with patch.object(providers_mod.requests, "get", return_value=_response(payload)):
            articles = NewsAPIProvider("k").get_news()

        assert len(articles) == 1
        assert articles[0].title == "Gold up"
        assert articles[0].source == "Reuters"

    def test_the_key_and_query_reach_the_request(self):
        getter = MagicMock(return_value=_response({"status": "ok", "articles": []}))

        with patch.object(providers_mod.requests, "get", getter):
            NewsAPIProvider("placeholder-key").get_news(query="gold")

        params = getter.call_args.kwargs["params"]
        assert params["q"] == "gold"
        assert params["apiKey"] == "placeholder-key"  # pragma: allowlist secret

    def test_the_page_size_is_capped_at_the_api_maximum(self):
        getter = MagicMock(return_value=_response({"status": "ok", "articles": []}))

        with patch.object(providers_mod.requests, "get", getter):
            NewsAPIProvider("k").get_news(page_size=500)

        assert getter.call_args.kwargs["params"]["pageSize"] == 100

    def test_a_non_ok_status_yields_an_empty_list(self):
        payload = {"status": "error", "message": "rate limited"}

        with patch.object(providers_mod.requests, "get", return_value=_response(payload)):
            assert NewsAPIProvider("k").get_news() == []

    def test_a_request_exception_yields_an_empty_list(self):
        import requests

        with patch.object(providers_mod.requests, "get", side_effect=requests.exceptions.Timeout("slow")):
            assert NewsAPIProvider("k").get_news() == []

    def test_an_unexpected_error_yields_an_empty_list(self):
        with patch.object(providers_mod.requests, "get", side_effect=RuntimeError("weird")):
            assert NewsAPIProvider("k").get_news() == []

    def test_one_unformattable_article_does_not_drop_the_others(self):
        payload = {"status": "ok", "articles": [{"publishedAt": "garbage"}, _NEWSAPI_ARTICLE]}

        with patch.object(providers_mod.requests, "get", return_value=_response(payload)):
            articles = NewsAPIProvider("k").get_news()

        assert [a.title for a in articles] == ["Gold up"]

    def test_an_article_with_no_source_name_is_labelled_unknown(self):
        payload = {"status": "ok", "articles": [{**_NEWSAPI_ARTICLE, "source": {}}]}

        with patch.object(providers_mod.requests, "get", return_value=_response(payload)):
            assert NewsAPIProvider("k").get_news()[0].source == "Unknown"


# ── Alpha Vantage ─────────────────────────────────────────────────────────────


_AV_ITEM = {
    "title": "Gold outlook",
    "summary": "Analysts see upside",
    "source": "AlphaVantage",
    "time_published": "20261201T133000",
    "url": "https://example.test/av",
    "authors": ["First Author", "Second Author"],
    "overall_sentiment_score": "0.35",
    "ticker_sentiment": [{"ticker": "GLD"}, {"ticker": "GC"}],
}


class TestAlphaVantageProvider:
    def test_it_refuses_to_construct_without_a_key(self):
        with pytest.raises(ValueError, match="requires an API key"):
            AlphaVantageNewsProvider("")

    def test_a_successful_fetch_parses_the_feed(self):
        with patch.object(providers_mod.requests, "get", return_value=_response({"feed": [_AV_ITEM]})):
            articles = AlphaVantageNewsProvider("k").get_news()

        assert len(articles) == 1
        assert articles[0].title == "Gold outlook"

    def test_the_compact_timestamp_format_is_parsed(self):
        with patch.object(providers_mod.requests, "get", return_value=_response({"feed": [_AV_ITEM]})):
            published = AlphaVantageNewsProvider("k").get_news()[0].published_at

        assert (published.year, published.month, published.day, published.hour) == (2026, 12, 1, 13)

    def test_the_sentiment_score_is_coerced_to_a_float(self):
        with patch.object(providers_mod.requests, "get", return_value=_response({"feed": [_AV_ITEM]})):
            assert AlphaVantageNewsProvider("k").get_news()[0].sentiment == pytest.approx(0.35)

    def test_ticker_sentiment_becomes_the_symbol_list(self):
        with patch.object(providers_mod.requests, "get", return_value=_response({"feed": [_AV_ITEM]})):
            assert AlphaVantageNewsProvider("k").get_news()[0].symbols == ["GLD", "GC"]

    def test_no_tickers_means_no_symbols_rather_than_an_empty_list(self):
        item = {**_AV_ITEM, "ticker_sentiment": []}

        with patch.object(providers_mod.requests, "get", return_value=_response({"feed": [item]})):
            assert AlphaVantageNewsProvider("k").get_news()[0].symbols is None

    def test_multiple_authors_are_joined(self):
        with patch.object(providers_mod.requests, "get", return_value=_response({"feed": [_AV_ITEM]})):
            assert AlphaVantageNewsProvider("k").get_news()[0].author == "First Author, Second Author"

    def test_tickers_reach_the_request_when_given(self):
        getter = MagicMock(return_value=_response({"feed": []}))

        with patch.object(providers_mod.requests, "get", getter):
            AlphaVantageNewsProvider("k").get_news(tickers="GLD,GC")

        assert getter.call_args.kwargs["params"]["tickers"] == "GLD,GC"

    def test_no_tickers_omits_the_parameter(self):
        getter = MagicMock(return_value=_response({"feed": []}))

        with patch.object(providers_mod.requests, "get", getter):
            AlphaVantageNewsProvider("k").get_news()

        assert "tickers" not in getter.call_args.kwargs["params"]

    def test_an_api_error_message_yields_an_empty_list(self):
        payload = {"Error Message": "invalid api call"}

        with patch.object(providers_mod.requests, "get", return_value=_response(payload)):
            assert AlphaVantageNewsProvider("k").get_news() == []

    def test_a_request_exception_yields_an_empty_list(self):
        import requests

        with patch.object(providers_mod.requests, "get", side_effect=requests.exceptions.ConnectionError("down")):
            assert AlphaVantageNewsProvider("k").get_news() == []

    def test_an_unexpected_error_yields_an_empty_list(self):
        with patch.object(providers_mod.requests, "get", side_effect=RuntimeError("weird")):
            assert AlphaVantageNewsProvider("k").get_news() == []

    def test_one_bad_item_does_not_drop_the_good_ones(self):
        payload = {"feed": [{"time_published": "not-a-time"}, _AV_ITEM]}

        with patch.object(providers_mod.requests, "get", return_value=_response(payload)):
            assert [a.title for a in AlphaVantageNewsProvider("k").get_news()] == ["Gold outlook"]


# ── RSS ───────────────────────────────────────────────────────────────────────


class TestRssFeedProvider:
    def test_it_starts_from_the_default_feed_set(self):
        assert set(RSSFeedProvider().feeds) == set(RSSFeedProvider.DEFAULT_FEEDS)

    def test_a_feed_url_can_be_overridden_by_environment(self, monkeypatch):
        monkeypatch.setenv("RSS_FEED_REUTERS_BUSINESS", "https://mirror.test/rss")

        assert RSSFeedProvider().feeds["reuters_business"] == "https://mirror.test/rss"

    def test_an_empty_override_is_ignored(self, monkeypatch):
        monkeypatch.setenv("RSS_FEED_REUTERS_BUSINESS", "")

        assert RSSFeedProvider().feeds["reuters_business"] == RSSFeedProvider.DEFAULT_FEEDS["reuters_business"]

    def test_an_extra_feed_can_be_added_by_environment(self, monkeypatch):
        monkeypatch.setenv("RSS_FEED_EXTRA_MYWIRE", "https://mywire.test/rss")

        assert RSSFeedProvider().feeds["mywire"] == "https://mywire.test/rss"

    def test_the_default_set_is_not_mutated_by_an_override(self, monkeypatch):
        """The class attribute is shared; overriding must copy, not write through."""
        monkeypatch.setenv("RSS_FEED_EXTRA_TEMP", "https://temp.test/rss")
        RSSFeedProvider()

        assert "temp" not in RSSFeedProvider.DEFAULT_FEEDS

    def test_a_feed_can_be_added_at_runtime(self):
        provider = RSSFeedProvider()
        provider.add_feed("custom", "https://custom.test/rss")

        assert provider.feeds["custom"] == "https://custom.test/rss"

    def test_an_unknown_feed_name_is_skipped(self):
        assert RSSFeedProvider().get_news(feeds=["nope"]) == []

    def test_the_stdlib_path_parses_a_live_looking_feed(self, monkeypatch):
        monkeypatch.setattr(providers_mod, "_FEEDPARSER_AVAILABLE", False)
        recent = f"{datetime.now(UTC).strftime('%a, %d %b %Y %H:%M:%S')} +0000"
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><item>'
            b"<title>Fresh</title><description>d</description>"
            b"<link>https://example.test/f</link><pubDate>" + recent.encode() + b"</pubDate>"
            b"</item></channel></rss>"
        )
        provider = RSSFeedProvider()
        provider.feeds = {"one": "https://example.test/rss"}

        with patch.object(providers_mod.requests, "get", return_value=_response(content=xml)):
            articles = provider.get_news()

        assert [a.title for a in articles] == ["Fresh"]

    def test_the_stdlib_path_drops_entries_older_than_the_cutoff(self, monkeypatch):
        monkeypatch.setattr(providers_mod, "_FEEDPARSER_AVAILABLE", False)
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><item>'
            b"<title>Stale</title><link>https://example.test/s</link>"
            b"<pubDate>Tue, 01 Jan 2019 13:30:00 +0000</pubDate>"
            b"</item></channel></rss>"
        )
        provider = RSSFeedProvider()
        provider.feeds = {"one": "https://example.test/rss"}

        with patch.object(providers_mod.requests, "get", return_value=_response(content=xml)):
            assert provider.get_news(hours_back=24) == []

    def test_a_failing_feed_does_not_stop_the_others(self, monkeypatch):
        """The whole point of trying feeds in order."""
        monkeypatch.setattr(providers_mod, "_FEEDPARSER_AVAILABLE", False)
        recent = f"{datetime.now(UTC).strftime('%a, %d %b %Y %H:%M:%S')} +0000"
        good = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><item>'
            b"<title>Good</title><link>https://example.test/g</link>"
            b"<pubDate>" + recent.encode() + b"</pubDate></item></channel></rss>"
        )
        provider = RSSFeedProvider()
        provider.feeds = {"broken": "https://broken.test/rss", "good": "https://good.test/rss"}

        def _get(url, **kwargs):
            if url == provider.feeds["broken"]:
                raise RuntimeError("feed down")
            return _response(content=good)

        with patch.object(providers_mod.requests, "get", side_effect=_get):
            assert [a.title for a in provider.get_news()] == ["Good"]

    def test_the_feedparser_path_is_used_when_available(self, monkeypatch):
        monkeypatch.setattr(providers_mod, "_FEEDPARSER_AVAILABLE", True)
        now = datetime.now(UTC)
        entry = {
            "title": "Parsed",
            "summary": "s",
            "link": "https://example.test/p",
            "author": "R",
        }
        entry_obj = SimpleNamespace(
            **entry,
            published_parsed=now.timetuple(),
            get=entry.get,
        )
        fake_feedparser = MagicMock()
        fake_feedparser.parse.return_value = SimpleNamespace(entries=[entry_obj])
        monkeypatch.setattr(providers_mod, "feedparser", fake_feedparser, raising=False)

        provider = RSSFeedProvider()
        provider.feeds = {"one": "https://example.test/rss"}

        assert [a.title for a in provider.get_news()] == ["Parsed"]

    def test_format_article_falls_back_to_now_without_a_parsed_date(self):
        entry = {"title": "T", "summary": "s", "link": "u", "author": None}
        entry_obj = SimpleNamespace(**entry, get=entry.get)

        article = RSSFeedProvider().format_article(entry_obj, "src")

        assert article.source == "src"
        assert (datetime.now(UTC) - _as_utc(article.published_at)).total_seconds() < 5

    def test_format_article_prefers_updated_when_published_is_absent(self):
        entry = {"title": "T", "summary": "s", "link": "u", "author": None}
        entry_obj = SimpleNamespace(
            **entry,
            published_parsed=None,
            updated_parsed=datetime(2026, 12, 1, 13, 30).timetuple(),
            get=entry.get,
        )

        article = RSSFeedProvider().format_article(entry_obj, "src")

        assert (article.published_at.year, article.published_at.hour) == (2026, 13)


# ── aggregation ───────────────────────────────────────────────────────────────


class TestMultiSourceAggregator:
    def test_rss_is_the_only_provider_by_default(self):
        aggregator = MultiSourceAggregator()

        assert len(aggregator.providers) == 1
        assert isinstance(aggregator.providers[0], RSSFeedProvider)

    def test_rss_can_be_switched_off(self):
        assert MultiSourceAggregator(use_rss=False).providers == []

    def test_keys_add_their_providers(self):
        aggregator = MultiSourceAggregator(newsapi_key="a", alphavantage_key="b", use_rss=False)

        assert [type(p) for p in aggregator.providers] == [NewsAPIProvider, AlphaVantageNewsProvider]

    def test_it_collects_from_every_configured_provider(self):
        aggregator = MultiSourceAggregator(newsapi_key="a", use_rss=True)
        aggregator.providers[0].get_news = MagicMock(return_value=[_article("From NewsAPI")])
        aggregator.providers[1].get_news = MagicMock(return_value=[_article("From RSS")])

        titles = {a.title for a in aggregator.get_aggregated_news(query="gold")}

        assert titles == {"From NewsAPI", "From RSS"}

    def test_a_provider_that_raises_does_not_lose_the_others(self):
        aggregator = MultiSourceAggregator(newsapi_key="a", use_rss=True)
        aggregator.providers[0].get_news = MagicMock(side_effect=RuntimeError("down"))
        aggregator.providers[1].get_news = MagicMock(return_value=[_article("Survivor")])

        assert [a.title for a in aggregator.get_aggregated_news(query="gold")] == ["Survivor"]

    def test_newsapi_is_skipped_without_a_query(self):
        aggregator = MultiSourceAggregator(newsapi_key="a", use_rss=False)
        aggregator.providers[0].get_news = MagicMock(return_value=[_article()])

        assert aggregator.get_aggregated_news() == []

    def test_alpha_vantage_is_skipped_without_symbols(self):
        aggregator = MultiSourceAggregator(alphavantage_key="b", use_rss=False)
        aggregator.providers[0].get_news = MagicMock(return_value=[_article()])

        assert aggregator.get_aggregated_news() == []

    def test_symbols_are_comma_joined_for_alpha_vantage(self):
        aggregator = MultiSourceAggregator(alphavantage_key="b", use_rss=False)
        aggregator.providers[0].get_news = MagicMock(return_value=[])

        aggregator.get_aggregated_news(symbols=["GLD", "GC"])

        assert aggregator.providers[0].get_news.call_args.kwargs["tickers"] == "GLD,GC"

    def test_duplicate_titles_are_collapsed(self):
        aggregator = MultiSourceAggregator(use_rss=True)
        aggregator.providers[0].get_news = MagicMock(
            return_value=[_article("Gold Rallies"), _article("  gold rallies  "), _article("Other")]
        )

        titles = [a.title for a in aggregator.get_aggregated_news()]

        assert len(titles) == 2

    def test_deduplication_can_be_switched_off(self):
        aggregator = MultiSourceAggregator(use_rss=True)
        aggregator.providers[0].get_news = MagicMock(return_value=[_article("Same"), _article("Same")])

        assert len(aggregator.get_aggregated_news(deduplicate=False)) == 2

    def test_results_come_back_newest_first(self):
        now = datetime.now(UTC)
        aggregator = MultiSourceAggregator(use_rss=True)
        aggregator.providers[0].get_news = MagicMock(
            return_value=[
                _article("old", now - timedelta(hours=5)),
                _article("new", now),
                _article("middle", now - timedelta(hours=2)),
            ]
        )

        assert [a.title for a in aggregator.get_aggregated_news()] == ["new", "middle", "old"]

    def test_naive_and_aware_timestamps_sort_together(self):
        """Mixing feedparser's naive datetimes with aware ones used to raise in sorted()."""
        now = datetime.now(UTC)
        aggregator = MultiSourceAggregator(use_rss=True)
        aggregator.providers[0].get_news = MagicMock(
            return_value=[
                _article("naive", (now - timedelta(hours=3)).replace(tzinfo=None)),
                _article("aware", now),
            ]
        )

        assert [a.title for a in aggregator.get_aggregated_news()] == ["aware", "naive"]


class TestInitializeAggregator:
    def test_it_publishes_the_module_level_instance(self):
        aggregator = initialize_aggregator(newsapi_key="a")

        assert providers_mod.news_aggregator is aggregator

    def test_it_wires_the_keys_through(self):
        aggregator = initialize_aggregator(newsapi_key="a", alphavantage_key="b")

        assert any(isinstance(p, NewsAPIProvider) for p in aggregator.providers)
        assert any(isinstance(p, AlphaVantageNewsProvider) for p in aggregator.providers)
