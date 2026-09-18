# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
mobile/analytics.py
====================
MobileAnalytics — tracks mobile app usage events and performance metrics.

Events are persisted to the real database when wired via app_state or db,
and flushed in batches to avoid per-event write overhead.

Wire by passing app_state (with .db attribute) or db directly:

    analytics = MobileAnalytics(app_state=app_state)
    analytics = MobileAnalytics(db=db_session)

Without wiring, events are buffered in memory only (useful for testing).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

# Maximum in-memory buffer before forced flush
_BUFFER_LIMIT = 500
# Batch flush interval in seconds (when background flushing is enabled)
_FLUSH_INTERVAL_S = 30


class MobileAnalytics:
    """
    Mobile app analytics tracker.

    Tracks screen views, user actions, performance metrics, and errors.
    Persists to the real database when wired; buffers in memory otherwise.
    """

    def __init__(
        self,
        app_state: Any | None = None,
        db: Any | None = None,
        enable_background_flush: bool = False,
    ) -> None:
        self._app_state = app_state
        self._db = db
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._session_counts: dict[str, int] = defaultdict(int)
        self._flush_timer: threading.Timer | None = None

        if enable_background_flush:
            self._schedule_flush()

    # ── DB access ─────────────────────────────────────────────────────────────

    def _get_db(self) -> Any:
        if self._db is not None:
            return self._db
        if self._app_state is not None:
            return getattr(self._app_state, "db", None)
        return None

    # ── Core event tracking ───────────────────────────────────────────────────

    def track_event(
        self,
        user_id: str,
        event_type: str,
        properties: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> None:
        """
        Track an analytics event.

        Buffers the event and flushes to DB when buffer reaches _BUFFER_LIMIT
        or when flush() is called explicitly.
        """
        event: dict[str, Any] = {
            "user_id": user_id,
            "event_type": event_type,
            "properties": properties or {},
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        with self._lock:
            self._buffer.append(event)
            self._session_counts[f"{user_id}:{event_type}"] += 1

            if len(self._buffer) >= _BUFFER_LIMIT:
                self._flush_locked()

    def track_screen_view(
        self,
        user_id: str,
        screen_name: str,
        session_id: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Track a screen view with optional dwell time."""
        props: dict[str, Any] = {"screen": screen_name}
        if duration_ms is not None:
            props["duration_ms"] = duration_ms
        self.track_event(user_id, "screen_view", props, session_id)

    def track_trade_action(
        self,
        user_id: str,
        action: str,
        symbol: str,
        side: str | None = None,
        quantity: float | None = None,
        result: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Track a trading action (place_order, cancel_order, close_position)."""
        props: dict[str, Any] = {
            "action": action,
            "symbol": symbol,
        }
        if side:
            props["side"] = side
        if quantity:
            props["quantity"] = quantity
        if result:
            props["result"] = result
        if latency_ms:
            props["latency_ms"] = latency_ms
        self.track_event(user_id, "trade_action", props)

    def track_signal_interaction(
        self,
        user_id: str,
        signal_id: str,
        action: str,
        symbol: str,
        direction: str,
        confidence: float,
    ) -> None:
        """Track signal view / approve / dismiss interactions."""
        self.track_event(
            user_id,
            "signal_interaction",
            {
                "signal_id": signal_id,
                "action": action,
                "symbol": symbol,
                "direction": direction,
                "confidence": confidence,
            },
        )

    def track_error(
        self,
        user_id: str,
        error_type: str,
        message: str,
        screen: str | None = None,
        stack_trace: str | None = None,
    ) -> None:
        """Track a client-side error."""
        props: dict[str, Any] = {
            "error_type": error_type,
            "message": message,
        }
        if screen:
            props["screen"] = screen
        if stack_trace:
            props["stack_trace"] = stack_trace[:2000]  # truncate
        self.track_event(user_id, "error", props)
        logger.warning(
            "MobileAnalytics error tracked: user=%s type=%s msg=%s",
            user_id,
            error_type,
            message,
        )

    def track_performance(
        self,
        user_id: str,
        metric: str,
        value_ms: float,
        context: str | None = None,
    ) -> None:
        """Track a performance metric (e.g. WS latency, render time)."""
        props: dict[str, Any] = {"metric": metric, "value_ms": value_ms}
        if context:
            props["context"] = context
        self.track_event(user_id, "performance", props)

    def track_notification_interaction(
        self,
        user_id: str,
        notification_type: str,
        action: str,
    ) -> None:
        """Track push notification tap / dismiss."""
        self.track_event(
            user_id,
            "notification_interaction",
            {
                "notification_type": notification_type,
                "action": action,
            },
        )

    # ── Session stats ─────────────────────────────────────────────────────────

    def get_event_count(self, user_id: str, event_type: str) -> int:
        """Return in-memory count for a user+event_type pair."""
        return self._session_counts.get(f"{user_id}:{event_type}", 0)

    def get_buffer_size(self) -> int:
        with self._lock:
            return len(self._buffer)

    # ── Flush to DB ───────────────────────────────────────────────────────────

    def flush(self) -> int:
        """Flush buffered events to DB. Returns number of events flushed."""
        with self._lock:
            return self._flush_locked()

    def _flush_locked(self) -> int:
        """Must be called with self._lock held."""
        if not self._buffer:
            return 0

        events = self._buffer[:]
        self._buffer.clear()

        db = self._get_db()
        if db is None:
            # No DB wired — events are discarded after buffer clear
            logger.debug("MobileAnalytics: no DB wired, %d events discarded", len(events))
            return len(events)

        try:
            # Try bulk insert if DB supports it
            fn_bulk = getattr(db, "bulk_insert_analytics", None)
            if fn_bulk:
                fn_bulk(events)
            else:
                # Fall back to individual inserts
                fn_insert = getattr(db, "insert_analytics_event", None)
                if fn_insert:
                    for ev in events:
                        try:
                            fn_insert(ev)
                        except Exception as exc:
                            logger.warning("MobileAnalytics: insert failed: %s", exc)

            logger.debug("MobileAnalytics: flushed %d events to DB", len(events))
            return len(events)
        except Exception:
            logger.exception("MobileAnalytics: flush failed")
            # Re-buffer events on failure to avoid data loss
            with self._lock:
                self._buffer = events + self._buffer
            return 0

    def _schedule_flush(self) -> None:
        """Schedule periodic background flush."""
        self._flush_timer = threading.Timer(_FLUSH_INTERVAL_S, self._background_flush)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _background_flush(self) -> None:
        try:
            flushed = self.flush()
            if flushed:
                logger.debug("MobileAnalytics: background flush: %d events", flushed)
        except Exception as exc:
            logger.warning("MobileAnalytics: background flush error: %s", exc)
        finally:
            self._schedule_flush()

    def teardown(self) -> None:
        """Flush remaining events and stop background timer."""
        if self._flush_timer:
            self._flush_timer.cancel()
            self._flush_timer = None
        self.flush()
