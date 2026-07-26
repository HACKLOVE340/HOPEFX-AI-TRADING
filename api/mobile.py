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


# ── Mobile app config ─────────────────────────────────────────────────────────


_APP_STORE_URL = "https://apps.apple.com/app/hopefx"
_PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=io.hopefx"


def _qr_url(target: str) -> str:
    """QR image URL for a public store link.

    Rendered via api.qrserver.com, which core/middleware.py already allows in
    the CSP img-src directive.

    Safe here specifically because these are public app-store URLs — there is
    nothing confidential to leak by asking a third party to draw them. That is
    NOT true of the 2FA setup QR, whose otpauth:// URI embeds the TOTP shared
    secret; that one must be rendered locally.
    """
    from urllib.parse import quote

    return (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size=200x200&data={quote(target, safe='')}&bgcolor=ffffff&color=0f172a&margin=8"
    )


@router.get("/config", summary="Mobile app configuration")
async def get_mobile_config(user: TokenPayload = Depends(get_current_user)):
    """
    Return mobile app configuration: minimum version, download links,
    feature flags, and API base URL.
    """
    import os as _os

    return {
        "min_version": "1.0.0",
        "latest_version": "1.0.0",
        "api_base_url": _os.getenv("APP_BASE_URL", "http://localhost:8000"),
        "ws_url": _os.getenv("APP_BASE_URL", "http://localhost:8000").replace("http", "ws"),
        "app_store_url": _APP_STORE_URL,
        "play_store_url": _PLAY_STORE_URL,
        # frontend/src/pages/MobilePage.tsx renders config.qr_ios / qr_android.
        # These were never returned, so `config?.qr_ios ?? ''` was always empty
        # and the page showed its "QR code available after login" placeholder
        # permanently — for every user, logged in or not.
        "qr_ios": _qr_url(_APP_STORE_URL),
        "qr_android": _qr_url(_PLAY_STORE_URL),
        "features": {
            "copy_trading": True,
            "push_notifications": True,
            "biometric_auth": True,
            "dark_mode": True,
        },
        "maintenance": False,
        "maintenance_message": None,
    }


# ── Mobile sessions ───────────────────────────────────────────────────────────


@router.get("/sessions", summary="Active mobile sessions")
async def list_mobile_sessions(user: TokenPayload = Depends(get_current_user)):
    """Return active mobile sessions for the authenticated user."""
    try:
        from database.connection import SessionLocal
        from database.user_models import UserSession

        db = SessionLocal()
        try:
            sessions = (
                db.query(UserSession)
                .filter(
                    UserSession.user_id == user.sub,
                    UserSession.is_active.is_(True),
                )
                .order_by(UserSession.created_at.desc())
                .limit(20)
                .all()
            )
            return [
                {
                    "id": str(s.id),
                    "device": getattr(s, "device_info", "Mobile"),
                    "ip_address": getattr(s, "ip_address", None),
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "last_active": s.last_active_at.isoformat() if getattr(s, "last_active_at", None) else None,
                }
                for s in sessions
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Mobile sessions DB query failed: %s", exc)
        return []


@router.delete("/sessions/{session_id}", summary="Revoke a mobile session")
async def revoke_mobile_session(
    session_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Revoke a specific mobile session for the authenticated user."""
    try:
        from database.connection import SessionLocal
        from database.user_models import UserSession

        db = SessionLocal()
        try:
            session = (
                db.query(UserSession).filter(UserSession.id == session_id, UserSession.user_id == user.sub).first()
            )
            if not session:
                from fastapi import HTTPException as _HTTPException

                raise _HTTPException(status_code=404, detail="Session not found")
            session.is_active = False
            db.commit()
            return {"revoked": True, "session_id": session_id}
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Mobile session revoke failed: %s", exc)
        return {"revoked": False, "error": str(exc)}
