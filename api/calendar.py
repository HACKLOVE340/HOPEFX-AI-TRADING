"""
api/calendar.py
===============
Economic calendar endpoints.

Routes
------
GET /api/calendar/upcoming          — next 7 days of events (filterable by importance)
GET /api/calendar/today             — today's events only
GET /api/calendar/high-impact       — only HIGH/CRITICAL events in next 48h
POST /api/calendar/auto-pause       — set auto-pause trading before high-impact events
GET  /api/calendar/auto-pause       — get current auto-pause config
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["Economic Calendar"])

# Auto-pause config store (replace with DB in production)
_auto_pause_config: Dict[str, Any] = {
    "enabled": False,
    "minutes_before": 30,
    "min_importance": "high",
}


# ── Seed data helper ──────────────────────────────────────────────────────────

def _seed_calendar():
    """Return a seeded EconomicCalendar with realistic upcoming events."""
    from news.economic_calendar import EconomicCalendar, EconomicEvent, EventImportance, EventType

    cal = EconomicCalendar()
    now = datetime.now(timezone.utc)

    seed_events = [
        # Today / tomorrow
        dict(title="US Non-Farm Payrolls", event_type=EventType.EMPLOYMENT,
             importance=EventImportance.CRITICAL, hours=2, country="US",
             currency="USD", forecast=185.0, previous=175.0),
        dict(title="US CPI (YoY)", event_type=EventType.INFLATION,
             importance=EventImportance.HIGH, hours=6, country="US",
             currency="USD", forecast=3.1, previous=3.2),
        dict(title="FOMC Meeting Minutes", event_type=EventType.CENTRAL_BANK,
             importance=EventImportance.CRITICAL, hours=26, country="US",
             currency="USD", forecast=None, previous=None),
        dict(title="ECB Interest Rate Decision", event_type=EventType.CENTRAL_BANK,
             importance=EventImportance.CRITICAL, hours=30, country="EU",
             currency="EUR", forecast=4.5, previous=4.5),
        dict(title="UK GDP (QoQ)", event_type=EventType.GDP,
             importance=EventImportance.HIGH, hours=48, country="UK",
             currency="GBP", forecast=0.2, previous=0.1),
        dict(title="US Retail Sales (MoM)", event_type=EventType.RETAIL_SALES,
             importance=EventImportance.MEDIUM, hours=52, country="US",
             currency="USD", forecast=0.3, previous=-0.1),
        dict(title="US Initial Jobless Claims", event_type=EventType.EMPLOYMENT,
             importance=EventImportance.MEDIUM, hours=72, country="US",
             currency="USD", forecast=215.0, previous=220.0),
        dict(title="BOJ Rate Decision", event_type=EventType.CENTRAL_BANK,
             importance=EventImportance.HIGH, hours=96, country="JP",
             currency="JPY", forecast=-0.1, previous=-0.1),
        dict(title="US PPI (MoM)", event_type=EventType.INFLATION,
             importance=EventImportance.MEDIUM, hours=120, country="US",
             currency="USD", forecast=0.2, previous=0.3),
        dict(title="Michigan Consumer Sentiment", event_type=EventType.CONSUMER_CONFIDENCE,
             importance=EventImportance.LOW, hours=144, country="US",
             currency="USD", forecast=68.0, previous=67.4),
    ]

    for ev in seed_events:
        hours = ev.pop("hours")
        event = EconomicEvent(
            scheduled_time=now + timedelta(hours=hours),
            **ev,
        )
        cal.add_event(event)

    return cal


# ── Models ────────────────────────────────────────────────────────────────────

class EventOut(BaseModel):
    title: str
    event_type: str
    importance: str
    scheduled_time: str
    country: str
    currency: Optional[str]
    forecast: Optional[float]
    previous: Optional[float]
    actual: Optional[float]
    minutes_until: int
    is_high_impact: bool


class AutoPauseConfig(BaseModel):
    enabled: bool
    minutes_before: int = 30
    min_importance: str = "high"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event_to_out(event: Any) -> EventOut:
    now = datetime.now(timezone.utc)
    delta = event.scheduled_time - now
    minutes_until = max(0, int(delta.total_seconds() / 60))
    is_high = event.importance.value in ("high", "critical")
    return EventOut(
        title=event.title,
        event_type=event.event_type.value,
        importance=event.importance.value,
        scheduled_time=event.scheduled_time.isoformat(),
        country=event.country,
        currency=getattr(event, "currency", None),
        forecast=event.forecast,
        previous=event.previous,
        actual=event.actual,
        minutes_until=minutes_until,
        is_high_impact=is_high,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/upcoming", response_model=List[EventOut])
async def get_upcoming(
    hours: int = Query(168, ge=1, le=720, description="Look-ahead window in hours"),
    importance: Optional[str] = Query(None, description="Filter: low|medium|high|critical"),
) -> List[EventOut]:
    """Return upcoming economic events within the specified window."""
    try:
        from news.economic_calendar import EventImportance
        cal = _seed_calendar()
        min_imp = None
        if importance:
            try:
                min_imp = EventImportance(importance.lower())
            except ValueError:
                pass
        events = cal.get_upcoming_events(hours_ahead=hours, min_importance=min_imp)
        return [_event_to_out(e) for e in events]
    except Exception as exc:
        logger.warning("Calendar error: %s", exc)
        return []


@router.get("/today", response_model=List[EventOut])
async def get_today() -> List[EventOut]:
    """Return today's economic events."""
    return await get_upcoming(hours=24)


@router.get("/high-impact", response_model=List[EventOut])
async def get_high_impact() -> List[EventOut]:
    """Return HIGH and CRITICAL events in the next 48 hours."""
    return await get_upcoming(hours=48, importance="high")


@router.post("/auto-pause", response_model=AutoPauseConfig)
async def set_auto_pause(config: AutoPauseConfig) -> AutoPauseConfig:
    """Configure auto-pause trading before high-impact events."""
    _auto_pause_config.update(config.model_dump())
    logger.info("Auto-pause config updated: %s", _auto_pause_config)
    return AutoPauseConfig(**_auto_pause_config)


@router.get("/auto-pause", response_model=AutoPauseConfig)
async def get_auto_pause() -> AutoPauseConfig:
    return AutoPauseConfig(**_auto_pause_config)
