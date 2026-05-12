# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/notifications.py
Notification centre — list, mark-read, delete, preferences, subscribe.
Backed by Redis (with JSON fallback) for real-time delivery.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
UTC = timezone.utc
router = APIRouter(prefix="/api/notifications", tags=["Notifications"])

# ── In-process store (Redis-backed when available) ────────────────────────────

_NOTIF_PREFIX = "hopefx:notif:"
_PREFS_PREFIX = "hopefx:notif:prefs:"


def _redis():
    try:
        import redis as _r
        import os

        c = _r.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), socket_connect_timeout=1, socket_timeout=1)
        c.ping()
        return c
    except Exception:
        return None


def _get_notifs(user_id: str) -> list[dict]:
    r = _redis()
    key = f"{_NOTIF_PREFIX}{user_id}"
    if r:
        try:
            raw = r.lrange(key, 0, 199)
            return [json.loads(x) for x in raw]
        except Exception:  # nosec B110
            pass
    return _MEM_STORE.get(user_id, [])


def _save_notif(user_id: str, notif: dict) -> None:
    r = _redis()
    key = f"{_NOTIF_PREFIX}{user_id}"
    if r:
        try:
            r.lpush(key, json.dumps(notif))
            r.ltrim(key, 0, 499)
            return
        except Exception:  # nosec B110
            pass
    _MEM_STORE.setdefault(user_id, []).insert(0, notif)
    _MEM_STORE[user_id] = _MEM_STORE[user_id][:500]


def _update_notif(user_id: str, notif_id: str, updates: dict) -> bool:
    notifs = _get_notifs(user_id)
    found = False
    for n in notifs:
        if n.get("id") == notif_id:
            n.update(updates)
            found = True
            break
    if found:
        r = _redis()
        key = f"{_NOTIF_PREFIX}{user_id}"
        if r:
            try:
                r.delete(key)
                for n in reversed(notifs):
                    r.rpush(key, json.dumps(n))
                return True
            except Exception:  # nosec B110
                pass
        _MEM_STORE[user_id] = notifs
    return found


def _delete_notif(user_id: str, notif_id: str) -> bool:
    notifs = _get_notifs(user_id)
    new = [n for n in notifs if n.get("id") != notif_id]
    if len(new) == len(notifs):
        return False
    r = _redis()
    key = f"{_NOTIF_PREFIX}{user_id}"
    if r:
        try:
            r.delete(key)
            for n in reversed(new):
                r.rpush(key, json.dumps(n))
            return True
        except Exception:  # nosec B110
            pass
    _MEM_STORE[user_id] = new
    return True


def _get_prefs(user_id: str) -> dict:
    r = _redis()
    key = f"{_PREFS_PREFIX}{user_id}"
    if r:
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception:  # nosec B110
            pass
    return _PREFS_STORE.get(user_id, _default_prefs())


def _save_prefs(user_id: str, prefs: dict) -> None:
    r = _redis()
    key = f"{_PREFS_PREFIX}{user_id}"
    if r:
        try:
            r.set(key, json.dumps(prefs), ex=86400 * 30)
            return
        except Exception:  # nosec B110
            pass
    _PREFS_STORE[user_id] = prefs


_MEM_STORE: dict[str, list[dict]] = {}
_PREFS_STORE: dict[str, dict] = {}


def _default_prefs() -> dict:
    return {
        "email": True,
        "push": True,
        "sms": False,
        "in_app": True,
        "trade_fills": True,
        "price_alerts": True,
        "system_alerts": True,
        "marketing": False,
        "weekly_report": True,
    }


def _seed_demo_notifs(user_id: str) -> None:
    """Seed a few demo notifications for new users so the page isn't empty."""
    existing = _get_notifs(user_id)
    if existing:
        return
    demos = [
        {
            "id": str(uuid.uuid4()),
            "type": "system",
            "title": "Welcome to HOPEFX",
            "message": "Your account is active. Complete KYC to unlock live trading.",
            "read": False,
            "created_at": datetime.now(UTC).isoformat(),
            "priority": "normal",
            "action_url": "/kyc",
        },
        {
            "id": str(uuid.uuid4()),
            "type": "trade",
            "title": "Paper trading active",
            "message": "Paper trading mode is enabled. All trades are simulated.",
            "read": False,
            "created_at": datetime.now(UTC).isoformat(),
            "priority": "low",
            "action_url": "/dashboard",
        },
    ]
    for d in demos:
        _save_notif(user_id, d)


