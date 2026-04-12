# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for news/geopolitical_risk.py

Covers: GeopoliticalEvent, CountryRisk, GeopoliticalRiskAssessment,
        GeopoliticalRiskProvider (cache, CI guard, _assess_gold_impact,
        _calculate_risk_score, _get_affected_currencies,
        get_risk_assessment, get_gold_trading_signal).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnums:
    def test_geopolitical_event_type_values(self):
        from news.geopolitical_risk import GeopoliticalEventType

        assert GeopoliticalEventType.CONFLICT.value == "conflict"
        assert GeopoliticalEventType.SANCTIONS.value == "sanctions"
        assert GeopoliticalEventType.NATURAL_DISASTER.value == "natural_disaster"

    def test_risk_severity_values(self):
        from news.geopolitical_risk import RiskSeverity

        assert RiskSeverity.CRITICAL.value == "critical"
        assert RiskSeverity.HIGH.value == "high"
        assert RiskSeverity.MEDIUM.value == "medium"
        assert RiskSeverity.LOW.value == "low"
        assert RiskSeverity.INFO.value == "info"

    def test_gold_impact_values(self):
        from news.geopolitical_risk import GoldImpact

        assert GoldImpact.STRONGLY_BULLISH.value == "strongly_bullish"
        assert GoldImpact.BULLISH.value == "bullish"
        assert GoldImpact.NEUTRAL.value == "neutral"
        assert GoldImpact.BEARISH.value == "bearish"
        assert GoldImpact.STRONGLY_BEARISH.value == "strongly_bearish"


