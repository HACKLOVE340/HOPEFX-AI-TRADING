# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
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
        ..., min_length=10, description="Firebase Cloud Messaging device token"
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
        "note": "Notification logged (no FCM key)"
        if not push_manager.fcm_enabled
        else "Sent via FCM",
    }


@router.get("/push-status")
async def push_status(user: TokenPayload = Depends(get_current_user)):
    """Return FCM status and registered device count for the current user."""
    return {
        "fcm_enabled": push_manager.fcm_enabled,
        "devices": len(push_manager.get_tokens(user.sub)),
    }
