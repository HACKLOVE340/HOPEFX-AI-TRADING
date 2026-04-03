# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
notifications/heartbeat.py
==========================
Telegram "I'm alive" heartbeat — sends a status ping every hour.

The heartbeat message includes:
  - System uptime
  - Current equity and daily P&L
  - Number of open positions
  - Current drawdown %
  - Last signal direction + confidence
  - Any active risk alerts

Environment variables
---------------------
  TELEGRAM_BOT_TOKEN        — Telegram bot token (required)
  TELEGRAM_CHAT_ID          — Chat ID(s) to send to (required)
  HEARTBEAT_INTERVAL_HOURS  — Ping interval in hours (default: 1)
  HEARTBEAT_ENABLED         — Set to "false" to disable (default: true)

Usage
-----
    from notifications.heartbeat import start_heartbeat

    # Pass a callable that returns current system status dict
    start_heartbeat(get_status_fn=lambda: {
        "equity": 10420.0,
        "balance": 10400.0,
        "daily_pnl": 32.0,
        "open_positions": 1,
        "drawdown_pct": 0.5,
        "last_signal": {"direction": "long", "confidence": 0.72},
        "risk_alerts": [],
    })

    # Or start from the main loop with app_state:
    start_heartbeat(app_state=app_state)
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_HOURS: float = float(os.getenv("HEARTBEAT_INTERVAL_HOURS", "1"))
_HEARTBEAT_ENABLED: bool = os.getenv("HEARTBEAT_ENABLED", "true").lower() == "true"
_TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")


# ── Telegram sender ───────────────────────────────────────────────────────────


async def _send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    try:
        import aiohttp

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with (
            aiohttp.ClientSession() as session,
            session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
            if resp.status == 200:
                return True
            body = await resp.text()
            logger.warning("Telegram heartbeat send failed: %d %s", resp.status, body[:200])
            return False
    except Exception as exc:
        logger.warning("Telegram heartbeat send error: %s", exc)
        return False


def _send_telegram_sync(token: str, chat_id: str, text: str) -> bool:
    """Synchronous wrapper for _send_telegram."""
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_send_telegram(token, chat_id, text))
        loop.close()
        return result
    except Exception as exc:
        logger.warning("Telegram sync send error: %s", exc)
        return False


# ── Status builder ────────────────────────────────────────────────────────────


def _build_message(status: dict[str, Any], uptime_seconds: float) -> str:
    """Build the heartbeat message from a status dict."""
    uptime = str(timedelta(seconds=int(uptime_seconds)))
    equity = status.get("equity", 0)
    balance = status.get("balance", equity)
    daily_pnl = status.get("daily_pnl", 0)
    open_pos = status.get("open_positions", 0)
    drawdown = status.get("drawdown_pct", 0)
    last_sig = status.get("last_signal") or {}
    risk_alerts = status.get("risk_alerts") or []
    broker = status.get("broker", "unknown")
    mode = status.get("mode", "paper")

    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
    dd_emoji = "⚠️" if drawdown > 5 else ("🟡" if drawdown > 2 else "🟢")

    sig_text = ""
    if last_sig:
        direction = last_sig.get("direction", "neutral")
        conf = last_sig.get("confidence", 0)
        sig_text = f"\n📊 Last signal: <b>{direction.upper()}</b> ({conf:.0%} conf)"

    alerts_text = ""
    if risk_alerts:
        alerts_text = "\n⚠️ Risk alerts:\n" + "\n".join(f"  • {a}" for a in risk_alerts[:3])

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    return (
        f"💓 <b>HOPEFX Heartbeat</b> — {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 Broker: {broker} ({mode})\n"
        f"⏱ Uptime: {uptime}\n"
        f"💰 Equity: <b>${equity:,.2f}</b>\n"
        f"💵 Balance: ${balance:,.2f}\n"
        f"{pnl_emoji} Daily P&L: <b>${daily_pnl:+,.2f}</b>\n"
        f"{dd_emoji} Drawdown: {drawdown:.2f}%\n"
        f"📈 Open positions: {open_pos}"
        f"{sig_text}"
        f"{alerts_text}"
    )


# ── HeartbeatService ──────────────────────────────────────────────────────────


