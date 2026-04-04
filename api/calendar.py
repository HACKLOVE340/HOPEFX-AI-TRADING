# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
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

UTC = timezone.utc
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["Economic Calendar"])

# Redis/DB config store key
_AUTO_PAUSE_KEY = "calendar:auto_pause"

# Default auto-pause config — used when no persisted value exists
_AUTO_PAUSE_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "minutes_before": 30,
    "min_importance": "high",
}

# In-process cache — refreshed from shared store on every read
_auto_pause_config: dict[str, Any] = dict(_AUTO_PAUSE_DEFAULTS)


def _get_auto_pause() -> dict[str, Any]:
    """Read auto-pause config from the shared config store (Redis → DB → defaults)."""
    global _auto_pause_config
    try:
        from core.config_store import config_store

        stored = config_store.get(_AUTO_PAUSE_KEY)
        if stored:
            _auto_pause_config = {**_AUTO_PAUSE_DEFAULTS, **stored}
            return dict(_auto_pause_config)
    except Exception as exc:
        logger.debug("_get_auto_pause: config_store read failed: %s", exc)
    return dict(_auto_pause_config)


def _save_auto_pause(config: dict[str, Any], changed_by: str = "api") -> None:
    """Persist auto-pause config to the shared config store (Redis + DB)."""
    global _auto_pause_config
    _auto_pause_config = dict(config)
    try:
        from core.config_store import config_store

        config_store.set(_AUTO_PAUSE_KEY, config, changed_by=changed_by)
    except Exception as exc:
        logger.warning("_save_auto_pause: config_store write failed: %s", exc)


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
    now = datetime.now(UTC)

    seed_events = [
        # Today / tomorrow
        {
            "title": "US Non-Farm Payrolls",
            "event_type": EventType.EMPLOYMENT,
            "importance": EventImportance.CRITICAL,
            "hours": 2,
            "country": "US",
            "currency": "USD",
            "forecast": 185.0,
            "previous": 175.0,
        },
        {
            "title": "US CPI (YoY)",
            "event_type": EventType.INFLATION,
            "importance": EventImportance.HIGH,
            "hours": 6,
            "country": "US",
            "currency": "USD",
            "forecast": 3.1,
            "previous": 3.2,
        },
        {
            "title": "FOMC Meeting Minutes",
            "event_type": EventType.CENTRAL_BANK,
            "importance": EventImportance.CRITICAL,
            "hours": 26,
            "country": "US",
            "currency": "USD",
            "forecast": None,
            "previous": None,
        },
        {
            "title": "ECB Interest Rate Decision",
            "event_type": EventType.CENTRAL_BANK,
            "importance": EventImportance.CRITICAL,
            "hours": 30,
            "country": "EU",
            "currency": "EUR",
            "forecast": 4.5,
            "previous": 4.5,
        },
        {
            "title": "UK GDP (QoQ)",
            "event_type": EventType.GDP,
            "importance": EventImportance.HIGH,
            "hours": 48,
            "country": "UK",
            "currency": "GBP",
            "forecast": 0.2,
            "previous": 0.1,
        },
        {
            "title": "US Retail Sales (MoM)",
            "event_type": EventType.RETAIL_SALES,
            "importance": EventImportance.MEDIUM,
            "hours": 52,
            "country": "US",
            "currency": "USD",
            "forecast": 0.3,
            "previous": -0.1,
        },
        {
            "title": "US Initial Jobless Claims",
            "event_type": EventType.EMPLOYMENT,
            "importance": EventImportance.MEDIUM,
            "hours": 72,
            "country": "US",
            "currency": "USD",
            "forecast": 215.0,
            "previous": 220.0,
        },
        {
            "title": "BOJ Rate Decision",
            "event_type": EventType.CENTRAL_BANK,
            "importance": EventImportance.HIGH,
            "hours": 96,
            "country": "JP",
            "currency": "JPY",
            "forecast": -0.1,
            "previous": -0.1,
        },
        {
            "title": "US PPI (MoM)",
            "event_type": EventType.INFLATION,
            "importance": EventImportance.MEDIUM,
            "hours": 120,
            "country": "US",
            "currency": "USD",
            "forecast": 0.2,
            "previous": 0.3,
        },
        {
            "title": "Michigan Consumer Sentiment",
            "event_type": EventType.CONSUMER_CONFIDENCE,
            "importance": EventImportance.LOW,
            "hours": 144,
            "country": "US",
            "currency": "USD",
            "forecast": 68.0,
            "previous": 67.4,
        },
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
    currency: str | None
    forecast: float | None
    previous: float | None
    actual: float | None
    minutes_until: int
    is_high_impact: bool


class AutoPauseConfig(BaseModel):
    enabled: bool
    minutes_before: int = 30
    min_importance: str = "high"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _event_to_out(event: Any) -> EventOut:
    now = datetime.now(UTC)
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


@router.get("/upcoming", response_model=list[EventOut])
async def get_upcoming(
    hours: int = Query(168, ge=1, le=720, description="Look-ahead window in hours"),
    importance: str | None = Query(
        None,
        description="Filter: low|medium|high|critical",
    ),
) -> list[EventOut]:
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


@router.get("/today", response_model=list[EventOut])
async def get_today() -> list[EventOut]:
    """Return today's economic events."""
    return await get_upcoming(hours=24)


@router.get("/high-impact", response_model=list[EventOut])
async def get_high_impact() -> list[EventOut]:
    """Return HIGH and CRITICAL events in the next 48 hours."""
    return await get_upcoming(hours=48, importance="high")


@router.post("/auto-pause", response_model=AutoPauseConfig)
async def set_auto_pause(config: AutoPauseConfig) -> AutoPauseConfig:
    """
    Configure auto-pause trading before high-impact events.

    Persists to the shared config store (Redis + DB) so the setting
    survives pod restarts and is shared across all replicas.
    """
    new_config = config.model_dump()
    _save_auto_pause(new_config, changed_by="calendar_api")
    logger.info("Auto-pause config updated: %s", new_config)
    return AutoPauseConfig(**new_config)


@router.get("/auto-pause", response_model=AutoPauseConfig)
async def get_auto_pause() -> AutoPauseConfig:
    """
    Return the current auto-pause config.

    Always reads from the shared config store so all pods return the
    same value regardless of which pod last wrote it.
    """
    return AutoPauseConfig(**_get_auto_pause())


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
    outcome: str | None
    set_at: str | None
    expires_at: str | None
    position_size_multiplier: float
    notes: str


@router.get("/fomc", response_model=list[FomcEvent])
async def get_fomc_calendar(upcoming_only: bool = True) -> list[FomcEvent]:
    """
    Return FOMC meeting dates with countdown timers.

    upcoming_only=true (default) returns only future meetings.
    The next meeting is flagged with is_next=True.
    Meetings within 2 hours of statement release are flagged is_within_2h=True.
    """
    now = datetime.now(UTC)
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
            ),
        )

    # Mark the soonest upcoming as is_next
    upcoming = [e for e in events if e.minutes_until > 0]
    if upcoming:
        upcoming[0] = FomcEvent(**{**upcoming[0].model_dump(), "is_next": True})
        events = [upcoming[0], *events[1:]]

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
            status_code=400,
            detail="outcome must be hawkish | dovish | neutral",
        )

    now = datetime.now(UTC)
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
        },
    )

    logger.info(
        "FOMC regime override set: outcome=%s multiplier=%.1f expires=%s",
        outcome,
        multiplier,
        expires.isoformat(),
    )

    # Persist to shared config store so it survives restarts and is pod-safe
    try:
        from core.config_store import config_store

        config_store.set("fomc_regime_override", _fomc_regime_override, changed_by="fomc_api")
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
    # Load from shared config store on first call
    if not _fomc_regime_override.get("active"):
        try:
            from core.config_store import config_store

            stored = config_store.get("fomc_regime_override")
            if stored:
                _fomc_regime_override.update(stored)
        except Exception as exc:
            logger.warning("FOMC regime load from config_store failed (non-fatal): %s", exc)

    # Auto-expire
    if _fomc_regime_override.get("active") and _fomc_regime_override.get("expires_at"):
        expires = datetime.fromisoformat(_fomc_regime_override["expires_at"])
        if datetime.now(UTC) > expires:
            _fomc_regime_override.update(
                {
                    "active": False,
                    "outcome": None,
                    "position_size_multiplier": 1.0,
                },
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
        },
    )
    try:
        from core.config_store import config_store

        config_store.delete("fomc_regime_override")
    except Exception as exc:
        logger.warning("FOMC regime config_store delete failed (non-fatal): %s", exc)
    return {"cleared": True}
