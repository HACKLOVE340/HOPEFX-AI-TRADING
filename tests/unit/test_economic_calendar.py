# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_economic_calendar.py
====================================
`news/economic_calendar.py` was 193 statements at 33.20 %.

This is the module that tells the desk when FOMC, NFP and CPI land — the
windows where XAUUSD gaps and where a strategy most wants to stand aside. Two
whole feed paths were unexercised: the Finnhub live fetch and, more importantly,
`build_keyless_calendar`, the deterministic fallback that is what a deployment
*without* `FINNHUB_API_KEY` actually runs. That fallback is pure date
arithmetic — first-Friday NFP, Thursday jobless claims, published FOMC dates —
so it is exactly the kind of code that is both easy to get subtly wrong and
easy to verify.

The live fetch is tested with `urllib.request.urlopen` substituted: no test
here touches the network, and none needs a Finnhub key.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch

import pytest

import news.economic_calendar as cal_mod
from news.economic_calendar import (
    EconomicCalendar,
    EconomicEvent,
    EventImportance,
    EventType,
    _classify_event_type,
    _safe_float,
    build_keyless_calendar,
    fetch_live_calendar,
    get_economic_calendar,
)

pytestmark = pytest.mark.unit

UTC = timezone.utc


def _event(
    title="US CPI",
    hours=2,
    importance=EventImportance.HIGH,
    event_type=EventType.INFLATION,
    country="US",
    currency="USD",
    **kw,
):
    return EconomicEvent(
        title=title,
        event_type=event_type,
        importance=importance,
        scheduled_time=datetime.now(UTC) + timedelta(hours=hours),
        country=country,
        currency=currency,
        **kw,
    )


# ── the event record ──────────────────────────────────────────────────────────


class TestEconomicEventSerialisation:
    def test_to_dict_flattens_the_enums(self):
        payload = _event(forecast=3.2, previous=3.1, actual=3.4).to_dict()

        assert payload["event_type"] == "inflation"
        assert payload["importance"] == "high"
        assert payload["title"] == "US CPI"

    def test_the_timestamp_is_iso_formatted(self):
        payload = _event().to_dict()

        assert datetime.fromisoformat(payload["scheduled_time"]).tzinfo is not None

    def test_absent_values_stay_none(self):
        payload = _event().to_dict()

        assert payload["actual"] is None
        assert payload["forecast"] is None
        assert payload["previous"] is None


class TestIsSurprise:
    def test_without_an_actual_there_is_no_surprise(self):
        assert _event(forecast=3.0).is_surprise() is False

    def test_without_a_forecast_there_is_no_surprise(self):
        assert _event(actual=3.0).is_surprise() is False

    def test_a_small_deviation_is_not_a_surprise(self):
        assert _event(forecast=100.0, actual=105.0).is_surprise() is False

    def test_a_large_deviation_is_a_surprise(self):
        assert _event(forecast=100.0, actual=150.0).is_surprise() is True

    def test_a_miss_in_either_direction_counts(self):
        assert _event(forecast=100.0, actual=50.0).is_surprise() is True

    def test_the_threshold_is_configurable(self):
        event = _event(forecast=100.0, actual=105.0)

        assert event.is_surprise(threshold=0.01) is True
        assert event.is_surprise(threshold=0.5) is False

    def test_a_zero_forecast_avoids_dividing_by_zero(self):
        """A 0.0 forecast is common for rate *changes*; it must not raise."""
        assert _event(forecast=0.0, actual=0.25).is_surprise() is True
        assert _event(forecast=0.0, actual=0.0).is_surprise() is False


class TestImpactDirection:
    def test_it_is_unknown_without_both_numbers(self):
        assert _event(forecast=1.0).get_impact_direction() is None
        assert _event(actual=1.0).get_impact_direction() is None

    def test_a_beat_is_bullish(self):
        assert _event(forecast=1.0, actual=2.0).get_impact_direction() == "bullish"

    def test_a_miss_is_bearish(self):
        assert _event(forecast=2.0, actual=1.0).get_impact_direction() == "bearish"

    def test_an_exact_print_is_neutral(self):
        assert _event(forecast=2.0, actual=2.0).get_impact_direction() == "neutral"


# ── the calendar container ────────────────────────────────────────────────────


class TestCalendarOrdering:
    def test_events_are_kept_in_chronological_order(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(title="later", hours=10))
        calendar.add_event(_event(title="sooner", hours=1))

        assert [e.title for e in calendar.events] == ["sooner", "later"]

    def test_a_new_calendar_is_empty(self):
        assert EconomicCalendar().events == []


