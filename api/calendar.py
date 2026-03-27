# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
    from news.economic_calendar import (
        EconomicCalendar,
        EconomicEvent,
        EventImportance,
        EventType,
    )

    cal = EconomicCalendar()
    now = datetime.now(timezone.utc)

    seed_events = [
        # Today / tomorrow
        dict(
            title="US Non-Farm Payrolls",
            event_type=EventType.EMPLOYMENT,
            importance=EventImportance.CRITICAL,
            hours=2,
            country="US",
            currency="USD",
            forecast=185.0,
            previous=175.0,
        ),
        dict(
            title="US CPI (YoY)",
            event_type=EventType.INFLATION,
            importance=EventImportance.HIGH,
            hours=6,
            country="US",
            currency="USD",
            forecast=3.1,
            previous=3.2,
        ),
        dict(
            title="FOMC Meeting Minutes",
            event_type=EventType.CENTRAL_BANK,
            importance=EventImportance.CRITICAL,
            hours=26,
            country="US",
            currency="USD",
            forecast=None,
            previous=None,
        ),
        dict(
            title="ECB Interest Rate Decision",
            event_type=EventType.CENTRAL_BANK,
            importance=EventImportance.CRITICAL,
            hours=30,
            country="EU",
            currency="EUR",
            forecast=4.5,
            previous=4.5,
        ),
        dict(
            title="UK GDP (QoQ)",
            event_type=EventType.GDP,
            importance=EventImportance.HIGH,
            hours=48,
            country="UK",
            currency="GBP",
            forecast=0.2,
            previous=0.1,
        ),
        dict(
            title="US Retail Sales (MoM)",
            event_type=EventType.RETAIL_SALES,
            importance=EventImportance.MEDIUM,
            hours=52,
            country="US",
            currency="USD",
            forecast=0.3,
            previous=-0.1,
        ),
        dict(
            title="US Initial Jobless Claims",
            event_type=EventType.EMPLOYMENT,
            importance=EventImportance.MEDIUM,
            hours=72,
            country="US",
            currency="USD",
            forecast=215.0,
            previous=220.0,
        ),
        dict(
            title="BOJ Rate Decision",
            event_type=EventType.CENTRAL_BANK,
            importance=EventImportance.HIGH,
            hours=96,
            country="JP",
            currency="JPY",
            forecast=-0.1,
            previous=-0.1,
        ),
        dict(
            title="US PPI (MoM)",
            event_type=EventType.INFLATION,
            importance=EventImportance.MEDIUM,
            hours=120,
            country="US",
            currency="USD",
            forecast=0.2,
            previous=0.3,
        ),
        dict(
            title="Michigan Consumer Sentiment",
            event_type=EventType.CONSUMER_CONFIDENCE,
            importance=EventImportance.LOW,
            hours=144,
            country="US",
            currency="USD",
            forecast=68.0,
            previous=67.4,
        ),
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
    importance: Optional[str] = Query(
        None, description="Filter: low|medium|high|critical"
    ),
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
                logger.warning(
                    "get_upcoming: unrecognised importance value %r — returning all events",
                    importance,
                )
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


# ── FOMC calendar + post-event regime adjustment ──────────────────────────────

# Known 2024-2026 FOMC meeting dates (UTC, 18:00 = statement release)
_FOMC_DATES = [
    "2024-01-31",
    "2024-03-20",
    "2024-05-01",
    "2024-06-12",
    "2024-07-31",
    "2024-09-18",
    "2024-11-07",
    "2024-12-18",
    "2025-01-29",
    "2025-03-19",
    "2025-05-07",
    "2025-06-18",
    "2025-07-30",
    "2025-09-17",
    "2025-11-05",
    "2025-12-17",
    "2026-01-28",
    "2026-03-18",
    "2026-05-06",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-11-04",
    "2026-12-16",
]

# In-memory store for post-event regime overrides
_fomc_regime_override: dict = {
    "active": False,
    "outcome": None,  # "hawkish" | "dovish" | "neutral"
    "set_at": None,
    "expires_at": None,  # 48h after event
    "position_size_multiplier": 1.0,
    "notes": "",
}


class FomcEvent(BaseModel):
    date: str
    time_utc: str = "18:00"
    minutes_until: int
    is_next: bool
    is_within_2h: bool


class FomcRegimeOverride(BaseModel):
    outcome: str  # "hawkish" | "dovish" | "neutral"
    notes: str = ""


class FomcRegimeStatus(BaseModel):
    active: bool
    outcome: Optional[str]
    set_at: Optional[str]
    expires_at: Optional[str]
    position_size_multiplier: float
    notes: str


@router.get("/fomc", response_model=List[FomcEvent])
async def get_fomc_calendar(upcoming_only: bool = True) -> List[FomcEvent]:
    """
    Return FOMC meeting dates with countdown timers.

    upcoming_only=true (default) returns only future meetings.
    The next meeting is flagged with is_next=True.
    Meetings within 2 hours of statement release are flagged is_within_2h=True.
    """
    now = datetime.now(timezone.utc)
    events = []
    for date_str in _FOMC_DATES:
        dt = datetime.fromisoformat(f"{date_str}T18:00:00+00:00")
        delta_min = int((dt - now).total_seconds() / 60)
        if upcoming_only and delta_min < -60:
            continue
        events.append(
            FomcEvent(
                date=date_str,
                time_utc="18:00",
                minutes_until=max(0, delta_min),
                is_next=False,
                is_within_2h=abs(delta_min) <= 120,
            )
        )

    # Mark the soonest upcoming as is_next
    upcoming = [e for e in events if e.minutes_until > 0]
    if upcoming:
        upcoming[0] = FomcEvent(**{**upcoming[0].model_dump(), "is_next": True})
        events = [upcoming[0]] + events[1:]

    return events


@router.post("/fomc/regime", response_model=FomcRegimeStatus)
async def set_fomc_regime(body: FomcRegimeOverride) -> FomcRegimeStatus:
    """
    Record the FOMC outcome and apply a 48-hour regime adjustment.

    Outcome classification:
    - hawkish  → rate hike / hawkish surprise → reduce gold position size 20%
    - dovish   → rate cut / dovish surprise   → increase gold position size 20%
    - neutral  → as expected                  → no change

    The multiplier is read by the signal engine when sizing positions.
    """
    outcome = body.outcome.lower()
    if outcome not in ("hawkish", "dovish", "neutral"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400, detail="outcome must be hawkish | dovish | neutral"
        )

    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=48)

    multiplier = {"hawkish": 0.8, "dovish": 1.2, "neutral": 1.0}[outcome]

    _fomc_regime_override.update(
        {
            "active": True,
            "outcome": outcome,
            "set_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "position_size_multiplier": multiplier,
            "notes": body.notes,
        }
    )

    logger.info(
        "FOMC regime override set: outcome=%s multiplier=%.1f expires=%s",
        outcome,
        multiplier,
        expires.isoformat(),
    )

    # Persist to DB so it survives restarts
    try:
        from api.db_store import db_set

        db_set("fomc_regime_override", _fomc_regime_override, changed_by="fomc_api")
    except Exception as exc:
        logger.warning("FOMC regime persist failed (non-fatal): %s", exc)

    return FomcRegimeStatus(**_fomc_regime_override)


