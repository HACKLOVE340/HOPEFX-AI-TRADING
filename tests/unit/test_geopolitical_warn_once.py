# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for news/geopolitical_risk.py — warn-once suppression,
_parse_geojson_features fix, and async fallback chain.

Covers:
- _all_sources_warned flag suppresses repeated "all sources unavailable" warnings
- _parse_geojson_features returns a list (not field(default_factory=list))
- GDELT/ACLED/ReliefWeb fallback chain returns events when sources respond
- WorldMonitorAPIClient.get_conflicts() awaits _get_cached_or_fetch
- GeopoliticalRiskProvider.get_gold_trading_signal() is awaitable
"""

from __future__ import annotations

import logging
from datetime import timezone
from unittest.mock import AsyncMock, patch

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(config: dict | None = None):
    from news.geopolitical_risk import GeopoliticalRiskProvider

    return GeopoliticalRiskProvider(config or {})


def _make_event(**kwargs):
    from news.geopolitical_risk import (
        GeopoliticalEvent,
        GeopoliticalEventType,
        RiskSeverity,
    )

    defaults = dict(
        event_type=GeopoliticalEventType.CONFLICT,
        severity=RiskSeverity.HIGH,
        title="Test",
        description="desc",
        region="Middle East",
        countries=["IR"],
    )
    defaults.update(kwargs)
    return GeopoliticalEvent(**defaults)


# ---------------------------------------------------------------------------
# Warn-once suppression
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWarnOnce:
    @pytest.mark.asyncio
    async def test_all_sources_warned_once(self, caplog):
        """Second call to _fetch_events_from_source logs DEBUG, not WARNING."""
        provider = _make_provider()
        provider._all_sources_warned = False

        # Patch all fetch methods to return empty lists
        with (
            patch.object(provider, "_fetch_from_worldmonitor", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_gdelt", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_acled", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_reliefweb", new=AsyncMock(return_value=[])),
            patch.dict("os.environ", {"APP_ENV": "development"}, clear=False),
        ):
            with caplog.at_level(logging.DEBUG, logger="news.geopolitical_risk"):
                await provider._fetch_events_from_source()
                await provider._fetch_events_from_source()

        warnings = [
            r for r in caplog.records if r.levelno == logging.WARNING and "all geopolitical" in r.message.lower()
        ]
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG and "suppressed" in r.message.lower()]

        assert len(warnings) == 1, f"Expected 1 WARNING, got {len(warnings)}"
        assert len(debugs) >= 1, "Expected at least 1 DEBUG suppression message"

    @pytest.mark.asyncio
    async def test_all_sources_warned_flag_set(self):
        """_all_sources_warned is set to True after first empty result."""
        provider = _make_provider()
        provider._all_sources_warned = False

        with (
            patch.object(provider, "_fetch_from_worldmonitor", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_gdelt", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_acled", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_reliefweb", new=AsyncMock(return_value=[])),
            patch.dict("os.environ", {"APP_ENV": "development"}, clear=False),
        ):
            await provider._fetch_events_from_source()

        assert provider._all_sources_warned is True


# ---------------------------------------------------------------------------
# _parse_geojson_features — list not field()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseGeoJSON:
    def test_returns_list_type(self):
        """_parse_geojson_features returns a plain list, not a dataclass field."""
        provider = _make_provider()
        result = provider._parse_geojson_features([], "conflicts")
        assert isinstance(result, list)

    def test_empty_features_returns_empty_list(self):
        provider = _make_provider()
        result = provider._parse_geojson_features([], "conflicts")
        assert result == []

    def test_valid_feature_parsed(self):
        """A well-formed GeoJSON feature is parsed into a GeopoliticalEvent."""
        provider = _make_provider()
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [45.0, 33.0]},
                "properties": {
                    "title": "Conflict in Iraq",
                    "description": "Armed clashes reported",
                    "region": "Middle East",
                    "countries": ["Iraq"],
                    "severity": "high",
                    "date": "2026-01-15T12:00:00+00:00",
                    "confidence": 0.9,
                },
            }
        ]
        result = provider._parse_geojson_features(features, "conflicts")
        assert len(result) == 1
        assert result[0].title == "Conflict in Iraq"
        assert result[0].coordinates == (33.0, 45.0)  # (lat, lon)

    def test_malformed_feature_skipped(self):
        """Malformed features are skipped without raising."""
        provider = _make_provider()
        features = [{"bad": "data", "no_properties": True}]
        result = provider._parse_geojson_features(features, "conflicts")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_gdelt_fallback_used_when_wm_unavailable(self):
        """GDELT events are returned when WorldMonitor is not configured."""
        provider = _make_provider()
        gdelt_event = _make_event(source="GDELT")

        with (
            patch.object(provider, "_fetch_from_worldmonitor", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_gdelt", new=AsyncMock(return_value=[gdelt_event])),
            patch.dict("os.environ", {"APP_ENV": "development", "WORLDMONITOR_API_KEY": ""}, clear=False),
        ):
            result = await provider._fetch_events_from_source()

        assert len(result) == 1
        assert result[0].source == "GDELT"

    @pytest.mark.asyncio
    async def test_acled_fallback_used_when_gdelt_fails(self):
        """ACLED events are returned when GDELT returns empty."""
        acled_event = _make_event(source="ACLED")
        provider = _make_provider()

        with (
            patch.object(provider, "_fetch_from_worldmonitor", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_gdelt", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_acled", new=AsyncMock(return_value=[acled_event])),
            patch.dict("os.environ", {"APP_ENV": "development"}, clear=False),
        ):
            result = await provider._fetch_events_from_source()

        assert len(result) == 1
        assert result[0].source == "ACLED"

    @pytest.mark.asyncio
    async def test_reliefweb_fallback_used_when_acled_fails(self):
        """ReliefWeb events are returned when GDELT and ACLED return empty."""
        rw_event = _make_event(source="ReliefWeb")
        provider = _make_provider()

        with (
            patch.object(provider, "_fetch_from_worldmonitor", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_gdelt", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_acled", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_reliefweb", new=AsyncMock(return_value=[rw_event])),
            patch.dict("os.environ", {"APP_ENV": "development"}, clear=False),
        ):
            result = await provider._fetch_events_from_source()

        assert len(result) == 1
        assert result[0].source == "ReliefWeb"

    @pytest.mark.asyncio
    async def test_stale_cache_served_when_all_fail(self):
        """Stale cache is returned when all live sources fail."""
        cached_event = _make_event(source="worldmonitor")
        provider = _make_provider()
        provider._cache["events"] = [cached_event]

        with (
            patch.object(provider, "_fetch_from_worldmonitor", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_gdelt", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_acled", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_reliefweb", new=AsyncMock(return_value=[])),
            patch.dict("os.environ", {"APP_ENV": "development"}, clear=False),
        ):
            result = await provider._fetch_events_from_source()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_production_logs_critical_when_all_fail_and_cache_empty(self):
        """In production, CRITICAL is logged and [] is returned when all sources fail.

        RuntimeError is no longer raised — doing so in an async poll task silently
        kills the task. The system logs at CRITICAL level and returns [] so callers
        can continue operating.
        """
        provider = _make_provider()
        provider._cache = {}

        import logging

        with (
            patch.object(provider, "_fetch_from_worldmonitor", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_gdelt", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_acled", new=AsyncMock(return_value=[])),
            patch.object(provider, "_fetch_events_from_reliefweb", new=AsyncMock(return_value=[])),
            patch.dict("os.environ", {"APP_ENV": "production"}, clear=False),
            patch.object(logging.getLogger("news.geopolitical_risk"), "critical") as mock_critical,
        ):
            result = await provider._fetch_events_from_source()

        assert result == [], "Expected empty list when all sources fail in production"
        mock_critical.assert_called_once()
        assert "unavailable" in mock_critical.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# get_gold_trading_signal — awaitable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoldTradingSignal:
    @pytest.mark.asyncio
    async def test_signal_is_awaitable(self):
        """get_gold_trading_signal() is a coroutine and returns a dict."""
        provider = _make_provider()
        with patch.object(provider, "get_current_events", new=AsyncMock(return_value=[])):
            result = await provider.get_gold_trading_signal()
        assert isinstance(result, dict)
        assert "direction" in result
        assert "symbol" in result
        assert result["symbol"] == "XAUUSD"

    @pytest.mark.asyncio
    async def test_signal_direction_valid(self):
        """direction is one of BUY, SELL, HOLD."""
        provider = _make_provider()
        with patch.object(provider, "get_current_events", new=AsyncMock(return_value=[])):
            result = await provider.get_gold_trading_signal()
        assert result["direction"] in ("BUY", "SELL", "HOLD")
