# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_news_router.py
==============================
`news/__init__.py` was 117 statements at 27.48 %: the imports ran, the router
factory did not.

Every one of the eight `/api/news/*` endpoints was unexercised, including the
error handlers — which matters more here than usual, because these handlers
are the deployment's only defence against a third-party outage becoming a 500.
Each geopolitical route wraps a bare `except Exception` that turns a provider
failure into an HTTP 500 with a *scrubbed* detail string, and the two sentiment
routes deliberately degrade to a neutral score instead. Nothing checked that
those two policies were applied to the routes they were meant for, or that the
scrubbed messages do not leak the upstream exception text.

The whole module was also invisible to the `news/` coverage gate in `ci.yml`,
because `.coveragerc` never listed `news` as a source.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import news as news_mod
from news import create_news_router

pytestmark = pytest.mark.unit

UTC = timezone.utc


def _client(**router_patches):
    app = FastAPI()
    router = create_news_router()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client():
    return _client()


def _provider(**attrs):
    """A geopolitical provider stub with only the attributes a test needs."""
    return SimpleNamespace(**attrs)


def _event(name="Conflict"):
    evt = MagicMock()
    evt.to_dict.return_value = {"name": name, "severity": "high"}
    return evt


# ── the factory itself ────────────────────────────────────────────────────────


class TestTheFactory:
    def test_it_builds_a_router_under_the_api_news_prefix(self):
        router = create_news_router()

        assert router is not None
        assert router.prefix == "/api/news"

    def test_it_registers_every_documented_endpoint(self):
        paths = {r.path for r in create_news_router().routes}

        assert paths == {
            "/api/news/geopolitical/signal",
            "/api/news/geopolitical/events",
            "/api/news/geopolitical/assessment",
            "/api/news/geopolitical/world-monitor",
            "/api/news/economic/upcoming",
            "/api/news/sentiment/{symbol}",
            "/api/news/latest",
            "/api/news/sentiment",
        }

    def test_without_fastapi_it_returns_none_rather_than_raising(self, monkeypatch):
        """The module is importable in non-API deployments; the factory must say so."""
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def _no_fastapi(name, *args, **kwargs):
            if name == "fastapi":
                raise ImportError("no fastapi here")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", _no_fastapi):
            assert create_news_router() is None


# ── /geopolitical/signal ──────────────────────────────────────────────────────


class TestGoldSignal:
    def test_it_returns_the_provider_s_signal(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_gold_trading_signal=AsyncMock(return_value={"direction": "buy", "confidence": 0.8})),
        )

        body = client.get("/api/news/geopolitical/signal").json()

        assert body["confidence"] == 0.8

    def test_the_direction_is_normalised_to_uppercase(self, client, monkeypatch):
        """The API contract promises uppercase; the provider does not."""
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_gold_trading_signal=AsyncMock(return_value={"direction": "sell"})),
        )

        assert client.get("/api/news/geopolitical/signal").json()["direction"] == "SELL"

    def test_a_non_string_direction_is_passed_through_untouched(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_gold_trading_signal=AsyncMock(return_value={"direction": None})),
        )

        assert client.get("/api/news/geopolitical/signal").json()["direction"] is None

    def test_normalising_does_not_mutate_the_provider_s_dict(self, client, monkeypatch):
        """It copies before writing — a shared cached dict must not be rewritten."""
        original = {"direction": "buy"}
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_gold_trading_signal=AsyncMock(return_value=original)),
        )

        client.get("/api/news/geopolitical/signal")

        assert original["direction"] == "buy"

    def test_a_provider_failure_is_a_500_that_leaks_nothing(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_gold_trading_signal=AsyncMock(side_effect=RuntimeError("api key sk-live-xyz bad"))),
        )

        resp = client.get("/api/news/geopolitical/signal")

        assert resp.status_code == 500
        assert "sk-live-xyz" not in resp.text
        assert "check server logs" in resp.json()["detail"]


# ── /geopolitical/events ──────────────────────────────────────────────────────


