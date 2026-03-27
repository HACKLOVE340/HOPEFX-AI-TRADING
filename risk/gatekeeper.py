# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
risk/gatekeeper.py
==================
Prop-firm risk gatekeeper — event-driven signal filter.

Flow
----
  hopefx:signal  →  prop checks  →  pass → hopefx:order
                                  →  fail → hopefx:breach + pause

Checks performed (in order)
----------------------------
1. Kill-switch active          — hard block, no recovery
2. Daily drawdown limit        — block when daily DD >= DAILY_DD_LIMIT_PCT
3. Max drawdown limit          — block when total DD >= MAX_DD_LIMIT_PCT
4. News blackout               — block during high-impact news windows
5. Max daily trades            — block when daily trade count >= MAX_DAILY_TRADES
6. Confidence floor            — block when signal confidence < MIN_CONFIDENCE

On any breach
-------------
- Publishes a breach event to hopefx:breach with reason + metrics.
- Sets an internal pause flag; resumes after PAUSE_AFTER_BREACH_S seconds
  (or immediately on kill-switch — no auto-resume).
- Logs at WARNING level with structured fields.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from core.event_bus import bus, CH_SIGNAL, CH_ORDER, CH_BREACH

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
DAILY_DD_LIMIT_PCT:    float = float(os.environ.get("RISK_MAX_DAILY_LOSS_PCT",  "0.05"))
MAX_DD_LIMIT_PCT:      float = float(os.environ.get("RISK_MAX_DRAWDOWN_PCT",    "0.10"))
MIN_CONFIDENCE:        float = float(os.environ.get("GATEKEEPER_MIN_CONF",      "0.55"))
MAX_DAILY_TRADES:      int   = int(os.environ.get("GATEKEEPER_MAX_DAILY_TRADES","20"))
PAUSE_AFTER_BREACH_S:  float = float(os.environ.get("GATEKEEPER_PAUSE_S",       "60"))
# Minutes before/after a high-impact news event to block trading
NEWS_BLACKOUT_BEFORE_MIN: int = int(os.environ.get("NEWS_BLACKOUT_BEFORE_MIN", "5"))
NEWS_BLACKOUT_AFTER_MIN:  int = int(os.environ.get("NEWS_BLACKOUT_AFTER_MIN",  "5"))


# ─────────────────────────────────────────────────────────────────────────────
# News blackout calendar
# ─────────────────────────────────────────────────────────────────────────────

class _NewsCalendar:
    """
    Lightweight news blackout checker.

    Loads high-impact event times from Redis key 'hopefx:news_events'
    (list of ISO-8601 strings). Falls back to an empty calendar when
    Redis is unavailable — trading is NOT blocked on calendar load failure.
    """

    def __init__(self) -> None:
        self._events: List[datetime] = []
        self._last_refresh: Optional[datetime] = None
        self._refresh_interval = timedelta(minutes=15)

    async def refresh(self) -> None:
        """Pull event times from Redis; silently skip on error."""
        now = datetime.now(timezone.utc)
        if (self._last_refresh and
                now - self._last_refresh < self._refresh_interval):
            return  # not due yet

        try:
            import redis.asyncio as aioredis
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            r = aioredis.from_url(url, decode_responses=True, socket_timeout=3)
            raw = await r.lrange("hopefx:news_events", 0, -1)
            await r.aclose()
            self._events = []
            for ts in raw:
                try:
                    self._events.append(datetime.fromisoformat(ts))
                except ValueError:
                    pass
            self._last_refresh = now
            logger.debug("NewsCalendar: loaded %d events.", len(self._events))
        except Exception as exc:  # noqa: BLE001
            logger.warning("NewsCalendar refresh failed: %s — blackout disabled.", exc)

    def is_blackout(self, now: Optional[datetime] = None) -> bool:
        """Return True when now falls within any news blackout window."""
        now = now or datetime.now(timezone.utc)
        before = timedelta(minutes=NEWS_BLACKOUT_BEFORE_MIN)
        after  = timedelta(minutes=NEWS_BLACKOUT_AFTER_MIN)
        for event_time in self._events:
            if (event_time - before) <= now <= (event_time + after):
                return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Equity tracker (updated via breach events from connect_to_life / main_loop)
# ─────────────────────────────────────────────────────────────────────────────

