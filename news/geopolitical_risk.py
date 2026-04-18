# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""

# ── Module constants ─────────────────────────────────────────────────────────
_RISK_HIGH = 70
_RISK_MEDIUM = 50
_RISK_LOW = 30
_RISK_VERY_LOW = 60
_EVENT_WEIGHT_MAJOR = 6
_EVENT_WEIGHT_MODERATE = 4
_EVENT_WEIGHT_MINOR = 5
_EVENT_WEIGHT_MICRO = 3
_BULLISH_RATIO_STRONG = 2
_BLACKOUT_MINUTES = 60

Geopolitical Risk Intelligence Module

Integrates World Monitor data for geopolitical risk assessment in trading:
- Conflict zone monitoring (wars, military activities)
- Sanctions tracking (trade restrictions, economic warfare)
- Country instability index (political risk scores)
- Infrastructure disruptions (outages, natural disasters)
- Weather/natural hazard alerts

World Monitor Source: https://worldmonitor.app/
GitHub: https://github.com/koala73/worldmonitor

This module is particularly valuable for XAU/USD (Gold) trading since:
- Gold is a safe-haven asset that rises during geopolitical crises
- Sanctions affect global gold supply chains
- Conflicts drive flight-to-safety demand
- Currency instability increases gold appeal

Author: HOPEFX Development Team
"""

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def _acled_date_range(days: int = 7) -> str:
    """Return ACLED date range string 'YYYY-MM-DD|YYYY-MM-DD' for the past N days."""
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    return f"{start.strftime('%Y-%m-%d')}|{end.strftime('%Y-%m-%d')}"


class GeopoliticalEventType(Enum):
    """Types of geopolitical events"""

    CONFLICT = "conflict"
    SANCTIONS = "sanctions"
    HOTSPOT = "hotspot"
    NATURAL_DISASTER = "natural_disaster"
    INFRASTRUCTURE_OUTAGE = "infrastructure_outage"
    MILITARY_ACTIVITY = "military_activity"
    POLITICAL_UNREST = "political_unrest"
    CYBER_ATTACK = "cyber_attack"
    ECONOMIC_CRISIS = "economic_crisis"
    TERRORISM = "terrorism"


class RiskSeverity(Enum):
    """Risk severity levels"""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class GoldImpact(Enum):
    """Potential impact on gold prices"""

    STRONGLY_BULLISH = "strongly_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONGLY_BEARISH = "strongly_bearish"


@dataclass
class GeopoliticalEvent:
    """Represents a geopolitical event that may impact markets"""

    event_type: GeopoliticalEventType
    severity: RiskSeverity
    title: str
    description: str
    region: str
    countries: list[str]
    coordinates: tuple[float, float] | None = None  # (lat, lon)
    timestamp: datetime = field(default_factory=_utc_now)
    source: str = "worldmonitor"
    confidence: float = 0.8

    # Trading impact assessment
    gold_impact: GoldImpact | None = None
    affected_currencies: list[str] = field(default_factory=list)
    risk_score: float = 0.0  # 0-100

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "region": self.region,
            "countries": self.countries,
            "coordinates": self.coordinates,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "confidence": self.confidence,
            "gold_impact": self.gold_impact.value if self.gold_impact else None,
            "affected_currencies": self.affected_currencies,
            "risk_score": self.risk_score,
        }


@dataclass
class CountryRisk:
    """Country instability index data"""

    country_code: str
    country_name: str
    instability_index: float  # 0-100 (higher = more unstable)
    trend: str  # 'increasing', 'stable', 'decreasing'
    risk_factors: list[str]
    last_updated: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "country_code": self.country_code,
            "country_name": self.country_name,
            "instability_index": self.instability_index,
            "trend": self.trend,
            "risk_factors": self.risk_factors,
            "last_updated": self.last_updated.isoformat(),
        }


@dataclass
class GeopoliticalRiskAssessment:
    """Overall geopolitical risk assessment"""

    global_risk_score: float  # 0-100
    gold_outlook: GoldImpact
    active_conflicts: int
    sanctions_count: int
    hotspots: int
    high_risk_regions: list[str]
    key_events: list[GeopoliticalEvent]
    country_risks: dict[str, CountryRisk]
    trading_recommendations: list[str]
    timestamp: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "global_risk_score": self.global_risk_score,
            "gold_outlook": self.gold_outlook.value,
            "active_conflicts": self.active_conflicts,
            "sanctions_count": self.sanctions_count,
            "hotspots": self.hotspots,
            "high_risk_regions": self.high_risk_regions,
            "key_events": [e.to_dict() for e in self.key_events],
            "country_risks": {k: v.to_dict() for k, v in self.country_risks.items()},
            "trading_recommendations": self.trading_recommendations,
            "timestamp": self.timestamp.isoformat(),
        }


class GeopoliticalRiskProvider:
    """
    Provides geopolitical risk intelligence from World Monitor.

    World Monitor is a real-time global intelligence dashboard that tracks:
    - Active conflicts and military activity
    - Sanctions regimes
    - Natural disasters and weather events
    - Infrastructure outages
    - Country instability indices

    This data is crucial for XAU/USD trading since gold prices are
    highly sensitive to geopolitical risks (safe-haven demand).
    """

    # World Monitor layer mapping to event types
    LAYER_MAPPING = {
        "conflicts": GeopoliticalEventType.CONFLICT,
        "hotspots": GeopoliticalEventType.HOTSPOT,
        "sanctions": GeopoliticalEventType.SANCTIONS,
        "weather": GeopoliticalEventType.NATURAL_DISASTER,
        "outages": GeopoliticalEventType.INFRASTRUCTURE_OUTAGE,
        "natural": GeopoliticalEventType.NATURAL_DISASTER,
        "military": GeopoliticalEventType.MILITARY_ACTIVITY,
        "protests": GeopoliticalEventType.POLITICAL_UNREST,
    }

    # Regions that significantly impact gold prices
    GOLD_SENSITIVE_REGIONS = {
        "middle_east": [
            "Iran",
            "Iraq",
            "Syria",
            "Israel",
            "Saudi Arabia",
            "Yemen",
            "Lebanon",
            "Qatar",
            "UAE",
        ],
        "eastern_europe": ["Russia", "Ukraine", "Belarus", "Poland"],
        "asia_pacific": ["China", "Taiwan", "North Korea", "South Korea", "Japan"],
        "major_economies": [
            "United States",
            "China",
            "Germany",
            "Japan",
            "United Kingdom",
            "France",
            "Italy",
        ],
    }

    # Keywords that indicate high-impact events for gold
    HIGH_IMPACT_KEYWORDS = {
        "conflict": [
            "war",
            "invasion",
            "military strike",
            "bombing",
            "attack",
            "escalation",
            "nuclear",
            "missile",
            "troops",
            "deployed",
        ],
        "sanctions": [
            "sanctions",
            "embargo",
            "trade ban",
            "asset freeze",
            "financial restrictions",
            "export controls",
        ],
        "economic": [
            "default",
            "currency crisis",
            "inflation surge",
            "bank collapse",
            "recession",
            "debt crisis",
        ],
        "political": [
            "coup",
            "assassination",
            "revolution",
            "civil unrest",
            "election crisis",
            "government collapse",
        ],
    }

    # Currency exposure by country
    COUNTRY_CURRENCIES = {
        "United States": "USD",
        "European Union": "EUR",
        "United Kingdom": "GBP",
        "Japan": "JPY",
        "Switzerland": "CHF",
        "Australia": "AUD",
        "Canada": "CAD",
        "China": "CNY",
        "Russia": "RUB",
    }

    # ISO 3166-1 alpha-2 country codes for proper code generation
    COUNTRY_ISO_CODES = {
        "United States": "US",
        "United Kingdom": "GB",
        "European Union": "EU",
        "Russia": "RU",
        "Ukraine": "UA",
        "Belarus": "BY",
        "Poland": "PL",
        "China": "CN",
        "Taiwan": "TW",
        "Japan": "JP",
        "North Korea": "KP",
        "South Korea": "KR",
        "Iran": "IR",
        "Iraq": "IQ",
        "Syria": "SY",
        "Israel": "IL",
        "Saudi Arabia": "SA",
        "Yemen": "YE",
        "Lebanon": "LB",
        "Qatar": "QA",
        "UAE": "AE",
        "Germany": "DE",
        "France": "FR",
        "Italy": "IT",
        "Switzerland": "CH",
        "Australia": "AU",
        "Canada": "CA",
    }

    def __init__(self, config: dict | None = None):
        """
        Initialize geopolitical risk provider.

        Args:
            config: Configuration dictionary with optional settings:
                - api_endpoint: World Monitor API endpoint (if using API)
                - data_layers: List of layers to monitor
                - time_range: Time range for events (e.g., '7d')
                - cache_ttl: Cache time-to-live in seconds
                - poll_interval: Background poll interval in seconds (default 300)
        """
        self.config = config or {}

        # Default configuration
        self.base_url = self.config.get("api_endpoint", "https://worldmonitor.app")
        self.time_range = self.config.get("time_range", "7d")
        self.cache_ttl = self.config.get("cache_ttl", 300)  # 5 minutes
        self._poll_interval: float = float(self.config.get("poll_interval", 300))

        # Layers to monitor (from the URL provided)
        self.data_layers = self.config.get(
            "data_layers",
            ["conflicts", "hotspots", "sanctions", "weather", "outages", "natural"],
        )

        # Cache for events
        self._cache: dict = {}
        self._cache_timestamp: datetime | None = None

        # Historical events for trend analysis
        self.event_history: list[GeopoliticalEvent] = []

        # Background polling task
        self._poll_task: asyncio.Task | None = None
        self._running: bool = False

        # Suppress repeated "all sources unavailable" warnings — log once per
        # provider lifetime, then downgrade to DEBUG to keep logs readable.
        self._all_sources_warned: bool = False

        logger.info("GeopoliticalRiskProvider initialized with layers: %s", self.data_layers)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(), name="geopolitical_risk_poll")
        logger.info(
            "GeopoliticalRiskProvider: background poll started (interval=%.0fs)",
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Cancel the background polling loop."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
        self._poll_task = None
        logger.info("GeopoliticalRiskProvider: background poll stopped")

    async def _poll_loop(self) -> None:
        """Continuously refresh geopolitical events in the background."""
        # Stagger startup by 10 s so it doesn't race with other feed startups
        await asyncio.sleep(10)
        while self._running:
            t0 = time.monotonic()
            try:
                await self._refresh_cache()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("GeopoliticalRiskProvider poll error: %s", exc)
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(1.0, self._poll_interval - elapsed))

    async def _refresh_cache(self) -> None:
        """Fetch fresh events and update the internal cache. Called by the poll loop."""
        if os.getenv("HOPEFX_CI") or os.getenv("ENVIRONMENT", "").lower() in (
            "testing",
            "test",
            "ci",
        ):
            return

        try:
            events = await self._fetch_events_from_source()
            for event in events:
                event.gold_impact = self._assess_gold_impact(event)
                event.risk_score = self._calculate_risk_score(event)
                event.affected_currencies = self._get_affected_currencies(event)

            self._cache["events"] = events
            self._cache_timestamp = datetime.now(UTC)

            cutoff = datetime.now(UTC) - timedelta(days=7)
            self.event_history.extend(events)
            self.event_history = [e for e in self.event_history if e.timestamp > cutoff]

            logger.debug("GeopoliticalRiskProvider: cache refreshed with %d events", len(events))
        except Exception as exc:
            logger.error("GeopoliticalRiskProvider: cache refresh failed: %s", exc)

    async def get_current_events(self, force_refresh: bool = False) -> list[GeopoliticalEvent]:
        """
        Return current geopolitical events.

        Normally served from the cache populated by the background poll loop.
        Pass force_refresh=True to trigger an immediate async fetch.
        """
        if not force_refresh and self._is_cache_valid():
            return self._cache.get("events", [])

        if os.getenv("HOPEFX_CI") or os.getenv("ENVIRONMENT", "").lower() in (
            "testing",
            "test",
            "ci",
        ):
            return self._cache.get("events", [])

        await self._refresh_cache()
        return self._cache.get("events", [])

    async def get_risk_assessment(self) -> GeopoliticalRiskAssessment:
        """Return a comprehensive geopolitical risk assessment."""
        events = await self.get_current_events()

        conflicts = [e for e in events if e.event_type == GeopoliticalEventType.CONFLICT]
        sanctions = [e for e in events if e.event_type == GeopoliticalEventType.SANCTIONS]
        hotspots = [e for e in events if e.event_type == GeopoliticalEventType.HOTSPOT]

        global_risk = self._calculate_global_risk(events)
        gold_outlook = self._determine_gold_outlook(events, global_risk)
        high_risk_regions = self._identify_high_risk_regions(events)
        country_risks = self._get_country_risks(events)
        recommendations = self._generate_trading_recommendations(events, global_risk, gold_outlook)

        return GeopoliticalRiskAssessment(
            global_risk_score=global_risk,
            gold_outlook=gold_outlook,
            active_conflicts=len(conflicts),
            sanctions_count=len(sanctions),
            hotspots=len(hotspots),
            high_risk_regions=high_risk_regions,
            key_events=events[:10],
            country_risks=country_risks,
            trading_recommendations=recommendations,
        )

    async def get_gold_trading_signal(self) -> dict[str, Any]:
        """Return a geopolitical-based gold trading signal."""
        assessment = await self.get_risk_assessment()

        signal_map = {
            GoldImpact.STRONGLY_BULLISH: {"direction": "BUY", "strength": 1.0},
            GoldImpact.BULLISH: {"direction": "BUY", "strength": 0.7},
            GoldImpact.NEUTRAL: {"direction": "HOLD", "strength": 0.5},
            GoldImpact.BEARISH: {"direction": "SELL", "strength": 0.7},
            GoldImpact.STRONGLY_BEARISH: {"direction": "SELL", "strength": 1.0},
        }

        signal_info = signal_map.get(assessment.gold_outlook, {"direction": "HOLD", "strength": 0.5})
        confidence = self._calculate_signal_confidence(assessment)

        return {
            "symbol": "XAUUSD",
            "direction": signal_info["direction"],
            "strength": signal_info["strength"],
            "confidence": confidence,
            "risk_score": assessment.global_risk_score,
            "gold_outlook": assessment.gold_outlook.value,
            "active_conflicts": assessment.active_conflicts,
            "key_regions": assessment.high_risk_regions[:3],
            "recommendations": assessment.trading_recommendations,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def _fetch_events_from_source(self) -> list[GeopoliticalEvent]:
        """
        Fetch live geopolitical events using a tiered source strategy:

        1. World Monitor self-hosted API — only attempted when WORLDMONITOR_API_KEY
           is set (or api_endpoint is overridden), because worldmonitor.app is an
           open-source project that must be self-hosted; it is not a public service.
        2. GDELT 2.0 Doc API — free, no key required.
        3. ACLED API — free for research; requires ACLED_API_KEY + ACLED_EMAIL.
        4. ReliefWeb API — free, no key required.
        5. In-memory cache from the previous successful fetch.
        6. Empty list (graceful degradation) — a single WARNING is emitted, not
           one per layer, so logs stay readable.

        Configuration keys (passed via __init__ config dict or env vars):
            api_endpoint    : World Monitor base URL (default "https://worldmonitor.app")
            api_key         : World Monitor Bearer token (env WORLDMONITOR_API_KEY)
            time_range      : lookback window, default "7d"
            request_timeout : HTTP timeout in seconds, default 15
        """
        api_key = self.config.get("api_key") or os.getenv("WORLDMONITOR_API_KEY", "")
        timeout_s = int(self.config.get("request_timeout", 15))
        _is_production = os.getenv("APP_ENV", "development").lower() == "production"

        # ── 1. World Monitor (self-hosted) — only when explicitly configured ──
        # worldmonitor.app is not a public API; attempting it without a key or a
        # custom endpoint just produces DNS failures and noisy log spam.
        custom_endpoint = self.config.get("api_endpoint", "")
        wm_enabled = bool(api_key or (custom_endpoint and custom_endpoint != "https://worldmonitor.app"))

        if wm_enabled:
            events = await self._fetch_from_worldmonitor(api_key, timeout_s)
            if events:
                logger.info("Fetched %d geopolitical events from World Monitor", len(events))
                return events

        # ── 2. GDELT fallback (always attempted — free, no key) ───────────────
        gdelt_events = await self._fetch_events_from_gdelt()
        if gdelt_events:
            logger.info("Fetched %d geopolitical events from GDELT", len(gdelt_events))
            return gdelt_events

        # ── 3. ACLED fallback (requires ACLED_API_KEY + ACLED_EMAIL) ──────────
        acled_events = await self._fetch_events_from_acled(timeout_s)
        if acled_events:
            logger.info("Fetched %d geopolitical events from ACLED", len(acled_events))
            return acled_events

        # ── 4. ReliefWeb fallback (free, no key) ──────────────────────────────
        reliefweb_events = await self._fetch_events_from_reliefweb(timeout_s)
        if reliefweb_events:
            logger.info("Fetched %d geopolitical events from ReliefWeb", len(reliefweb_events))
            return reliefweb_events

        # ── 5. Serve stale cache ───────────────────────────────────────────────
        cached = self._cache.get("events", [])
        if cached:
            logger.warning(
                "All geopolitical sources unavailable — serving %d cached events",
                len(cached),
            )
            return cached

        # ── 6. Graceful degradation ────────────────────────────────────────────
        if _is_production:
            raise RuntimeError(
                "All geopolitical data sources unreachable and cache is empty. "
                "Ensure outbound HTTPS access to api.gdeltproject.org, "
                "api.acleddata.com, or api.reliefweb.int. "
                "World Monitor (self-hosted): https://worldmonitor.app/"
            )
        # Warn once — subsequent identical failures are downgraded to DEBUG so
        # the log is not flooded every poll interval.
        if not self._all_sources_warned:
            logger.warning(
                "All geopolitical data sources unavailable and cache empty — "
                "returning no events. Ensure outbound HTTPS access to "
                "api.gdeltproject.org, api.acleddata.com, or api.reliefweb.int. "
                "World Monitor: https://worldmonitor.app/"
            )
            self._all_sources_warned = True
        else:
            logger.debug(
                "All geopolitical data sources still unavailable (suppressed repeat warning)."
            )
        return []

    async def _fetch_from_worldmonitor(
        self, api_key: str, timeout_s: int
    ) -> list[GeopoliticalEvent]:
        """Fetch from a self-hosted World Monitor instance."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = aiohttp.ClientTimeout(total=timeout_s)
        events: list[GeopoliticalEvent] = []
        fetch_errors: list[str] = []

        try:
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                for layer in self.data_layers:
                    url = (
                        f"{self.base_url}/api/v1/events"
                        f"?layer={layer}&range={self.time_range}&format=geojson"
                    )
                    try:
                        async with session.get(url) as resp:
                            if resp.status >= 400:
                                fetch_errors.append(f"layer={layer} HTTP {resp.status}")
                                continue
                            data = await resp.json(content_type=None)
                            layer_events = self._parse_geojson_features(
                                data.get("features", []), layer
                            )
                            events.extend(layer_events)
                    except aiohttp.ClientError as exc:
                        fetch_errors.append(f"layer={layer}: {exc}")
        except Exception as exc:
            logger.debug("World Monitor session error: %s", exc)
            return []

        if fetch_errors:
            logger.debug(
                "World Monitor: %d layer(s) failed: %s",
                len(fetch_errors),
                "; ".join(fetch_errors),
            )
        return events

    async def _fetch_events_from_gdelt(self) -> list[GeopoliticalEvent]:
        """
        Fetch geopolitical events from the GDELT Project GKG API using aiohttp.

        Uses the GDELT 2.0 Event Database query API (free, no key required).
        Filters for conflict/crisis themes relevant to gold trading.

        Reference: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
        """
        timeout_s = int(self.config.get("request_timeout", 15))
        gdelt_url = (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            "?query=gold+conflict+sanctions+geopolitical"
            "&mode=artlist&maxrecords=25&format=json"
            "&timespan=1d"
        )
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session, session.get(gdelt_url) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

            articles = data.get("articles", [])
            events: list[GeopoliticalEvent] = []
            for article in articles:
                title = article.get("title", "")
                url_str = article.get("url", "")
                seendate = article.get("seendate", "")
                domain = article.get("domain", "")
                try:
                    # GDELT seendate format: YYYYMMDDTHHMMSSZ
                    ts = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    ts = datetime.now(UTC)

                event = GeopoliticalEvent(
                    event_type=GeopoliticalEventType.POLITICAL_UNREST,
                    title=title,
                    description=f"Source: {domain} | {url_str}",
                    severity=RiskSeverity.MEDIUM,
                    region="Global",
                    countries=[],
                    timestamp=ts,
                    source="GDELT",
                )
                events.append(event)
            logger.debug("GDELT returned %d articles", len(events))
            return events
        except Exception as exc:
            logger.debug("GDELT fallback fetch failed: %s", exc)
            return []

    async def _fetch_events_from_acled(self, timeout_s: int = 15) -> list[GeopoliticalEvent]:
        """
        Fetch conflict events from the ACLED API (Armed Conflict Location & Event Data).

        Free for research/non-commercial use. Requires ACLED_API_KEY and ACLED_EMAIL
        environment variables. Returns empty list when credentials are absent.

        Reference: https://apidocs.acleddata.com/
        """
        api_key = os.getenv("ACLED_API_KEY", "")
        email = os.getenv("ACLED_EMAIL", "")
        if not api_key or not email:
            return []

        url = (
            "https://api.acleddata.com/acled/read"
            f"?key={api_key}&email={email}"
            "&limit=25&fields=event_date|event_type|country|location|notes|fatalities"
            "&event_date_where=BETWEEN"
            f"&event_date={_acled_date_range()}"
        )
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session, session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

            events: list[GeopoliticalEvent] = []
            for row in data.get("data", []):
                title = f"{row.get('event_type', 'Event')} in {row.get('location', row.get('country', 'Unknown'))}"
                notes = row.get("notes", "")
                country = row.get("country", "")
                raw_date = row.get("event_date", "")
                try:
                    ts = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    ts = datetime.now(UTC)

                fatalities = int(row.get("fatalities", 0) or 0)
                severity = (
                    RiskSeverity.CRITICAL if fatalities > 100
                    else RiskSeverity.HIGH if fatalities > 10
                    else RiskSeverity.MEDIUM if fatalities > 0
                    else RiskSeverity.LOW
                )

                events.append(GeopoliticalEvent(
                    event_type=GeopoliticalEventType.CONFLICT,
                    title=title,
                    description=notes[:500] if notes else "",
                    severity=severity,
                    region=country,
                    countries=[country] if country else [],
                    timestamp=ts,
                    source="ACLED",
                ))
            logger.debug("ACLED returned %d events", len(events))
            return events
        except Exception as exc:
            logger.debug("ACLED fallback fetch failed: %s", exc)
            return []

    async def _fetch_events_from_reliefweb(self, timeout_s: int = 15) -> list[GeopoliticalEvent]:
        """
        Fetch crisis/disaster events from the ReliefWeb API (UN OCHA).

        Free, no API key required.

        Reference: https://apidocs.reliefweb.int/
        """
        url = (
            "https://api.reliefweb.int/v1/reports"
            "?appname=hopefx-trading"
            "&filter[field]=theme.name&filter[value][]=Conflict and Violence"
            "&filter[value][]=Disaster Management"
            "&limit=25&fields[include][]=title&fields[include][]=date"
            "&fields[include][]=country&fields[include][]=body-html"
            "&sort[]=date:desc"
        )
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session, session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

            events: list[GeopoliticalEvent] = []
            for item in data.get("data", []):
                fields = item.get("fields", {})
                title = fields.get("title", "Untitled")
                raw_date = (fields.get("date") or {}).get("created", "")
                countries_raw = fields.get("country", [])
                country_names = [c.get("name", "") for c in countries_raw if isinstance(c, dict)]

                try:
                    ts = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except (ValueError, TypeError, AttributeError):
                    ts = datetime.now(UTC)

                events.append(GeopoliticalEvent(
                    event_type=GeopoliticalEventType.POLITICAL_UNREST,
                    title=title,
                    description="",
                    severity=RiskSeverity.MEDIUM,
                    region=", ".join(country_names) if country_names else "Global",
                    countries=country_names,
                    timestamp=ts,
                    source="ReliefWeb",
                ))
            logger.debug("ReliefWeb returned %d events", len(events))
            return events
        except Exception as exc:
            logger.debug("ReliefWeb fallback fetch failed: %s", exc)
            return []

    # ── Severity / type mapping helpers ──────────────────────────────────────

    _SEVERITY_MAP: dict[str, RiskSeverity] = {
        "critical": RiskSeverity.CRITICAL,
        "high": RiskSeverity.HIGH,
        "medium": RiskSeverity.MEDIUM,
        "moderate": RiskSeverity.MEDIUM,
        "low": RiskSeverity.LOW,
        "info": RiskSeverity.INFO,
        "informational": RiskSeverity.INFO,
    }

    def _parse_geojson_features(self, features: list[dict], layer: str) -> list[GeopoliticalEvent]:
        """Convert World Monitor GeoJSON features to GeopoliticalEvent objects."""
        event_type = self.LAYER_MAPPING.get(layer, GeopoliticalEventType.HOTSPOT)
        parsed: list[GeopoliticalEvent] = []

        for feat in features:
            try:
                props = feat.get("properties") or {}
                geom = feat.get("geometry") or {}

                title = str(props.get("title") or props.get("name") or "Untitled event")
                description = str(props.get("description") or props.get("summary") or "")
                region = str(props.get("region") or props.get("area") or "Global")

                # Parse countries — may be a list or comma-separated string
                raw_countries = props.get("countries") or props.get("country") or ""
                if isinstance(raw_countries, list):
                    countries = [c.strip() for c in raw_countries if c]
                else:
                    countries = [c.strip() for c in str(raw_countries).split(",") if c.strip()]

                # Parse severity
                raw_sev = str(props.get("severity") or props.get("level") or "medium").lower()
                severity = self._SEVERITY_MAP.get(raw_sev, RiskSeverity.MEDIUM)

                # Parse timestamp
                raw_ts = props.get("date") or props.get("timestamp") or props.get("updated")
                try:
                    ts = datetime.fromisoformat(str(raw_ts))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                except (TypeError, ValueError):
                    ts = datetime.now(UTC)

                # Parse coordinates [lon, lat] → (lat, lon)
                coordinates: tuple[float, float] | None = None
                if geom.get("type") == "Point":
                    coords = geom.get("coordinates", [])
                    if len(coords) >= 2:
                        coordinates = (float(coords[1]), float(coords[0]))

                # Confidence from API quality score (0–1), default 0.8
                confidence = float(props.get("confidence") or props.get("quality") or 0.8)
                confidence = max(0.0, min(1.0, confidence))

                event = GeopoliticalEvent(
                    event_type=event_type,
                    severity=severity,
                    title=title,
                    description=description,
                    region=region,
                    countries=countries,
                    coordinates=coordinates,
                    timestamp=ts,
                    source="worldmonitor",
                    confidence=confidence,
                )
                parsed.append(event)
            except Exception as exc:
                logger.debug("Skipping malformed World Monitor feature: %s", exc)

        return parsed

    def _assess_gold_impact(self, event: GeopoliticalEvent) -> GoldImpact:
        """
        Assess potential impact on gold prices.

        Gold typically rises during:
        - Military conflicts (safe-haven demand)
        - Economic sanctions (trade disruption)
        - Political instability (currency weakness)
        - Natural disasters affecting major economies
        """
        # Start with neutral
        impact_score = 0

        # Event type impact
        type_impact = {
            GeopoliticalEventType.CONFLICT: 2,
            GeopoliticalEventType.HOTSPOT: 1,
            GeopoliticalEventType.SANCTIONS: 1,
            GeopoliticalEventType.NATURAL_DISASTER: 1,
            GeopoliticalEventType.INFRASTRUCTURE_OUTAGE: 1,
            GeopoliticalEventType.MILITARY_ACTIVITY: 2,
            GeopoliticalEventType.POLITICAL_UNREST: 1,
            GeopoliticalEventType.CYBER_ATTACK: 1,
            GeopoliticalEventType.ECONOMIC_CRISIS: 2,
            GeopoliticalEventType.TERRORISM: 2,
        }
        impact_score += type_impact.get(event.event_type, 0)

        # Severity impact
        severity_impact = {
            RiskSeverity.CRITICAL: 3,
            RiskSeverity.HIGH: 2,
            RiskSeverity.MEDIUM: 1,
            RiskSeverity.LOW: 0,
            RiskSeverity.INFO: 0,
        }
        impact_score += severity_impact.get(event.severity, 0)

        # Region impact (gold-sensitive regions)
        for countries in self.GOLD_SENSITIVE_REGIONS.values():
            if any(country in countries for country in event.countries):
                impact_score += 1
                break

        # Check for high-impact keywords
        text = f"{event.title} {event.description}".lower()
        for keywords in self.HIGH_IMPACT_KEYWORDS.values():
            if any(keyword in text for keyword in keywords):
                impact_score += 1
                break

        # Map score to gold impact
        if impact_score >= 6:
            return GoldImpact.STRONGLY_BULLISH
        if impact_score >= 4:
            return GoldImpact.BULLISH
        if impact_score >= 2:
            return GoldImpact.NEUTRAL
        if impact_score >= 1:
            return GoldImpact.BEARISH
        return GoldImpact.NEUTRAL

    def _calculate_risk_score(self, event: GeopoliticalEvent) -> float:
        """Calculate risk score for an event (0-100)"""
        score = 0.0

        # Base score by severity
        severity_scores = {
            RiskSeverity.CRITICAL: 80,
            RiskSeverity.HIGH: 60,
            RiskSeverity.MEDIUM: 40,
            RiskSeverity.LOW: 20,
            RiskSeverity.INFO: 10,
        }
        score = severity_scores.get(event.severity, 30)

        # Adjust by event type
        if event.event_type in [
            GeopoliticalEventType.CONFLICT,
            GeopoliticalEventType.MILITARY_ACTIVITY,
        ]:
            score += 15

        # Adjust by region significance
        for countries in self.GOLD_SENSITIVE_REGIONS.values():
            if any(country in countries for country in event.countries):
                score += 10
                break

        # Apply confidence
        score *= event.confidence

        return min(100, score)

    def _get_affected_currencies(self, event: GeopoliticalEvent) -> list[str]:
        """Determine currencies affected by an event"""
        currencies = []

        for country in event.countries:
            if country in self.COUNTRY_CURRENCIES:
                currencies.append(self.COUNTRY_CURRENCIES[country])

        # Major events affect global reserve currencies
        if event.severity in [RiskSeverity.CRITICAL, RiskSeverity.HIGH]:
            if "USD" not in currencies:
                currencies.append("USD")
            if "CHF" not in currencies:
                currencies.append("CHF")  # Swiss franc safe haven

        return list(set(currencies))

    def _calculate_global_risk(self, events: list[GeopoliticalEvent]) -> float:
        """Calculate overall global risk score"""
        if not events:
            return 20.0  # Base risk level

        # Sum weighted risk scores
        total_risk = sum(e.risk_score for e in events)

        # Normalize by number of events using power of 0.7 for diminishing returns.
        # This ensures that 10 low-risk events don't outweigh 2 high-risk events.
        # The 0.7 exponent provides sub-linear scaling: more events increase risk
        # but at a decreasing rate, preventing score inflation from noise events.
        DIMINISHING_RETURNS_EXPONENT = 0.7
        avg_risk = total_risk / (len(events) ** DIMINISHING_RETURNS_EXPONENT) if events else 0

        # Count critical/high severity events
        critical_count = sum(1 for e in events if e.severity in [RiskSeverity.CRITICAL, RiskSeverity.HIGH])

        # Boost for multiple high-risk events
        risk_boost = min(critical_count * 5, 25)

        return min(100, avg_risk + risk_boost)

    def _determine_gold_outlook(self, events: list[GeopoliticalEvent], global_risk: float) -> GoldImpact:
        """Determine overall gold outlook based on events"""
        if not events:
            return GoldImpact.NEUTRAL

        # Count bullish vs bearish events for gold
        bullish_count = sum(1 for e in events if e.gold_impact in [GoldImpact.BULLISH, GoldImpact.STRONGLY_BULLISH])
        bearish_count = sum(1 for e in events if e.gold_impact in [GoldImpact.BEARISH, GoldImpact.STRONGLY_BEARISH])

        # Consider global risk level
        if global_risk >= 70:
            return GoldImpact.STRONGLY_BULLISH
        if global_risk >= 50 and bullish_count > bearish_count:
            return GoldImpact.BULLISH

        # Default based on event balance
        if bullish_count > bearish_count * 2:
            return GoldImpact.STRONGLY_BULLISH
        if bullish_count > bearish_count:
            return GoldImpact.BULLISH
        if bearish_count > bullish_count:
            return GoldImpact.BEARISH
        return GoldImpact.NEUTRAL

    def _identify_high_risk_regions(self, events: list[GeopoliticalEvent]) -> list[str]:
        """Identify regions with highest risk"""
        region_scores = {}

        for event in events:
            if event.region not in region_scores:
                region_scores[event.region] = 0
            region_scores[event.region] += event.risk_score

        # Sort by risk score
        sorted_regions = sorted(region_scores.items(), key=lambda x: -x[1])

        # Return top 5 high-risk regions
        return [region for region, score in sorted_regions[:5] if score >= 30]

    def _get_country_risks(self, events: list[GeopoliticalEvent]) -> dict[str, CountryRisk]:
        """Calculate risk for individual countries"""
        country_risks = {}

        for event in events:
            for country in event.countries:
                if country not in country_risks:
                    country_risks[country] = {"risk_scores": [], "factors": []}

                country_risks[country]["risk_scores"].append(event.risk_score)
                country_risks[country]["factors"].append(event.event_type.value)

        # Create CountryRisk objects
        result = {}
        for country, data in country_risks.items():
            avg_risk = sum(data["risk_scores"]) / len(data["risk_scores"])

            # Use ISO country code mapping, fall back to first 2 chars if unknown
            country_code = self.COUNTRY_ISO_CODES.get(country, country[:2].upper())

            result[country] = CountryRisk(
                country_code=country_code,
                country_name=country,
                instability_index=avg_risk,
                trend="stable",  # Would need historical data
                risk_factors=list(set(data["factors"])),
            )

        return result

    def _generate_trading_recommendations(
        self,
        events: list[GeopoliticalEvent],
        global_risk: float,
        gold_outlook: GoldImpact,
    ) -> list[str]:
        """Generate trading recommendations based on geopolitical situation"""
        recommendations = []

        # Risk-based recommendations
        if global_risk >= 70:
            recommendations.append("HIGH ALERT: Elevated geopolitical risk - Consider increasing gold allocation")
            recommendations.append("Reduce exposure to risk assets during heightened uncertainty")
        elif global_risk >= 50:
            recommendations.append("MODERATE RISK: Monitor developing situations - Gold as portfolio hedge")
        else:
            recommendations.append("LOW RISK: Geopolitical environment relatively stable")

        # Gold-specific recommendations
        if gold_outlook == GoldImpact.STRONGLY_BULLISH:
            recommendations.append("GOLD BULLISH: Strong safe-haven demand expected - Consider long XAU/USD")
        elif gold_outlook == GoldImpact.BULLISH:
            recommendations.append("GOLD POSITIVE: Moderate safe-haven flows - Favor gold on dips")
        elif gold_outlook == GoldImpact.BEARISH:
            recommendations.append("GOLD CAUTIOUS: Risk-on sentiment may pressure gold - Reduce long exposure")

        # Region-specific recommendations
        conflict_events = [e for e in events if e.event_type == GeopoliticalEventType.CONFLICT]
        if conflict_events:
            regions = {e.region for e in conflict_events}
            recommendations.append(f"Active conflicts in {', '.join(regions)} - Monitor for escalation")

        # Sanctions recommendations
        sanctions_events = [e for e in events if e.event_type == GeopoliticalEventType.SANCTIONS]
        if sanctions_events:
            countries = set()
            for e in sanctions_events:
                countries.update(e.countries)
            recommendations.append(f"Sanctions affecting {', '.join(list(countries)[:3])} - Watch commodity flows")

        return recommendations

    def _calculate_signal_confidence(self, assessment: GeopoliticalRiskAssessment) -> float:
        """Calculate confidence in the trading signal"""
        confidence = 0.5  # Base confidence

        # More events = more data = higher confidence
        event_count = len(assessment.key_events)
        if event_count >= 5:
            confidence += 0.2
        elif event_count >= 3:
            confidence += 0.1

        # Clear direction = higher confidence
        if assessment.gold_outlook in [
            GoldImpact.STRONGLY_BULLISH,
            GoldImpact.STRONGLY_BEARISH,
        ]:
            confidence += 0.2
        elif assessment.gold_outlook in [GoldImpact.BULLISH, GoldImpact.BEARISH]:
            confidence += 0.1

        # High risk = higher confidence in bullish gold
        if assessment.global_risk_score >= 60:
            confidence += 0.1

        return min(confidence, 1.0)

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if self._cache_timestamp is None:
            return False

        age = (datetime.now(UTC) - self._cache_timestamp).total_seconds()
        return age < self.cache_ttl


