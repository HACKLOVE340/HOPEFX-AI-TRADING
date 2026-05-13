# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/outbox.py
==============
Transactional outbox for at-least-once delivery of critical compliance events.

Pattern
-------
1. The caller writes an OutboxEvent row in the SAME DB transaction as the
   state change (kill switch activation, AML block, order fill).
2. OutboxRelay polls the outbox table every RELAY_INTERVAL_SECONDS and
   publishes unpublished rows to Redis pub/sub.
3. On successful publish, published_at is set.  Rows are never deleted so
   the outbox doubles as an audit trail.

This guarantees that even if Redis is down at the moment of the state change,
the event will be delivered once Redis recovers — no event is silently lost.

Usage
-----
    # In the same DB session as your state change:
    from core.outbox import write_outbox_event
    write_outbox_event(session, event_type="KILL_SWITCH", channel="hopefx:breach",
                       payload={"reason": "drawdown exceeded", "activated_by": "risk"})

    # Start the relay background task at startup:
    from core.outbox import OutboxRelay
    relay = OutboxRelay()
    _t = asyncio.create_task(relay.run())
    _t.add_done_callback(lambda _: None)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

# Module-level defaults — read once at import time.
# OutboxRelay re-reads these via _get_batch_config() on every tick so that
# operators can tune them via env vars without restarting the process.
RELAY_INTERVAL_SECONDS: float = float(os.getenv("OUTBOX_RELAY_INTERVAL_SECONDS", "2.0"))
MAX_ATTEMPTS: int = int(os.getenv("OUTBOX_MAX_ATTEMPTS", "10"))
BATCH_SIZE: int = int(os.getenv("OUTBOX_BATCH_SIZE", "50"))


def _get_batch_config() -> tuple[float, int, int]:
    """
    Return (relay_interval_s, max_attempts, batch_size) read live from env.

    Re-reading on every relay tick allows operators to tune throughput and
    retry limits via env vars without a process restart.
    """
    interval = float(os.getenv("OUTBOX_RELAY_INTERVAL_SECONDS", str(RELAY_INTERVAL_SECONDS)))
    attempts = int(os.getenv("OUTBOX_MAX_ATTEMPTS", str(MAX_ATTEMPTS)))
    batch = int(os.getenv("OUTBOX_BATCH_SIZE", str(BATCH_SIZE)))
    # Clamp to sane bounds to prevent accidental misconfiguration.
    interval = max(0.1, min(interval, 60.0))
    attempts = max(1, min(attempts, 100))
    batch = max(1, min(batch, 500))
    return interval, attempts, batch


# ── Write helper ──────────────────────────────────────────────────────────────


def write_outbox_event(
    session,
    event_type: str,
    channel: str,
    payload: dict[str, Any],
) -> None:
    """
    Write a single OutboxEvent row using an existing SQLAlchemy session.

    Call this inside the same ``session.commit()`` block as the state change
    so the event and the state change are atomic.

    Parameters
    ----------
    session    : Active SQLAlchemy session (not yet committed).
    event_type : Human-readable event type (e.g. "KILL_SWITCH", "AML_BLOCK").
    channel    : Redis pub/sub channel to publish to (e.g. "hopefx:breach").
    payload    : JSON-serialisable dict — the event body.
    """
    try:
        from database.models import OutboxEvent

        row = OutboxEvent(
            event_type=event_type,
            channel=channel,
            payload=json.dumps(payload),
            created_at=datetime.now(UTC),
            attempts=0,
        )
        session.add(row)
        # Do NOT commit here — the caller owns the transaction.
        logger.debug("outbox: queued %s → %s", event_type, channel)
    except Exception as exc:
        logger.error("outbox: failed to queue %s: %s", event_type, exc)


def write_outbox_event_standalone(
    event_type: str,
    channel: str,
    payload: dict[str, Any],
) -> bool:
    """
    Write an OutboxEvent in its own DB transaction.

    Use this when you don't have an existing session (e.g. from a background
    task or a path that doesn't already hold a DB session).

    Returns True on success, False on failure.
    """
    session = _get_db_session()
    if session is None:
        logger.warning("outbox: DB unavailable — event %s not persisted", event_type)
        return False
    try:
        from database.models import OutboxEvent

        row = OutboxEvent(
            event_type=event_type,
            channel=channel,
            payload=json.dumps(payload),
            status="pending",
            created_at=datetime.now(UTC),
            attempts=0,
        )
        session.add(row)
        session.commit()
        logger.debug("outbox: standalone queued %s → %s", event_type, channel)
        return True
    except Exception as exc:
        session.rollback()
        logger.error("outbox: standalone write failed for %s: %s", event_type, exc)
        return False
    finally:
        session.close()


# ── Relay worker ──────────────────────────────────────────────────────────────


