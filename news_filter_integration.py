# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
import json
import logging
import os
import time
from datetime import datetime, timezone

import redis
import requests

UTC = timezone.utc

logger = logging.getLogger(__name__)


class NewsFilterIntegration:
    def __init__(self, redis_host="localhost", redis_port=6379, event_cache_duration=300):
        self.redis_client = redis.StrictRedis(host=redis_host, port=redis_port, decode_responses=True)
        self.event_cache_duration = event_cache_duration

    # ForexFactory calendar endpoint — returns JSON array of upcoming events.
    # Override via NEWS_FEED_URL env var to point at an alternative provider.
    NEWS_FEED_URL: str = os.getenv(
        "NEWS_FEED_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    )

    def fetch_forex_events(self):
        try:
            response = requests.get(
                self.NEWS_FEED_URL,
                timeout=10,
                headers={"User-Agent": "HOPEFX-AI-TRADING/1.0"},
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.error("fetch_forex_events: request failed: %s", exc)
            return []
        except ValueError as exc:
            logger.error("fetch_forex_events: invalid JSON response: %s", exc)
            return []

    def filter_events(self, events):
        log = logging.getLogger(__name__)
        now = datetime.now(UTC)
        upcoming_events = []
        for event in events:
            try:
                raw = event.get("date", "")
                # Parse as UTC-aware; ForexFactory returns UTC timestamps.
                event_time = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                duration_s = float(event.get("duration", 0)) * 60
                delta = (event_time - now).total_seconds()
                if 0 <= delta <= duration_s:
                    upcoming_events.append(event)
                    self.cache_event(event)
            except (KeyError, ValueError, TypeError) as exc:
                log.warning("filter_events: skipping malformed event %r: %s", event, exc)
        return upcoming_events

    def cache_event(self, event):
        key = f"hopefx:news_event:{event['id']}"
        try:
            self.redis_client.set(key, json.dumps(event), ex=self.event_cache_duration)
        except Exception as exc:
            logger.warning("cache_event: failed to cache event %s: %s", event.get("id"), exc)

    def is_trading_paused(self) -> bool:
        """Return True if trading is currently paused due to a high-impact news window.

        Checks the Redis key written by pause_trading(); falls back to False
        (allow trading) if Redis is unavailable so a connectivity issue never
        silently blocks execution.
        """
        try:
            return bool(self.redis_client.get("hopefx:news_pause"))
        except Exception as exc:
            logger.warning(
                "is_trading_paused: Redis unavailable, defaulting to not-paused: %s",
                exc,
            )
            return False

    def pause_trading(self) -> None:
        """Set the news-pause flag in Redis and log the event."""
        logger.warning("Trading paused due to high-impact news event window.")
        try:
            # TTL of 3600 s (1 h) as a safety net; resume_trading() clears it early.
            self.redis_client.set("hopefx:news_pause", "1", ex=3600)
        except Exception as exc:
            logger.error("pause_trading: failed to set Redis pause flag: %s", exc)

    def resume_trading(self) -> None:
        """Clear the news-pause flag so trading can resume."""
        logger.info("Trading resumed after news window.")
        try:
            self.redis_client.delete("hopefx:news_pause")
        except Exception as exc:
            logger.error("resume_trading: failed to clear Redis pause flag: %s", exc)

    def run(self, check_interval: int = 60) -> None:
        """Poll for high-impact news events and manage the trading pause flag."""
        while True:
            events = self.fetch_forex_events()
            upcoming_events = self.filter_events(events)

            if upcoming_events:
                logger.info(
                    "High-impact news window detected (%d event(s)) — pausing trading.",
                    len(upcoming_events),
                )
                self.pause_trading()
            elif self.is_trading_paused():
                self.resume_trading()
            time.sleep(check_interval)


if __name__ == "__main__":
    nf_integration = NewsFilterIntegration()
    nf_integration.run()