class TestUpcomingEvents:
    def test_an_event_inside_the_window_is_returned(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(hours=2))

        assert len(calendar.get_upcoming_events(hours_ahead=24)) == 1

    def test_an_event_beyond_the_window_is_excluded(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(hours=48))

        assert calendar.get_upcoming_events(hours_ahead=24) == []

    def test_a_past_event_is_excluded(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(hours=-1))

        assert calendar.get_upcoming_events() == []

    def test_the_importance_floor_filters_lower_grades(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(title="low", importance=EventImportance.LOW))
        calendar.add_event(_event(title="high", importance=EventImportance.HIGH))

        titles = [e.title for e in calendar.get_upcoming_events(min_importance=EventImportance.HIGH)]

        assert titles == ["high"]

    def test_the_floor_is_inclusive(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(importance=EventImportance.MEDIUM))

        assert len(calendar.get_upcoming_events(min_importance=EventImportance.MEDIUM)) == 1

    def test_critical_clears_a_high_floor(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(importance=EventImportance.CRITICAL))

        assert len(calendar.get_upcoming_events(min_importance=EventImportance.HIGH)) == 1

    def test_high_impact_is_the_high_floor(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(title="medium", importance=EventImportance.MEDIUM))
        calendar.add_event(_event(title="critical", importance=EventImportance.CRITICAL))

        assert [e.title for e in calendar.get_high_impact_events()] == ["critical"]


class TestEventsByCurrency:
    def test_it_selects_the_matching_currency(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(title="usd", currency="USD"))
        calendar.add_event(_event(title="eur", currency="EUR"))

        assert [e.title for e in calendar.get_events_by_currency("USD")] == ["usd"]

    def test_it_respects_the_day_window(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(hours=24 * 10, currency="USD"))

        assert calendar.get_events_by_currency("USD", days_ahead=7) == []

    def test_an_unknown_currency_yields_nothing(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(currency="USD"))

        assert calendar.get_events_by_currency("ZAR") == []


class TestUpcomingEventWarnings:
    def test_a_quiet_window_reports_no_warning(self):
        report = EconomicCalendar().check_upcoming_events()

        assert report["has_upcoming_events"] is False
        assert report["events"] == []
        assert report["max_importance"] is None
        assert report["earliest_event"] is None

    def test_a_high_impact_event_raises_the_flag(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(hours=1, importance=EventImportance.HIGH))

        report = calendar.check_upcoming_events(warning_hours=2)

        assert report["has_upcoming_events"] is True
        assert report["max_importance"] == "high"

    def test_critical_outranks_high_in_the_summary(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(title="h", hours=1, importance=EventImportance.HIGH))
        calendar.add_event(_event(title="c", hours=1, importance=EventImportance.CRITICAL))

        assert calendar.check_upcoming_events(warning_hours=2)["max_importance"] == "critical"

    def test_the_earliest_event_is_the_one_reported(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(title="second", hours=1.5, importance=EventImportance.HIGH))
        calendar.add_event(_event(title="first", hours=0.5, importance=EventImportance.HIGH))

        assert calendar.check_upcoming_events(warning_hours=2)["earliest_event"]["title"] == "first"

    def test_a_medium_event_does_not_trip_the_warning(self):
        """The warning exists to halt trading; only HIGH+ justifies that."""
        calendar = EconomicCalendar()
        calendar.add_event(_event(hours=1, importance=EventImportance.MEDIUM))

        assert calendar.check_upcoming_events(warning_hours=2)["has_upcoming_events"] is False


class TestSampleEvents:
    def test_it_populates_the_calendar(self):
        calendar = EconomicCalendar()
        created = calendar.create_sample_events()

        assert len(created) == 5
        assert len(calendar.events) == 5

    def test_the_samples_are_all_in_the_future(self):
        calendar = EconomicCalendar()
        now = datetime.now(UTC)

        for event in calendar.create_sample_events():
            assert event.scheduled_time > now

    def test_they_cover_more_than_one_currency(self):
        calendar = EconomicCalendar()
        calendar.create_sample_events()

        assert {e.currency for e in calendar.events} >= {"USD", "EUR", "GBP"}