class WorldMonitorIntegration:
    """
    Integration layer for World Monitor dashboard.

    World Monitor URL structure (from user's link):
    https://worldmonitor.app/?lat=46.4000&lon=-163.8957&zoom=2.50&view=mena&timeRange=7d&layers=conflicts,hotspots,sanctions,weather,outages,natural

    Parameters
    ----------
    - lat/lon: Map center coordinates
    - zoom: Map zoom level
    - view: Regional view preset (global, americas, europe, mena, asia, etc.)
    - timeRange: Event time window (1h, 6h, 24h, 48h, 7d)
    - layers: Active data layers (conflicts, hotspots, sanctions, weather, outages, natural)
    """

    # Regional view presets with coordinates
    REGIONAL_VIEWS = {
        "global": {"lat": 20.0, "lon": 0.0, "zoom": 2.0},
        "americas": {"lat": 20.0, "lon": -100.0, "zoom": 3.0},
        "europe": {"lat": 50.0, "lon": 10.0, "zoom": 4.0},
        "mena": {"lat": 30.0, "lon": 45.0, "zoom": 4.0},  # Middle East & North Africa
        "asia": {"lat": 35.0, "lon": 105.0, "zoom": 3.5},
        "africa": {"lat": 0.0, "lon": 20.0, "zoom": 3.5},
        "oceania": {"lat": -25.0, "lon": 135.0, "zoom": 4.0},
    }

    # Available data layers
    DATA_LAYERS = [
        "conflicts",  # Active conflict zones
        "hotspots",  # Intelligence hotspots
        "sanctions",  # Economic sanctions
        "weather",  # Weather alerts
        "outages",  # Infrastructure outages
        "natural",  # Natural disasters
        "military",  # Military activity (bases, flights)
        "protests",  # Social unrest
        "nuclear",  # Nuclear facilities
        "pipelines",  # Energy infrastructure
        "cables",  # Undersea cables
        "datacenters",  # Major data centers
    ]

    def __init__(self, config: dict | None = None):
        """Initialize World Monitor integration"""
        self.config = config or {}
        self.base_url = "https://worldmonitor.app"

        logger.info("WorldMonitorIntegration initialized")

    def build_monitor_url(
        self,
        view: str = "global",
        time_range: str = "7d",
        layers: list[str] | None = None,
        lat: float | None = None,
        lon: float | None = None,
        zoom: float | None = None,
    ) -> str:
        """
        Build World Monitor dashboard URL.

        Args:
            view: Regional view preset
            time_range: Time range (1h, 6h, 24h, 48h, 7d)
            layers: Data layers to enable
            lat: Custom latitude
            lon: Custom longitude
            zoom: Custom zoom level

        Returns:
            Complete World Monitor URL
        """
        # Get view coordinates
        view_config = self.REGIONAL_VIEWS.get(view, self.REGIONAL_VIEWS["global"])

        # Use custom coordinates if provided
        lat = lat if lat is not None else view_config["lat"]
        lon = lon if lon is not None else view_config["lon"]
        zoom = zoom if zoom is not None else view_config["zoom"]

        # Default layers
        if layers is None:
            layers = [
                "conflicts",
                "hotspots",
                "sanctions",
                "weather",
                "outages",
                "natural",
            ]

        # Build URL
        url = f"{self.base_url}/"
        url += f"?lat={lat:.4f}"
        url += f"&lon={lon:.4f}"
        url += f"&zoom={zoom:.2f}"
        url += f"&view={view}"
        url += f"&timeRange={time_range}"
        url += f"&layers={','.join(layers)}"

        return url

    def get_gold_relevant_views(self) -> dict[str, str]:
        """
        Get World Monitor URLs for regions most relevant to gold trading.

        Returns:
            Dictionary of region names to URLs
        """
        gold_regions = {
            "middle_east": {
                "view": "mena",
                "layers": ["conflicts", "hotspots", "sanctions", "military"],
            },
            "eastern_europe": {
                "view": "europe",
                "layers": ["conflicts", "hotspots", "sanctions", "military"],
                "lat": 50.0,
                "lon": 30.0,
                "zoom": 4.5,
            },
            "asia_pacific": {
                "view": "asia",
                "layers": ["conflicts", "hotspots", "sanctions", "military"],
            },
            "global_overview": {
                "view": "global",
                "layers": ["conflicts", "hotspots", "sanctions", "weather", "outages"],
            },
        }

        urls = {}
        for region, config in gold_regions.items():
            urls[region] = self.build_monitor_url(
                view=config.get("view", "global"),
                layers=config.get("layers"),
                lat=config.get("lat"),
                lon=config.get("lon"),
                zoom=config.get("zoom"),
                time_range="7d",
            )

        return urls


