"""
api/settings.py
===============
User-facing settings endpoints.

Routes
------
POST /api/settings/notifications   — save notification channel config
GET  /api/settings/notifications   — retrieve current config
POST /api/notifications/test       — send a test message to a channel
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Settings"])

# In-memory store (replace with DB in production)
_notification_config: Dict[str, Any] = {}


# ── Models ────────────────────────────────────────────────────────────────────

class NotificationSettings(BaseModel):
    discord_enabled: bool = False
    discord_webhook_url: str = ""
    slack_enabled: bool = False
    slack_webhook_url: str = ""
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    email_enabled: bool = False
    email_address: str = ""
    notify_on_trade: bool = True
    notify_on_signal: bool = True
    notify_on_error: bool = True
    notify_on_daily_summary: bool = True


class TestNotificationRequest(BaseModel):
    channel: str  # "discord" | "slack" | "telegram"
    settings: NotificationSettings


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/settings/notifications", summary="Save notification settings")
async def save_notification_settings(body: NotificationSettings):
    global _notification_config
    _notification_config = body.model_dump()
    logger.info("Notification settings updated")
    return {"status": "saved"}


@router.get("/api/settings/notifications", summary="Get notification settings")
async def get_notification_settings():
    return _notification_config or NotificationSettings().model_dump()


@router.post("/api/notifications/test", summary="Send a test notification")
async def test_notification(body: TestNotificationRequest):
    """
    Send a test message to the specified channel using the provided config.
    Returns 200 on success, 502 if the channel rejects the message.
    """
    channel = body.channel.lower()
    cfg = body.settings

    try:
        if channel == "discord":
            await _test_discord(cfg.discord_webhook_url)
        elif channel == "slack":
            await _test_slack(cfg.slack_webhook_url)
        elif channel == "telegram":
            await _test_telegram(cfg.telegram_bot_token, cfg.telegram_chat_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown channel: {channel}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Test notification failed for %s: %s", channel, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Channel delivery failed: {exc}",
        )

    return {"status": "delivered", "channel": channel}


# ── Channel helpers ───────────────────────────────────────────────────────────

async def _test_discord(webhook_url: str) -> None:
    if not webhook_url:
        raise ValueError("Discord webhook URL is empty")
    import aiohttp
    payload = {
        "embeds": [{
            "title": "HOPEFX — Test Notification",
            "description": "✅ Discord notifications are working correctly.",
            "color": 0x22C55E,
        }]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, json=payload) as resp:
            if resp.status not in (200, 204):
                text = await resp.text()
                raise ValueError(f"Discord returned {resp.status}: {text[:200]}")


async def _test_slack(webhook_url: str) -> None:
    if not webhook_url:
        raise ValueError("Slack webhook URL is empty")
    import aiohttp
    payload = {"text": "✅ *HOPEFX* — Slack notifications are working correctly."}
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"Slack returned {resp.status}: {text[:200]}")


async def _test_telegram(bot_token: str, chat_id: str) -> None:
    if not bot_token or not chat_id:
        raise ValueError("Telegram bot token or chat ID is empty")
    import aiohttp
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "✅ *HOPEFX* — Telegram notifications are working correctly.",
        "parse_mode": "Markdown",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise ValueError(f"Telegram error: {data.get('description', 'unknown')}")