class TestUpdateEventActual:
    def test_it_writes_the_actual_and_returns_the_event(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(title="US CPI", forecast=3.2))

        updated = calendar.update_event_actual("US CPI", 3.5)

        assert updated is not None
        assert updated.actual == 3.5

    def test_an_unknown_title_returns_none(self):
        assert EconomicCalendar().update_event_actual("Nope", 1.0) is None

    def test_a_scheduled_time_disambiguates_repeated_titles(self):
        calendar = EconomicCalendar()
        first, second = _event(title="US CPI", hours=1), _event(title="US CPI", hours=48)
        calendar.add_event(first)
        calendar.add_event(second)

        calendar.update_event_actual("US CPI", 9.9, scheduled_time=second.scheduled_time)

        assert second.actual == 9.9
        assert first.actual is None

    def test_updating_makes_the_surprise_check_answerable(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(title="US CPI", forecast=3.0))

        event = calendar.update_event_actual("US CPI", 6.0)

        assert event.is_surprise() is True
        assert event.get_impact_direction() == "bullish"


class TestEventSummary:
    def test_an_empty_calendar_summarises_to_zero(self):
        summary = EconomicCalendar().get_event_summary()

        assert summary["total_events"] == 0
        assert summary["critical_events"] == 0
        assert summary["high_impact_events"] == 0

    def test_counts_are_broken_out_by_importance_type_and_currency(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(importance=EventImportance.CRITICAL, currency="USD"))
        calendar.add_event(_event(importance=EventImportance.HIGH, event_type=EventType.GDP, currency="EUR"))

        summary = calendar.get_event_summary()

        assert summary["total_events"] == 2
        assert summary["by_importance"]["critical"] == 1
        assert summary["by_type"]["gdp"] == 1
        assert summary["by_currency"] == {"USD": 1, "EUR": 1}

    def test_high_impact_rolls_up_high_and_critical(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(importance=EventImportance.CRITICAL))
        calendar.add_event(_event(importance=EventImportance.HIGH))
        calendar.add_event(_event(importance=EventImportance.LOW))

        assert calendar.get_event_summary()["high_impact_events"] == 2

    def test_an_event_without_a_currency_is_not_counted_under_one(self):
        calendar = EconomicCalendar()
        calendar.add_event(_event(currency=None))

        assert calendar.get_event_summary()["by_currency"] == {}


# ── helpers ───────────────────────────────────────────────────────────────────


class TestSafeFloat:
    @pytest.mark.parametrize("value", [None, "", "abc", [], {}])
    def test_unusable_values_become_none(self, value):
        assert _safe_float(value) is None

    @pytest.mark.parametrize(("value", "expected"), [("3.5", 3.5), (2, 2.0), (-1.25, -1.25), ("0", 0.0)])
    def test_usable_values_become_floats(self, value, expected):
        assert _safe_float(value) == pytest.approx(expected)

    def test_zero_is_kept_rather_than_treated_as_missing(self):
        """A 0.0 print is data. Collapsing it to None loses a real reading."""
        assert _safe_float(0) == 0.0
        assert _safe_float("0.0") == 0.0


class TestClassifyEventType:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("US Interest Rate Decision", EventType.INTEREST_RATE),
            ("BOE Rate Decision", EventType.INTEREST_RATE),
            ("FOMC Statement", EventType.CENTRAL_BANK),
            ("ECB Press Conference", EventType.CENTRAL_BANK),
            ("Fed Chair Speech", EventType.CENTRAL_BANK_SPEECH),
            ("GDP Growth Rate", EventType.GDP),
            ("Nonfarm Payrolls", EventType.EMPLOYMENT),
            ("Non-Farm Payrolls", EventType.EMPLOYMENT),
            ("Initial Jobless Claims", EventType.EMPLOYMENT),
            ("Unemployment Rate", EventType.EMPLOYMENT),
            ("Core CPI", EventType.INFLATION),
            ("PPI MoM", EventType.INFLATION),
            ("Retail Sales MoM", EventType.RETAIL_SALES),
            ("Manufacturing PMI", EventType.PMI),
            ("Consumer Confidence", EventType.CONSUMER_CONFIDENCE),
            ("Consumer Sentiment", EventType.CONSUMER_CONFIDENCE),
        ],
    )
    def test_known_titles_are_classified(self, title, expected):
        assert _classify_event_type(title) is expected

    def test_an_unrecognised_title_is_other(self):
        assert _classify_event_type("Tulip Auction Results") is EventType.OTHER

    def test_matching_is_case_insensitive(self):
        assert _classify_event_type("CORE CPI") is EventType.INFLATION

    def test_the_first_matching_keyword_wins(self):
        """'interest rate' precedes 'fomc' in the table, so ordering is observable."""
        assert _classify_event_type("FOMC Interest Rate Decision") is EventType.INTEREST_RATE