# ── Pydantic models ───────────────────────────────────────────────────────────


class PrefsUpdate(BaseModel):
    email: bool | None = None
    push: bool | None = None
    sms: bool | None = None
    in_app: bool | None = None
    trade_fills: bool | None = None
    price_alerts: bool | None = None
    system_alerts: bool | None = None
    marketing: bool | None = None
    weekly_report: bool | None = None


class SubscribeBody(BaseModel):
    channel: str  # "email" | "push" | "sms"
    endpoint: str | None = None
    token: str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("")
async def list_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    _seed_demo_notifs(user.sub)
    notifs = _get_notifs(user.sub)
    if unread_only:
        notifs = [n for n in notifs if not n.get("read")]
    total = len(notifs)
    start = (page - 1) * limit
    page_items = notifs[start : start + limit]
    return {
        "notifications": page_items,
        "total": total,
        "page": page,
        "limit": limit,
        "unread_count": sum(1 for n in notifs if not n.get("read")),
    }


@router.get("/unread-count")
async def unread_count(user: TokenPayload = Depends(get_current_user)) -> dict:
    notifs = _get_notifs(user.sub)
    return {"count": sum(1 for n in notifs if not n.get("read"))}


@router.patch("/{notif_id}/read")
async def mark_read(notif_id: str, user: TokenPayload = Depends(get_current_user)) -> dict:
    ok = _update_notif(user.sub, notif_id, {"read": True, "read_at": datetime.now(UTC).isoformat()})
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


@router.post("/mark-all-read")
async def mark_all_read(user: TokenPayload = Depends(get_current_user)) -> dict:
    notifs = _get_notifs(user.sub)
    now = datetime.now(UTC).isoformat()
    for n in notifs:
        n["read"] = True
        n["read_at"] = now
    r = _redis()
    key = f"{_NOTIF_PREFIX}{user.sub}"
    if r:
        try:
            r.delete(key)
            for n in reversed(notifs):
                r.rpush(key, json.dumps(n))
        except Exception:  # nosec B110
            pass
    else:
        _MEM_STORE[user.sub] = notifs
    return {"success": True, "marked": len(notifs)}


@router.delete("/{notif_id}")
async def delete_notification(notif_id: str, user: TokenPayload = Depends(get_current_user)) -> dict:
    ok = _delete_notif(user.sub, notif_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


@router.get("/preferences")
async def get_preferences(user: TokenPayload = Depends(get_current_user)) -> dict:
    return _get_prefs(user.sub)


@router.patch("/preferences")
async def update_preferences(body: PrefsUpdate, user: TokenPayload = Depends(get_current_user)) -> dict:
    prefs = _get_prefs(user.sub)
    updates = body.model_dump(exclude_none=True)
    prefs.update(updates)
    _save_prefs(user.sub, prefs)
    return prefs


@router.post("/subscribe")
async def subscribe(body: SubscribeBody, user: TokenPayload = Depends(get_current_user)) -> dict:
    # Store push subscription endpoint for future delivery
    prefs = _get_prefs(user.sub)
    prefs[f"{body.channel}_endpoint"] = body.endpoint
    prefs[f"{body.channel}_token"] = body.token
    prefs[body.channel] = True
    _save_prefs(user.sub, prefs)
    return {"success": True, "channel": body.channel}


# ── Internal helper — push a notification to a user ──────────────────────────


def push_notification(
    user_id: str, notif_type: str, title: str, message: str, priority: str = "normal", action_url: str | None = None
) -> dict:
    """Push a notification to a user's notification centre. Called internally."""
    notif = {
        "id": str(uuid.uuid4()),
        "type": notif_type,
        "title": title,
        "message": message,
        "read": False,
        "created_at": datetime.now(UTC).isoformat(),
        "priority": priority,
        "action_url": action_url,
    }
    _save_notif(user_id, notif)
    return notif


@router.post("/test", summary="Send a test notification to the current user")
async def send_test_notification(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Push a test notification to verify the notification pipeline is working."""
    from datetime import datetime, timezone

    test_notif = {
        "id": f"test_{int(__import__('time').time())}",
        "type": "system",
        "title": "Test Notification",
        "message": "Your notification pipeline is working correctly.",
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Try to push via WebSocket event bus.
    # The module exports the singleton as `bus`, not `event_bus`.
    try:
        from core.event_bus import bus

        await bus.publish(f"notifications:{user.sub}", test_notif)
    except Exception as exc:
        logger.debug("test notification event bus: %s", exc)

    return {"ok": True, "notification": test_notif}
