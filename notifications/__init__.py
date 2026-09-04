# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Notification System
Multi-channel alerts: Discord, Telegram, Email, SMS, Webhooks
"""

import asyncio
import inspect
import json  # noqa: F401
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)


class NotificationLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Notification:
    level: NotificationLevel
    message: str
    data: dict | None = None
    timestamp: float | None = None

    def __post_init__(self):
        if self.timestamp is None:
            import time

            self.timestamp = time.time()


class NotificationManager:
    """
    Unified notification system
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        # Only channels _dispatch() can actually send are advertised here.
        # "email" used to be listed off an ``smtp_host`` key that _dispatch has
        # no branch for (and that no caller in this module ever passes), so an
        # operator reading ``channels`` was told email alerts were on when
        # nothing would ever be sent (F249). Email delivery lives in
        # notifications.manager.EmailChannel — templates, SendGrid/SMTP modes
        # and bounce suppression — and is routed through NotificationService,
        # not through this lightweight manager.
        self.channels: dict[str, bool] = {
            "discord": bool(self.config.get("discord_webhook")),
            "telegram": bool(self.config.get("telegram_bot_token")),
            "webhook": bool(self.config.get("webhook_url")),
        }
        if self.config.get("smtp_host"):
            logger.warning(
                "NotificationManager was given smtp_host but does not send email; "
                "use notifications.manager.EmailChannel for email delivery"
            )

    def has_channel(self) -> bool:
        """True when at least one channel is configured and dispatchable.

        The alert path needs to distinguish "delivered" from "there was nowhere
        to deliver it" — reporting the second as the first is how a critical
        alert goes missing quietly.
        """
        return any(self.channels.values())
        self.queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def start(self):
        """Start notification processor"""
        self._running = True
        _t = asyncio.create_task(self._process_queue())
        _t.add_done_callback(lambda _: None)
        logger.info("NotificationManager started")

    async def stop(self):
        """Stop notification processor"""
        self._running = False
        logger.info("NotificationManager stopped")

    async def send(self, notification: Notification):
        """Queue a notification"""
        await self.queue.put(notification)

    async def send_alert(self, level: str, message: str, data: dict | None = None):
        """Quick send method"""
        notification = Notification(level=NotificationLevel(level.lower()), message=message, data=data)
        await self.send(notification)

    async def _process_queue(self):
        """Process notification queue"""
        while self._running:
            try:
                notification = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                await self._dispatch(notification)
            except TimeoutError:
                continue
            except Exception as e:
                logger.error("Notification processing error: %s", e)

    async def _dispatch(self, notification: Notification):
        """Send to all configured channels with per-channel retry."""
        tasks = []

        if self.channels.get("discord"):
            tasks.append(self._with_retry(self._send_discord, notification, channel="discord"))
        if self.channels.get("telegram"):
            tasks.append(self._with_retry(self._send_telegram, notification, channel="telegram"))
        if self.channels.get("webhook"):
            tasks.append(self._with_retry(self._send_webhook, notification, channel="webhook"))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _with_retry(self, send_fn, notification: Notification, channel: str) -> None:
        """Retry a delivery function with exponential backoff (max 3 attempts)."""
        delays = (2.0, 4.0, 8.0)
        for attempt, delay in enumerate(delays, start=1):
            try:
                await send_fn(notification)
                return
            except Exception as exc:
                if attempt == len(delays):
                    logger.error(
                        "Notification channel %s failed after %d attempts: %s",
                        channel,
                        attempt,
                        exc,
                    )
                else:
                    logger.warning(
                        "Notification channel %s attempt %d/%d failed (%s) — retrying in %.0fs",
                        channel,
                        attempt,
                        len(delays),
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

    @staticmethod
    def _validate_discord_url(url: str) -> bool:
        """Return True only if *url* is an HTTPS discord.com webhook."""
        from urllib.parse import urlparse

        try:
            p = urlparse(url)
            host = (p.hostname or "").lower()
            return p.scheme == "https" and host in ("discord.com", "discordapp.com")
        except Exception:
            return False

    @staticmethod
    def _validate_https_url(url: str) -> bool:
        """Return True only if *url* uses HTTPS."""
        from urllib.parse import urlparse

        try:
            return urlparse(url).scheme == "https"
        except Exception:
            return False

    async def _send_discord(self, notification: Notification):
        """Send to Discord webhook"""
        webhook_url = self.config.get("discord_webhook")
        if not webhook_url:
            return
        if not self._validate_discord_url(webhook_url):
            logger.warning("Discord webhook URL is not a valid HTTPS discord.com URL — skipping")
            return

        color_map = {
            NotificationLevel.INFO: 3447003,
            NotificationLevel.WARNING: 16776960,
            NotificationLevel.ERROR: 15158332,
            NotificationLevel.CRITICAL: 16711680,
        }

        embed = {
            "title": f"HOPEFX Alert - {notification.level.value.upper()}",
            "description": notification.message,
            "color": color_map.get(notification.level, 3447003),
            "timestamp": self._format_timestamp(notification.timestamp),
            "fields": [],
        }

        if notification.data:
            for key, value in notification.data.items():
                embed["fields"].append({"name": key, "value": str(value)[:1000], "inline": True})

        payload = {"embeds": [embed]}

        async with aiohttp.ClientSession() as session, session.post(webhook_url, json=payload) as resp:
            if resp.status != 204:
                raise RuntimeError(f"Discord webhook returned HTTP {resp.status}")

    @staticmethod
    def _escape_mdv2(text: str) -> str:
        """
        Escape all MarkdownV2 reserved characters in a plain-text string.

        Telegram MarkdownV2 requires these characters to be escaped with a
        leading backslash when they appear outside of formatting constructs:
        _ * [ ] ( ) ~ ` > # + - = | { } . !
        """
        # Characters that must be escaped per Telegram MarkdownV2 spec
        _RESERVED = r"\_*[]()~`>#+-=|{}.!"
        return "".join(f"\\{ch}" if ch in _RESERVED else ch for ch in text)

    async def _send_telegram(self, notification: Notification):
        """Send to Telegram using MarkdownV2 with correct escaping."""
        bot_token = self.config.get("telegram_bot_token")
        chat_id = self.config.get("telegram_chat_id")
        if not bot_token or not chat_id:
            return

        emoji_map = {
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "❌",
            NotificationLevel.CRITICAL: "🚨",
        }

        esc = self._escape_mdv2
        level_label = esc(notification.level.value.upper())
        # Emoji are safe — they contain no MarkdownV2 reserved chars
        emoji = emoji_map.get(notification.level, "ℹ️")

        lines = [
            f"{emoji} *HOPEFX Alert*",
            f"*{level_label}*",
            "",
            esc(notification.message),
        ]

        if notification.data:
            lines.append("")
            lines.append("*Data:*")
            for key, value in notification.data.items():
                # Escape both key and value; backtick-wrap value for monospace
                lines.append(f"• {esc(str(key))}: `{esc(str(value))}`")

        text = "\n".join(lines)

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"}

        async with aiohttp.ClientSession() as session, session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Telegram sendMessage returned HTTP {resp.status}: {body[:200]}")

    async def _send_webhook(self, notification: Notification):
        """Send to custom webhook"""
        webhook_url = self.config.get("webhook_url")
        if not webhook_url:
            return
        if not self._validate_https_url(webhook_url):
            logger.warning("Custom webhook URL must use HTTPS — skipping")
            return

        payload = {
            "source": "HOPEFX",
            "level": notification.level.value,
            "message": notification.message,
            "timestamp": notification.timestamp,
            "data": notification.data,
        }

        async with aiohttp.ClientSession() as session, session.post(webhook_url, json=payload) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Webhook endpoint returned HTTP {resp.status}")

    def _format_timestamp(self, timestamp: float) -> str:
        """Format timestamp for Discord"""
        dt = datetime.fromtimestamp(timestamp, tz=UTC)
        return dt.isoformat()


# Simple alert function for compatibility
async def send_alert(level: str, message: str, **kwargs) -> bool:
    """Global alert function — logs *and* dispatches to configured channels.

    ``execution/sl_tp_monitor.py`` raises "CLOSE FAILURE — MANUAL INTERVENTION
    REQUIRED" through here. This used to be a ``logger.log`` call and nothing
    else, so that alert never left the process (F247).

    Returns True when the alert was handed to at least one channel.
    """
    logger.log(getattr(logging, level.upper(), logging.INFO), "ALERT [%s]: %s", level, message)
    data = kwargs.get("data")
    if data is None and kwargs:
        data = dict(kwargs)
    return await notifications.send_alert(level, message, data)


def send_alert_nowait(level: str, message: str, data: dict | None = None, engine=None) -> bool:
    """Dispatch an alert from **synchronous** code.

    Several alert sites are sync methods on otherwise-async objects
    (``PerformanceMonitor._fire_rollback_alert``,
    ``SharpeCircuitBreaker._fire_trip_event``,
    ``execution.sl_tp_monitor._send_alert``). Calling the coroutine and dropping
    it produced a "coroutine was never awaited" warning and no alert (F248).

    Schedules on the running loop when there is one, otherwise runs the
    dispatch to completion. Returns False when the alert could not be handed
    off at all — the caller has only a log line.

    ``engine`` — when a caller holds an alert engine (``app_state.alert_engine``),
    pass it and its ``send_alert`` is used, so engine-registered handlers still
    fire. Otherwise the module-level dispatcher is used.
    """

    async def _deliver() -> bool:
        target = getattr(engine, "send_alert", None) if engine is not None else None
        if target is None:
            return await send_alert(level, message, data=data)
        result = target(level, message, data)
        if inspect.isawaitable(result):
            result = await result
        # An engine that returns None predates the delivered/undelivered
        # distinction; treat a completed call as handed off.
        return True if result is None else bool(result)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            return bool(asyncio.run(_deliver()))
        except Exception as exc:
            logger.error("Alert dispatch failed for [%s] %s: %s", level, message, exc)
            return False

    task = loop.create_task(_deliver())

    def _report(t: asyncio.Task) -> None:
        try:
            if not t.result():
                logger.error("Alert NOT DELIVERED — [%s] %s reached the log only.", level, message)
        except Exception as exc:
            logger.error("Alert dispatch failed for [%s] %s: %s", level, message, exc)

    task.add_done_callback(_report)
    return True


# Compatibility alias
AlertEngine = NotificationManager

__version__ = "1.0.0"


# ── Module-level singleton used by NuclearHopeFXSupervisor ───────────────────


class _NotificationsSingleton:
    """
    Lightweight singleton that wraps NotificationManager and exposes
    send_critical_alert() for use by the nuclear supervisor and kill switch.

    Reads Telegram / Discord credentials from environment variables so it
    works with zero configuration (silently no-ops when creds are absent).

    Environment variables
    ---------------------
    TELEGRAM_BOT_TOKEN   Telegram bot token
    TELEGRAM_CHAT_ID     Telegram chat ID
    DISCORD_WEBHOOK_URL  Discord webhook URL
    NOTIFICATION_WEBHOOK_URL  Generic webhook URL
    """

    def __init__(self) -> None:
        import os

        config = {
            "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
            "discord_webhook": os.environ.get("DISCORD_WEBHOOK_URL", ""),
            "webhook_url": os.environ.get("NOTIFICATION_WEBHOOK_URL", ""),
        }
        self._manager = NotificationManager(config)
        self._started = False

    async def _ensure_started(self) -> None:
        if not self._started:
            await self._manager.start()
            self._started = True

    async def send_critical_alert(self, message: str, data: dict | None = None) -> None:
        """Send a CRITICAL-level alert to all configured channels."""
        await self._ensure_started()
        notification = Notification(
            level=NotificationLevel.CRITICAL,
            message=message,
            data=data,
        )
        await self._manager.send(notification)
        logger.critical("CRITICAL ALERT: %s", message)

    async def send_warning(self, message: str, data: dict | None = None) -> None:
        """Send a WARNING-level alert to all configured channels."""
        await self._ensure_started()
        notification = Notification(
            level=NotificationLevel.WARNING,
            message=message,
            data=data,
        )
        await self._manager.send(notification)
        logger.warning("WARNING ALERT: %s", message)

    async def send_info(self, message: str, data: dict | None = None) -> None:
        """Send an INFO-level alert to all configured channels."""
        await self._ensure_started()
        notification = Notification(
            level=NotificationLevel.INFO,
            message=message,
            data=data,
        )
        await self._manager.send(notification)
        logger.info("INFO ALERT: %s", message)

    async def send(self, notification: Notification) -> None:
        """Pass-through to underlying NotificationManager."""
        await self._ensure_started()
        await self._manager.send(notification)

    # Level strings arrive from many callers ('warn', 'fatal', 'emergency').
    # An unrecognised one is mapped UP, never down: silently demoting an
    # emergency to INFO is the failure mode this whole path exists to prevent.
    _LEVEL_ALIASES = {
        "debug": NotificationLevel.INFO,
        "info": NotificationLevel.INFO,
        "notice": NotificationLevel.INFO,
        "warn": NotificationLevel.WARNING,
        "warning": NotificationLevel.WARNING,
        "error": NotificationLevel.ERROR,
        "err": NotificationLevel.ERROR,
        "critical": NotificationLevel.CRITICAL,
        "crit": NotificationLevel.CRITICAL,
        "fatal": NotificationLevel.CRITICAL,
        "emergency": NotificationLevel.CRITICAL,
    }

    @classmethod
    def _coerce_level(cls, level: str) -> NotificationLevel:
        key = str(level).strip().lower()
        mapped = cls._LEVEL_ALIASES.get(key)
        if mapped is None:
            logger.warning("Unrecognised alert level %r — treating as ERROR", level)
            return NotificationLevel.ERROR
        return mapped

    async def send_alert(self, level: str, message: str, data: dict | None = None) -> bool:
        """Dispatch an alert to every configured channel.

        Returns True only when a channel was actually configured to receive it.
        A False return means the alert exists in the log and nowhere else —
        callers must be able to tell those apart (F159).
        """
        # Tolerant of an injected manager that predates has_channel().
        probe = getattr(self._manager, "has_channel", None)
        configured = probe() if callable(probe) else any(getattr(self._manager, "channels", {}).values())
        if not configured:
            return False
        await self._ensure_started()
        await self._manager.send(Notification(level=self._coerce_level(level), message=message, data=data))
        return True

    async def stop(self) -> None:
        """Stop the underlying manager."""
        if self._started:
            await self._manager.stop()
            self._started = False


# Singleton instance — imported by nuclear_supervisor and kill_switch
notifications = _NotificationsSingleton()

try:
    from notifications.manager import NotificationChannel  # noqa: F401
except Exception as _exc:
    logging.getLogger(__name__).debug("NotificationChannel unavailable: %s", _exc)

try:
    from notifications.alert_engine import get_alert_engine
except Exception as _ae_exc:
    logging.getLogger(__name__).debug("AlertEngine unavailable: %s", _ae_exc)

    def get_alert_engine():  # type: ignore[misc]
        """Stub when alert_engine module is unavailable."""
        return None