class TestGlobalCalendar:
    def test_it_returns_a_calendar(self):
        assert isinstance(get_economic_calendar(), EconomicCalendar)

    def test_repeated_calls_share_one_instance(self):
        assert get_economic_calendar() is get_economic_calendar()


# ── the Finnhub live fetch ────────────────────────────────────────────────────


def _urlopen_returning(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=response)


class TestFetchLiveCalendar:
    def test_without_a_key_it_says_so_rather_than_calling_out(self, monkeypatch):
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        with pytest.raises(RuntimeError, match="FINNHUB_API_KEY is not set"):
            fetch_live_calendar()

    def test_a_whitespace_only_key_counts_as_absent(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "   ")

        with pytest.raises(RuntimeError, match="FINNHUB_API_KEY is not set"):
            fetch_live_calendar()

    def test_it_parses_an_event_into_the_calendar(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        payload = {
            "economicCalendar": [
                {
                    "time": "2026-12-01 13:30:00",
                    "country": "US",
                    "impact": "3",
                    "event": "Core CPI",
                    "estimate": "3.2",
                    "prev": "3.1",
                    "actual": "3.4",
                }
            ]
        }

        with patch("urllib.request.urlopen", _urlopen_returning(payload)):
            calendar = fetch_live_calendar()

        assert len(calendar.events) == 1
        event = calendar.events[0]
        assert event.title == "Core CPI"
        assert event.event_type is EventType.INFLATION
        assert event.importance is EventImportance.HIGH
        assert event.currency == "USD"
        assert event.forecast == pytest.approx(3.2)
        assert event.actual == pytest.approx(3.4)
        assert event.scheduled_time.tzinfo is not None

    def test_a_date_without_a_time_defaults_to_midday_utc(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        payload = {"economicCalendar": [{"date": "2026-12-01", "country": "US", "event": "GDP"}]}

        with patch("urllib.request.urlopen", _urlopen_returning(payload)):
            calendar = fetch_live_calendar()

        assert calendar.events[0].scheduled_time.hour == 12

    @pytest.mark.parametrize(
        ("impact", "expected"),
        [
            ("1", EventImportance.LOW),
            ("2", EventImportance.MEDIUM),
            ("3", EventImportance.HIGH),
            ("high", EventImportance.HIGH),
            ("medium", EventImportance.MEDIUM),
            ("HIGH", EventImportance.HIGH),
            ("nonsense", EventImportance.LOW),
        ],
    )
    def test_both_numeric_and_word_impact_encodings_are_understood(self, monkeypatch, impact, expected):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        payload = {"economicCalendar": [{"date": "2026-12-01", "country": "US", "event": "Thing", "impact": impact}]}

        with patch("urllib.request.urlopen", _urlopen_returning(payload)):
            calendar = fetch_live_calendar()

        assert calendar.events[0].importance is expected

    @pytest.mark.parametrize(
        ("country", "currency"),
        [("US", "USD"), ("EU", "EUR"), ("GB", "GBP"), ("JP", "JPY"), ("CH", "CHF")],
    )
    def test_countries_map_to_currencies(self, monkeypatch, country, currency):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        payload = {"economicCalendar": [{"date": "2026-12-01", "country": country, "event": "Thing"}]}

        with patch("urllib.request.urlopen", _urlopen_returning(payload)):
            calendar = fetch_live_calendar()

        assert calendar.events[0].currency == currency

    def test_an_unmapped_country_has_no_currency(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        payload = {"economicCalendar": [{"date": "2026-12-01", "country": "ZA", "event": "Thing"}]}

        with patch("urllib.request.urlopen", _urlopen_returning(payload)):
            calendar = fetch_live_calendar()

        assert calendar.events[0].currency is None

    def test_a_malformed_item_is_skipped_without_losing_the_good_ones(self, monkeypatch):
        """One bad row from a third party must not empty the desk's calendar."""
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        payload = {
            "economicCalendar": [
                {"time": "not-a-timestamp", "country": "US", "event": "Broken"},
                {"date": "2026-12-01", "country": "US", "event": "Good"},
            ]
        }

        with patch("urllib.request.urlopen", _urlopen_returning(payload)):
            calendar = fetch_live_calendar()

        assert [e.title for e in calendar.events] == ["Good"]

    def test_an_empty_payload_yields_an_empty_calendar(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")

        with patch("urllib.request.urlopen", _urlopen_returning({})):
            calendar = fetch_live_calendar()

        assert calendar.events == []

    def test_the_request_targets_finnhub_over_https_with_the_window(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "secret-key")
        opener = _urlopen_returning({})

        with patch("urllib.request.urlopen", opener):
            fetch_live_calendar(days_ahead=3)

        # Decompose rather than prefix-match: a `startswith` on a URL is the
        # bypassable shape CodeQL flags, and checking the parts separately is a
        # stricter assertion anyway -- it pins the host rather than a prefix of it.
        parsed = urlsplit(opener.call_args.args[0].full_url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "finnhub.io"
        assert parsed.path == "/api/v1/calendar/economic"
        query = parse_qs(parsed.query)
        assert "from" in query and "to" in query

    def test_a_missing_event_name_falls_back_to_a_placeholder(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        payload = {"economicCalendar": [{"date": "2026-12-01", "country": "US"}]}

        with patch("urllib.request.urlopen", _urlopen_returning(payload)):
            calendar = fetch_live_calendar()

        assert calendar.events[0].title == "Unknown Event"


# ── the keyless fallback ──────────────────────────────────────────────────────


class TestBuildKeylessCalendar:
    def test_it_needs_no_api_key(self, monkeypatch):
        """This is what a deployment without FINNHUB_API_KEY actually runs."""
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        assert isinstance(build_keyless_calendar(), EconomicCalendar)

    def test_a_long_window_finds_the_recurring_releases(self):
        calendar = build_keyless_calendar(days_ahead=60)

        titles = {e.title for e in calendar.events}
        assert any("Jobless Claims" in t for t in titles)
        assert any("Non-Farm Payrolls" in t for t in titles)

    def test_every_event_is_in_the_future_and_inside_the_window(self):
        now = datetime.now(UTC)
        calendar = build_keyless_calendar(days_ahead=45)

        for event in calendar.events:
            assert now <= event.scheduled_time <= now + timedelta(days=45, hours=13)

    def test_jobless_claims_land_on_thursdays(self):
        calendar = build_keyless_calendar(days_ahead=60)

        for event in calendar.events:
            if "Jobless Claims" in event.title:
                assert event.scheduled_time.weekday() == 3

    def test_payrolls_land_on_a_first_friday(self):
        calendar = build_keyless_calendar(days_ahead=90)

        for event in calendar.events:
            if "Non-Farm Payrolls" in event.title:
                assert event.scheduled_time.weekday() == 4
                assert event.scheduled_time.day <= 7

    def test_the_recurring_releases_are_at_twelve_thirty_utc(self):
        calendar = build_keyless_calendar(days_ahead=60)

        for event in calendar.events:
            if "scheduled" in event.title and "FOMC" not in event.title:
                assert (event.scheduled_time.hour, event.scheduled_time.minute) == (12, 30)

    def test_fomc_dates_are_at_eighteen_hundred_utc(self):
        calendar = build_keyless_calendar(days_ahead=400)
        fomc = [e for e in calendar.events if "FOMC" in e.title]

        assert fomc, "a 400-day window must contain at least one published FOMC date"
        for event in fomc:
            assert event.scheduled_time.hour == 18
            assert event.importance is EventImportance.CRITICAL

    def test_every_event_is_labelled_scheduled(self):
        """The desk must be able to tell an estimate from a live print."""
        calendar = build_keyless_calendar(days_ahead=60)

        assert calendar.events, "window should not be empty"
        for event in calendar.events:
            assert "(scheduled)" in event.title

    def test_estimates_carry_no_forecast_or_actual(self):
        calendar = build_keyless_calendar(days_ahead=60)

        for event in calendar.events:
            assert event.forecast is None
            assert event.actual is None

    def test_a_zero_day_window_yields_nothing(self):
        assert build_keyless_calendar(days_ahead=0).events == []

    def test_the_result_is_chronological(self):
        calendar = build_keyless_calendar(days_ahead=90)
        times = [e.scheduled_time for e in calendar.events]

        assert times == sorted(times)

    def test_the_published_fomc_dates_are_well_formed(self):
        for ds in cal_mod._FOMC_DECISION_DATES:
            assert datetime.strptime(ds, "%Y-%m-%d")

    def test_the_fomc_dates_are_in_ascending_order(self):
        dates = list(cal_mod._FOMC_DECISION_DATES)

        assert dates == sorted(dates)
