"""
HOPEFX Notification Manager
Multi-channel alerts with rate limiting, batching, and templating
"""

import asyncio
import logging
import time
import json
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    requests = None  # type: ignore
from enum import Enum
import queue
import threading

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    SMTP_AVAILABLE = True
except ImportError:
    SMTP_AVAILABLE = False

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
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    channels: List[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(int(time.time() * 1000)))
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'level': self.level.value,
            'title': self.title,
            'message': self.message,
            'data': self.data,
            'timestamp': datetime.fromtimestamp(self.timestamp).isoformat(),
            'channels': self.channels
        }


class NotificationChannel:
    """Base notification channel — also used as an enum-like namespace."""

    # Enum-style constants used by tests
    CONSOLE = "console"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    EMAIL = "email"

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.enabled = config.get('enabled', True)
        self.rate_limit_seconds = config.get('rate_limit_seconds', 60)
        self._last_send_time: Dict[str, float] = {}
        self._lock = asyncio.Lock()
    
    async def send(self, notification: Notification) -> bool:
        """Send notification - implement in subclass"""
        raise NotImplementedError
    
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
                logger.error(f"{self.name} send failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        return False


class DiscordChannel(NotificationChannel):
    """Discord webhook notifications"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("discord", config)
        self.webhook_url = config.get('webhook_url')
        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured")
            self.enabled = False
    
    async def send(self, notification: Notification) -> bool:
        if not self.enabled or not AIOHTTP_AVAILABLE:
            return False
        
        if not self._check_rate_limit(notification.level.value):
            logger.debug(f"Discord rate limited for {notification.level.value}")
            return False
        
        # Color based on level
        colors = {
            NotificationLevel.DEBUG: 0x808080,
            NotificationLevel.INFO: 0x00FF00,
            NotificationLevel.WARNING: 0xFFA500,
            NotificationLevel.ERROR: 0xFF0000,
            NotificationLevel.CRITICAL: 0x8B0000
        }
        
        embed = {
            "title": notification.title,
            "description": notification.message[:2000],  # Discord limit
            "color": colors.get(notification.level, 0x808080),
            "timestamp": datetime.utcnow().isoformat(),
            "fields": []
        }
        
        # Add data fields
        for key, value in notification.data.items():
            if len(embed['fields']) < 25:  # Discord limit
                embed['fields'].append({
                    "name": str(key)[:256],
                    "value": str(value)[:1024],
                    "inline": True
                })
        
        payload = {"embeds": [embed]}
        
        async def _send():
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status in [200, 204]:
                        logger.debug(f"Discord notification sent: {notification.title}")
                        return True
                    else:
                        logger.error(f"Discord error {response.status}: {await response.text()}")
                        return False
        
        return await self._send_with_retry(_send)


class TelegramChannel(NotificationChannel):
    """Telegram bot notifications"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("telegram", config)
        self.bot_token = config.get('bot_token')
        self.chat_id = config.get('chat_id')
        
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
            NotificationLevel.CRITICAL: "🚨"
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
            "disable_notification": notification.level in [NotificationLevel.DEBUG, NotificationLevel.INFO]
        }
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        async def _send():
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.debug(f"Telegram notification sent: {notification.title}")
                        return True
                    else:
                        logger.error(f"Telegram error {response.status}: {await response.text()}")
                        return False
        
        return await self._send_with_retry(_send)


class EmailChannel(NotificationChannel):
    """Email notifications"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("email", config)
        self.smtp_host = config.get('smtp_host')
        self.smtp_port = config.get('smtp_port', 587)
        self.username = config.get('username')
        self.password = config.get('password')
        self.from_addr = config.get('from_addr')
        self.to_addrs = config.get('to_addrs', [])
        
        if not all([self.smtp_host, self.username, self.password]):
            logger.warning("Email SMTP not fully configured")
            self.enabled = False
        
        # Higher rate limit for email
        self.rate_limit_seconds = config.get('rate_limit_seconds', 300)  # 5 minutes
    
    async def send(self, notification: Notification) -> bool:
        if not self.enabled or not SMTP_AVAILABLE:
            return False
        
        if not self._check_rate_limit(notification.level.value):
            return False
        
        # Only send WARNING and above via email
        if notification.level.value not in ['warning', 'error', 'critical']:
            return False
        
        def _send_sync():
            try:
                msg = MIMEMultipart()
                msg['From'] = self.from_addr
                msg['To'] = ", ".join(self.to_addrs)
                msg['Subject'] = f"[HOPEFX] {notification.level.value.upper()}: {notification.title}"
                
                body = f"""
HOPEFX Trading System Notification

