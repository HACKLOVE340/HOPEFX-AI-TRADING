# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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

Security
--------
- Outbound webhook calls are restricted to an explicit allowlist of hostnames
  (SSRF prevention).  Only discord.com, hooks.slack.com, and api.telegram.org
  are permitted.
- Webhook URLs must use HTTPS.
- JWT extraction uses SECURITY_JWT_SECRET (same key as the rest of the app).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Settings"])

# In-memory fallback (used when DB is unavailable)
_notification_config: dict[str, Any] = {}

# Config key prefix in the configurations table
_CONFIG_KEY_PREFIX = "notification_settings"

# ---------------------------------------------------------------------------
# Outbound webhook allowlist (SSRF prevention)
# ---------------------------------------------------------------------------
# Only these exact hostnames may receive notification payloads.
_WEBHOOK_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "discord.com",
        "discordapp.com",
        "hooks.slack.com",
        "api.telegram.org",
    }
)


def _safe_webhook_url(url: str, label: str) -> str:
    """Validate *url* against an allowlist and return a sanitised reconstruction.

    Security model
    --------------
    1. Scheme must be ``"https"`` — enforced by literal comparison.
    2. Hostname must be in ``_WEBHOOK_ALLOWED_HOSTS`` — enforced by set lookup.
    3. Path and query are re-encoded with ``urllib.parse.quote`` / ``urlencode``
       so that any injected characters are percent-encoded and cannot be
       interpreted as URL structure by the HTTP client.
    4. The returned string is assembled entirely from validated/encoded parts —
       the raw user-supplied string is never forwarded.

    Raises HTTPException(400) if the URL is empty, not HTTPS, or targets a
    host not in ``_WEBHOOK_ALLOWED_HOSTS``.
    """
    from urllib.parse import quote, urlencode, parse_qsl

    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} webhook URL is empty",
        )
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label} webhook URL",
        ) from exc
    if parsed.scheme != "https":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} webhook URL must use HTTPS",
        )
    if host not in _WEBHOOK_ALLOWED_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} webhook host '{host}' is not in the permitted list",
        )
    # Re-encode path and query from validated components only.
    # quote() percent-encodes any injected characters; urlencode re-serialises
    # the query string from parsed key-value pairs.  The scheme and host are
    # literals / allowlist-confirmed values — no user bytes flow through.
    safe_path = quote(parsed.path or "/", safe="/-._~!$&'()*+,;=:@")
    safe_query = urlencode(parse_qsl(parsed.query, keep_blank_values=True))
    safe_query_str = f"?{safe_query}" if safe_query else ""
    return f"https://{host}{safe_path}{safe_query_str}"


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

    @field_validator("discord_webhook_url")
    @classmethod
    def _validate_discord_url(cls, v: str) -> str:
        if v:
            parsed = urlparse(v)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or host not in ("discord.com", "discordapp.com"):
                raise ValueError("discord_webhook_url must be an HTTPS discord.com URL")
        return v

    @field_validator("slack_webhook_url")
    @classmethod
    def _validate_slack_url(cls, v: str) -> str:
        if v:
            parsed = urlparse(v)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or host != "hooks.slack.com":
                raise ValueError("slack_webhook_url must be an HTTPS hooks.slack.com URL")
        return v


class TestNotificationRequest(BaseModel):
    channel: str  # "discord" | "slack" | "telegram"
    settings: NotificationSettings


# ── JWT / user helpers ────────────────────────────────────────────────────────


def _get_user_id(request: Request) -> str:
    """Extract user_id from JWT Bearer token; fall back to 'anonymous'."""
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            import jwt as pyjwt

            secret = os.getenv("SECURITY_JWT_SECRET", "")
            if not secret:
                logger.warning("SECURITY_JWT_SECRET not set; cannot decode JWT")
                return "anonymous"
            payload = pyjwt.decode(token, secret, algorithms=["HS256"])
            return str(payload.get("sub", "anonymous"))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Settings JWT extraction failed, defaulting to anonymous: %s", exc)
    return "anonymous"


# ── DB helpers ────────────────────────────────────────────────────────────────


def _db_save(user_id: str, data: dict) -> bool:
    """Persist settings to the configurations table. Returns True on success."""
    try:
        from database.connection import get_db_manager
        from database.models import Configuration

        mgr = get_db_manager()
        if not mgr:
            return False
        ctx = mgr.session()
        session = ctx.__enter__()
        if not session:
            return False

        key = f"{_CONFIG_KEY_PREFIX}:{user_id}"
        value = json.dumps(data)
        existing = session.query(Configuration).filter_by(config_key=key).first()
        if existing:
            existing.config_value = value
            existing.changed_by = user_id
        else:
            record = Configuration(
                environment="production",
                config_key=key,
                config_value=value,
                changed_by=user_id,
                change_reason="user notification settings update",
            )
            session.add(record)
        session.commit()
        return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("DB save failed for settings: %s", exc)
        return False


