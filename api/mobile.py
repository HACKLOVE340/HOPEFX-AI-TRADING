# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Mobile Push Notification API

Endpoints:
  POST /api/mobile/register-push   — register device FCM token
  DELETE /api/mobile/register-push — unregister device token
  POST /api/mobile/test-push       — send a test notification to self
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from mobile.push_notifications import push_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mobile", tags=["Mobile"])


# ── Models ────────────────────────────────────────────────────────────────────


class RegisterPushBody(BaseModel):
    fcm_token: str = Field(
        ...,
        min_length=10,
        description="Firebase Cloud Messaging device token",
    )
    platform: str = Field("android", description="'android' or 'ios'")


class UnregisterPushBody(BaseModel):
    fcm_token: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/register-push")
async def register_push(
    body: RegisterPushBody,
    user: TokenPayload = Depends(get_current_user),
):
    """Register a device FCM token for the authenticated user."""
    push_manager.register_device(user.sub, body.fcm_token)
    return {
        "registered": True,
        "user_id": user.sub,
        "platform": body.platform,
        "fcm_enabled": push_manager.fcm_enabled,
    }


@router.delete("/register-push")
async def unregister_push(
    body: UnregisterPushBody,
    user: TokenPayload = Depends(get_current_user),
):
    """Remove a device FCM token for the authenticated user."""
    push_manager.unregister_device(user.sub, body.fcm_token)
    return {"unregistered": True, "user_id": user.sub}


@router.post("/test-push")
async def test_push(user: TokenPayload = Depends(get_current_user)):
    """Send a test push notification to all devices registered for the current user."""
    sent = push_manager.send_notification(
        user_id=user.sub,
        title="HOPEFX Test Notification",
        body="Push notifications are working correctly.",
        category="test",
    )
    tokens = push_manager.get_tokens(user.sub)
    return {
        "sent": sent,
        "fcm_enabled": push_manager.fcm_enabled,
        "devices": len(tokens),
        "note": "Notification logged (no FCM key)" if not push_manager.fcm_enabled else "Sent via FCM",
    }


@router.get("/push-status")
async def push_status(user: TokenPayload = Depends(get_current_user)):
    """Return FCM status and registered device count for the current user."""
    return {
        "fcm_enabled": push_manager.fcm_enabled,
        "devices": len(push_manager.get_tokens(user.sub)),
    }


# ── React Native / Expo push token endpoint ───────────────────────────────────
# The React Native app sends Expo push tokens (not raw FCM tokens).
# This endpoint accepts the Expo token format and stores it alongside FCM tokens.


class ExpoPushTokenBody(BaseModel):
    token: str = Field(..., min_length=10, description="Expo push token (ExponentPushToken[...])")
    platform: str = Field("android", description="'ios' or 'android'")
    device_id: str = Field("unknown", description="Device model ID")


@router.post("/push-token", summary="Register Expo push token (React Native)")
async def register_expo_push_token(
    body: ExpoPushTokenBody,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Register an Expo push token from the React Native mobile app.
    Stores the token and maps it to the authenticated user.
    """
    push_manager.register_device(user.sub, body.token)
    logger.info(
        "Expo push token registered: user=%s platform=%s device=%s",
        user.sub,
        body.platform,
        body.device_id,
    )
    return {
        "registered": True,
        "user_id": user.sub,
        "platform": body.platform,
        "device_id": body.device_id,
    }


# ── Notification preferences ──────────────────────────────────────────────────
# Persisted via api/db_store (configurations table).
# Key: "mobile:notif_prefs:{user_id}"

_NOTIF_PREFS_KEY = "mobile:notif_prefs:{uid}"

_DEFAULT_PREFS = {
    "signals": True,
    "trade_fills": True,
    "price_alerts": True,
    "daily_summary": True,
    "risk_warnings": True,
}


def _load_notif_prefs(user_id: str) -> dict:
    from api.db_store import db_get

    return db_get(_NOTIF_PREFS_KEY.format(uid=user_id)) or _DEFAULT_PREFS.copy()


def _save_notif_prefs(user_id: str, prefs: dict) -> None:
    from api.db_store import db_set

    db_set(_NOTIF_PREFS_KEY.format(uid=user_id), prefs, changed_by=user_id)


class NotificationPrefsBody(BaseModel):
    signals: bool | None = None
    trade_fills: bool | None = None
    price_alerts: bool | None = None
    daily_summary: bool | None = None
    risk_warnings: bool | None = None


@router.get("/notification-prefs", summary="Get notification preferences")
async def get_notification_prefs(user: TokenPayload = Depends(get_current_user)):
    """Return the authenticated user's push notification preferences."""
    return _load_notif_prefs(user.sub)


@router.patch("/notification-prefs", summary="Update notification preferences")
async def update_notification_prefs(
    body: NotificationPrefsBody,
    user: TokenPayload = Depends(get_current_user),
):
    """Partially update push notification preferences for the authenticated user."""
    current = _load_notif_prefs(user.sub)
    updates = body.model_dump(exclude_none=True)
    current.update(updates)
    _save_notif_prefs(user.sub, current)
    logger.info("Notification prefs updated: user=%s prefs=%s", user.sub, current)
    return current