Level: {notification.level.value.upper()}
Time: {datetime.fromtimestamp(notification.timestamp).isoformat()}
Title: {notification.title}

Message:
{notification.message}

Details:
{json.dumps(notification.data, indent=2, default=str)}

---
This is an automated message from HOPEFX AI Trading System
                """
                
                msg.attach(MIMEText(body, 'plain'))
                
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.username, self.password)
                    server.send_message(msg)
                
                return True
                
            except Exception as e:
                logger.error(f"Email send failed: {e}")
                return False
        
        # Run in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _send_sync)


class ConsoleChannel(NotificationChannel):
    """Console output for development"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("console", config)
        self.colors = {
            NotificationLevel.DEBUG: "\033[90m",    # Gray
            NotificationLevel.INFO: "\033[92m",       # Green
            NotificationLevel.WARNING: "\033[93m",    # Yellow
            NotificationLevel.ERROR: "\033[91m",      # Red
            NotificationLevel.CRITICAL: "\033[95m"    # Magenta
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
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.channels: Dict[str, NotificationChannel] = {}
        self._notification_queue: asyncio.Queue = asyncio.Queue()
        self._processed_ids: set = set()
        self._max_history = 1000
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Sync API: list of enabled channel names
        self.enabled_channels: List[str] = [NotificationChannel.CONSOLE]
        if self.config.get("discord_enabled") or self.config.get("discord_webhook_url"):
            self.enabled_channels.append(NotificationChannel.DISCORD)
        if self.config.get("telegram_enabled") or self.config.get("telegram_bot_token"):
            self.enabled_channels.append(NotificationChannel.TELEGRAM)
        if self.config.get("email_enabled") or self.config.get("email_smtp_host"):
            self.enabled_channels.append(NotificationChannel.EMAIL)

        # Notification history for sync API
        self.notification_history: List[Dict[str, Any]] = []

        self._initialize_channels()
    
    def _initialize_channels(self):
        """Initialize configured channels"""
        # Discord
        if self.config.get('discord_webhook'):
            self.channels['discord'] = DiscordChannel({
                'webhook_url': self.config['discord_webhook'],
                'enabled': self.config.get('discord_enabled', True),
                'rate_limit_seconds': self.config.get('discord_rate_limit', 60)
            })
        
        # Telegram
        if self.config.get('telegram_bot_token') and self.config.get('telegram_chat_id'):
            self.channels['telegram'] = TelegramChannel({
                'bot_token': self.config['telegram_bot_token'],
                'chat_id': self.config['telegram_chat_id'],
                'enabled': self.config.get('telegram_enabled', True),
                'rate_limit_seconds': self.config.get('telegram_rate_limit', 60)
            })
        
        # Email
        if self.config.get('smtp_host'):
            self.channels['email'] = EmailChannel({
                'smtp_host': self.config['smtp_host'],
                'smtp_port': self.config.get('smtp_port', 587),
                'username': self.config.get('smtp_username'),
                'password': self.config.get('smtp_password'),
                'from_addr': self.config.get('smtp_from'),
                'to_addrs': self.config.get('smtp_to', []),
                'enabled': self.config.get('email_enabled', True)
            })
        
        # Console (always enabled in development)
        if self.config.get('environment') == 'development':
            self.channels['console'] = ConsoleChannel({'enabled': True})
        
        logger.info(f"Notification channels initialized: {list(self.channels.keys())}")
    
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
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Notification manager stopped")
    
    async def send_alert(
        self,
        level: str,
        title: str,
        message: str = "",
        data: Dict[str, Any] = None,
        channels: Optional[List[str]] = None,
        bypass_rate_limit: bool = False
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
            channels=channels or list(self.channels.keys())
        )
        
        # Deduplication check (simple)
        content_hash = hash((title, message, str(sorted((data or {}).items()))))
        if content_hash in self._processed_ids:
            logger.debug(f"Duplicate notification suppressed: {title}")
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
                notification = await asyncio.wait_for(
                    self._notification_queue.get(),
                    timeout=1.0
                )
                
                # Send to each channel
                for channel_name in notification.channels:
                    channel = self.channels.get(channel_name)
                    if not channel or not channel.enabled:
                        continue
                    
                    try:
                        success = await asyncio.wait_for(
                            channel.send(notification),
                            timeout=10.0
                        )
                        
                        if not success:
                            logger.warning(f"Failed to send to {channel_name}")
                            
                    except Exception as e:
                        logger.error(f"Error sending to {channel_name}: {e}")
                
                self._notification_queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification processor error: {e}")
    
    # ------------------------------------------------------------------
    # Sync API (used by tests)
    # ------------------------------------------------------------------

    def send(self, message: str, level: "NotificationLevel" = None,
             channels: List[str] = None, metadata: Dict = None) -> None:
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
                logger.error(f"Notification channel {ch} error: {exc}")
        # Record in history
        self.notification_history.append({
            "message": message,
            "level": getattr(level, "value", str(level)) if level else "INFO",
            "channels": list(targets),
            "metadata": metadata or {},
        })

    def notify_trade(self, symbol: str, price: float, quantity: float = 0,
                     action: str = None, side: str = None, trade_id: str = None,
                     pnl: float = None, channels: List[str] = None, **kwargs) -> None:
        """Send a trade notification."""
        direction = action or side or "TRADE"
        msg = f"{direction} {quantity} {symbol} @ {price}"
        if pnl is not None:
            msg += f" | PnL: {pnl:+.2f}"
        meta: Dict[str, Any] = {"symbol": symbol, "price": price, "quantity": quantity}
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

    def notify_signal(self, symbol: str, signal_type: str, strategy: str = None,
                      price: float = None, confidence: float = None,
                      strength: float = None, channels: List[str] = None, **kwargs) -> None:
        """Send a trading signal notification."""
        msg = f"Signal: {signal_type} {symbol}"
        if strategy:
            msg += f" [{strategy}]"
        conf = confidence if confidence is not None else strength
        if conf is not None:
            msg += f" conf={conf:.2f}"
        meta: Dict[str, Any] = {"symbol": symbol, "signal_type": signal_type}
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

    def _send_discord(self, message: str, level: "NotificationLevel" = None,
                      metadata: Dict = None) -> None:
        """Send message to Discord webhook (sync)."""
        if requests is None:
            logger.warning("requests not installed; cannot send Discord notification")
            return
        webhook_url = self.config.get("discord_webhook_url", "")
        if not webhook_url:
            logger.debug("Discord webhook not configured; skipping")
            return
        if not webhook_url.startswith("https://"):
            logger.warning(f"Rejecting non-HTTPS Discord webhook: {webhook_url}")
            return
        embed: Dict[str, Any] = {"description": message}
        if metadata:
            embed["fields"] = [{"name": str(k), "value": str(v), "inline": True}
                                for k, v in metadata.items()]
        payload: Dict[str, Any] = {"embeds": [embed]}
        try:
            resp = requests.post(webhook_url, json=payload, timeout=5)
            resp.raise_for_status()
        except Exception as exc:
            logger.error(f"Discord send failed: {exc}")

    def _send_telegram(self, message: str, level: "NotificationLevel" = None,
                       metadata: Dict = None) -> None:
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
            logger.error(f"Telegram send failed: {exc}")

    def _send_email(self, message: str, level: "NotificationLevel" = None,
                    metadata: Dict = None) -> None:
        """Send email notification via SMTP (sync)."""
        import smtplib
        from email.mime.text import MIMEText
        smtp_host = (self.config.get("smtp_host") or
                     self.config.get("email_smtp_host") or
                     ("localhost" if self.config.get("email_enabled") else ""))
        smtp_port = int(self.config.get("smtp_port", 587))
        username = self.config.get("smtp_username", "")
        password = self.config.get("smtp_password", "")
        to_addr = (self.config.get("smtp_to") or
                   self.config.get("email_to") or username)
        if not smtp_host or not username:
            logger.debug("Email not configured; skipping")
            return
        body = message
        if metadata:
            body += "\n\n" + "\n".join(f"{k}: {v}" for k, v in metadata.items())
        msg = MIMEText(body)
        msg["Subject"] = f"[HOPEFX] {getattr(level, 'value', 'INFO').upper()}: {message[:60]}"
        msg["From"] = username
        msg["To"] = to_addr
        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(username, password)
                server.sendmail(username, [to_addr], msg.as_string())
        except Exception as exc:
            logger.error(f"Email send failed: {exc}")

    def get_status(self) -> Dict[str, Any]:
        """Get notification manager status"""
        return {
            'running': self._running,
            'queue_size': self._notification_queue.qsize(),
            'channels': {
                name: {
                    'enabled': ch.enabled,
                    'rate_limited': not ch._check_rate_limit()
                }
                for name, ch in self.channels.items()
            }
        }


# Global instance
_notification_manager: Optional[NotificationManager] = None

def get_notification_manager() -> Optional[NotificationManager]:
    """Get global notification manager"""
    global _notification_manager
    return _notification_manager

def init_notification_manager(config: Dict[str, Any]) -> NotificationManager:
    """Initialize global notification manager"""
    global _notification_manager
    _notification_manager = NotificationManager(config)
    return _notification_manager