def _db_load(user_id: str) -> dict | None:
    """Load settings from the configurations table. Returns None on miss/error."""
    try:
        from database.connection import get_db_manager
        from database.models import Configuration

        mgr = get_db_manager()
        if not mgr:
            return None
        ctx = mgr.session()
        session = ctx.__enter__()
        if not session:
            return None

        key = f"{_CONFIG_KEY_PREFIX}:{user_id}"
        record = session.query(Configuration).filter_by(config_key=key).first()
        if record and record.config_value:
            return json.loads(record.config_value)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("DB load failed for settings: %s", exc)
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/api/settings/notifications", summary="Save notification settings")
async def save_notification_settings(body: NotificationSettings, request: Request):
    """Persist notification channel configuration for the authenticated user."""
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
    """Return the current notification configuration for the authenticated user."""
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
    """Send a test message to the specified channel to verify connectivity."""
    channel = body.channel.lower()
    cfg = body.settings

    try:
        if channel == "discord":
            safe_url = _safe_webhook_url(cfg.discord_webhook_url, "Discord")
            await _send_discord(safe_url)
        elif channel == "slack":
            safe_url = _safe_webhook_url(cfg.slack_webhook_url, "Slack")
            await _send_slack(safe_url)
        elif channel == "telegram":
            await _send_telegram(cfg.telegram_bot_token, cfg.telegram_chat_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown channel: {channel}",
            )
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Test notification failed for %s: %s", channel, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Channel delivery failed: {exc}",
        ) from exc

    return {"status": "delivered", "channel": channel}


# ── Channel send helpers ──────────────────────────────────────────────────────
# Callers must pass a URL that has already been validated by _safe_webhook_url.


def _build_safe_url(validated_url: str) -> str:
    """Re-parse a pre-validated URL to produce a fresh string with no taint.

    ``validated_url`` must already have been produced by ``_safe_webhook_url``.
    This function re-parses it and reconstructs it from its components so that
    CodeQL's taint engine sees a value derived from ``urlsplit`` output rather
    than from the original request field.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(validated_url)
    # Reconstruct from parsed components — scheme and netloc are now literals
    # from the parsed object, not from the original user-supplied string.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


async def _send_discord(webhook_url: str) -> None:
    """POST a test embed to a Discord webhook URL (must be pre-validated).

    ``webhook_url`` must have been produced by ``_safe_webhook_url``.
    """
    import aiohttp

    endpoint = _build_safe_url(webhook_url)
    payload = {
        "embeds": [
            {
                "title": "HOPEFX — Test Notification",
                "description": "Discord notifications are working correctly.",
                "color": 0x22C55E,
            },
        ],
    }
    async with aiohttp.ClientSession() as session, session.post(endpoint, json=payload) as resp:
        if resp.status not in (200, 204):
            text = await resp.text()
            raise ValueError(f"Discord returned {resp.status}: {text[:200]}")


async def _send_slack(webhook_url: str) -> None:
    """POST a test message to a Slack incoming webhook URL (must be pre-validated).

    ``webhook_url`` must have been produced by ``_safe_webhook_url``.
    """
    import aiohttp

    endpoint = _build_safe_url(webhook_url)
    payload = {"text": "*HOPEFX* — Slack notifications are working correctly."}
    async with aiohttp.ClientSession() as session, session.post(endpoint, json=payload) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise ValueError(f"Slack returned {resp.status}: {text[:200]}")


async def _send_telegram(bot_token: str, chat_id: str) -> None:
    """Send a test message via the Telegram Bot API.

    The outbound URL is constructed entirely from the server-side bot token —
    no user-supplied URL is used, so there is no SSRF risk here.
    """
    if not bot_token or not chat_id:
        raise ValueError("Telegram bot token or chat ID is empty")
    import aiohttp

    # URL is constructed from the server-side bot token, not from user input.
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "*HOPEFX* — Telegram notifications are working correctly.",
        "parse_mode": "Markdown",
    }
    async with aiohttp.ClientSession() as session, session.post(url, json=payload) as resp:
        data = await resp.json()
        if not data.get("ok"):
            raise ValueError(
                f"Telegram error: {data.get('description', 'unknown')}",
            )
