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
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

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
    CENTRAL_BANK_SPEECH = "central_bank_speech"
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
    actual: Optional[float] = None
    forecast: Optional[float] = None
    previous: Optional[float] = None
    currency: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'title': self.title,
            'event_type': self.event_type.value,
            'importance': self.importance.value,
            'scheduled_time': self.scheduled_time.isoformat(),
            'country': self.country,
            'actual': self.actual,
            'forecast': self.forecast,
            'previous': self.previous,
            'currency': self.currency,
            'description': self.description
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

    def get_impact_direction(self) -> Optional[str]:
        """Determine if event is bullish or bearish for currency"""
        if self.actual is None or self.forecast is None:
            return None

        # For most economic indicators, higher than expected is bullish
        if self.actual > self.forecast:
            return 'bullish'
        elif self.actual < self.forecast:
            return 'bearish'
        else:
            return 'neutral'


class EconomicCalendar:
    """
    Economic calendar manager
    """

    # High-impact event keywords
    HIGH_IMPACT_EVENTS = {
        'interest rate', 'fomc', 'ecb rate', 'boj rate',
        'nonfarm payrolls', 'employment', 'gdp',
        'cpi', 'inflation', 'retail sales'
    }

    def __init__(self):
        self.events: List[EconomicEvent] = []
        self.logger = logging.getLogger(self.__class__.__name__)

    def add_event(self, event: EconomicEvent):
        """Add an event to the calendar"""
        self.events.append(event)
        self.events.sort(key=lambda x: x.scheduled_time)

    def get_upcoming_events(
        self,
        hours_ahead: int = 24,
        min_importance: Optional[EventImportance] = None
    ) -> List[EconomicEvent]:
        """
        Get upcoming events

        Args:
            hours_ahead: Look ahead this many hours
            min_importance: Minimum importance level

        Returns:
            List of upcoming events
        """
        now = datetime.now()
        cutoff = now + timedelta(hours=hours_ahead)

        upcoming = [
            event for event in self.events
            if now <= event.scheduled_time <= cutoff
        ]

        # Filter by importance if specified
        if min_importance:
            importance_values = {
                EventImportance.LOW: 1,
                EventImportance.MEDIUM: 2,
                EventImportance.HIGH: 3,
                EventImportance.CRITICAL: 4
            }
            min_value = importance_values[min_importance]
            upcoming = [
                event for event in upcoming
                if importance_values[event.importance] >= min_value
            ]

        return upcoming

    def get_events_by_currency(
        self,
        currency: str,
        days_ahead: int = 7
    ) -> List[EconomicEvent]:
        """Get events for a specific currency"""
        now = datetime.now()
        cutoff = now + timedelta(days=days_ahead)

        return [
            event for event in self.events
            if event.currency == currency
            and now <= event.scheduled_time <= cutoff
        ]

    def get_high_impact_events(
        self,
        hours_ahead: int = 24
    ) -> List[EconomicEvent]:
        """Get high and critical importance events"""
        return self.get_upcoming_events(
            hours_ahead=hours_ahead,
            min_importance=EventImportance.HIGH
        )

    def check_upcoming_events(
        self,
        warning_hours: int = 2
    ) -> Dict:
        """
        Check for upcoming high-impact events

        Returns dictionary with warnings
        """
        warnings = {
            'has_upcoming_events': False,
            'events': [],
            'max_importance': None,
            'earliest_event': None
        }

        upcoming = self.get_high_impact_events(hours_ahead=warning_hours)

        if upcoming:
            warnings['has_upcoming_events'] = True
            warnings['events'] = [e.to_dict() for e in upcoming]

            # Find highest importance
            importance_order = [
                EventImportance.CRITICAL,
                EventImportance.HIGH,
                EventImportance.MEDIUM,
                EventImportance.LOW
            ]

            for importance in importance_order:
                if any(e.importance == importance for e in upcoming):
                    warnings['max_importance'] = importance.value
                    break

            # Earliest event
            warnings['earliest_event'] = upcoming[0].to_dict()

        return warnings

    def create_sample_events(self, days_ahead: int = 7):
        """
        Create sample economic events for testing
        """
        now = datetime.now()

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
                description="Monthly employment report"
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
                description="Federal Reserve interest rate decision"
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
                description="European Central Bank rate decision"
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
                description="Consumer Price Index"
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
                description="Gross Domestic Product"
            )
        ]

        for event in sample_events:
            self.add_event(event)

        self.logger.info(f"Created {len(sample_events)} sample events")
        return sample_events

    def update_event_actual(
        self,
        title: str,
        actual: float,
        scheduled_time: Optional[datetime] = None
    ):
        """Update actual value for an event after it occurs"""
        for event in self.events:
            if event.title == title:
                if scheduled_time is None or event.scheduled_time == scheduled_time:
                    event.actual = actual
                    self.logger.info(f"Updated {title}: actual={actual}")
                    return event

        self.logger.warning(f"Event not found: {title}")
        return None

    def get_event_summary(self, days_ahead: int = 7) -> Dict:
        """Get summary of upcoming events"""
        upcoming = self.get_upcoming_events(hours_ahead=days_ahead * 24)

        # Count by importance
        importance_counts = {
            importance: sum(1 for e in upcoming if e.importance == importance)
            for importance in EventImportance
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
            'total_events': len(upcoming),
            'by_importance': {k.value: v for k, v in importance_counts.items()},
            'by_type': type_counts,
            'by_currency': currency_counts,
            'critical_events': importance_counts[EventImportance.CRITICAL],
            'high_impact_events': importance_counts[EventImportance.HIGH] + importance_counts[EventImportance.CRITICAL]
        }


# Global calendar instance
_economic_calendar = None


def get_economic_calendar() -> EconomicCalendar:
    """Get or create global economic calendar"""
    global _economic_calendar
    if _economic_calendar is None:
        _economic_calendar = EconomicCalendar()
    return _economic_calendar