class _EquityTracker:
    """Tracks peak equity and computes daily / max drawdown fractions."""

    def __init__(self, initial_balance: float) -> None:
        self._initial:  float = initial_balance
        self._peak:     float = initial_balance
        self._current:  float = initial_balance
        self._day_open: float = initial_balance
        self._day:      int   = datetime.now(timezone.utc).day

    def update(self, equity: float) -> None:
        today = datetime.now(timezone.utc).day
        if today != self._day:
            self._day_open = equity
            self._day = today
        self._current = equity
        if equity > self._peak:
            self._peak = equity

    @property
    def daily_dd(self) -> float:
        """Fraction of day-open equity lost today (positive = loss)."""
        if self._day_open <= 0:
            return 0.0
        return max(0.0, (self._day_open - self._current) / self._day_open)

    @property
    def max_dd(self) -> float:
        """Fraction of all-time peak equity lost (positive = loss)."""
        if self._peak <= 0:
            return 0.0
        return max(0.0, (self._peak - self._current) / self._peak)


# ─────────────────────────────────────────────────────────────────────────────
# Gatekeeper
# ─────────────────────────────────────────────────────────────────────────────

class Gatekeeper:
    """
    Subscribes to hopefx:signal, applies prop-firm checks, routes to
    hopefx:order on pass or hopefx:breach on fail.

    Usage
    -----
    gk = Gatekeeper()
    await gk.start()   # runs until cancelled
    """

    def __init__(self) -> None:
        initial_balance = float(os.environ.get("INITIAL_BALANCE", "100000"))
        self._equity    = _EquityTracker(initial_balance)
        self._calendar  = _NewsCalendar()
        self._kill_active: bool = False
        self._paused_until: Optional[float] = None   # monotonic time
        self._daily_trades: int = 0
        self._trade_day:    int = datetime.now(timezone.utc).day
        self._running:      bool = False
        self._pass_count:   int = 0
        self._block_count:  int = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to EventBus and begin consuming signals."""
        self._running = True
        logger.info(
            "Gatekeeper starting — daily_dd_limit=%.1f%% max_dd_limit=%.1f%%",
            DAILY_DD_LIMIT_PCT * 100, MAX_DD_LIMIT_PCT * 100,
        )
        # Also subscribe to breach channel to catch kill events from other modules
        asyncio.create_task(self._breach_listener())
        await self._signal_consumer()

    async def stop(self) -> None:
        self._running = False
        logger.info(
            "Gatekeeper stopped. passed=%d blocked=%d",
            self._pass_count, self._block_count,
        )

    # ── signal consumer ───────────────────────────────────────────────────────

    async def _signal_consumer(self) -> None:
        """Main loop: read signals, apply checks, route."""
        async for msg in bus.subscribe(CH_SIGNAL):
            if not self._running:
                break
            # Ignore heartbeats
            if msg.get("type") == "heartbeat":
                continue
            try:
                await self._on_signal(msg)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("Gatekeeper signal error: %s", exc)

    async def _breach_listener(self) -> None:
        """Listen for breach events from other modules (e.g. equity updates)."""
        async for msg in bus.subscribe(CH_BREACH):
            if not self._running:
                break
            reason = msg.get("reason", "")
            # Equity update from connect_to_life / main_loop
            if reason == "equity_update":
                equity = float(msg.get("equity", 0))
                if equity > 0:
                    self._equity.update(equity)
            # Kill event from any source
            elif reason in ("kill_switch", "kill_event", "stale_feed"):
                if reason in ("kill_switch", "kill_event"):
                    self._kill_active = True
                    logger.critical("Gatekeeper: kill event received — all trading halted.")

    # ── signal handler ────────────────────────────────────────────────────────

    async def _on_signal(self, signal: dict) -> None:
        """Apply all prop checks; route to order or breach channel."""
        # Refresh news calendar (no-op if not due)
        await self._calendar.refresh()

        # Reset daily trade counter on new day
        today = datetime.now(timezone.utc).day
        if today != self._trade_day:
            self._daily_trades = 0
            self._trade_day = today

        # Run checks — collect all failures for the breach payload
        failures = self._run_checks(signal)

        if not failures:
            # All checks passed — forward to execution
            self._pass_count += 1
            self._daily_trades += 1
            order_request = {
                "type":       "order_request",
                "symbol":     signal.get("symbol"),
                "direction":  signal.get("direction"),
                "confidence": signal.get("confidence"),
                "mid":        signal.get("mid"),
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "signal_ref": signal.get("tick_seq"),
            }
            logger.info(
                "GATE PASS  %s %s  conf=%.4f",
                signal.get("direction"), signal.get("symbol"), signal.get("confidence", 0),
            )
            await bus.publish_order(order_request)
        else:
            # One or more checks failed — publish breach and pause
            self._block_count += 1
            primary_reason = failures[0]["reason"]
            logger.warning(
                "GATE BLOCK  reason=%s  symbol=%s  checks_failed=%s",
                primary_reason, signal.get("symbol"), [f["reason"] for f in failures],
            )
            breach = {
                "type":         "breach",
                "reason":       primary_reason,
                "checks_failed": failures,
                "signal":       signal,
                "daily_dd":     round(self._equity.daily_dd * 100, 4),
                "max_dd":       round(self._equity.max_dd * 100, 4),
                "timestamp":    datetime.now(timezone.utc).isoformat(),
            }
            await bus.publish_breach(breach)

            # Pause trading (except kill-switch — no auto-resume)
            if primary_reason != "kill_switch_active":
                import time
                self._paused_until = time.monotonic() + PAUSE_AFTER_BREACH_S
                logger.warning(
                    "Gatekeeper paused for %.0f s after breach.", PAUSE_AFTER_BREACH_S
                )

    # ── checks ────────────────────────────────────────────────────────────────

    def _run_checks(self, signal: dict) -> List[Dict]:
        """
        Run all prop checks against the signal.

        Returns a list of failure dicts (empty = all passed).
        Each failure dict has keys: reason, detail.
        """
        import time
        failures: List[Dict] = []

        # 1. Kill-switch
        if self._kill_active:
            failures.append({
                "reason": "kill_switch_active",
                "detail": "Kill switch is active — all trading halted.",
            })
            return failures  # hard stop — skip remaining checks

        # 2. Pause window
        if self._paused_until and time.monotonic() < self._paused_until:
            remaining = self._paused_until - time.monotonic()
            failures.append({
                "reason": "post_breach_pause",
                "detail": f"Paused after breach — {remaining:.0f} s remaining.",
            })
            return failures

        # 3. Daily drawdown
        if self._equity.daily_dd >= DAILY_DD_LIMIT_PCT:
            failures.append({
                "reason": "daily_dd_limit",
                "detail": (
                    f"Daily DD {self._equity.daily_dd * 100:.2f}% >= "
                    f"limit {DAILY_DD_LIMIT_PCT * 100:.1f}%"
                ),
            })

        # 4. Max drawdown
        if self._equity.max_dd >= MAX_DD_LIMIT_PCT:
            failures.append({
                "reason": "max_dd_limit",
                "detail": (
                    f"Max DD {self._equity.max_dd * 100:.2f}% >= "
                    f"limit {MAX_DD_LIMIT_PCT * 100:.1f}%"
                ),
            })

        # 5. News blackout
        if self._calendar.is_blackout():
            failures.append({
                "reason": "news_blackout",
                "detail": "High-impact news event within blackout window.",
            })

        # 6. Daily trade cap
        if self._daily_trades >= MAX_DAILY_TRADES:
            failures.append({
                "reason": "daily_trade_cap",
                "detail": (
                    f"Daily trade count {self._daily_trades} >= "
                    f"cap {MAX_DAILY_TRADES}"
                ),
            })

        # 7. Confidence floor
        confidence = float(signal.get("confidence", 0))
        if confidence < MIN_CONFIDENCE:
            failures.append({
                "reason": "low_confidence",
                "detail": (
                    f"Signal confidence {confidence:.4f} < "
                    f"floor {MIN_CONFIDENCE:.2f}"
                ),
            })

        return failures

    # ── metrics ───────────────────────────────────────────────────────────────

    def metrics(self) -> dict:
        return {
            "pass_count":    self._pass_count,
            "block_count":   self._block_count,
            "daily_trades":  self._daily_trades,
            "daily_dd_pct":  round(self._equity.daily_dd * 100, 4),
            "max_dd_pct":    round(self._equity.max_dd * 100, 4),
            "kill_active":   self._kill_active,
        }
