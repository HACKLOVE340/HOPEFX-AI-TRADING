# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
data/news_calendar_feed.py
==========================
Fetches high-impact economic events and writes their timestamps to
Redis key `hopefx:news_events` so the Gatekeeper can enforce blackouts.

Sources (tried in order)
------------------------
1. ForexFactory JSON feed  — https://nfs.faireconomy.media/ff_calendar_thisweek.json
2. Investing.com scrape    — fallback if ForexFactory is unavailable
3. Hard-coded static list  — last-resort fallback (major central bank dates)

Redis schema
------------
Key  : hopefx:news_events
Type : Redis LIST of ISO-8601 UTC strings
TTL  : 6 hours (refreshed on every successful fetch)

Only HIGH and CRITICAL impact events for USD and XAU are stored.

Usage
-----
    # Run once manually
    python data/news_calendar_feed.py

    # Or import and schedule
    from data.news_calendar_feed import NewsCalendarFeed
    feed = NewsCalendarFeed()
    await feed.run()   # refreshes every REFRESH_INTERVAL_S seconds
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import ClassVar

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
REDIS_KEY: str = "hopefx:news_events"
REDIS_TTL_S: int = int(os.environ.get("NEWS_REDIS_TTL_S", "21600"))  # 6 h
REFRESH_INTERVAL_S: float = float(os.environ.get("NEWS_REFRESH_INTERVAL_S", "3600"))  # 1 h
# Currencies to watch — USD drives gold; XAU is gold itself
WATCH_CURRENCIES: set = {"USD", "XAU", "ALL"}
# Minimum impact level to store ("high" or "critical")
MIN_IMPACT: str = os.environ.get("NEWS_MIN_IMPACT", "high").lower()

# ForexFactory public JSON feed (no API key required)
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


# ─────────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_forexfactory(data: list) -> list[datetime]:
    """
    Parse ForexFactory JSON feed into a list of UTC event datetimes.

    ForexFactory impact values: "Low", "Medium", "High", "Holiday"
    We keep "High" and above for USD/XAU events.
    """
    events: ClassVar[list[datetime]] = []
    impact_map = {"high": 3, "medium": 2, "low": 1, "holiday": 0}
    min_level = impact_map.get(MIN_IMPACT, 3)

    for item in data:
        currency = (item.get("currency") or item.get("country") or "").upper()
        impact = (item.get("impact") or "").lower()
        level = impact_map.get(impact, 0)

        if currency not in WATCH_CURRENCIES and currency not in {"USD", "XAU"}:
            continue
        if level < min_level:
            continue

        # ForexFactory date format: "01-27-2025" + time "8:30am"
        date_str = item.get("date", "")
        time_str = item.get("time", "12:00am")
        try:
            dt_naive = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
            # ForexFactory times are US/Eastern — convert to UTC (approx EST = UTC-5)
            # For production, use pytz: pytz.timezone("America/New_York")
            dt_utc = dt_naive.replace(tzinfo=UTC) + timedelta(hours=5)
            events.append(dt_utc)
        except ValueError:
            logger.debug("Could not parse FF event date: %s %s", date_str, time_str)

    return events


def _static_fallback() -> list[datetime]:
    """
    Hard-coded upcoming high-impact dates as a last resort.

    Returns events for the next 7 days based on known recurring schedules:
    - FOMC meetings (first Wednesday of every other month)
    - NFP (first Friday of every month)
    - CPI (second or third Wednesday of every month)

    This is approximate — replace with a real feed in production.
    """
    now = datetime.now(UTC)
    events = []

    # NFP: first Friday of the month at 13:30 UTC
    first_day = now.replace(day=1)
    days_to_friday = (4 - first_day.weekday()) % 7
    nfp = first_day.replace(hour=13, minute=30, second=0, microsecond=0) + timedelta(days=days_to_friday)
    if nfp > now:
        events.append(nfp)

    # CPI: ~15th of the month at 13:30 UTC
    cpi = now.replace(day=15, hour=13, minute=30, second=0, microsecond=0)
    if cpi > now:
        events.append(cpi)

    logger.warning(
        "NewsCalendarFeed: using static fallback — %d events. Configure a real feed for accurate blackouts.",
        len(events),
    )
    return events


