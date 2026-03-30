# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
import requests
import redis
import time
from datetime import datetime, timezone


class NewsFilterIntegration:
    def __init__(
        self, redis_host="localhost", redis_port=6379, event_cache_duration=300
    ):
        self.redis_client = redis.StrictRedis(
            host=redis_host, port=redis_port, decode_responses=True
        )
        self.event_cache_duration = event_cache_duration

    def fetch_forex_events(self):
        url = "https://api.forexfactory.com/v1/events"
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for HTTP errors
            events = response.json()
            return events
        except requests.RequestException as e:
            print(f"API Error: {e}")
            return []

    def filter_events(self, events):
        now = datetime.now(timezone.utc)
        upcoming_events = []
        for event in events:
            event_time = datetime.strptime(event["date"], "%Y-%m-%d %H:%M:%S")
            if (
                0 <= (event_time - now).total_seconds() <= event["duration"] * 60
            ):  # Check if event is upcoming
                upcoming_events.append(event)
                self.cache_event(event)
        return upcoming_events

    def cache_event(self, event):
        self.redis_client.set(event["id"], event, ex=self.event_cache_duration)

    def is_trading_paused(self) -> bool:
        """Return True if trading is currently paused due to a high-impact news window.

        Checks the Redis key written by pause_trading(); falls back to False
        (allow trading) if Redis is unavailable so a connectivity issue never
        silently blocks execution.
        """
        try:
            return bool(self.redis_client.get("hopefx:news_pause"))
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "is_trading_paused: Redis unavailable, defaulting to not-paused: %s", exc
            )
            return False

    def pause_trading(self) -> None:
        """Set the news-pause flag in Redis and log the event."""
        import logging
        logging.getLogger(__name__).warning(
            "Trading paused due to high-impact news event window."
        )
        try:
            # TTL of 3600 s (1 h) as a safety net; resume_trading() clears it early.
            self.redis_client.set("hopefx:news_pause", "1", ex=3600)
        except Exception as exc:  # noqa: BLE001
            import logging as _log
            _log.getLogger(__name__).error(
                "pause_trading: failed to set Redis pause flag: %s", exc
            )

    def resume_trading(self) -> None:
        """Clear the news-pause flag so trading can resume."""
        import logging
        logging.getLogger(__name__).info("Trading resumed after news window.")
        try:
            self.redis_client.delete("hopefx:news_pause")
        except Exception as exc:  # noqa: BLE001
            import logging as _log
            _log.getLogger(__name__).error(
                "resume_trading: failed to clear Redis pause flag: %s", exc
            )

    def run(self, check_interval: int = 60) -> None:
        """Poll for high-impact news events and manage the trading pause flag."""
        import logging
        log = logging.getLogger(__name__)
        while True:
            events = self.fetch_forex_events()
            upcoming_events = self.filter_events(events)

            if upcoming_events:
                log.info("High-impact news window detected (%d event(s)) — pausing trading.", len(upcoming_events))
                self.pause_trading()
            else:
                if self.is_trading_paused():
                    self.resume_trading()
            time.sleep(check_interval)


if __name__ == "__main__":
    nf_integration = NewsFilterIntegration()
    nf_integration.run()