class TestGeopoliticalEvents:
    def test_events_are_serialised_and_counted(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_current_events=AsyncMock(return_value=[_event("A"), _event("B")])),
        )

        body = client.get("/api/news/geopolitical/events").json()

        assert body["count"] == 2
        assert [e["name"] for e in body["events"]] == ["A", "B"]

    def test_no_events_is_an_empty_list_not_an_error(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_current_events=AsyncMock(return_value=[])),
        )

        body = client.get("/api/news/geopolitical/events").json()

        assert body == {"events": [], "count": 0}

    def test_force_refresh_defaults_to_false(self, client, monkeypatch):
        fetch = AsyncMock(return_value=[])
        monkeypatch.setattr(news_mod, "_get_risk_provider", lambda: _provider(get_current_events=fetch))

        client.get("/api/news/geopolitical/events")

        assert fetch.await_args.kwargs["force_refresh"] is False

    def test_force_refresh_reaches_the_provider(self, client, monkeypatch):
        fetch = AsyncMock(return_value=[])
        monkeypatch.setattr(news_mod, "_get_risk_provider", lambda: _provider(get_current_events=fetch))

        client.get("/api/news/geopolitical/events?force_refresh=true")

        assert fetch.await_args.kwargs["force_refresh"] is True

    def test_a_failure_is_a_scrubbed_500(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_current_events=AsyncMock(side_effect=OSError("upstream 502"))),
        )

        resp = client.get("/api/news/geopolitical/events")

        assert resp.status_code == 500
        assert "upstream 502" not in resp.text


# ── /geopolitical/assessment ──────────────────────────────────────────────────


class TestRiskAssessment:
    def test_the_assessment_is_returned_as_a_dict(self, client, monkeypatch):
        assessment = MagicMock()
        assessment.to_dict.return_value = {"global_risk_score": 0.42, "gold_outlook": "bullish"}
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_risk_assessment=AsyncMock(return_value=assessment)),
        )

        body = client.get("/api/news/geopolitical/assessment").json()

        assert body["global_risk_score"] == 0.42
        assert body["gold_outlook"] == "bullish"

    def test_a_failure_is_a_scrubbed_500(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_risk_assessment=AsyncMock(side_effect=ValueError("boom"))),
        )

        resp = client.get("/api/news/geopolitical/assessment")

        assert resp.status_code == 500
        assert "Assessment unavailable" in resp.json()["detail"]


# ── /geopolitical/world-monitor ───────────────────────────────────────────────


class TestWorldMonitorUrls:
    def test_it_returns_the_enhanced_view_suite(self, client, monkeypatch):
        integration = MagicMock()
        integration.get_enhanced_views.return_value = {"gold_regions": "https://worldmonitor.app/x"}
        monkeypatch.setattr(news_mod, "WorldMonitorIntegration", lambda: integration)

        body = client.get("/api/news/geopolitical/world-monitor").json()

        assert body["gold_regions"].startswith("https://worldmonitor.app")

    def test_a_failure_is_a_scrubbed_500(self, client, monkeypatch):
        def _boom():
            raise RuntimeError("integration down")

        monkeypatch.setattr(news_mod, "WorldMonitorIntegration", _boom)

        resp = client.get("/api/news/geopolitical/world-monitor")

        assert resp.status_code == 500
        assert "integration down" not in resp.text


# ── /economic/upcoming ────────────────────────────────────────────────────────


def _econ_event(hours_from_now, title="CPI", naive=False, importance="high"):
    when = datetime.now(UTC) + timedelta(hours=hours_from_now)
    if naive:
        when = when.replace(tzinfo=None)
    return SimpleNamespace(
        title=title,
        scheduled_time=when,
        country="US",
        importance=SimpleNamespace(value=importance),
        forecast="2.1%",
        previous="2.0%",
    )


