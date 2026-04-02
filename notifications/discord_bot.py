# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
notifications/discord_bot.py
============================
Discord community bot for signal posting.

Posts rich embed messages to a Discord channel when the signal engine
generates a consensus signal. Designed for community transparency — members
can see live signals, model confidence, and risk parameters without accessing
the API directly.

Features
--------
- Rich embeds with colour-coded direction (green=BUY, red=SELL, grey=neutral)
- Signal fields: symbol, direction, confidence, ML probability, model version,
  entry price, stop loss, take profit, risk/reward ratio
- Fallback warning embed when the ML fallback model is active
- Rate limiting: minimum DISCORD_SIGNAL_COOLDOWN_SECONDS between posts per symbol
- Async-first: uses aiohttp for non-blocking webhook delivery
- Sync fallback: uses requests when called from non-async context
- Retry with exponential backoff on 429 (Discord rate limit) responses
- Configurable via environment variables — no code changes needed

Environment variables
---------------------
DISCORD_WEBHOOK_URL           — Webhook URL for the signals channel (required)
DISCORD_FALLBACK_WEBHOOK_URL  — Separate webhook for system alerts (optional,
                                 defaults to DISCORD_WEBHOOK_URL)
DISCORD_SIGNAL_COOLDOWN_SECONDS — Min seconds between posts per symbol (default: 300)
DISCORD_BOT_USERNAME          — Display name for the bot (default: HOPEFX Signals)
DISCORD_BOT_AVATAR_URL        — Avatar URL for the bot (optional)
DISCORD_MENTION_ROLE_ID       — Discord role ID to @mention on signals (optional)

Usage
-----
    from notifications.discord_bot import discord_signal_bot

    # Post a signal (async)
    await discord_signal_bot.post_signal(signal_payload)

    # Post a system alert (async)
    await discord_signal_bot.post_alert("ML fallback activated", level="critical")

    # Post a signal (sync, from non-async context)
    discord_signal_bot.post_signal_sync(signal_payload)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
_FALLBACK_WEBHOOK = os.getenv("DISCORD_FALLBACK_WEBHOOK_URL", _WEBHOOK_URL)
_COOLDOWN_SECONDS = int(os.getenv("DISCORD_SIGNAL_COOLDOWN_SECONDS", "300"))
_BOT_USERNAME = os.getenv("DISCORD_BOT_USERNAME", "HOPEFX Signals")
_BOT_AVATAR_URL = os.getenv("DISCORD_BOT_AVATAR_URL", "")
_MENTION_ROLE_ID = os.getenv("DISCORD_MENTION_ROLE_ID", "")

# Embed colours (Discord uses decimal integers)
_COLOUR_BUY = 0x00C853  # green
_COLOUR_SELL = 0xD50000  # red
_COLOUR_NEUTRAL = 0x9E9E9E  # grey
_COLOUR_WARNING = 0xFF6F00  # amber
_COLOUR_CRITICAL = 0xB71C1C  # dark red
_COLOUR_INFO = 0x1565C0  # blue


def _direction_colour(direction: str) -> int:
    d = direction.upper()
    if d in ("BUY", "LONG"):
        return _COLOUR_BUY
    if d in ("SELL", "SHORT"):
        return _COLOUR_SELL
    return _COLOUR_NEUTRAL


def _direction_emoji(direction: str) -> str:
    d = direction.upper()
    if d in ("BUY", "LONG"):
        return "📈"
    if d in ("SELL", "SHORT"):
        return "📉"
    return "⏸️"


def _rr_ratio(entry: float, sl: float | None, tp: float | None) -> str:
    """Compute risk/reward ratio string, or 'N/A' if SL/TP not set."""
    if not sl or not tp or entry == 0:
        return "N/A"
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk == 0:
        return "N/A"
    return f"{reward / risk:.2f}:1"