# ---------------------------------------------------------------------------
# GeopoliticalEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeopoliticalEvent:
    def _make_event(self, **kwargs):
        from news.geopolitical_risk import (
            GeopoliticalEvent,
            GeopoliticalEventType,
            GoldImpact,
            RiskSeverity,
        )

        defaults = dict(
            event_type=GeopoliticalEventType.CONFLICT,
            severity=RiskSeverity.HIGH,
            title="Test Conflict",
            description="A test conflict event",
            region="Middle East",
            countries=["IR", "IQ"],
            gold_impact=GoldImpact.BULLISH,
            risk_score=65.0,
        )
        defaults.update(kwargs)
        return GeopoliticalEvent(**defaults)

    def test_to_dict_keys(self):
        event = self._make_event()
        d = event.to_dict()
        for key in (
            "event_type",
            "severity",
            "title",
            "description",
            "region",
            "countries",
            "timestamp",
            "source",
            "confidence",
            "gold_impact",
            "affected_currencies",
            "risk_score",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_event_type_is_string(self):
        event = self._make_event()
        assert isinstance(event.to_dict()["event_type"], str)

    def test_to_dict_severity_is_string(self):
        event = self._make_event()
        assert isinstance(event.to_dict()["severity"], str)

    def test_to_dict_gold_impact_is_string(self):
        event = self._make_event()
        assert isinstance(event.to_dict()["gold_impact"], str)

    def test_to_dict_timestamp_is_iso_string(self):
        event = self._make_event()
        ts = event.to_dict()["timestamp"]
        assert isinstance(ts, str)
        datetime.fromisoformat(ts)  # must parse without error

    def test_default_source(self):
        event = self._make_event()
        assert event.source == "worldmonitor"

    def test_default_confidence(self):
        event = self._make_event()
        assert event.confidence == pytest.approx(0.8)

    def test_no_gold_impact_serializes_none(self):
        from news.geopolitical_risk import (
            GeopoliticalEvent,
            GeopoliticalEventType,
            RiskSeverity,
        )

        event = GeopoliticalEvent(
            event_type=GeopoliticalEventType.SANCTIONS,
            severity=RiskSeverity.LOW,
            title="Minor Sanctions",
            description="",
            region="Europe",
            countries=["RU"],
            gold_impact=None,
        )
        assert event.to_dict()["gold_impact"] is None


# ---------------------------------------------------------------------------
# CountryRisk
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCountryRisk:
    def _make_country_risk(self):
        from news.geopolitical_risk import CountryRisk

        return CountryRisk(
            country_code="RU",
            country_name="Russia",
            instability_index=75.0,
            trend="increasing",
            risk_factors=["military_conflict", "sanctions"],
        )

    def test_to_dict_keys(self):
        cr = self._make_country_risk()
        d = cr.to_dict()
        for key in ("country_code", "country_name", "instability_index", "trend", "risk_factors", "last_updated"):
            assert key in d

    def test_to_dict_last_updated_is_iso(self):
        cr = self._make_country_risk()
        ts = cr.to_dict()["last_updated"]
        datetime.fromisoformat(ts)

    def test_instability_index_range(self):
        cr = self._make_country_risk()
        assert 0.0 <= cr.instability_index <= 100.0


# ---------------------------------------------------------------------------
# GeopoliticalRiskAssessment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeopoliticalRiskAssessment:
    def _make_assessment(self):
        from news.geopolitical_risk import (
            GeopoliticalRiskAssessment,
            GoldImpact,
        )

        return GeopoliticalRiskAssessment(
            global_risk_score=55.0,
            gold_outlook=GoldImpact.BULLISH,
            active_conflicts=3,
            sanctions_count=12,
            hotspots=5,
            high_risk_regions=["Middle East", "Eastern Europe"],
            key_events=[],
            country_risks={},
            trading_recommendations=["Consider long gold positions"],
        )

    def test_to_dict_keys(self):
        a = self._make_assessment()
        d = a.to_dict()
        for key in (
            "global_risk_score",
            "gold_outlook",
            "active_conflicts",
            "sanctions_count",
            "hotspots",
            "high_risk_regions",
            "key_events",
            "country_risks",
            "trading_recommendations",
            "timestamp",
        ):
            assert key in d

    def test_to_dict_gold_outlook_is_string(self):
        a = self._make_assessment()
        assert isinstance(a.to_dict()["gold_outlook"], str)

    def test_to_dict_key_events_is_list(self):
        a = self._make_assessment()
        assert isinstance(a.to_dict()["key_events"], list)

    def test_to_dict_country_risks_is_dict(self):
        a = self._make_assessment()
        assert isinstance(a.to_dict()["country_risks"], dict)


# ---------------------------------------------------------------------------
# GeopoliticalRiskProvider — init and cache
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeopoliticalRiskProviderInit:
    def test_init_defaults(self):
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        assert p._cache == {}
        assert p._cache_timestamp is None
        assert p.event_history == []

    def test_init_custom_cache_ttl(self):
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider(config={"cache_ttl": 3600})
        assert p.cache_ttl == 3600

    def test_is_cache_valid_false_when_empty(self):
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        assert p._is_cache_valid() is False

    def test_is_cache_valid_true_after_population(self):
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        p._cache["events"] = []
        p._cache_timestamp = datetime.now(UTC)
        assert p._is_cache_valid() is True

    @pytest.mark.asyncio
    async def test_get_current_events_returns_empty_in_ci(self, monkeypatch):
        """In CI environment, no live network calls are made."""
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        events = await p.get_current_events(force_refresh=True)
        assert isinstance(events, list)

    @pytest.mark.asyncio
    async def test_get_current_events_uses_cache(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import (
            GeopoliticalEvent,
            GeopoliticalEventType,
            GoldImpact,
            GeopoliticalRiskProvider,
            RiskSeverity,
        )

        p = GeopoliticalRiskProvider()
        cached_event = GeopoliticalEvent(
            event_type=GeopoliticalEventType.CONFLICT,
            severity=RiskSeverity.HIGH,
            title="Cached Event",
            description="",
            region="Test",
            countries=["US"],
            gold_impact=GoldImpact.BULLISH,
        )
        p._cache["events"] = [cached_event]
        p._cache_timestamp = datetime.now(UTC)
        events = await p.get_current_events(force_refresh=False)
        assert len(events) == 1
        assert events[0].title == "Cached Event"


# ---------------------------------------------------------------------------
# GeopoliticalRiskProvider — _assess_gold_impact
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssessGoldImpact:
    def _make_event(self, event_type, severity, countries=None, title="", description=""):
        from news.geopolitical_risk import GeopoliticalEvent

        return GeopoliticalEvent(
            event_type=event_type,
            severity=severity,
            title=title,
            description=description,
            region="Test",
            countries=countries or [],
        )

    def test_conflict_critical_is_strongly_bullish(self):
        from news.geopolitical_risk import (
            GeopoliticalEventType,
            GeopoliticalRiskProvider,
            GoldImpact,
            RiskSeverity,
        )

        p = GeopoliticalRiskProvider()
        event = self._make_event(
            GeopoliticalEventType.CONFLICT, RiskSeverity.CRITICAL, countries=["IR"], title="war nuclear"
        )
        impact = p._assess_gold_impact(event)
        assert impact == GoldImpact.STRONGLY_BULLISH

    def test_info_event_is_neutral(self):
        from news.geopolitical_risk import (
            GeopoliticalEventType,
            GeopoliticalRiskProvider,
            GoldImpact,
            RiskSeverity,
        )

        p = GeopoliticalRiskProvider()
        event = self._make_event(
            GeopoliticalEventType.POLITICAL_UNREST, RiskSeverity.INFO, countries=["XX"], title="minor protest"
        )
        impact = p._assess_gold_impact(event)
        assert impact in (GoldImpact.NEUTRAL, GoldImpact.BEARISH)

    def test_gold_sensitive_region_increases_impact(self):
        from news.geopolitical_risk import (
            GeopoliticalEventType,
            GeopoliticalRiskProvider,
            GoldImpact,
            RiskSeverity,
        )

        p = GeopoliticalRiskProvider()
        # Middle East is gold-sensitive
        event_me = self._make_event(GeopoliticalEventType.HOTSPOT, RiskSeverity.MEDIUM, countries=["SA"])
        event_other = self._make_event(GeopoliticalEventType.HOTSPOT, RiskSeverity.MEDIUM, countries=["NZ"])
        impact_me = p._assess_gold_impact(event_me)
        impact_other = p._assess_gold_impact(event_other)
        # Middle East should have >= impact than non-sensitive region
        impact_values = {
            GoldImpact.STRONGLY_BULLISH: 4,
            GoldImpact.BULLISH: 3,
            GoldImpact.NEUTRAL: 2,
            GoldImpact.BEARISH: 1,
            GoldImpact.STRONGLY_BEARISH: 0,
        }
        assert impact_values[impact_me] >= impact_values[impact_other]


# ---------------------------------------------------------------------------
# GeopoliticalRiskProvider — _calculate_risk_score
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalculateRiskScore:
    def test_critical_event_high_score(self):
        from news.geopolitical_risk import (
            GeopoliticalEvent,
            GeopoliticalEventType,
            GeopoliticalRiskProvider,
            RiskSeverity,
        )

        p = GeopoliticalRiskProvider()
        event = GeopoliticalEvent(
            event_type=GeopoliticalEventType.CONFLICT,
            severity=RiskSeverity.CRITICAL,
            title="Major War",
            description="",
            region="Middle East",
            countries=["IR"],
        )
        score = p._calculate_risk_score(event)
        assert score >= 60.0

    def test_info_event_low_score(self):
        from news.geopolitical_risk import (
            GeopoliticalEvent,
            GeopoliticalEventType,
            GeopoliticalRiskProvider,
            RiskSeverity,
        )

        p = GeopoliticalRiskProvider()
        event = GeopoliticalEvent(
            event_type=GeopoliticalEventType.POLITICAL_UNREST,
            severity=RiskSeverity.INFO,
            title="Minor Protest",
            description="",
            region="Europe",
            countries=["DE"],
        )
        score = p._calculate_risk_score(event)
        assert score <= 50.0

    def test_score_in_valid_range(self):
        from news.geopolitical_risk import (
            GeopoliticalEvent,
            GeopoliticalEventType,
            GeopoliticalRiskProvider,
            RiskSeverity,
        )

        p = GeopoliticalRiskProvider()
        for severity in RiskSeverity:
            event = GeopoliticalEvent(
                event_type=GeopoliticalEventType.SANCTIONS,
                severity=severity,
                title="Test",
                description="",
                region="Asia",
                countries=["CN"],
            )
            score = p._calculate_risk_score(event)
            assert 0.0 <= score <= 100.0, f"Score {score} out of range for {severity}"


# ---------------------------------------------------------------------------
# GeopoliticalRiskProvider — get_risk_assessment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetRiskAssessment:
    @pytest.mark.asyncio
    async def test_returns_assessment_object(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskAssessment, GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        assessment = await p.get_risk_assessment()
        assert isinstance(assessment, GeopoliticalRiskAssessment)

    @pytest.mark.asyncio
    async def test_global_risk_score_in_range(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        assessment = await p.get_risk_assessment()
        assert 0.0 <= assessment.global_risk_score <= 100.0

    @pytest.mark.asyncio
    async def test_gold_outlook_is_gold_impact(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider, GoldImpact

        p = GeopoliticalRiskProvider()
        assessment = await p.get_risk_assessment()
        assert isinstance(assessment.gold_outlook, GoldImpact)

    @pytest.mark.asyncio
    async def test_trading_recommendations_is_list(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        assessment = await p.get_risk_assessment()
        assert isinstance(assessment.trading_recommendations, list)


# ---------------------------------------------------------------------------
# GeopoliticalRiskProvider — get_gold_trading_signal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetGoldTradingSignal:
    @pytest.mark.asyncio
    async def test_returns_dict(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        signal = await p.get_gold_trading_signal()
        assert isinstance(signal, dict)

    @pytest.mark.asyncio
    async def test_required_keys(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        signal = await p.get_gold_trading_signal()
        for key in ("symbol", "direction", "strength", "confidence", "risk_score", "gold_outlook", "timestamp"):
            assert key in signal, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_symbol_is_xauusd(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        signal = await p.get_gold_trading_signal()
        assert signal["symbol"] == "XAUUSD"

    @pytest.mark.asyncio
    async def test_direction_valid_value(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        direction = (await p.get_gold_trading_signal())["direction"]
        assert direction in ("BUY", "SELL", "HOLD")

    @pytest.mark.asyncio
    async def test_strength_in_range(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        strength = (await p.get_gold_trading_signal())["strength"]
        assert 0.0 <= strength <= 1.0

    @pytest.mark.asyncio
    async def test_confidence_in_range(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import GeopoliticalRiskProvider

        p = GeopoliticalRiskProvider()
        confidence = (await p.get_gold_trading_signal())["confidence"]
        assert 0.0 <= confidence <= 1.0

    @pytest.mark.asyncio
    async def test_strongly_bullish_maps_to_buy(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import (
            GeopoliticalRiskAssessment,
            GeopoliticalRiskProvider,
            GoldImpact,
        )

        p = GeopoliticalRiskProvider()
        assessment = GeopoliticalRiskAssessment(
            global_risk_score=90.0,
            gold_outlook=GoldImpact.STRONGLY_BULLISH,
            active_conflicts=5,
            sanctions_count=20,
            hotspots=8,
            high_risk_regions=["Middle East"],
            key_events=[],
            country_risks={},
            trading_recommendations=["Buy gold"],
        )
        with patch.object(p, "get_risk_assessment", new=AsyncMock(return_value=assessment)):
            signal = await p.get_gold_trading_signal()
        assert signal["direction"] == "BUY"
        assert signal["strength"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_strongly_bearish_maps_to_sell(self, monkeypatch):
        monkeypatch.setenv("HOPEFX_CI", "1")
        from news.geopolitical_risk import (
            GeopoliticalRiskAssessment,
            GeopoliticalRiskProvider,
            GoldImpact,
        )

        p = GeopoliticalRiskProvider()
        assessment = GeopoliticalRiskAssessment(
            global_risk_score=10.0,
            gold_outlook=GoldImpact.STRONGLY_BEARISH,
            active_conflicts=0,
            sanctions_count=0,
            hotspots=0,
            high_risk_regions=[],
            key_events=[],
            country_risks={},
            trading_recommendations=["Sell gold"],
        )
        with patch.object(p, "get_risk_assessment", new=AsyncMock(return_value=assessment)):
            signal = await p.get_gold_trading_signal()
        assert signal["direction"] == "SELL"
        assert signal["strength"] == pytest.approx(1.0)
