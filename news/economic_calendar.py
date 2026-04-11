# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Economic Calendar Module

Tracks major economic events and their potential market impact:
- Central bank decisions
- Economic data releases
- Earnings announcements
- Political events

Author: HOPEFX Development Team
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from enum import Enum

logger = logging.getLogger(__name__)


class EventImportance(Enum):
    """Event importance levels"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventType(Enum):
    """Economic event types"""

    INTEREST_RATE = "interest_rate"
    GDP = "gdp"
    EMPLOYMENT = "employment"
    INFLATION = "inflation"
    RETAIL_SALES = "retail_sales"
    PMI = "pmi"
    CENTRAL_BANK = "central_bank"
    CENTRAL_BANK_SPEECH = "central_bank_speech"
    CONSUMER_CONFIDENCE = "consumer_confidence"
    EARNINGS = "earnings"
    POLITICAL = "political"
    OTHER = "other"


@dataclass
class EconomicEvent:
    """Represents an economic calendar event"""

    title: str
    event_type: EventType
    importance: EventImportance
    scheduled_time: datetime
    country: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    currency: str | None = None
    description: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "title": self.title,
            "event_type": self.event_type.value,
            "importance": self.importance.value,
            "scheduled_time": self.scheduled_time.isoformat(),
            "country": self.country,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
            "currency": self.currency,
            "description": self.description,
        }

    def is_surprise(self, threshold: float = 0.1) -> bool:
        """Check if actual value significantly differs from forecast"""
        if self.actual is None or self.forecast is None:
            return False

        # Calculate percentage difference
        if self.forecast == 0:
            return self.actual != 0

        diff_pct = abs((self.actual - self.forecast) / self.forecast)
        return diff_pct > threshold

    def get_impact_direction(self) -> str | None:
        """Determine if event is bullish or bearish for currency"""
        if self.actual is None or self.forecast is None:
            return None

        # For most economic indicators, higher than expected is bullish
        if self.actual > self.forecast:
            return "bullish"
        if self.actual < self.forecast:
            return "bearish"
        return "neutral"


class EconomicCalendar:
    """
    Economic calendar manager
    """

    # High-impact event keywords
    HIGH_IMPACT_EVENTS = {
        "interest rate",
        "fomc",
        "ecb rate",
        "boj rate",
        "nonfarm payrolls",
        "employment",
        "gdp",
        "cpi",
        "inflation",
        "retail sales",
    }

    def __init__(self):
        self.events: list[EconomicEvent] = []
        self.logger = logging.getLogger(self.__class__.__name__)

    def add_event(self, event: EconomicEvent):
        """Add an event to the calendar"""
        self.events.append(event)
        self.events.sort(key=lambda x: x.scheduled_time)

    def get_upcoming_events(
        self, hours_ahead: int = 24, min_importance: EventImportance | None = None
    ) -> list[EconomicEvent]:
        """
        Get upcoming events

        Args:
            hours_ahead: Look ahead this many hours
            min_importance: Minimum importance level

        Returns:
            List of upcoming events
        """
        now = datetime.now(UTC)
        cutoff = now + timedelta(hours=hours_ahead)

        upcoming = [event for event in self.events if now <= event.scheduled_time <= cutoff]

        # Filter by importance if specified
        if min_importance:
            importance_values = {
                EventImportance.LOW: 1,
                EventImportance.MEDIUM: 2,
                EventImportance.HIGH: 3,
                EventImportance.CRITICAL: 4,
            }
            min_value = importance_values[min_importance]
            upcoming = [event for event in upcoming if importance_values[event.importance] >= min_value]

        return upcoming

    def get_events_by_currency(self, currency: str, days_ahead: int = 7) -> list[EconomicEvent]:
        """Get events for a specific currency"""
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=days_ahead)

        return [event for event in self.events if event.currency == currency and now <= event.scheduled_time <= cutoff]

    def get_high_impact_events(self, hours_ahead: int = 24) -> list[EconomicEvent]:
        """Get high and critical importance events"""
        return self.get_upcoming_events(hours_ahead=hours_ahead, min_importance=EventImportance.HIGH)

    def check_upcoming_events(self, warning_hours: int = 2) -> dict:
        """
        Check for upcoming high-impact events

        Returns dictionary with warnings
        """
        warnings = {
            "has_upcoming_events": False,
            "events": [],
            "max_importance": None,
            "earliest_event": None,
        }

        upcoming = self.get_high_impact_events(hours_ahead=warning_hours)

        if upcoming:
            warnings["has_upcoming_events"] = True
            warnings["events"] = [e.to_dict() for e in upcoming]

            # Find highest importance
            importance_order = [
                EventImportance.CRITICAL,
                EventImportance.HIGH,
                EventImportance.MEDIUM,
                EventImportance.LOW,
            ]

            for importance in importance_order:
                if any(e.importance == importance for e in upcoming):
                    warnings["max_importance"] = importance.value
                    break

            # Earliest event
            warnings["earliest_event"] = upcoming[0].to_dict()

        return warnings

    def create_sample_events(self, days_ahead: int = 7):
        """
        Create sample economic events for testing
        """
        now = datetime.now(UTC)

        sample_events = [
            EconomicEvent(
                title="US Nonfarm Payrolls",
                event_type=EventType.EMPLOYMENT,
                importance=EventImportance.CRITICAL,
                scheduled_time=now + timedelta(days=1, hours=8, minutes=30),
                country="US",
                forecast=200000,
                previous=185000,
                currency="USD",
                description="Monthly employment report",
            ),
            EconomicEvent(
                title="FOMC Interest Rate Decision",
                event_type=EventType.INTEREST_RATE,
                importance=EventImportance.CRITICAL,
                scheduled_time=now + timedelta(days=3, hours=14),
                country="US",
                forecast=5.25,
                previous=5.00,
                currency="USD",
                description="Federal Reserve interest rate decision",
            ),
            EconomicEvent(
                title="ECB Interest Rate Decision",
                event_type=EventType.INTEREST_RATE,
                importance=EventImportance.CRITICAL,
                scheduled_time=now + timedelta(days=5, hours=12, minutes=45),
                country="EU",
                forecast=4.00,
                previous=4.00,
                currency="EUR",
                description="European Central Bank rate decision",
            ),
            EconomicEvent(
                title="US CPI",
                event_type=EventType.INFLATION,
                importance=EventImportance.HIGH,
                scheduled_time=now + timedelta(days=2, hours=8, minutes=30),
                country="US",
                forecast=3.2,
                previous=3.1,
                currency="USD",
                description="Consumer Price Index",
            ),
            EconomicEvent(
                title="UK GDP",
                event_type=EventType.GDP,
                importance=EventImportance.HIGH,
                scheduled_time=now + timedelta(days=4, hours=7),
                country="UK",
                forecast=0.3,
                previous=0.2,
                currency="GBP",
                description="Gross Domestic Product",
            ),
        ]

        for event in sample_events:
            self.add_event(event)

        self.logger.info("Created %s sample events", len(sample_events))

        return sample_events

    def update_event_actual(self, title: str, actual: float, scheduled_time: datetime | None = None):
        """Update actual value for an event after it occurs"""
        for event in self.events:
            if event.title == title and (scheduled_time is None or event.scheduled_time == scheduled_time):
                event.actual = actual
                self.logger.info("Updated %s: actual=%s", title, actual)

                return event

        self.logger.warning("Event not found: %s", title)

        return None

    def get_event_summary(self, days_ahead: int = 7) -> dict:
        """Get summary of upcoming events"""
        upcoming = self.get_upcoming_events(hours_ahead=days_ahead * 24)

        # Count by importance
        importance_counts = {
            importance: sum(1 for e in upcoming if e.importance == importance) for importance in EventImportance
        }

        # Count by type
        type_counts = {}
        for event in upcoming:
            type_counts[event.event_type.value] = type_counts.get(event.event_type.value, 0) + 1

        # Count by currency
        currency_counts = {}
        for event in upcoming:
            if event.currency:
                currency_counts[event.currency] = currency_counts.get(event.currency, 0) + 1

        return {
            "total_events": len(upcoming),
            "by_importance": {k.value: v for k, v in importance_counts.items()},
            "by_type": type_counts,
            "by_currency": currency_counts,
            "critical_events": importance_counts[EventImportance.CRITICAL],
            "high_impact_events": importance_counts[EventImportance.HIGH] + importance_counts[EventImportance.CRITICAL],
        }


# ── Live feed ─────────────────────────────────────────────────────────────────

# Finnhub impact → EventImportance mapping
_FINNHUB_IMPACT_MAP: dict[str, EventImportance] = {
    "1": EventImportance.LOW,
    "2": EventImportance.MEDIUM,
    "3": EventImportance.HIGH,
}

# Finnhub event name keywords → EventType
_KEYWORD_TYPE_MAP: list[tuple[str, EventType]] = [
    ("interest rate", EventType.INTEREST_RATE),
    ("rate decision", EventType.INTEREST_RATE),
    ("fomc", EventType.CENTRAL_BANK),
    ("ecb", EventType.CENTRAL_BANK),
    ("boj", EventType.CENTRAL_BANK),
    ("boe", EventType.CENTRAL_BANK),
    ("central bank", EventType.CENTRAL_BANK),
    ("speech", EventType.CENTRAL_BANK_SPEECH),
    ("press conference", EventType.CENTRAL_BANK_SPEECH),
    ("gdp", EventType.GDP),
    ("nonfarm", EventType.EMPLOYMENT),
    ("non-farm", EventType.EMPLOYMENT),
    ("employment", EventType.EMPLOYMENT),
    ("jobless", EventType.EMPLOYMENT),
    ("unemployment", EventType.EMPLOYMENT),
    ("cpi", EventType.INFLATION),
    ("ppi", EventType.INFLATION),
    ("inflation", EventType.INFLATION),
    ("retail sales", EventType.RETAIL_SALES),
    ("pmi", EventType.PMI),
    ("consumer confidence", EventType.CONSUMER_CONFIDENCE),
    ("consumer sentiment", EventType.CONSUMER_CONFIDENCE),
]

# Country code → ISO currency
_COUNTRY_CURRENCY: dict[str, str] = {
    "US": "USD",
    "EU": "EUR",
    "GB": "GBP",
    "JP": "JPY",
    "CA": "CAD",
    "AU": "AUD",
    "NZ": "NZD",
    "CH": "CHF",
    "CN": "CNY",
}


def _classify_event_type(title: str) -> EventType:
    lower = title.lower()
    for keyword, etype in _KEYWORD_TYPE_MAP:
        if keyword in lower:
            return etype
    return EventType.OTHER


def fetch_live_calendar(days_ahead: int = 7) -> "EconomicCalendar":
    """
    Fetch the economic calendar from Finnhub's REST API.

    Requires FINNHUB_API_KEY env var. Returns a populated EconomicCalendar.
    Raises RuntimeError when the API key is absent or the request fails.

    Finnhub endpoint: GET https://finnhub.io/api/v1/calendar/economic
    Docs: https://finnhub.io/docs/api/economic-calendar
    """
    import json
    import os
    import urllib.request
    from datetime import date

    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is not set — cannot fetch live economic calendar")

    today = date.today()
    end_date = today + timedelta(days=days_ahead)
    url = (
        f"https://finnhub.io/api/v1/calendar/economic"
        f"?from={today.isoformat()}&to={end_date.isoformat()}&token={api_key}"
    )

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — hardcoded https:// Finnhub URL
        payload = json.loads(resp.read())

    cal = EconomicCalendar()
    for item in payload.get("economicCalendar", []):
        try:
            # Parse scheduled time — Finnhub returns "YYYY-MM-DD HH:MM:SS" UTC
            time_str = item.get("time", "")
            if time_str:
                scheduled = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            else:
                date_str = item.get("date", "")
                scheduled = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, tzinfo=UTC)

            country = (item.get("country") or "").upper()
            currency = _COUNTRY_CURRENCY.get(country)
            impact_raw = str(item.get("impact", "1"))
            # Finnhub uses "low"/"medium"/"high" strings in some versions
            if impact_raw in _FINNHUB_IMPACT_MAP:
                importance = _FINNHUB_IMPACT_MAP[impact_raw]
            elif impact_raw.lower() == "high":
                importance = EventImportance.HIGH
            elif impact_raw.lower() == "medium":
                importance = EventImportance.MEDIUM
            else:
                importance = EventImportance.LOW

            title = item.get("event", "Unknown Event")
            event = EconomicEvent(
                title=title,
                event_type=_classify_event_type(title),
                importance=importance,
                scheduled_time=scheduled,
                country=country,
                currency=currency,
                forecast=_safe_float(item.get("estimate")),
                previous=_safe_float(item.get("prev")),
                actual=_safe_float(item.get("actual")),
            )
            cal.add_event(event)
        except Exception as exc:
            logger.debug("Skipping malformed Finnhub calendar item: %s — %s", item, exc)

    logger.info("Fetched %d events from Finnhub economic calendar", len(cal.events))
    return cal


def _safe_float(value) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Global calendar instance
_economic_calendar = None


def get_economic_calendar() -> EconomicCalendar:
    """Get or create global economic calendar"""
    global _economic_calendar
    if _economic_calendar is None:
        _economic_calendar = EconomicCalendar()
    return _economic_calendar