@router.get("/fomc/regime", response_model=FomcRegimeStatus)
async def get_fomc_regime() -> FomcRegimeStatus:
    """
    Return the current FOMC regime override status.

    If the override has expired, it is automatically cleared.
    The position_size_multiplier is used by the signal engine.
    """
    # Load from DB on first call
    if not _fomc_regime_override.get("active"):
        try:
            from api.db_store import db_get

            stored = db_get("fomc_regime_override")
            if stored:
                _fomc_regime_override.update(stored)
        except Exception as exc:
            logger.warning("FOMC regime load from DB failed (non-fatal): %s", exc)

    # Auto-expire
    if _fomc_regime_override.get("active") and _fomc_regime_override.get("expires_at"):
        expires = datetime.fromisoformat(_fomc_regime_override["expires_at"])
        if datetime.now(timezone.utc) > expires:
            _fomc_regime_override.update(
                {
                    "active": False,
                    "outcome": None,
                    "position_size_multiplier": 1.0,
                }
            )

    return FomcRegimeStatus(**_fomc_regime_override)


@router.delete("/fomc/regime")
async def clear_fomc_regime() -> dict:
    """Manually clear the FOMC regime override."""
    _fomc_regime_override.update(
        {
            "active": False,
            "outcome": None,
            "set_at": None,
            "expires_at": None,
            "position_size_multiplier": 1.0,
            "notes": "",
        }
    )
    try:
        from api.db_store import db_delete

        db_delete("fomc_regime_override")
    except Exception as exc:
        logger.warning("FOMC regime DB delete failed (non-fatal): %s", exc)
    return {"cleared": True}