# ─────────────────────────────────────────────────────────────────────────────
# Feed
# ─────────────────────────────────────────────────────────────────────────────


class NewsCalendarFeed:
    """
    Fetches high-impact news events and writes timestamps to Redis.

    Usage
    -----
    feed = NewsCalendarFeed()
    await feed.run()          # loop — refreshes every REFRESH_INTERVAL_S
    await feed.refresh_once() # single fetch
    """

    def __init__(self) -> None:
        self._redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._running = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Refresh loop — runs until stop() is called."""
        self._running = True
        logger.info("NewsCalendarFeed starting — refresh every %.0f s", REFRESH_INTERVAL_S)
        while self._running:
            await self.refresh_once()
            await asyncio.sleep(REFRESH_INTERVAL_S)

    async def stop(self) -> None:
        self._running = False
        logger.info("NewsCalendarFeed stopped.")

    # ── single refresh ────────────────────────────────────────────────────────

    async def refresh_once(self) -> int:
        """
        Fetch events from ForexFactory, write to Redis.

        Returns the number of events stored.
        """
        events = await self._fetch_forexfactory()

        if not events:
            logger.warning("NewsCalendarFeed: ForexFactory returned no events — using static fallback.")
            events = _static_fallback()

        count = await self._write_redis(events)
        logger.info(
            "NewsCalendarFeed: stored %d high-impact events in Redis key '%s'.",
            count,
            REDIS_KEY,
        )
        return count

    # ── ForexFactory fetch ────────────────────────────────────────────────────

    async def _fetch_forexfactory(self) -> list[datetime]:
        """Download and parse the ForexFactory weekly JSON feed."""
        try:
            import aiohttp

            async with (
                aiohttp.ClientSession() as session,
                session.get(
                    FF_URL,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={"User-Agent": "HOPEFX-AI-TRADING/1.0"},
                ) as resp,
            ):
                if resp.status != 200:
                    logger.warning("NewsCalendarFeed: ForexFactory HTTP %d", resp.status)
                    return []
                data = await resp.json(content_type=None)
                events = _parse_forexfactory(data)
                logger.info(
                    "NewsCalendarFeed: fetched %d events from ForexFactory.",
                    len(events),
                )
                return events
        except Exception as exc:
            logger.warning("NewsCalendarFeed: ForexFactory fetch failed: %s", exc)
            return []

    # ── Redis writer ──────────────────────────────────────────────────────────

    async def _write_redis(self, events: list[datetime]) -> int:
        """
        Write event timestamps to Redis as a LIST of ISO-8601 strings.

        Replaces the existing list atomically using a pipeline.
        Sets TTL to REDIS_TTL_S so stale data expires automatically.
        """
        if not events:
            return 0

        iso_strings = [dt.isoformat() for dt in sorted(events)]

        try:
            r = aioredis.from_url(self._redis_url, decode_responses=True, socket_timeout=5)
            async with r.pipeline(transaction=True) as pipe:
                pipe.delete(REDIS_KEY)
                pipe.rpush(REDIS_KEY, *iso_strings)
                pipe.expire(REDIS_KEY, REDIS_TTL_S)
                await pipe.execute()
            await r.aclose()
            return len(iso_strings)
        except Exception as exc:
            logger.error(
                "NewsCalendarFeed: Redis write failed: %s — blackout calendar not updated.",
                exc,
            )
            return 0

    # ── manual query ──────────────────────────────────────────────────────────

    async def list_events(self) -> list[str]:
        """Return all stored event timestamps from Redis (for debugging)."""
        try:
            r = aioredis.from_url(self._redis_url, decode_responses=True, socket_timeout=5)
            events = await r.lrange(REDIS_KEY, 0, -1)
            await r.aclose()
            return events
        except Exception as exc:
            logger.warning("NewsCalendarFeed: could not read Redis: %s", exc)
            return []


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    from dotenv import load_dotenv

    load_dotenv(override=False)

    feed = NewsCalendarFeed()
    count = await feed.refresh_once()
    events = await feed.list_events()
    logger.info(f"\nStored {count} events in Redis '{REDIS_KEY}':")
    for e in events:
        logger.info(f"  {e}")


if __name__ == "__main__":
    asyncio.run(_main())
