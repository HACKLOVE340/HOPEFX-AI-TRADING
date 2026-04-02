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
import logging
import aiohttp
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass
import json  # noqa: F401
from datetime import datetime, timezone

UTC = timezone.utc

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
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            import time

            self.timestamp = time.time()


class NotificationManager:
    """
    Unified notification system
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.channels: dict[str, bool] = {
            "discord": bool(self.config.get("discord_webhook")),
            "telegram": bool(self.config.get("telegram_bot_token")),
            "email": bool(self.config.get("smtp_host")),
            "webhook": bool(self.config.get("webhook_url")),
        }
        self.queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def start(self):
        """Start notification processor"""
        self._running = True
        asyncio.create_task(self._process_queue())
        logger.info("NotificationManager started")

    async def stop(self):
        """Stop notification processor"""
        self._running = False
        logger.info("NotificationManager stopped")

    async def send(self, notification: Notification):
        """Queue a notification"""
        await self.queue.put(notification)

    async def send_alert(self, level: str, message: str, data: dict = None):
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
                logger.error(f"Notification processing error: {e}")

    async def _dispatch(self, notification: Notification):
        """Send to all configured channels"""
        tasks = []

        if self.channels.get("discord"):
            tasks.append(self._send_discord(notification))
        if self.channels.get("telegram"):
            tasks.append(self._send_telegram(notification))
        if self.channels.get("webhook"):
            tasks.append(self._send_webhook(notification))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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
                logger.error(f"Discord notification failed: {resp.status}")

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
                logger.error(
                    "Telegram notification failed: status=%s body=%s",
                    resp.status,
                    body[:200],
                )

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
                logger.error(f"Webhook notification failed: {resp.status}")

    def _format_timestamp(self, timestamp: float) -> str:
        """Format timestamp for Discord"""
        dt = datetime.fromtimestamp(timestamp, tz=UTC)
        return dt.isoformat()


# Simple alert function for compatibility
async def send_alert(level: str, message: str, **kwargs):
    """Global alert function"""
    logger.log(getattr(logging, level.upper(), logging.INFO), f"ALERT [{level}]: {message}")


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

    async def send_critical_alert(self, message: str, data: dict = None) -> None:
        """Send a CRITICAL-level alert to all configured channels."""
        await self._ensure_started()
        notification = Notification(
            level=NotificationLevel.CRITICAL,
            message=message,
            data=data,
        )
        await self._manager.send(notification)
        logger.critical("CRITICAL ALERT: %s", message)

    async def send_warning(self, message: str, data: dict = None) -> None:
        """Send a WARNING-level alert to all configured channels."""
        await self._ensure_started()
        notification = Notification(
            level=NotificationLevel.WARNING,
            message=message,
            data=data,
        )
        await self._manager.send(notification)
        logger.warning("WARNING ALERT: %s", message)

    async def send_info(self, message: str, data: dict = None) -> None:
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

    async def stop(self) -> None:
        """Stop the underlying manager."""
        if self._started:
            await self._manager.stop()
            self._started = False


# Singleton instance — imported by nuclear_supervisor and kill_switch
notifications = _NotificationsSingleton()

try:
    from notifications.manager import NotificationChannel
except Exception as _exc:
    logging.getLogger(__name__).debug("NotificationChannel unavailable: %s", _exc)