class TestUpcomingEconomicEvents:
    def _with_events(self, monkeypatch, events):
        calendar = MagicMock()
        calendar.get_upcoming_events.return_value = events
        monkeypatch.setattr(news_mod, "EconomicCalendar", lambda: calendar)

    def test_an_event_inside_the_window_is_returned(self, client, monkeypatch):
        self._with_events(monkeypatch, [_econ_event(2)])

        body = client.get("/api/news/economic/upcoming").json()

        assert body["count"] == 1
        assert body["events"][0]["title"] == "CPI"
        assert body["events"][0]["country"] == "US"
        assert body["events"][0]["importance"] == "high"

    def test_an_event_beyond_the_window_is_excluded(self, client, monkeypatch):
        self._with_events(monkeypatch, [_econ_event(48)])

        assert client.get("/api/news/economic/upcoming").json()["count"] == 0

    def test_a_past_event_is_excluded(self, client, monkeypatch):
        self._with_events(monkeypatch, [_econ_event(-2)])

        assert client.get("/api/news/economic/upcoming").json()["count"] == 0

    def test_a_naive_timestamp_is_treated_as_utc_rather_than_crashing(self, client, monkeypatch):
        """Comparing naive and aware datetimes raises; the handler must not."""
        self._with_events(monkeypatch, [_econ_event(2, naive=True)])

        body = client.get("/api/news/economic/upcoming").json()

        assert body["count"] == 1

    def test_a_wider_window_admits_a_later_event(self, client, monkeypatch):
        self._with_events(monkeypatch, [_econ_event(48)])

        assert client.get("/api/news/economic/upcoming?hours_ahead=72").json()["count"] == 1

    def test_the_window_is_echoed_back(self, client, monkeypatch):
        self._with_events(monkeypatch, [])

        assert client.get("/api/news/economic/upcoming?hours_ahead=48").json()["hours_ahead"] == 48

    @pytest.mark.parametrize("hours", [0, 169, -1])
    def test_a_window_outside_one_to_one_sixty_eight_is_rejected(self, client, monkeypatch, hours):
        self._with_events(monkeypatch, [])

        assert client.get(f"/api/news/economic/upcoming?hours_ahead={hours}").status_code == 422

    def test_one_malformed_event_does_not_drop_the_rest(self, client, monkeypatch):
        broken = SimpleNamespace(title="bad", scheduled_time="not-a-datetime")
        self._with_events(monkeypatch, [broken, _econ_event(2)])

        body = client.get("/api/news/economic/upcoming").json()

        assert body["count"] == 1

    def test_an_importance_without_a_value_attribute_is_stringified(self, client, monkeypatch):
        evt = _econ_event(2)
        evt.importance = "CRITICAL"
        self._with_events(monkeypatch, [evt])

        assert client.get("/api/news/economic/upcoming").json()["events"][0]["importance"] == "CRITICAL"

    def test_a_calendar_failure_is_a_scrubbed_500(self, client, monkeypatch):
        def _boom():
            raise RuntimeError("calendar source down")

        monkeypatch.setattr(news_mod, "EconomicCalendar", _boom)

        resp = client.get("/api/news/economic/upcoming")

        assert resp.status_code == 500
        assert "calendar source down" not in resp.text


# ── /sentiment/{symbol} ───────────────────────────────────────────────────────


class TestSymbolSentiment:
    def _with_analyzer(self, monkeypatch, analyzer):
        monkeypatch.setattr(news_mod, "FinancialSentimentAnalyzer", lambda: analyzer)

    def test_a_score_object_is_unpacked(self, client, monkeypatch):
        analyzer = MagicMock()
        analyzer.analyze_batch.return_value = SimpleNamespace(score=0.6, label="bullish")
        self._with_analyzer(monkeypatch, analyzer)

        body = client.get("/api/news/sentiment/XAUUSD").json()

        assert body == {"symbol": "XAUUSD", "sentiment_score": 0.6, "label": "bullish"}

    def test_the_symbol_is_upper_cased(self, client, monkeypatch):
        analyzer = MagicMock()
        analyzer.analyze_batch.return_value = SimpleNamespace(score=0.0, label="neutral")
        self._with_analyzer(monkeypatch, analyzer)

        assert client.get("/api/news/sentiment/xauusd").json()["symbol"] == "XAUUSD"

    @pytest.mark.parametrize(
        ("symbol", "expected_term"),
        [("XAUUSD", "gold"), ("BTCUSD", "bitcoin"), ("EURUSD", "euro"), ("GBPUSD", "pound"), ("USDJPY", "yen")],
    )
    def test_known_symbols_map_to_search_terms(self, client, monkeypatch, symbol, expected_term):
        analyzer = MagicMock()
        analyzer.analyze_batch.return_value = SimpleNamespace(score=0.0, label="neutral")
        self._with_analyzer(monkeypatch, analyzer)

        client.get(f"/api/news/sentiment/{symbol}")

        assert expected_term in analyzer.analyze_batch.call_args.args[0]

    def test_an_unknown_symbol_searches_for_itself(self, client, monkeypatch):
        analyzer = MagicMock()
        analyzer.analyze_batch.return_value = SimpleNamespace(score=0.0, label="neutral")
        self._with_analyzer(monkeypatch, analyzer)

        client.get("/api/news/sentiment/ZZZUSD")

        assert analyzer.analyze_batch.call_args.args[0] == ["ZZZUSD"]

    @pytest.mark.parametrize(("raw", "label"), [(0.5, "bullish"), (-0.5, "bearish"), (0.0, "neutral")])
    def test_a_bare_float_score_gets_a_derived_label(self, client, monkeypatch, raw, label):
        analyzer = MagicMock()
        analyzer.analyze_batch.return_value = raw
        self._with_analyzer(monkeypatch, analyzer)

        body = client.get("/api/news/sentiment/XAUUSD").json()

        assert body["sentiment_score"] == pytest.approx(raw)
        assert body["label"] == label

    def test_a_missing_engine_degrades_to_neutral_rather_than_500(self, client, monkeypatch):
        """Sentiment is advisory. An unavailable model must not fail the request."""

        def _boom():
            raise ImportError("no textblob")

        monkeypatch.setattr(news_mod, "FinancialSentimentAnalyzer", _boom)

        resp = client.get("/api/news/sentiment/XAUUSD")

        assert resp.status_code == 200
        body = resp.json()
        assert body["sentiment_score"] == 0.0
        assert body["label"] == "neutral"
        assert "textblob" in body["note"]