class HeartbeatService:
    """
    Sends a Telegram status ping every HEARTBEAT_INTERVAL_HOURS.

    Runs in a daemon thread so it doesn't block the main loop.
    """

    def __init__(
        self,
        token: str = _TELEGRAM_TOKEN,
        chat_id: str = _TELEGRAM_CHAT_ID,
        interval_hours: float = _HEARTBEAT_INTERVAL_HOURS,
        get_status_fn: Callable[[], dict[str, Any]] | None = None,
        app_state: Any | None = None,
    ) -> None:
        self._token = token
        self._chat_ids = [c.strip() for c in chat_id.split(",") if c.strip()]
        self._interval = interval_hours * 3600
        self._get_status_fn = get_status_fn
        self._app_state = app_state
        self._start_time = time.monotonic()
        self._thread: threading.Thread | None = None
        self._running = False
        self._ping_count = 0
        self._last_ping: float | None = None
        # Event used to interrupt the wait in _loop() when stop() is called.
        self._stop_event = threading.Event()

    def _get_status(self) -> dict[str, Any]:
        """Collect current system status."""
        if self._get_status_fn is not None:
            try:
                return self._get_status_fn()
            except Exception as exc:
                logger.debug("get_status_fn failed: %s", exc)

        # Try to read from app_state
        status: dict[str, Any] = {}
        if self._app_state is not None:
            try:
                broker = getattr(self._app_state, "broker", None)
                if broker:
                    info = broker.get_account_info()
                    status["equity"] = float(info.get("equity", 0))
                    status["balance"] = float(info.get("balance", 0))
                    status["open_positions"] = int(info.get("open_positions", 0))
                    status["broker"] = getattr(broker, "name", "broker")
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

            try:
                rm = getattr(self._app_state, "risk_manager", None)
                if rm:
                    status["daily_pnl"] = float(getattr(rm, "daily_pnl", 0))
                    status["drawdown_pct"] = float(getattr(rm, "current_drawdown", 0)) * 100
                    status["risk_alerts"] = (getattr(rm, "_halt_reason", None) and [rm._halt_reason]) or []
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

            try:
                from monitoring.trade_logger import get_trade_logger

                tl = get_trade_logger()
                s = tl.stats
                if not status.get("equity"):
                    status["equity"] = s.get("equity", 0)
                if not status.get("daily_pnl"):
                    status["daily_pnl"] = s.get("daily_pnl", 0)
                status["drawdown_pct"] = s.get("drawdown_pct", 0)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        status.setdefault("mode", os.getenv("TRADING_MODE", "paper"))
        return status

    def _send_ping(self) -> None:
        """Build and send the heartbeat message to all configured chat IDs."""
        if not self._token or not self._chat_ids:
            logger.debug("Heartbeat: no token/chat_id configured — skipping")
            return

        uptime = time.monotonic() - self._start_time
        status = self._get_status()
        message = _build_message(status, uptime)

        sent = 0
        for chat_id in self._chat_ids:
            ok = _send_telegram_sync(self._token, chat_id, message)
            if ok:
                sent += 1

        self._ping_count += 1
        self._last_ping = time.monotonic()
        logger.info(
            "Heartbeat ping #%d sent to %d/%d chats",
            self._ping_count,
            sent,
            len(self._chat_ids),
        )

    def _loop(self) -> None:
        """Main heartbeat loop — runs in daemon thread.

        Uses threading.Event.wait() instead of time.sleep() so stop() can
        interrupt the interval immediately without waiting up to 30 s.
        """
        logger.info(
            "HeartbeatService started — interval=%.1fh chats=%d",
            self._interval / 3600,
            len(self._chat_ids),
        )
        # Send an immediate startup ping
        self._send_ping()

        while self._running:
            # Block until the interval elapses or stop() sets the event.
            self._stop_event.wait(timeout=self._interval)
            if self._running:
                self._send_ping()

        logger.info("HeartbeatService stopped after %d pings", self._ping_count)

    def start(self) -> HeartbeatService:
        """Start the heartbeat daemon thread. Returns self for chaining."""
        if not _HEARTBEAT_ENABLED:
            logger.info("HeartbeatService disabled (HEARTBEAT_ENABLED=false)")
            return self
        if not self._token:
            logger.warning("HeartbeatService: TELEGRAM_BOT_TOKEN not set — heartbeat disabled")
            return self
        if not self._chat_ids:
            logger.warning("HeartbeatService: TELEGRAM_CHAT_ID not set — heartbeat disabled")
            return self

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="telegram-heartbeat")
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop the heartbeat thread gracefully."""
        self._running = False
        # Wake the sleeping _loop() immediately instead of waiting up to
        # _interval seconds for the Event.wait() timeout to expire.
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def ping_now(self) -> None:
        """Send an immediate ping (useful for testing or manual triggers)."""
        self._send_ping()

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "ping_count": self._ping_count,
            "interval_hours": self._interval / 3600,
            "last_ping_ago_s": (round(time.monotonic() - self._last_ping, 1) if self._last_ping else None),
            "chat_ids": len(self._chat_ids),
            "token_set": bool(self._token),
        }


# ── Module-level convenience ──────────────────────────────────────────────────
_heartbeat: HeartbeatService | None = None


def start_heartbeat(
    get_status_fn: Callable[[], dict[str, Any]] | None = None,
    app_state: Any | None = None,
    token: str = _TELEGRAM_TOKEN,
    chat_id: str = _TELEGRAM_CHAT_ID,
    interval_hours: float = _HEARTBEAT_INTERVAL_HOURS,
) -> HeartbeatService:
    """
    Start the global heartbeat service.

    Call once from app startup. Subsequent calls return the existing instance.
    """
    global _heartbeat
    if _heartbeat is None:
        _heartbeat = HeartbeatService(
            token=token,
            chat_id=chat_id,
            interval_hours=interval_hours,
            get_status_fn=get_status_fn,
            app_state=app_state,
        ).start()
    return _heartbeat


def get_heartbeat() -> HeartbeatService | None:
    """Return the running heartbeat instance, or None if not started."""
    return _heartbeat
