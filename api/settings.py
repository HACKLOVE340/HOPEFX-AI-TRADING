"""
api/settings.py
===============
User-facing settings endpoints with DB persistence.

Routes
------
POST /api/settings/notifications   — save notification channel config
GET  /api/settings/notifications   — retrieve current config
POST /api/notifications/test       — send a test message to a channel

Settings are stored in the `configurations` table keyed by
`notification_settings:{user_id}`. Falls back to an in-memory dict when
the DB is unavailable (dev mode without a running database).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Settings"])

# In-memory fallback (used when DB is unavailable)
_notification_config: Dict[str, Any] = {}

# Config key prefix in the configurations table
_CONFIG_KEY_PREFIX = "notification_settings"


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


# ── DB helpers ────────────────────────────────────────────────────────────────


def _get_user_id(request: Request) -> str:
    """Extract user_id from JWT token, fall back to 'anonymous'."""
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            import os

            import jwt as pyjwt

            secret = os.getenv(
                "JWT_SECRET_KEY", "hopefx-secret-key-change-in-production"
            )
            payload = pyjwt.decode(token, secret, algorithms=["HS256"])
            return str(payload.get("sub", "anonymous"))
    except Exception as exc:
        logger.debug(
            "Settings user extraction failed, defaulting to anonymous: %s", exc
        )
    return "anonymous"


def _db_save(user_id: str, data: dict) -> bool:
    """Persist settings to the configurations table. Returns True on success."""
    try:
        from database.connection import get_db_manager
        from database.models import Configuration

        mgr = get_db_manager()
        if not mgr:
            return False
        session = mgr.get_session()
        if not session:
            return False

        key = f"{_CONFIG_KEY_PREFIX}:{user_id}"
        value = json.dumps(data)
        existing = session.query(Configuration).filter_by(config_key=key).first()
        if existing:
            existing.config_value = value
            existing.changed_by = user_id
        else:
            from database.models import Configuration as Cfg

            record = Cfg(
                environment="production",
                config_key=key,
                config_value=value,
                changed_by=user_id,
                change_reason="user notification settings update",
            )
            session.add(record)
        session.commit()
        return True
    except Exception as exc:
        logger.debug("DB save failed for settings: %s", exc)
        return False


def _db_load(user_id: str) -> Optional[dict]:
    """Load settings from the configurations table. Returns None on miss/error."""
    try:
        from database.connection import get_db_manager
        from database.models import Configuration

        mgr = get_db_manager()
        if not mgr:
            return None
        session = mgr.get_session()
        if not session:
            return None

        key = f"{_CONFIG_KEY_PREFIX}:{user_id}"
        record = session.query(Configuration).filter_by(config_key=key).first()
        if record and record.config_value:
            return json.loads(record.config_value)
    except Exception as exc:
        logger.debug("DB load failed for settings: %s", exc)
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/api/settings/notifications", summary="Save notification settings")
async def save_notification_settings(body: NotificationSettings, request: Request):
    global _notification_config
    data = body.model_dump()
    user_id = _get_user_id(request)

    saved_to_db = _db_save(user_id, data)
    if not saved_to_db:
        _notification_config[user_id] = data
    else:
        logger.info("Notification settings persisted to DB for user %s", user_id)

    return {"status": "saved", "persisted": saved_to_db}


@router.get("/api/settings/notifications", summary="Get notification settings")
async def get_notification_settings(request: Request):
    user_id = _get_user_id(request)

    db_data = _db_load(user_id)
    if db_data:
        return {**NotificationSettings().model_dump(), **db_data}

    mem_data = _notification_config.get(user_id)
    if mem_data:
        return mem_data

    return NotificationSettings().model_dump()


@router.post("/api/notifications/test", summary="Send a test notification")
async def test_notification(body: TestNotificationRequest):
    """Send a test message to the specified channel."""
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
        "embeds": [
            {
                "title": "HOPEFX — Test Notification",
                "description": "Discord notifications are working correctly.",
                "color": 0x22C55E,
            }
        ]
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

    payload = {"text": "*HOPEFX* — Slack notifications are working correctly."}
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
        "text": "*HOPEFX* — Telegram notifications are working correctly.",
        "parse_mode": "Markdown",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise ValueError(
                    f"Telegram error: {data.get('description', 'unknown')}"
                )
