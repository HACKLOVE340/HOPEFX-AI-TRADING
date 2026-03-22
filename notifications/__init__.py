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
import json

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
    data: Optional[Dict] = None
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            import time
            self.timestamp = time.time()

class NotificationManager:
    """
    Unified notification system
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.channels: Dict[str, bool] = {
            'discord': bool(self.config.get('discord_webhook')),
            'telegram': bool(self.config.get('telegram_bot_token')),
            'email': bool(self.config.get('smtp_host')),
            'webhook': bool(self.config.get('webhook_url'))
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
    
    async def send_alert(self, level: str, message: str, data: Dict = None):
        """Quick send method"""
        notification = Notification(
            level=NotificationLevel(level.lower()),
            message=message,
            data=data
        )
        await self.send(notification)
    
    async def _process_queue(self):
        """Process notification queue"""
        while self._running:
            try:
                notification = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                await self._dispatch(notification)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Notification processing error: {e}")
    
    async def _dispatch(self, notification: Notification):
        """Send to all configured channels"""
        tasks = []
        
        if self.channels.get('discord'):
            tasks.append(self._send_discord(notification))
        if self.channels.get('telegram'):
            tasks.append(self._send_telegram(notification))
        if self.channels.get('webhook'):
            tasks.append(self._send_webhook(notification))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_discord(self, notification: Notification):
        """Send to Discord webhook"""
        webhook_url = self.config.get('discord_webhook')
        if not webhook_url:
            return
        
        color_map = {
            NotificationLevel.INFO: 3447003,
            NotificationLevel.WARNING: 16776960,
            NotificationLevel.ERROR: 15158332,
            NotificationLevel.CRITICAL: 16711680
        }
        
        embed = {
            "title": f"HOPEFX Alert - {notification.level.value.upper()}",
            "description": notification.message,
            "color": color_map.get(notification.level, 3447003),
            "timestamp": self._format_timestamp(notification.timestamp),
            "fields": []
        }
        
        if notification.data:
            for key, value in notification.data.items():
                embed["fields"].append({
                    "name": key,
                    "value": str(value)[:1000],
                    "inline": True
                })
        
        payload = {"embeds": [embed]}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status != 204:
                    logger.error(f"Discord notification failed: {resp.status}")
    
    async def _send_telegram(self, notification: Notification):
        """Send to Telegram"""
        bot_token = self.config.get('telegram_bot_token')
        chat_id = self.config.get('telegram_chat_id')
        if not bot_token or not chat_id:
            return
        
        emoji_map = {
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "❌",
            NotificationLevel.CRITICAL: "🚨"
        }
        
        text = f"{emoji_map.get(notification.level, 'ℹ️')} *HOPEFX Alert*\\n"
        text += f"*{notification.level.value.upper()}*\\n\\n"
        text += notification.message
        
        if notification.data:
            text += "\\n\\n*Data:*\\n"
            for key, value in notification.data.items():
                text += f"• {key}: `{value}`\\n"
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"Telegram notification failed: {resp.status}")
    
    async def _send_webhook(self, notification: Notification):
        """Send to custom webhook"""
        webhook_url = self.config.get('webhook_url')
        if not webhook_url:
            return
        
        payload = {
            "source": "HOPEFX",
            "level": notification.level.value,
            "message": notification.message,
            "timestamp": notification.timestamp,
            "data": notification.data
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status >= 400:
                    logger.error(f"Webhook notification failed: {resp.status}")
    
    def _format_timestamp(self, timestamp: float) -> str:
        """Format timestamp for Discord"""
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.isoformat()

# Simple alert function for compatibility
async def send_alert(level: str, message: str, **kwargs):
    """Global alert function"""
    logger.log(
        getattr(logging, level.upper(), logging.INFO),
        f"ALERT [{level}]: {message}"
    )

# Compatibility alias
AlertEngine = NotificationManager

__version__ = "1.0.0"