# ── /latest ───────────────────────────────────────────────────────────────────


class TestLatestNews:
    def test_it_prefers_the_provider_s_own_accessor(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_recent_news=MagicMock(return_value=[{"headline": "gold up"}])),
        )

        body = client.get("/api/news/latest").json()

        assert body["total"] == 1
        assert body["articles"][0]["headline"] == "gold up"

    def test_it_falls_back_to_the_aggregator(self, client, monkeypatch):
        aggregator = MagicMock()
        aggregator.get_latest.return_value = [{"headline": "from aggregator"}]
        monkeypatch.setattr(news_mod, "_get_risk_provider", lambda: _provider(news_aggregator=aggregator))

        body = client.get("/api/news/latest").json()

        assert body["articles"][0]["headline"] == "from aggregator"

    def test_a_provider_with_neither_returns_an_empty_list(self, client, monkeypatch):
        monkeypatch.setattr(news_mod, "_get_risk_provider", lambda: _provider(news_aggregator=None))

        assert client.get("/api/news/latest").json() == {"symbol": "XAU_USD", "articles": [], "total": 0}

    def test_the_symbol_and_limit_reach_the_provider(self, client, monkeypatch):
        recent = MagicMock(return_value=[])
        monkeypatch.setattr(news_mod, "_get_risk_provider", lambda: _provider(get_recent_news=recent))

        client.get("/api/news/latest?symbol=eur_usd&limit=5")

        assert recent.call_args.kwargs == {"symbol": "eur_usd", "limit": 5}

    @pytest.mark.parametrize("limit", [0, 101])
    def test_a_limit_outside_one_to_a_hundred_is_rejected(self, client, limit):
        assert client.get(f"/api/news/latest?limit={limit}").status_code == 422

    def test_a_failure_degrades_to_empty_rather_than_500(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_recent_news=MagicMock(side_effect=RuntimeError("feed down"))),
        )

        resp = client.get("/api/news/latest")

        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ── /sentiment (query-param variant) ──────────────────────────────────────────


class TestAggregateSentiment:
    def test_it_returns_the_provider_s_result(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_sentiment=MagicMock(return_value={"symbol": "XAU_USD", "sentiment_score": 0.3})),
        )

        assert client.get("/api/news/sentiment").json()["sentiment_score"] == 0.3

    def test_a_provider_without_the_method_falls_back_to_neutral(self, client, monkeypatch):
        monkeypatch.setattr(news_mod, "_get_risk_provider", lambda: _provider())

        body = client.get("/api/news/sentiment").json()

        assert body == {"symbol": "XAU_USD", "sentiment_score": 0.0, "label": "neutral"}

    def test_a_failure_falls_back_to_neutral(self, client, monkeypatch):
        monkeypatch.setattr(
            news_mod,
            "_get_risk_provider",
            lambda: _provider(get_sentiment=MagicMock(side_effect=RuntimeError("down"))),
        )

        resp = client.get("/api/news/sentiment?symbol=eurusd")

        assert resp.status_code == 200
        assert resp.json() == {"symbol": "EURUSD", "sentiment_score": 0.0, "label": "neutral"}


# ── the singleton accessor ────────────────────────────────────────────────────


class TestRiskProviderSingleton:
    def test_it_delegates_to_the_shared_factory(self, monkeypatch):
        """One instance per process, or the 'all sources unavailable' warning repeats forever."""
        sentinel = object()
        monkeypatch.setattr(news_mod, "get_geopolitical_provider", lambda: sentinel)

        assert news_mod._get_risk_provider() is sentinel

    def test_repeated_calls_share_one_instance(self):
        assert news_mod._get_risk_provider() is news_mod._get_risk_provider()
