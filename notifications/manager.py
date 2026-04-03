# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Notification Manager
Multi-channel alerts with rate limiting, batching, and templating
"""

import abc
import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

try:
    import requests
except ImportError:
    requests = None  # type: ignore
import contextlib
from enum import Enum

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    SMTP_AVAILABLE = True
except ImportError:
    SMTP_AVAILABLE = False

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (
        HtmlContent,
        Mail,
    )

    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

logger = logging.getLogger(__name__)


class NotificationLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Notification:
    """Notification message"""

    level: NotificationLevel
    title: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    channels: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(int(time.time() * 1000)))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "data": self.data,
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "channels": self.channels,
        }


class NotificationChannel(abc.ABC):
    """Abstract base class for notification channels.

    Concrete subclasses must implement ``send``.  Attempting to instantiate
    a subclass with ``send`` unimplemented raises ``TypeError`` at
    construction time.

    Class-level constants (CONSOLE, DISCORD, …) are kept for backward
    compatibility with code that uses ``NotificationChannel.DISCORD`` etc.
    """

    # Enum-style constants used by tests and channel factory
    CONSOLE = "console"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    EMAIL = "email"

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.config = config
        self.enabled = config.get("enabled", True)
        self.rate_limit_seconds = config.get("rate_limit_seconds", 60)
        self._last_send_time: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @abc.abstractmethod
    async def send(self, notification: Notification) -> bool:
        """Deliver *notification* to the channel. Returns True on success."""

    def _check_rate_limit(self, key: str = "default") -> bool:
        """Check if rate limit allows sending"""
        now = time.time()
        last = self._last_send_time.get(key, 0)

        if now - last < self.rate_limit_seconds:
            return False

        self._last_send_time[key] = now
        return True

    async def _send_with_retry(self, send_fn: Callable, max_retries: int = 3) -> bool:
        """Send with retry logic"""
        for attempt in range(max_retries):
            try:
                return await send_fn()
            except Exception as e:
                logger.error("%s send failed (attempt %s): %s", self.name, attempt + 1, e)

                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
        return False


class DiscordChannel(NotificationChannel):
    """Discord webhook notifications"""

    def __init__(self, config: dict[str, Any]):
        super().__init__("discord", config)
        self.webhook_url = config.get("webhook_url")
        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured")
            self.enabled = False

    async def send(self, notification: Notification) -> bool:
        if not self.enabled or not AIOHTTP_AVAILABLE:
            return False

        if not self._check_rate_limit(notification.level.value):
            logger.debug("Discord rate limited for %s", notification.level.value)

            return False

        # Color based on level
        colors = {
            NotificationLevel.DEBUG: 0x808080,
            NotificationLevel.INFO: 0x00FF00,
            NotificationLevel.WARNING: 0xFFA500,
            NotificationLevel.ERROR: 0xFF0000,
            NotificationLevel.CRITICAL: 0x8B0000,
        }

        embed = {
            "title": notification.title,
            "description": notification.message[:2000],  # Discord limit
            "color": colors.get(notification.level, 0x808080),
            "timestamp": datetime.now(UTC).isoformat(),
            "fields": [],
        }

        # Add data fields
        for key, value in notification.data.items():
            if len(embed["fields"]) < 25:  # Discord limit
                embed["fields"].append({"name": str(key)[:256], "value": str(value)[:1024], "inline": True})

        payload = {"embeds": [embed]}

        async def _send():
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response,
            ):
                if response.status in [200, 204]:
                    logger.debug("Discord notification sent: %s", notification.title)

                    return True
                logger.error("Discord error %s: %s", response.status, await response.text())

                return False

        return await self._send_with_retry(_send)


class TelegramChannel(NotificationChannel):
    """Telegram bot notifications"""

    def __init__(self, config: dict[str, Any]):
        super().__init__("telegram", config)
        self.bot_token = config.get("bot_token")
        self.chat_id = config.get("chat_id")

        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram bot token or chat ID not configured")
            self.enabled = False

    async def send(self, notification: Notification) -> bool:
        if not self.enabled or not AIOHTTP_AVAILABLE:
            return False

        if not self._check_rate_limit(notification.level.value):
            return False

        # Emoji based on level
        emojis = {
            NotificationLevel.DEBUG: "🔍",
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "❌",
            NotificationLevel.CRITICAL: "🚨",
        }

        emoji = emojis.get(notification.level, "ℹ️")
        text = f"{emoji} *{notification.title}*\n\n{notification.message}"

        if notification.data:
            text += "\n\n*Details:*\n"
            for key, value in notification.data.items():
                text += f"• {key}: `{value}`\n"

        # Truncate if too long
        if len(text) > 4096:
            text = text[:4093] + "..."

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_notification": notification.level in [NotificationLevel.DEBUG, NotificationLevel.INFO],
        }

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        async def _send():
            async with (
                aiohttp.ClientSession() as session,
                session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response,
            ):
                if response.status == 200:
                    logger.debug("Telegram notification sent: %s", notification.title)

                    return True
                logger.error("Telegram error %s: %s", response.status, await response.text())

                return False

        return await self._send_with_retry(_send)


class EmailChannel(NotificationChannel):
    """
    Email notifications via SendGrid API (primary) or raw SMTP (fallback).

    Priority:
      1. SendGrid API — if SENDGRID_API_KEY env var is set.
      2. Raw smtplib  — if SMTP credentials are configured (degraded mode).
      3. Disabled     — if neither is configured.

    Bounce/spam/unsubscribe suppressions are stored in the email_suppressions
    DB table and checked before every send.
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__("email", config)
        self.smtp_host = config.get("smtp_host")
        self.smtp_port = config.get("smtp_port", 587)
        self.username = config.get("username")
        self.password = config.get("password")
        self.from_addr = config.get("from_addr") or os.getenv("SMTP_FROM", "")
        self.to_addrs: list[str] = config.get("to_addrs", [])

        # Determine send mode
        self.sendgrid_api_key: str | None = os.getenv("SENDGRID_API_KEY") or config.get("sendgrid_api_key")
        if self.sendgrid_api_key and SENDGRID_AVAILABLE:
            self._send_mode = "sendgrid"
        elif self.smtp_host and self.username and self.password and SMTP_AVAILABLE:
            self._send_mode = "smtp"
            logger.warning("Email: SENDGRID_API_KEY not set — using raw SMTP fallback (degraded deliverability)")
        else:
            self._send_mode = "disabled"
            logger.warning("Email: no credentials configured — channel disabled")
            self.enabled = False

        # Higher rate limit for email
        self.rate_limit_seconds = config.get("rate_limit_seconds", 300)

        # In-memory suppression cache (populated from DB on first use)
        self._suppressed_emails: set = set()
        self._suppressions_loaded = False

    # ------------------------------------------------------------------
    # Suppression helpers
    # ------------------------------------------------------------------

    def _load_suppressions(self) -> None:
        """Load suppressed addresses from DB into the in-memory set."""
        if self._suppressions_loaded:
            return
        try:
            from database.connection import get_db_manager
            from database.models import EmailSuppression

            db = get_db_manager()
            if db and hasattr(db, "_engine"):
                from sqlalchemy.orm import sessionmaker

                Session = sessionmaker(bind=db._engine)
                with Session() as session:
                    rows = session.query(EmailSuppression.email).all()
                    self._suppressed_emails = {r.email.lower() for r in rows}
        except Exception as exc:
            logger.debug("Could not load email suppressions: %s", exc)
        self._suppressions_loaded = True

    def _is_suppressed(self, email: str) -> bool:
        self._load_suppressions()
        return email.lower() in self._suppressed_emails

    # ------------------------------------------------------------------
    # Async send entry point
    # ------------------------------------------------------------------

    async def send(self, notification: Notification) -> bool:
        if not self.enabled:
            return False

        if not self._check_rate_limit(notification.level.value):
            return False

        # Only send WARNING and above via email
        if notification.level.value not in ["warning", "error", "critical"]:
            return False

        # Filter suppressed recipients
        recipients = [a for a in self.to_addrs if not self._is_suppressed(a)]
        if not recipients:
            logger.debug("Email: all recipients suppressed — skipping send")
            return False

        subject = f"[HOPEFX] {notification.level.value.upper()}: {notification.title}"
        plain_body = (
            f"HOPEFX Trading System Notification\n\n"
            f"Level: {notification.level.value.upper()}\n"
            f"Time:  {datetime.fromtimestamp(notification.timestamp).isoformat()}\n"
            f"Title: {notification.title}\n\n"
            f"Message:\n{notification.message}\n\n"
            f"Details:\n{json.dumps(notification.data, indent=2, default=str)}\n\n"
            f"---\nThis is an automated message from HOPEFX AI Trading System"
        )

        # Render HTML template if one is specified in notification.data
        html_body: str | None = None
        template_name = notification.data.get("email_template")
        if template_name:
            try:
                from notifications.email_renderer import render_email

                html_body = render_email(
                    template_name,
                    title=notification.title,
                    message=notification.message,
                    level=notification.level.value,
                    timestamp=datetime.fromtimestamp(notification.timestamp).isoformat(),
                    **{k: v for k, v in notification.data.items() if k != "email_template"},
                )
            except Exception as exc:
                logger.warning("Email template render failed, using plain text: %s", exc)

        if self._send_mode == "sendgrid":
            return await asyncio.get_event_loop().run_in_executor(
                None,
                self._send_via_sendgrid,
                recipients,
                subject,
                plain_body,
                html_body,
            )
        if self._send_mode == "smtp":
            return await asyncio.get_event_loop().run_in_executor(
                None, self._send_via_smtp, recipients, subject, plain_body, html_body
            )
        return False

    # ------------------------------------------------------------------
    # SendGrid transport
    # ------------------------------------------------------------------

    def _send_via_sendgrid(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> bool:
        try:
            sg = SendGridAPIClient(api_key=self.sendgrid_api_key)
            message = Mail(
                from_email=self.from_addr or "noreply@hopefx.io",
                to_emails=recipients,
                subject=subject,
                plain_text_content=body,
            )
            if html_body:
                message.html_content = HtmlContent(html_body)
            response = sg.send(message)
            if response.status_code in (200, 202):
                logger.debug("SendGrid email sent (status %s)", response.status_code)
                return True
            logger.error("SendGrid error %s: %s", response.status_code, response.body)
            return False
        except Exception as exc:
            logger.error("SendGrid send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # SMTP fallback transport
    # ------------------------------------------------------------------

    def _send_via_smtp(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_addr or self.username
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            if html_body:
                msg.attach(MIMEText(html_body, "html"))
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            return True
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            return False


class ConsoleChannel(NotificationChannel):
    """Console output for development"""

    def __init__(self, config: dict[str, Any]):
        super().__init__("console", config)
        self.colors = {
            NotificationLevel.DEBUG: "\033[90m",  # Gray
            NotificationLevel.INFO: "\033[92m",  # Green
            NotificationLevel.WARNING: "\033[93m",  # Yellow
            NotificationLevel.ERROR: "\033[91m",  # Red
            NotificationLevel.CRITICAL: "\033[95m",  # Magenta
        }
        self.reset = "\033[0m"

    async def send(self, notification: Notification) -> bool:
        color = self.colors.get(notification.level, "")
        reset = self.reset

        print(f"{color}[{notification.level.value.upper()}] {notification.title}{reset}")
        print(f"  {notification.message}")

        if notification.data:
            for key, value in notification.data.items():
                print(f"  • {key}: {value}")

        return True


class NotificationManager:
    """
    Central notification manager with:
    - Multi-channel support
    - Rate limiting per channel
    - Async batch processing
    - Priority queue
    - Deduplication
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.channels: dict[str, NotificationChannel] = {}
        self._notification_queue: asyncio.Queue = asyncio.Queue()
        self._processed_ids: set = set()
        self._max_history = 1000
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        # Sync API: list of enabled channel names
        self.enabled_channels: list[str] = [NotificationChannel.CONSOLE]
        if self.config.get("discord_enabled") or self.config.get("discord_webhook_url"):
            self.enabled_channels.append(NotificationChannel.DISCORD)
        if self.config.get("telegram_enabled") or self.config.get("telegram_bot_token"):
            self.enabled_channels.append(NotificationChannel.TELEGRAM)
        if self.config.get("email_enabled") or self.config.get("email_smtp_host"):
            self.enabled_channels.append(NotificationChannel.EMAIL)

        # Notification history for sync API
        self.notification_history: list[dict[str, Any]] = []

        self._initialize_channels()

    def _initialize_channels(self):
        """Initialize configured channels"""
        # Discord
        if self.config.get("discord_webhook"):
            self.channels["discord"] = DiscordChannel(
                {
                    "webhook_url": self.config["discord_webhook"],
                    "enabled": self.config.get("discord_enabled", True),
                    "rate_limit_seconds": self.config.get("discord_rate_limit", 60),
                }
            )

        # Telegram
        if self.config.get("telegram_bot_token") and self.config.get("telegram_chat_id"):
            self.channels["telegram"] = TelegramChannel(
                {
                    "bot_token": self.config["telegram_bot_token"],
                    "chat_id": self.config["telegram_chat_id"],
                    "enabled": self.config.get("telegram_enabled", True),
                    "rate_limit_seconds": self.config.get("telegram_rate_limit", 60),
                }
            )

        # Email
        if self.config.get("smtp_host"):
            self.channels["email"] = EmailChannel(
                {
                    "smtp_host": self.config["smtp_host"],
                    "smtp_port": self.config.get("smtp_port", 587),
                    "username": self.config.get("smtp_username"),
                    "password": self.config.get("smtp_password"),
                    "from_addr": self.config.get("smtp_from"),
                    "to_addrs": self.config.get("smtp_to", []),
                    "enabled": self.config.get("email_enabled", True),
                }
            )

        # Console (always enabled in development)
        if self.config.get("environment") == "development":
            self.channels["console"] = ConsoleChannel({"enabled": True})

        logger.info("Notification channels initialized: %s", list(self.channels.keys()))


    async def start(self):
        """Start notification processor"""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("Notification manager started")

    async def stop(self):
        """Stop notification processor"""
        self._running = False

        if self._worker_task:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task

        logger.info("Notification manager stopped")

    async def send_alert(
        self,
        level: str,
        title: str,
        message: str = "",
        data: dict[str, Any] | None = None,
        channels: list[str] | None = None,
        bypass_rate_limit: bool = False,
    ) -> bool:
        """
        Send alert through configured channels

        Args:
            level: debug, info, warning, error, critical
            title: Alert title
            message: Alert message
            data: Additional data dict
            channels: Specific channels to use (None = all)
            bypass_rate_limit: Bypass rate limiting (use sparingly)
        """
        try:
            notif_level = NotificationLevel(level.lower())
        except ValueError:
            notif_level = NotificationLevel.INFO

        notification = Notification(
            level=notif_level,
            title=title,
            message=message,
            data=data or {},
            channels=channels or list(self.channels.keys()),
        )

        # Deduplication check (simple)
        content_hash = hash((title, message, str(sorted((data or {}).items()))))
        if content_hash in self._processed_ids:
            logger.debug("Duplicate notification suppressed: %s", title)

            return False

        # Add to queue
        await self._notification_queue.put(notification)

        with self._lock:
            self._processed_ids.add(content_hash)
            if len(self._processed_ids) > self._max_history:
                self._processed_ids.clear()  # Reset to prevent memory growth

        return True

    async def _process_queue(self):
        """Process notification queue"""
        while self._running:
            try:
                notification = await asyncio.wait_for(self._notification_queue.get(), timeout=1.0)

                # Send to each channel
                for channel_name in notification.channels:
                    channel = self.channels.get(channel_name)
                    if not channel or not channel.enabled:
                        continue

                    try:
                        success = await asyncio.wait_for(channel.send(notification), timeout=10.0)

                        if not success:
                            logger.warning("Failed to send to %s", channel_name)


                    except Exception as e:
                        logger.error("Error sending to %s: %s", channel_name, e)


                self._notification_queue.task_done()

            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Notification processor error: %s", e)


    # ------------------------------------------------------------------
    # Sync API (used by tests)
    # ------------------------------------------------------------------

    def send(
        self,
        message: str,
        level: "NotificationLevel" = None,
        channels: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Synchronous send — dispatches to each requested channel, swallowing errors."""
        targets = channels if channels is not None else self.enabled_channels
        for ch in targets:
            try:
                if ch == NotificationChannel.CONSOLE:
                    self._send_console(message, level)
                elif ch == NotificationChannel.DISCORD:
                    self._send_discord(message, level, metadata)
                elif ch == NotificationChannel.TELEGRAM:
                    self._send_telegram(message, level, metadata)
                elif ch == NotificationChannel.EMAIL:
                    self._send_email(message, level, metadata)
            except Exception as exc:
                logger.error("Notification channel %s error: %s", ch, exc)

        # Record in history
        self.notification_history.append(
            {
                "message": message,
                "level": getattr(level, "value", str(level)) if level else "INFO",
                "channels": list(targets),
                "metadata": metadata or {},
            }
        )

    def notify_trade(
        self,
        symbol: str,
        price: float,
        quantity: float = 0,
        action: str | None = None,
        side: str | None = None,
        trade_id: str | None = None,
        pnl: float | None = None,
        channels: list[str] | None = None,
        **kwargs,
    ) -> None:
        """Send a trade notification."""
        direction = action or side or "TRADE"
        msg = f"{direction} {quantity} {symbol} @ {price}"
        if pnl is not None:
            msg += f" | PnL: {pnl:+.2f}"
        meta: dict[str, Any] = {"symbol": symbol, "price": price, "quantity": quantity}
        if action:
            meta["action"] = action
        if side:
            meta["side"] = side
        if trade_id:
            meta["trade_id"] = trade_id
        if pnl is not None:
            meta["pnl"] = pnl
        meta.update(kwargs)
        self.send(msg, level=NotificationLevel.INFO, channels=channels, metadata=meta)

    def notify_signal(
        self,
        symbol: str,
        signal_type: str,
        strategy: str | None = None,
        price: float | None = None,
        confidence: float | None = None,
        strength: float | None = None,
        channels: list[str] | None = None,
        **kwargs,
    ) -> None:
        """Send a trading signal notification."""
        msg = f"Signal: {signal_type} {symbol}"
        if strategy:
            msg += f" [{strategy}]"
        conf = confidence if confidence is not None else strength
        if conf is not None:
            msg += f" conf={conf:.2f}"
        meta: dict[str, Any] = {"symbol": symbol, "signal_type": signal_type}
        if strategy:
            meta["strategy"] = strategy
        if price is not None:
            meta["price"] = price
        if confidence is not None:
            meta["confidence"] = confidence
        if strength is not None:
            meta["strength"] = strength
        meta.update(kwargs)
        self.send(msg, level=NotificationLevel.INFO, channels=channels, metadata=meta)

    def _send_console(self, message: str, level: "NotificationLevel" = None) -> None:
        """Log message to console at the appropriate level."""
        lvl = getattr(level, "value", str(level)).upper() if level else "INFO"
        log_fn = {
            "DEBUG": logger.debug,
            "INFO": logger.info,
            "WARNING": logger.warning,
            "ERROR": logger.error,
            "CRITICAL": logger.critical,
        }.get(lvl, logger.info)
        log_fn(f"[NOTIFICATION] {message}")

    def _send_discord(self, message: str, level: "NotificationLevel" = None, metadata: dict | None = None) -> None:
        """Send message to Discord webhook (sync)."""
        if requests is None:
            logger.warning("requests not installed; cannot send Discord notification")
            return
        webhook_url = self.config.get("discord_webhook_url", "")
        if not webhook_url:
            logger.debug("Discord webhook not configured; skipping")
            return
        from urllib.parse import urlparse as _urlparse
        _p = _urlparse(webhook_url)
        _host = (_p.hostname or "").lower()
        if _p.scheme != "https" or _host not in ("discord.com", "discordapp.com"):
            logger.warning("Rejecting Discord webhook: must be HTTPS discord.com URL")
            return
        embed: dict[str, Any] = {"description": message}
        if metadata:
            embed["fields"] = [{"name": str(k), "value": str(v), "inline": True} for k, v in metadata.items()]
        payload: dict[str, Any] = {"embeds": [embed]}
        try:
            resp = requests.post(webhook_url, json=payload, timeout=5)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Discord send failed: %s", exc)


    def _send_telegram(self, message: str, level: "NotificationLevel" = None, metadata: dict | None = None) -> None:
        """Send message via Telegram Bot API (sync)."""
        if requests is None:
            logger.warning("requests not installed; cannot send Telegram notification")
            return
        token = self.config.get("telegram_bot_token", "")
        chat_id = self.config.get("telegram_chat_id", "")
        if not token or not chat_id:
            logger.debug("Telegram not configured; skipping")
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        text = message
        if metadata:
            text += "\n" + "\n".join(f"{k}: {v}" for k, v in metadata.items())
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        try:
            resp = requests.post(url, json=payload, timeout=5)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)


    def _send_email(self, message: str, level: "NotificationLevel" = None, metadata: dict | None = None) -> None:
        """Send email notification — SendGrid primary, SMTP fallback (sync)."""
        to_addr = self.config.get("smtp_to") or self.config.get("email_to") or self.config.get("smtp_username", "")
        if not to_addr:
            logger.debug("Email not configured; skipping")
            return

        from_addr = (
            self.config.get("smtp_from")
            or os.getenv("SMTP_FROM")
            or self.config.get("smtp_username", "noreply@hopefx.io")
        )
        subject = f"[HOPEFX] {getattr(level, 'value', 'INFO').upper()}: {message[:60]}"
        body = message
        if metadata:
            body += "\n\n" + "\n".join(f"{k}: {v}" for k, v in metadata.items())

        sendgrid_key = os.getenv("SENDGRID_API_KEY") or self.config.get("sendgrid_api_key", "")
        if sendgrid_key and SENDGRID_AVAILABLE:
            try:
                sg = SendGridAPIClient(api_key=sendgrid_key)
                mail = Mail(
                    from_email=from_addr,
                    to_emails=[to_addr],
                    subject=subject,
                    plain_text_content=body,
                )
                sg.send(mail)
                return
            except Exception as exc:
                logger.error("SendGrid send failed: %s", exc)
                # Fall through to SMTP

        # SMTP fallback
        smtp_host = self.config.get("smtp_host") or self.config.get("email_smtp_host") or ""
        smtp_port = int(self.config.get("smtp_port", 587))
        username = self.config.get("smtp_username", "")
        password = self.config.get("smtp_password", "")
        if not smtp_host or not username:
            logger.debug("SMTP not configured; skipping email fallback")
            return
        try:
            from email.mime.text import MIMEText

            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to_addr
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(username, password)
                server.sendmail(from_addr, [to_addr], msg.as_string())
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)

    def get_status(self) -> dict[str, Any]:
        """Get notification manager status"""
        return {
            "running": self._running,
            "queue_size": self._notification_queue.qsize(),
            "channels": {
                name: {
                    "enabled": ch.enabled,
                    "rate_limited": not ch._check_rate_limit(),
                }
                for name, ch in self.channels.items()
            },
        }


# Global instance
_notification_manager: NotificationManager | None = None


def get_notification_manager() -> NotificationManager | None:
    """Get global notification manager"""
    return _notification_manager


def init_notification_manager(config: dict[str, Any]) -> NotificationManager:
    """Initialize global notification manager"""
    global _notification_manager
    _notification_manager = NotificationManager(config)
    return _notification_manager