class WorldMonitorAPIClient:
    """
    Direct API client for World Monitor data.

    World Monitor exposes modular REST APIs under /api/ for each data layer:
    - /api/acled.js - Armed Conflict Location & Event Data
    - /api/country-intel.js - Country-level risk, sanctions, market status
    - /api/firms-fires.js - NASA FIRMS satellite fire detection
    - /api/opensky.js - Military aircraft tracking
    - /api/theater-posture.js - Military force posture by region
    - /api/gdelt-doc.js - Global news intelligence
    - /api/cloudflare-outages.js - Internet outage monitoring

    Reference: https://github.com/koala73/worldmonitor/tree/main/api

    For self-hosting:
    1. Clone: git clone https://github.com/koala73/worldmonitor.git
    2. Install: npm install
    3. Run: npm run dev (or deploy to Vercel)
    4. Set self_hosted_url in config
    """

    # World Monitor API endpoints (Vercel Edge Functions)
    API_ENDPOINTS = {
        "conflicts": "/api/acled",  # Armed conflict events
        "country_intel": "/api/country-intel",  # Country risk & sanctions
        "fires": "/api/firms-fires",  # Satellite fire detection
        "flights": "/api/opensky",  # Military flight tracking
        "theater": "/api/theater-posture",  # Military force posture
        "news": "/api/gdelt-doc",  # Global news intelligence
        "outages": "/api/cloudflare-outages",  # Internet outages
        "earthquakes": "/api/usgs",  # Earthquake data
        "weather": "/api/weather-alerts",  # Severe weather
        "pipelines": "/api/pipelines",  # Energy infrastructure
        "cables": "/api/cables",  # Undersea cables
        "nuclear": "/api/nuclear-sites",  # Nuclear facilities
    }

    # Layer weights for gold trading (higher = more gold-relevant)
    GOLD_LAYER_WEIGHTS = {
        "conflicts": 1.0,
        "country_intel": 0.9,
        "theater": 0.8,
        "fires": 0.4,
        "news": 0.7,
        "outages": 0.5,
        "earthquakes": 0.3,
        "weather": 0.3,
        "pipelines": 0.6,
        "cables": 0.4,
        "nuclear": 0.7,
        "flights": 0.5,
    }

    def __init__(self, config: dict | None = None):
        """
        Initialize World Monitor API client.

        Args:
            config: Configuration dictionary with:
                - base_url: API base URL (default: https://worldmonitor.app)
                - self_hosted_url: URL for self-hosted instance
                - api_key: Optional API key for rate limiting bypass
                - timeout: Request timeout in seconds (default: 30)
                - enabled_layers: List of layers to fetch
                - custom_weights: Custom layer weights for gold impact
        """
        self.config = config or {}

        # Use self-hosted URL if provided, otherwise use public instance
        self.base_url = self.config.get("self_hosted_url", self.config.get("base_url", "https://worldmonitor.app"))

        self.api_key = self.config.get("api_key")
        self.timeout = self.config.get("timeout", 30)

        # Configurable layers
        self.enabled_layers = self.config.get("enabled_layers", ["conflicts", "country_intel", "news", "outages"])

        # Custom layer weights
        self.layer_weights = {**self.GOLD_LAYER_WEIGHTS}
        if "custom_weights" in self.config:
            self.layer_weights.update(self.config["custom_weights"])

        # Cache for API responses
        self._cache: dict[str, Any] = {}
        self._cache_timestamps: dict[str, datetime] = {}
        self.cache_ttl = self.config.get("cache_ttl", 300)  # 5 minutes

        logger.info("WorldMonitorAPIClient initialized with base_url: %s", self.base_url)

    async def _make_request(self, endpoint: str, params: dict | None = None) -> dict | None:
        """
        Make an async API request to World Monitor via aiohttp.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            JSON response or None if failed
        """
        url = f"{self.base_url}{endpoint}"
        headers = {"Accept": "application/json", "User-Agent": "HOPEFX-AI-Trading/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with (
                aiohttp.ClientSession(headers=headers, timeout=timeout) as session,
                session.get(url, params=params) as response,
            ):
                response.raise_for_status()
                return await response.json(content_type=None)
        except aiohttp.ClientError as e:
            logger.warning("World Monitor API request failed: %s - %s", endpoint, e)
            return None
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("World Monitor API response not JSON: %s - %s", endpoint, e)
            return None

    async def _get_cached_or_fetch(self, layer: str, params: dict | None = None) -> dict | None:
        """Get data from cache or fetch from API (async)."""
        cache_key = f"{layer}:{json.dumps(params or {}, sort_keys=True)}"

        # Check cache
        if cache_key in self._cache:
            cache_time = self._cache_timestamps.get(cache_key)
            if cache_time:
                age = (datetime.now(UTC) - cache_time).total_seconds()
                if age < self.cache_ttl:
                    return self._cache[cache_key]

        # Fetch from API
        endpoint = self.API_ENDPOINTS.get(layer)
        if not endpoint:
            logger.warning("Unknown layer: %s", layer)
            return None

        data = await self._make_request(endpoint, params)

        if data:
            self._cache[cache_key] = data
            self._cache_timestamps[cache_key] = datetime.now(UTC)

        return data

    async def get_conflicts(self, region: str | None = None) -> list[dict]:
        """
        Get active conflict events from ACLED.

        Args:
            region: Filter by region (e.g., 'Middle East', 'Europe')

        Returns:
            List of conflict events
        """
        params = {}
        if region:
            params["region"] = region

        data = await self._get_cached_or_fetch("conflicts", params)

        if data and isinstance(data, dict):
            return data.get("events", data.get("data", []))
        return []

    async def get_country_intel(self, country: str | None = None) -> dict:
        """Get country-level intelligence including risk scores and sanctions."""
        params = {}
        if country:
            params["country"] = country
        data = await self._get_cached_or_fetch("country_intel", params)
        return data or {}

    async def get_military_theater(self, theater: str | None = None) -> dict:
        """Get military force posture by theater."""
        params = {}
        if theater:
            params["theater"] = theater
        data = await self._get_cached_or_fetch("theater", params)
        return data or {}

    async def get_news_intel(self, topic: str | None = None, hours: int = 24) -> list[dict]:
        """Get global news intelligence from GDELT."""
        params: dict = {"hours": hours}
        if topic:
            params["topic"] = topic
        data = await self._get_cached_or_fetch("news", params)
        if data and isinstance(data, dict):
            return data.get("articles", data.get("news", []))
        return []

    async def get_outages(self) -> list[dict]:
        """Get current internet/infrastructure outages."""
        data = await self._get_cached_or_fetch("outages")
        if data and isinstance(data, dict):
            return data.get("outages", [])
        return []

    async def get_satellite_fires(self, region: str | None = None) -> list[dict]:
        """Get satellite fire detections from NASA FIRMS."""
        params = {}
        if region:
            params["region"] = region
        data = await self._get_cached_or_fetch("fires", params)
        if data and isinstance(data, dict):
            return data.get("fires", [])
        return []

    async def get_military_flights(self, region: str | None = None) -> list[dict]:
        """Get military flight tracking data from OpenSky."""
        params = {}
        if region:
            params["region"] = region
        data = await self._get_cached_or_fetch("flights", params)
        if data and isinstance(data, dict):
            return data.get("flights", data.get("aircraft", []))
        return []

    async def get_all_layers(self) -> dict[str, Any]:
        """Fetch data from all enabled layers concurrently."""
        tasks = {
            layer: self._get_cached_or_fetch(layer) for layer in self.enabled_layers if layer in self.API_ENDPOINTS
        }
        results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results: dict[str, Any] = {}
        for layer, result in zip(tasks.keys(), results_list, strict=True):
            if isinstance(result, Exception):
                logger.debug("WorldMonitorAPIClient layer=%s error: %s", layer, result)
            elif result:
                results[layer] = result
        return results

    async def calculate_gold_risk_score(self) -> dict[str, Any]:
        """Calculate gold-relevant risk score from all layers."""
        all_data = await self.get_all_layers()

        total_score = 0.0
        total_weight = 0.0
        layer_scores = {}

        for layer, data in all_data.items():
            weight = self.layer_weights.get(layer, 0.5)
            if isinstance(data, dict):
                event_count = len(data.get("events", data.get("data", [])))
            elif isinstance(data, list):
                event_count = len(data)
            else:
                event_count = 0

            layer_score = min(100, event_count * 10)
            layer_scores[layer] = {
                "score": layer_score,
                "weight": weight,
                "event_count": event_count,
            }
            total_score += layer_score * weight
            total_weight += weight

        final_score = total_score / total_weight if total_weight > 0 else 0

        if final_score >= 70:
            outlook = GoldImpact.STRONGLY_BULLISH
        elif final_score >= 50:
            outlook = GoldImpact.BULLISH
        elif final_score >= 30:
            outlook = GoldImpact.NEUTRAL
        else:
            outlook = GoldImpact.BEARISH

        return {
            "global_risk_score": round(final_score, 1),
            "gold_outlook": outlook.value,
            "layer_scores": layer_scores,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def clear_cache(self):
        """Clear the API response cache."""
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("World Monitor API cache cleared")


class WorldMonitorSelfHostConfig:
    """
    Configuration helper for self-hosting World Monitor.

    World Monitor can be self-hosted for:
    - Full control over data and privacy
    - Custom API rate limits
    - Extended data retention
    - Custom integrations

    Requirements:
    - Node.js 18+
    - Vercel CLI (for local dev) or any Node.js hosting
    - Optional: Redis for caching (Upstash recommended)
    - Optional: API keys for external services

    Docker deployment is also supported.
    """

    # Required environment variables for self-hosting
    ENV_TEMPLATE = {
        # AI/LLM Services (optional but recommended)
        "GROQ_API_KEY": "Your Groq API key for AI summarization",  # pragma: allowlist secret
        # Caching (optional)
        "UPSTASH_REDIS_REST_URL": "Redis URL for cross-user caching",
        "UPSTASH_REDIS_REST_TOKEN": "Redis auth token",  # nosec B105 - env var description, not a credential
        # Flight tracking (optional)
        "OPENSKY_USERNAME": "OpenSky Network username",
        "OPENSKY_PASSWORD": "OpenSky Network password",  # nosec B105 - env var description, not a credential  # pragma: allowlist secret
        # Ship tracking (optional)
        "VESSELFINDER_API_KEY": "VesselFinder API key",  # pragma: allowlist secret
        # Satellite fire detection (optional)
        "NASA_FIRMS_API_KEY": "NASA FIRMS API key",  # pragma: allowlist secret
    }

    # Docker compose template
    DOCKER_COMPOSE_TEMPLATE = """
version: '3.8'
services:
  worldmonitor:
    image: node:18-alpine
    working_dir: /app
    ports:
      - "5173:5173"
    environment:
      - NODE_ENV=production
      # Add your API keys here
      - GROQ_API_KEY=${GROQ_API_KEY:-}
      - NASA_FIRMS_API_KEY=${NASA_FIRMS_API_KEY:-}
    volumes:
      - ./worldmonitor:/app
    command: sh -c "npm install && npm run dev"

  # Optional: Redis cache
  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
"""

    @staticmethod
    def generate_setup_script() -> str:
        """Generate bash setup script for self-hosting."""
        return """#!/bin/bash
# World Monitor Self-Hosting Setup Script
# For HOPEFX AI Trading Integration

set -e

echo "=== World Monitor Self-Hosting Setup ==="

# Clone repository
if [ ! -d "worldmonitor" ]; then
    echo "Cloning World Monitor..."
    git clone https://github.com/koala73/worldmonitor.git
    cd worldmonitor
else
    echo "Updating World Monitor..."
    cd worldmonitor
    git pull
fi

# Install dependencies
echo "Installing dependencies..."
npm install

# Create .env.local if not exists
if [ ! -f ".env.local" ]; then
    echo "Creating .env.local template..."
    cat > .env.local << 'EOF'
# World Monitor Configuration
# See: https://github.com/koala73/worldmonitor/blob/main/docs/DOCUMENTATION.md

# AI Summarization (Groq - free tier available)
GROQ_API_KEY=

# Caching (Upstash Redis - free tier available)
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=

# Flight tracking (OpenSky - free registration)
OPENSKY_USERNAME=
OPENSKY_PASSWORD=

# Satellite fires (NASA FIRMS - free API key)
NASA_FIRMS_API_KEY=
EOF
    echo "Please edit .env.local with your API keys"
fi

echo ""
echo "=== Setup Complete ==="
echo "To start World Monitor:"
echo "  cd worldmonitor && npm run dev"
echo ""
echo "Dashboard will be available at: http://localhost:5173"
echo "API endpoints at: http://localhost:5173/api/"
"""

    @staticmethod
    def generate_hopefx_config(self_hosted_url: str = "http://localhost:5173") -> dict:
        """
        Generate HOPEFX configuration for self-hosted World Monitor.

        Args:
            self_hosted_url: URL of self-hosted instance

        Returns:
            Configuration dictionary for GeopoliticalRiskProvider
        """
        return {
            "self_hosted_url": self_hosted_url,
            "timeout": 30,
            "cache_ttl": 300,
            "enabled_layers": [
                "conflicts",
                "country_intel",
                "theater",
                "news",
                "outages",
            ],
            "custom_weights": {
                # Customize layer weights for your trading strategy
                "conflicts": 1.0,  # Military conflicts - highest gold impact
                "theater": 0.9,  # Military posture
                "news": 0.8,  # News intelligence
                "country_intel": 0.7,  # Country risk/sanctions
                "outages": 0.5,  # Infrastructure issues
            },
        }


class CustomDataLayerConfig:
    """
    Configure custom data layers for your specific trading needs.

    This allows you to:
    1. Enable/disable specific data layers
    2. Customize weighting for gold trading
    3. Add custom filters and regions
    4. Set alert thresholds
    """

    # Default layer configurations
    LAYER_CONFIGS = {
        "conflicts": {
            "enabled": True,
            "weight": 1.0,
            "gold_correlation": "strong_positive",
            "description": "Active armed conflicts from ACLED",
            "alert_threshold": 5,  # Alert if >5 new events
        },
        "sanctions": {
            "enabled": True,
            "weight": 0.9,
            "gold_correlation": "positive",
            "description": "Economic sanctions and trade restrictions",
            "alert_threshold": 3,
        },
        "military": {
            "enabled": True,
            "weight": 0.8,
            "gold_correlation": "strong_positive",
            "description": "Military activity, bases, flights, vessels",
            "alert_threshold": 10,
        },
        "hotspots": {
            "enabled": True,
            "weight": 0.7,
            "gold_correlation": "positive",
            "description": "Intelligence hotspots with news correlation",
            "alert_threshold": 5,
        },
        "natural": {
            "enabled": True,
            "weight": 0.5,
            "gold_correlation": "moderate_positive",
            "description": "Natural disasters, earthquakes, fires",
            "alert_threshold": 10,
        },
        "outages": {
            "enabled": True,
            "weight": 0.5,
            "gold_correlation": "moderate_positive",
            "description": "Internet and infrastructure outages",
            "alert_threshold": 5,
        },
        "weather": {
            "enabled": False,
            "weight": 0.3,
            "gold_correlation": "weak_positive",
            "description": "Severe weather alerts",
            "alert_threshold": 20,
        },
        "nuclear": {
            "enabled": True,
            "weight": 0.8,
            "gold_correlation": "strong_positive",
            "description": "Nuclear facilities and radiation monitoring",
            "alert_threshold": 1,
        },
        "pipelines": {
            "enabled": True,
            "weight": 0.6,
            "gold_correlation": "positive",
            "description": "Oil and gas infrastructure",
            "alert_threshold": 3,
        },
        "protests": {
            "enabled": False,
            "weight": 0.4,
            "gold_correlation": "moderate_positive",
            "description": "Social unrest and protests",
            "alert_threshold": 20,
        },
    }

    def __init__(self, config: dict | None = None):
        """
        Initialize custom layer configuration.

        Args:
            config: Override default configurations
        """
        self.layers = {**self.LAYER_CONFIGS}

        if config:
            for layer, settings in config.items():
                if layer in self.layers:
                    self.layers[layer].update(settings)
                else:
                    self.layers[layer] = settings

    def get_enabled_layers(self) -> list[str]:
        """Get list of enabled layer names."""
        return [name for name, cfg in self.layers.items() if cfg.get("enabled", False)]

    def get_layer_weights(self) -> dict[str, float]:
        """Get weight dictionary for enabled layers."""
        return {name: cfg["weight"] for name, cfg in self.layers.items() if cfg.get("enabled", False)}

    def enable_layer(self, layer: str, weight: float | None = None):
        """Enable a data layer."""
        if layer in self.layers:
            self.layers[layer]["enabled"] = True
            if weight is not None:
                self.layers[layer]["weight"] = weight
        else:
            self.layers[layer] = {
                "enabled": True,
                "weight": weight or 0.5,
            }

    def disable_layer(self, layer: str):
        """Disable a data layer."""
        if layer in self.layers:
            self.layers[layer]["enabled"] = False

    def set_weight(self, layer: str, weight: float):
        """Set layer weight for gold impact calculation."""
        if layer in self.layers:
            self.layers[layer]["weight"] = max(0.0, min(1.0, weight))

    def set_alert_threshold(self, layer: str, threshold: int):
        """Set alert threshold for a layer."""
        if layer in self.layers:
            self.layers[layer]["alert_threshold"] = threshold

    def get_gold_optimized_config(self) -> dict:
        """
        Get configuration optimized for gold (XAU/USD) trading.

        Returns:
            Layer configuration prioritizing gold-correlated events
        """
        gold_config = {}

        # Enable layers with strong gold correlation
        for name, cfg in self.layers.items():
            correlation = cfg.get("gold_correlation", "unknown")

            if correlation in ["strong_positive", "positive"]:
                gold_config[name] = {**cfg, "enabled": True}
            elif correlation == "moderate_positive":
                gold_config[name] = {
                    **cfg,
                    "enabled": True,
                    "weight": cfg["weight"] * 0.7,  # Reduce weight
                }
            else:
                gold_config[name] = {**cfg, "enabled": False}

        return gold_config

    def to_provider_config(self) -> dict:
        """Convert to GeopoliticalRiskProvider configuration format."""
        return {
            "data_layers": self.get_enabled_layers(),
            "custom_weights": self.get_layer_weights(),
        }


# Global provider instance
_geopolitical_provider = None
_api_client = None


def get_geopolitical_provider(
    config: dict | None = None,
) -> GeopoliticalRiskProvider:
    """Get or create global geopolitical risk provider"""
    global _geopolitical_provider
    if _geopolitical_provider is None:
        _geopolitical_provider = GeopoliticalRiskProvider(config)
    return _geopolitical_provider


def get_api_client(config: dict | None = None) -> WorldMonitorAPIClient:
    """
    Get or create global World Monitor API client.

    Args:
        config: API client configuration

    Returns:
        WorldMonitorAPIClient instance
    """
    global _api_client
    if _api_client is None:
        _api_client = WorldMonitorAPIClient(config)
    return _api_client


async def get_gold_geopolitical_signal() -> dict[str, Any]:
    """
    Async convenience function to get geopolitical-based gold trading signal.

    Returns:
        Trading signal dictionary
    """
    provider = get_geopolitical_provider()
    return await provider.get_gold_trading_signal()


async def get_gold_signal_from_api(config: dict | None = None) -> dict[str, Any]:
    """
    Get gold trading signal using direct World Monitor API (async).

    This uses the live API endpoints instead of sample data.

    Args:
        config: API client configuration

    Returns:
        Trading signal with real-time data
    """
    client = get_api_client(config)
    return await client.calculate_gold_risk_score()


def create_self_hosted_setup() -> str:
    """
    Generate setup script for self-hosting World Monitor.

    Returns:
        Bash script content
    """
    return WorldMonitorSelfHostConfig.generate_setup_script()


def get_custom_layer_config(gold_optimized: bool = True, custom_layers: dict | None = None) -> CustomDataLayerConfig:
    """
    Get custom data layer configuration.

    Args:
        gold_optimized: Use gold-optimized defaults
        custom_layers: Custom layer overrides

    Returns:
        CustomDataLayerConfig instance
    """
    config = CustomDataLayerConfig(custom_layers)

    if gold_optimized:
        gold_cfg = config.get_gold_optimized_config()
        return CustomDataLayerConfig(gold_cfg)

    return config