class OutboxRelay:
    """
    Background worker that relays unpublished OutboxEvent rows to Redis.

    Polls the outbox table every RELAY_INTERVAL_SECONDS.  On each tick:
    - Fetches up to BATCH_SIZE rows where published_at IS NULL and
      attempts < MAX_ATTEMPTS, ordered by created_at ASC.
    - Publishes each row's payload to its Redis channel.
    - Sets published_at on success; increments attempts + last_error on failure.

    The relay is idempotent — if it crashes mid-batch, unpublished rows will
    be retried on the next tick.
    """

    def __init__(self) -> None:
        self._running = False

    async def run(self) -> None:
        """Run the relay loop until cancelled."""
        self._running = True
        interval, max_attempts, batch_size = _get_batch_config()
        logger.info(
            "OutboxRelay started (interval=%.1fs batch=%d max_attempts=%d)",
            interval,
            batch_size,
            max_attempts,
        )
        while self._running:
            try:
                await self._relay_batch()
            except asyncio.CancelledError:
                logger.info("OutboxRelay stopped")
                return
            except Exception as exc:
                logger.warning("OutboxRelay tick error: %s", exc)
            # Re-read interval on every sleep so hot-reloading works.
            interval, _, _ = _get_batch_config()
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False

    async def _relay_batch(self) -> None:
        """Fetch and publish one batch of unpublished events."""
        session = _get_db_session()
        if session is None:
            return

        # Re-read batch config on every tick for live tunability.
        _, max_attempts, batch_size = _get_batch_config()

        try:
            from database.models import OutboxEvent

            # Fetch pending rows (status="pending" OR legacy published_at IS NULL)
            # ordered oldest-first for FIFO delivery guarantees.
            rows = (
                session.query(OutboxEvent)
                .filter(
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.attempts < max_attempts,
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(batch_size)
                .all()
            )

            if not rows:
                return

            redis_client = _get_redis()

            for row in rows:
                # ── Idempotency check ─────────────────────────────────────────
                # If the row has an idempotency_key, check whether a row with
                # the same key was already published.  This prevents duplicate
                # delivery when the relay crashes after publishing but before
                # committing published_at.
                if getattr(row, "idempotency_key", None):
                    already = (
                        session.query(OutboxEvent)
                        .filter(
                            OutboxEvent.idempotency_key == row.idempotency_key,
                            OutboxEvent.published_at.isnot(None),
                            OutboxEvent.id != row.id,
                        )
                        .first()
                    )
                    if already is not None:
                        # Mark as published without re-sending
                        row.published_at = datetime.now(UTC)
                        row.status = "published"
                        logger.debug(
                            "outbox: idempotency skip id=%d key=%s (already published as id=%d)",
                            row.id,
                            row.idempotency_key,
                            already.id,
                        )
                        continue

                try:
                    if redis_client is not None:
                        redis_client.publish(row.channel, row.payload)
                    else:
                        # Redis unavailable — fall back to in-process event bus
                        await _publish_in_process(row.channel, row.payload)

                    row.published_at = datetime.now(UTC)
                    row.status = "published"
                    logger.debug(
                        "outbox: published id=%d type=%s channel=%s",
                        row.id,
                        row.event_type,
                        row.channel,
                    )
                except Exception as pub_exc:
                    row.attempts = (row.attempts or 0) + 1
                    row.last_error = str(pub_exc)[:500]

                    # ── Dead-letter after max_attempts ────────────────────────
                    # Use per-row max_attempts if set, otherwise live config value.
                    row_max = getattr(row, "max_attempts", None) or max_attempts
                    if row.attempts >= row_max:
                        row.status = "dead_letter"
                        logger.error(
                            "outbox: dead-lettered id=%d type=%s after %d attempts: %s",
                            row.id,
                            row.event_type,
                            row.attempts,
                            pub_exc,
                        )
                    else:
                        logger.warning(
                            "outbox: publish failed id=%d attempt=%d/%d: %s",
                            row.id,
                            row.attempts,
                            row_max,
                            pub_exc,
                        )

            session.commit()

        except Exception as exc:
            session.rollback()
            logger.error("OutboxRelay._relay_batch error: %s", exc)
        finally:
            session.close()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_db_session():
    """Return a SQLAlchemy session from app_state, or None."""
    try:
        from core.app_state import app_state

        if app_state and app_state.db_session_factory:
            return app_state.db_session_factory()  # pylint: disable=not-callable
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return None


def _get_redis():
    """Return a synchronous Redis client, or None."""
    try:
        import redis as _redis

        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = _redis.from_url(url, decode_responses=True, socket_timeout=2)
        client.ping()
        return client
    except Exception:  # nosec B110 - Redis may be unavailable at startup
        return None


async def _publish_in_process(channel: str, payload: str) -> None:
    """Fallback: publish via the async Redis event bus."""
    try:
        from core.event_bus import bus

        data = json.loads(payload)
        await bus.publish(channel, data)
    except Exception as exc:
        logger.warning("outbox: in-process fallback publish failed: %s", exc)


# ── Module-level singleton ────────────────────────────────────────────────────

_relay: OutboxRelay | None = None


def get_relay() -> OutboxRelay:
    """Return the module-level OutboxRelay singleton."""
    global _relay
    if _relay is None:
        _relay = OutboxRelay()
    return _relay