def _build_signal_embed(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Discord embed dict from a signal payload."""
    symbol = payload.get("symbol", "UNKNOWN")
    direction = payload.get("direction", "NEUTRAL")
    confidence = float(payload.get("confidence", 0.0))
    ml_prob = float(payload.get("probability", confidence))
    model_ver = payload.get("model_version", "unknown")
    entry = payload.get("entry_price")
    sl = payload.get("stop_loss")
    tp = payload.get("take_profit")
    ts = payload.get("timestamp", datetime.now(UTC).isoformat())

    emoji = _direction_emoji(direction)
    rr = _rr_ratio(entry or 0, sl, tp)

    # Confidence bar (10 blocks)
    filled = round(ml_prob * 10)
    conf_bar = "█" * filled + "░" * (10 - filled)

    fields: list[dict[str, Any]] = [
        {
            "name": "Direction",
            "value": f"{emoji} **{direction.upper()}**",
            "inline": True,
        },
        {"name": "Symbol", "value": f"`{symbol}`", "inline": True},
        {
            "name": "ML Confidence",
            "value": f"`{conf_bar}` {ml_prob * 100:.1f}%",
            "inline": False,
        },
        {
            "name": "Strategy Confidence",
            "value": f"{confidence * 100:.1f}%",
            "inline": True,
        },
        {"name": "Model", "value": f"`{model_ver}`", "inline": True},
    ]

    if entry:
        fields.append({"name": "Entry", "value": f"`{entry:,.4f}`", "inline": True})
    if sl:
        fields.append({"name": "Stop Loss", "value": f"`{sl:,.4f}`", "inline": True})
    if tp:
        fields.append({"name": "Take Profit", "value": f"`{tp:,.4f}`", "inline": True})
    if rr != "N/A":
        fields.append({"name": "Risk/Reward", "value": f"`{rr}`", "inline": True})

    # Fallback model warning
    if "fallback" in model_ver.lower() or "macro_xgb" in model_ver.lower():
        fields.append(
            {
                "name": "⚠️ Fallback Model Active",
                "value": (
                    "Advanced model unavailable. Signal generated by fallback model "
                    "(~50% OOS accuracy, no demonstrated edge). "
                    "**Do not trade live capital on this signal.**"
                ),
                "inline": False,
            }
        )

    return {
        "title": f"{emoji} {symbol} Signal — {direction.upper()}",
        "color": _direction_colour(direction),
        "fields": fields,
        "footer": {
            "text": f"HOPEFX AI Trading • {ts[:19].replace('T', ' ')} UTC",
        },
        "timestamp": ts,
    }


def _build_alert_embed(
    message: str,
    level: str = "info",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Discord embed for a system alert."""
    level_map = {
        "info": (_COLOUR_INFO, "ℹ️"),
        "warning": (_COLOUR_WARNING, "⚠️"),
        "critical": (_COLOUR_CRITICAL, "🚨"),
        "error": (_COLOUR_CRITICAL, "❌"),
    }
    colour, emoji = level_map.get(level.lower(), (_COLOUR_INFO, "ℹ️"))

    fields: list[dict[str, Any]] = []
    if details:
        for k, v in details.items():
            fields.append({"name": k, "value": str(v)[:1024], "inline": False})

    return {
        "title": f"{emoji} System Alert — {level.upper()}",
        "description": message[:2048],
        "color": colour,
        "fields": fields,
        "footer": {
            "text": f"HOPEFX AI Trading • {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC",
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _build_payload(
    embeds: list[dict[str, Any]],
    content: str = "",
) -> dict[str, Any]:
    """Wrap embeds in a Discord webhook payload."""
    payload: dict[str, Any] = {
        "username": _BOT_USERNAME,
        "embeds": embeds,
    }
    if content:
        payload["content"] = content
    if _BOT_AVATAR_URL:
        payload["avatar_url"] = _BOT_AVATAR_URL
    return payload


class DiscordSignalBot:
    """
    Async Discord webhook client for signal and alert posting.

    Rate-limits per symbol to avoid flooding the channel.
    Uses aiohttp for async delivery; falls back to requests for sync callers.
    """

    def __init__(self) -> None:
        self._last_post: dict[str, float] = {}  # symbol → last post timestamp

    def _is_rate_limited(self, symbol: str) -> bool:
        last = self._last_post.get(symbol, 0.0)
        return (time.monotonic() - last) < _COOLDOWN_SECONDS

    def _mark_posted(self, symbol: str) -> None:
        self._last_post[symbol] = time.monotonic()

    async def _post_async(self, webhook_url: str, payload: dict[str, Any], retries: int = 3) -> bool:
        """POST payload to webhook URL with retry on 429."""
        if not webhook_url:
            logger.debug("Discord webhook URL not configured — skipping post")
            return False
        try:
            import aiohttp

            for _attempt in range(retries):
                async with (
                    aiohttp.ClientSession() as session,
                    session.post(
                        webhook_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp,
                ):
                    if resp.status in (200, 204):
                        return True
                    if resp.status == 429:
                        retry_after = float((await resp.json()).get("retry_after", 1.0))
                        logger.debug("Discord rate limited — retrying in %.1f s", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    logger.warning(
                        "Discord webhook returned %d: %s",
                        resp.status,
                        await resp.text(),
                    )
                    return False
        except ImportError:
            return self._post_sync(webhook_url, payload)
        except Exception as exc:
            logger.warning("Discord async post failed: %s", exc)
            return False
        return False

    @staticmethod
    def _is_valid_discord_url(url: str) -> bool:
        from urllib.parse import urlparse

        try:
            p = urlparse(url)
            host = (p.hostname or "").lower()
            return p.scheme == "https" and host in ("discord.com", "discordapp.com")
        except Exception:
            return False

    def _post_sync(self, webhook_url: str, payload: dict[str, Any]) -> bool:
        """Synchronous fallback using requests."""
        if not webhook_url:
            return False
        if not self._is_valid_discord_url(webhook_url):
            logger.warning("Discord webhook URL is not a valid HTTPS discord.com URL — skipping")
            return False
        try:
            import requests

            resp = requests.post(webhook_url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                return True
            logger.warning("Discord sync post returned %d", resp.status_code)
            return False
        except Exception as exc:
            logger.warning("Discord sync post failed: %s", exc)
            return False

    async def post_signal(self, signal_payload: dict[str, Any]) -> bool:
        """
        Post a signal embed to the Discord signals channel.

        Rate-limited per symbol (DISCORD_SIGNAL_COOLDOWN_SECONDS).
        Returns True if the message was posted successfully.
        """
        if not _WEBHOOK_URL:
            return False

        symbol = signal_payload.get("symbol", "UNKNOWN")
        if self._is_rate_limited(symbol):
            logger.debug(
                "Discord signal post rate-limited for %s (cooldown=%ds)",
                symbol,
                _COOLDOWN_SECONDS,
            )
            return False

        embed = _build_signal_embed(signal_payload)
        content = f"<@&{_MENTION_ROLE_ID}>" if _MENTION_ROLE_ID else ""
        payload = _build_payload([embed], content=content)

        ok = await self._post_async(_WEBHOOK_URL, payload)
        if ok:
            self._mark_posted(symbol)
            logger.info(
                "Discord signal posted: %s %s confidence=%.2f",
                symbol,
                signal_payload.get("direction", ""),
                signal_payload.get("probability", 0),
            )
        return ok

    def post_signal_sync(self, signal_payload: dict[str, Any]) -> bool:
        """Synchronous wrapper for post_signal (for non-async callers)."""
        if not _WEBHOOK_URL:
            return False
        symbol = signal_payload.get("symbol", "UNKNOWN")
        if self._is_rate_limited(symbol):
            return False
        embed = _build_signal_embed(signal_payload)
        content = f"<@&{_MENTION_ROLE_ID}>" if _MENTION_ROLE_ID else ""
        payload = _build_payload([embed], content=content)
        ok = self._post_sync(_WEBHOOK_URL, payload)
        if ok:
            self._mark_posted(symbol)
        return ok

    async def post_alert(
        self,
        message: str,
        level: str = "info",
        details: dict[str, Any] | None = None,
    ) -> bool:
        """
        Post a system alert embed to the fallback/alerts webhook.

        level: "info" | "warning" | "critical" | "error"
        """
        webhook = _FALLBACK_WEBHOOK or _WEBHOOK_URL
        if not webhook:
            return False
        embed = _build_alert_embed(message, level=level, details=details)
        payload = _build_payload([embed])
        ok = await self._post_async(webhook, payload)
        if ok:
            logger.info("Discord alert posted: level=%s msg=%s", level, message[:80])
        return ok

    async def post_ml_fallback_alert(
        self,
        reason: str,
        fallback_model: str,
        fallback_accuracy: float,
    ) -> bool:
        """Post a critical alert when the ML fallback model activates."""
        return await self.post_alert(
            message=(
                f"**ML Fallback Activated** — advanced_oos.pkl unavailable.\n"
                f"Running on `{fallback_model}` ({fallback_accuracy * 100:.1f}% OOS accuracy).\n"
                f"**No demonstrated edge above chance. Do not trade live capital.**"
            ),
            level="critical",
            details={
                "Reason": reason,
                "Fallback Model": fallback_model,
                "Fallback OOS Accuracy": f"{fallback_accuracy * 100:.1f}%",
                "Production Model": "advanced_oos.pkl (68.0% OOS, p=0.0000)",
                "Remediation": (
                    "Ensure advanced_oos.pkl exists in ml/saved_models/ and "
                    "scikit-learn/xgboost versions match training environment."
                ),
            },
        )


# Module-level singleton
discord_signal_bot = DiscordSignalBot()
