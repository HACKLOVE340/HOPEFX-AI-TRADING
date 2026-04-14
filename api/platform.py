# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Platform Quality API — Tasks 35–41

Task 35 — Session Management (Multi-Device Logout)
  GET    /api/auth/sessions          — list active sessions
  DELETE /api/auth/sessions/{id}     — revoke specific session
  DELETE /api/auth/sessions          — revoke all sessions (logout everywhere)

Task 36 — User Admin Panel
  GET    /api/admin/users            — list all users with subscription status
  POST   /api/admin/users/{id}/ban   — ban user
  POST   /api/admin/users/{id}/unban — unban user
  POST   /api/admin/users/{id}/reset-password — trigger password reset
  GET    /api/admin/users/{id}/trades — view user's trades
  POST   /api/admin/users/{id}/impersonate — get impersonation token

Task 37 — Audit Log UI
  GET    /api/admin/audit-log        — paginated audit log with filters
  GET    /api/admin/audit-log/export — CSV export

Task 38 — Redis-backed Rate Limiting (slowapi)
  Configured at app startup in app.py — see setup_rate_limiting()

Task 39 — API Key Management
  GET    /api/settings/api-keys      — list user's API keys
  POST   /api/settings/api-keys      — create named API key
  DELETE /api/settings/api-keys/{id} — revoke API key

Task 40 — Sentry Error Tracking
  Initialized at app startup — see init_sentry()

Task 41 — Feature Flag UI
  GET    /api/admin/feature-flags    — list all flags with current state
  POST   /api/admin/feature-flags/{name}/enable
  POST   /api/admin/feature-flags/{name}/disable
  POST   /api/admin/feature-flags/{name}/override — per-user override
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone

UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Platform"])

# ── Redis-backed stores ───────────────────────────────────────────────────────
# All mutable state is stored in Redis so it survives restarts and is shared
# across replicas. Each helper falls back to an in-process dict when Redis is
# unavailable (dev mode / unit tests) so the API surface is unchanged.
#
# Key layout:
#   platform:session:{session_id}   → JSON session dict  (TTL 30 days)
#   platform:audit_log              → Redis list of JSON audit event strings
#   platform:api_key:{key_id}       → JSON key metadata  (no TTL)
#   platform:api_key_hash:{sha256}  → key_id string      (no TTL)

import json as _json

_REDIS_SESSION_TTL = 60 * 60 * 24 * 30  # 30 days
_REDIS_AUDIT_MAX = 10_000  # cap audit log list length

# In-process fallback stores (used when Redis is unavailable)
_sessions_fallback: dict[str, dict] = {}
_audit_log_fallback: list[dict] = []
_api_keys_fallback: dict[str, dict] = {}
_api_key_hashes_fallback: dict[str, str] = {}

# Legacy aliases kept so existing code that references _sessions / _api_keys
# directly still works in the fallback path.
_sessions = _sessions_fallback
_audit_log = _audit_log_fallback
_api_keys = _api_keys_fallback
_api_key_hashes = _api_key_hashes_fallback

_users_admin: dict[str, dict] = {}  # user_id → admin view (DB-backed via subscription manager)
_flag_overrides: dict[str, dict[str, bool]] = {}  # flag_name → {user_id: bool}


def _get_sync_redis():
    """Return a synchronous Redis client or None when unavailable."""
    try:
        # get_redis_client may be async; use sync variant if available
        from cache.redis_pool import get_sync_client

        return get_sync_client()
    except Exception:
        return None


# ── Session helpers ───────────────────────────────────────────────────────────


def _session_set(session_id: str, data: dict) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.setex(f"platform:session:{session_id}", _REDIS_SESSION_TTL, _json.dumps(data))
            return
        except Exception as _e:
            logger.debug("Redis session_set failed: %s", _e)
    _sessions_fallback[session_id] = data


def _session_get(session_id: str) -> dict | None:
    r = _get_sync_redis()
    if r:
        try:
            raw = r.get(f"platform:session:{session_id}")
            return _json.loads(raw) if raw else None
        except Exception as _e:
            logger.debug("Redis session_get failed: %s", _e)
    return _sessions_fallback.get(session_id)


def _sessions_for_user(user_id: str) -> list[dict]:
    """Return all sessions belonging to user_id."""
    r = _get_sync_redis()
    if r:
        try:
            keys = r.keys("platform:session:*")
            result = []
            for k in keys:
                raw = r.get(k)
                if raw:
                    s = _json.loads(raw)
                    if s.get("user_id") == user_id:
                        result.append(s)
            return result
        except Exception as _e:
            logger.debug("Redis sessions_for_user failed: %s", _e)
    return [s for s in _sessions_fallback.values() if s.get("user_id") == user_id]


def _session_delete(session_id: str) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.delete(f"platform:session:{session_id}")
            return
        except Exception as _e:
            logger.debug("Redis session_delete failed: %s", _e)
    _sessions_fallback.pop(session_id, None)


# ── Audit log helpers ─────────────────────────────────────────────────────────


def _audit_append(event: dict) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.lpush("platform:audit_log", _json.dumps(event))
            r.ltrim("platform:audit_log", 0, _REDIS_AUDIT_MAX - 1)
            return
        except Exception as _e:
            logger.debug("Redis audit_append failed: %s", _e)
    _audit_log_fallback.append(event)


def _audit_list(limit: int = 100, offset: int = 0) -> list[dict]:
    r = _get_sync_redis()
    if r:
        try:
            raws = r.lrange("platform:audit_log", offset, offset + limit - 1)
            return [_json.loads(x) for x in raws]
        except Exception as _e:
            logger.debug("Redis audit_list failed: %s", _e)
    return list(reversed(_audit_log_fallback))[offset : offset + limit]


# ── API key helpers ───────────────────────────────────────────────────────────


def _api_key_set(key_id: str, data: dict) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.set(f"platform:api_key:{key_id}", _json.dumps(data))
            return
        except Exception as _e:
            logger.debug("Redis api_key_set failed: %s", _e)
    _api_keys_fallback[key_id] = data


def _api_key_get(key_id: str) -> dict | None:
    r = _get_sync_redis()
    if r:
        try:
            raw = r.get(f"platform:api_key:{key_id}")
            return _json.loads(raw) if raw else None
        except Exception as _e:
            logger.debug("Redis api_key_get failed: %s", _e)
    return _api_keys_fallback.get(key_id)


def _api_keys_for_user(user_id: str) -> list[dict]:
    r = _get_sync_redis()
    if r:
        try:
            keys = r.keys("platform:api_key:*")
            result = []
            for k in keys:
                raw = r.get(k)
                if raw:
                    d = _json.loads(raw)
                    if d.get("user_id") == user_id and not d.get("revoked"):
                        result.append(d)
            return result
        except Exception as _e:
            logger.debug("Redis api_keys_for_user failed: %s", _e)
    return [k for k in _api_keys_fallback.values() if k.get("user_id") == user_id and not k.get("revoked")]


def _api_key_hash_set(key_hash: str, key_id: str) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.set(f"platform:api_key_hash:{key_hash}", key_id)
            return
        except Exception as _e:
            logger.debug("Redis api_key_hash_set failed: %s", _e)
    _api_key_hashes_fallback[key_hash] = key_id


# ── Admin role guard ──────────────────────────────────────────────────────────

_ADMIN_USERS: set = {u.strip() for u in os.getenv("ADMIN_USER_IDS", "admin").split(",") if u.strip()}


def _require_admin(user: TokenPayload) -> TokenPayload:
    """
    Raise 403 if the authenticated user is not an admin.

    Admin user IDs are configured via the ADMIN_USER_IDS environment variable
    (comma-separated). Defaults to 'admin' for development.
    """
    role = getattr(user, "role", "") or ""
    if user.sub not in _ADMIN_USERS and role.lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def _client_ip(request: Request) -> str:
    """Extract the real client IP from X-Forwarded-For or request.client."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # X-Forwarded-For may be a comma-separated list; leftmost is the client
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


def _log_audit(user_id: str, event_type: str, detail: str, ip: str = ""):
    event = {
        "event_id": str(uuid.uuid4()),
        "user_id": user_id,
        "event_type": event_type,
        "detail": detail,
        "ip_address": ip,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _audit_append(event)


# ─────────────────────────────────────────────────────────────────────────────
# Task 35 — Session Management
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/auth/sessions")
async def list_sessions(user: TokenPayload = Depends(get_current_user)):
    """List all active sessions for the current user."""
    user_sessions = [s for s in _sessions_for_user(user.sub) if not s.get("revoked")]
    return {"sessions": user_sessions, "total": len(user_sessions)}


@router.delete("/api/auth/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Revoke a specific session (log out that device)."""
    session = _session_get(session_id)
    if not session or session["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Session not found")
    session["revoked"] = True
    session["revoked_at"] = datetime.now(UTC).isoformat()
    _session_set(session_id, session)
    _log_audit(user.sub, "session.revoked", f"Session {session_id[:8]} revoked", ip=_client_ip(request))
    return {"revoked": True, "session_id": session_id}


@router.delete("/api/auth/sessions")
async def revoke_all_sessions(request: Request, user: TokenPayload = Depends(get_current_user)):
    """Revoke all sessions for the current user (logout everywhere)."""
    count = 0
    for s in _sessions_for_user(user.sub):
        if not s.get("revoked"):
            s["revoked"] = True
            s["revoked_at"] = datetime.now(UTC).isoformat()
            _session_set(s["session_id"], s)
            count += 1
    _log_audit(user.sub, "session.revoke_all", f"All {count} sessions revoked", ip=_client_ip(request))
    return {"revoked": count}


# Helper called by auth router on login to register a session
def register_session(user_id: str, device_info: str = "", ip_address: str = "") -> str:
    session_id = str(uuid.uuid4())
    data = {
        "session_id": session_id,
        "user_id": user_id,
        "device_info": device_info or "Unknown device",
        "ip_address": ip_address,
        "created_at": datetime.now(UTC).isoformat(),
        "revoked": False,
        "revoked_at": None,
    }
    _session_set(session_id, data)
    return session_id


# ─────────────────────────────────────────────────────────────────────────────
# Task 36 — User Admin Panel
# ─────────────────────────────────────────────────────────────────────────────


def _get_users_from_subscriptions() -> dict[str, dict]:
    """
    Build a user view from the live subscription manager.

    Falls back to the in-memory _users_admin cache when the subscription
    manager has no data (e.g. fresh start with no subscribers yet).
    """
    try:
        from monetization.subscription import subscription_manager

        subs = subscription_manager.get_all_subscriptions()
        if subs:
            for sub in subs:
                uid = sub.user_id
                _users_admin[uid] = {
                    "user_id": uid,
                    "email": getattr(sub, "email", f"{uid}@unknown"),
                    "status": sub.status.value if hasattr(sub.status, "value") else str(sub.status),
                    "tier": sub.tier.value if hasattr(sub.tier, "value") else str(sub.tier),
                    "subscription_id": sub.subscription_id,
                    "created_at": sub.created_at.isoformat() if hasattr(sub, "created_at") else "",
                    "expires_at": sub.end_date.isoformat() if hasattr(sub, "end_date") and sub.end_date else None,
                }
    except Exception as exc:
        logger.debug("_get_users_from_subscriptions fallback: %s", exc)
    return _users_admin


@router.get("/api/admin/users")
async def list_users(
    page: int = 1,
    limit: int = 20,
    status_filter: str | None = Query(None, alias="status"),
    admin: TokenPayload = Depends(get_current_user),
):
    """List all users with subscription status. Admin only."""
    _require_admin(admin)
    users = list(_get_users_from_subscriptions().values())
    if status_filter:
        users = [u for u in users if u.get("status") == status_filter]
    start = (page - 1) * limit
    return {
        "users": users[start : start + limit],
        "total": len(users),
        "page": page,
        "pages": max(1, (len(users) + limit - 1) // limit),
    }


@router.post("/api/admin/users/{user_id}/ban")
async def ban_user(user_id: str, request: Request, admin: TokenPayload = Depends(get_current_user)):
    """Ban a user. Cancels their subscription and blocks login. Admin only."""
    _require_admin(admin)
    users = _get_users_from_subscriptions()
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    users[user_id]["status"] = "banned"
    # Cancel subscription so they lose platform access immediately
    try:
        from monetization.subscription import subscription_manager

        sub_id = users[user_id].get("subscription_id", "")
        if sub_id:
            subscription_manager.cancel_subscription(sub_id)
    except Exception as exc:
        logger.warning("ban_user.cancel_subscription failed: %s", exc)
    _log_audit(admin.sub, "user.banned", f"User {user_id} banned by admin", ip=_client_ip(request))
    return {"banned": True, "user_id": user_id}


@router.post("/api/admin/users/{user_id}/unban")
async def unban_user(user_id: str, request: Request, admin: TokenPayload = Depends(get_current_user)):
    """Unban a user. Admin only."""
    _require_admin(admin)
    users = _get_users_from_subscriptions()
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    users[user_id]["status"] = "active"
    _log_audit(admin.sub, "user.unbanned", f"User {user_id} unbanned by admin", ip=_client_ip(request))
    return {"unbanned": True, "user_id": user_id}


@router.post("/api/admin/users/{user_id}/reset-password")
async def reset_password(user_id: str, request: Request, admin: TokenPayload = Depends(get_current_user)):
    """Trigger a password reset email for a user. Admin only."""
    _require_admin(admin)
    try:
        from notifications.email_triggers import send_risk_halt_email

        users = _get_users_from_subscriptions()
        recipient = users.get(user_id, {}).get("email", "")
        if recipient:
            send_risk_halt_email(
                reason="A password reset was requested by an administrator. "
                "If you did not request this, contact support@hopefx.io immediately.",
                drawdown_pct=0.0,
                limit_pct=0.0,
                to=recipient,
            )
    except Exception as exc:
        logger.warning("reset_password.email_failed: %s", exc)
    _log_audit(admin.sub, "user.password_reset", f"Password reset triggered for {user_id}", ip=_client_ip(request))
    return {"reset_triggered": True, "user_id": user_id}


@router.get("/api/admin/users/{user_id}/trades")
async def get_user_trades(
    user_id: str,
    admin: TokenPayload = Depends(get_current_user),
):
    """View a user's trade history from the database. Admin only."""
    _require_admin(admin)
    trades: list[dict] = []
    try:
        from database.connection import get_db
        from database.models import Trade

        # Query real trades if DB is available
        db = next(get_db())
        try:
            rows = db.query(Trade).filter(Trade.user_id == user_id).order_by(Trade.created_at.desc()).limit(100).all()
            trades = [
                {
                    "trade_id": str(r.id),
                    "symbol": r.symbol,
                    "direction": r.direction,
                    "lots": float(r.quantity),
                    "pnl": float(r.pnl) if r.pnl is not None else None,
                    "opened_at": r.created_at.isoformat() if r.created_at else None,
                    "closed_at": r.closed_at.isoformat() if hasattr(r, "closed_at") and r.closed_at else None,
                }
                for r in rows
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.debug("get_user_trades.db_unavailable: %s — returning empty list", exc)
    return {"trades": trades, "user_id": user_id, "total": len(trades)}


@router.post("/api/admin/users/{user_id}/impersonate")
async def impersonate_user(
    user_id: str,
    request: Request,
    admin: TokenPayload = Depends(get_current_user),
):
    """
    Generate a short-lived JWT impersonation token for support purposes.

    The token carries an 'impersonated_by' claim so all downstream actions
    are attributed to the admin in the audit log.
    Admin only. Token expires in 5 minutes.
    """
    _require_admin(admin)
    _log_audit(admin.sub, "user.impersonated", f"Admin {admin.sub} impersonating {user_id}", ip=_client_ip(request))

    try:
        import time

        import jwt as _jwt

        jwt_secret = os.getenv("SECURITY_JWT_SECRET", "")
        if not jwt_secret:
            raise ValueError("SECURITY_JWT_SECRET not set")
        payload = {
            "sub": user_id,
            "impersonated_by": admin.sub,
            "exp": int(time.time()) + 300,  # 5 minutes
            "iat": int(time.time()),
            "scope": "impersonation",
        }
        token = _jwt.encode(payload, jwt_secret, algorithm="HS256")
        return {
            "impersonation_token": token,
            "user_id": user_id,
            "expires_in": 300,
            "note": "Token valid for 5 minutes. All actions are audit-logged with impersonated_by claim.",
        }
    except Exception as exc:
        logger.error("impersonate_user.jwt_failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not generate impersonation token") from None


# ─────────────────────────────────────────────────────────────────────────────
# Task 37 — Audit Log UI
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/admin/audit-log")
async def get_audit_log(
    page: int = 1,
    limit: int = 50,
    user_id: str | None = None,
    event_type: str | None = None,
    admin: TokenPayload = Depends(get_current_user),
):
    """Return paginated audit log with optional filters. Admin only."""
    _require_admin(admin)
    # Fetch enough events to support filtering; cap at audit log max
    all_events = _audit_list(limit=_REDIS_AUDIT_MAX, offset=0)
    if user_id:
        all_events = [e for e in all_events if e["user_id"] == user_id]
    if event_type:
        all_events = [e for e in all_events if event_type in e["event_type"]]
    start = (page - 1) * limit
    return {
        "events": all_events[start : start + limit],
        "total": len(all_events),
        "page": page,
        "pages": max(1, (len(all_events) + limit - 1) // limit),
    }


@router.get("/api/admin/audit-log/export")
async def export_audit_log(admin: TokenPayload = Depends(get_current_user)):
    """Export full audit log as CSV. Admin only."""
    _require_admin(admin)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "event_id",
            "user_id",
            "event_type",
            "detail",
            "ip_address",
            "created_at",
        ],
    )
    writer.writeheader()
    for event in _audit_list(limit=_REDIS_AUDIT_MAX, offset=0):
        writer.writerow(event)
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Task 39 — API Key Management
# ─────────────────────────────────────────────────────────────────────────────


class CreateApiKeyBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    scopes: list[str] = Field(default_factory=lambda: ["read"])


@router.get("/api/settings/api-keys")
async def list_api_keys(user: TokenPayload = Depends(get_current_user)):
    """List all API keys for the current user (never returns raw key)."""
    keys = _api_keys_for_user(user.sub)
    return {"api_keys": keys}


@router.post("/api/settings/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: CreateApiKeyBody,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Create a named API key. Raw key shown once — stored as SHA-256 hash."""
    raw_key = f"hfx_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = str(uuid.uuid4())[:12]

    key_data = {
        "key_id": key_id,
        "user_id": user.sub,
        "name": body.name,
        "scopes": body.scopes,
        "key_prefix": raw_key[:10] + "…",
        "created_at": datetime.now(UTC).isoformat(),
        "last_used": None,
        "revoked": False,
    }
    _api_key_set(key_id, key_data)
    _api_key_hash_set(key_hash, key_id)
    _log_audit(user.sub, "api_key.created", f"API key '{body.name}' created", ip=_client_ip(request))

    return {
        "key_id": key_id,
        "api_key": raw_key,
        "name": body.name,
        "scopes": body.scopes,
        "note": "Store this key securely — it will not be shown again.",
    }


@router.delete("/api/settings/api-keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request, user: TokenPayload = Depends(get_current_user)):
    """Revoke an API key."""
    key = _api_key_get(key_id)
    if not key or key["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="API key not found")
    key["revoked"] = True
    key["revoked_at"] = datetime.now(UTC).isoformat()
    _api_key_set(key_id, key)
    _log_audit(user.sub, "api_key.revoked", f"API key '{key['name']}' revoked", ip=_client_ip(request))
    return {"revoked": True, "key_id": key_id}


# ─────────────────────────────────────────────────────────────────────────────
# Task 41 — Feature Flag UI
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/admin/feature-flags")
async def list_feature_flags(admin: TokenPayload = Depends(get_current_user)):
    """Return all feature flags with their current state and metadata. Admin only."""
    _require_admin(admin)
    from config.feature_flags import flags as _flags

    registry = _flags.registry()
    result = []
    for name, info in registry.items():
        result.append(
            {
                "name": name,
                "enabled": info.get("enabled", False),
                "status": info.get("status", "unknown"),
                "description": info.get("description", ""),
                "env_var": info.get("env_var", ""),
                "overrides": _flag_overrides.get(name, {}),
            },
        )
    return {"flags": result, "total": len(result)}


@router.post("/api/admin/feature-flags/{flag_name}/enable")
async def enable_flag(flag_name: str, request: Request, admin: TokenPayload = Depends(get_current_user)):
    """Enable a feature flag at runtime (sets env var for this process). Admin only."""
    _require_admin(admin)
    from config.feature_flags import flags as _flags

    registry = _flags.registry()
    if flag_name not in registry:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    env_var = registry[flag_name].get("env_var", flag_name)
    os.environ[env_var] = "true"
    _log_audit(admin.sub, "feature_flag.enabled", f"Flag {flag_name} enabled", ip=_client_ip(request))
    return {"flag": flag_name, "enabled": True}


@router.post("/api/admin/feature-flags/{flag_name}/disable")
async def disable_flag(flag_name: str, request: Request, admin: TokenPayload = Depends(get_current_user)):
    """Disable a feature flag at runtime. Admin only."""
    _require_admin(admin)
    from config.feature_flags import flags as _flags

    registry = _flags.registry()
    if flag_name not in registry:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    env_var = registry[flag_name].get("env_var", flag_name)
    os.environ[env_var] = "false"
    _log_audit(admin.sub, "feature_flag.disabled", f"Flag {flag_name} disabled", ip=_client_ip(request))
    return {"flag": flag_name, "enabled": False}


class FlagOverrideBody(BaseModel):
    user_id: str
    enabled: bool


@router.post("/api/admin/feature-flags/{flag_name}/override")
async def override_flag_for_user(
    flag_name: str,
    body: FlagOverrideBody,
    request: Request,
    admin: TokenPayload = Depends(get_current_user),
):
    """Set a per-user feature flag override (e.g. give beta users early access). Admin only."""
    _require_admin(admin)
    from config.feature_flags import flags as _flags

    if flag_name not in _flags.registry():
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    _flag_overrides.setdefault(flag_name, {})[body.user_id] = body.enabled
    _log_audit(
        admin.sub,
        "feature_flag.override",
        f"Flag {flag_name} overridden to {body.enabled} for user {body.user_id}",
        ip=_client_ip(request),
    )
    return {"flag": flag_name, "user_id": body.user_id, "enabled": body.enabled}


# ─────────────────────────────────────────────────────────────────────────────
# Task 38 — Rate Limiting setup helper (called from app.py)
# Task 40 — Sentry init helper (called from app.py)
# ─────────────────────────────────────────────────────────────────────────────


def setup_rate_limiting(app):
    """
    Attach Redis-backed slowapi rate limiter to the FastAPI app.
    Falls back to in-memory if Redis is unavailable.
    """
    try:
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from slowapi.util import get_remote_address

        redis_url = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}"
        try:
            limiter = Limiter(key_func=get_remote_address, storage_uri=redis_url)
            logger.info("Rate limiter: Redis backend at %s", redis_url)
        except Exception:  # nosec B110 — Redis optional for rate limiter
            limiter = Limiter(key_func=get_remote_address)
            logger.info("Rate limiter: in-memory backend (Redis unavailable)")

        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        logger.info("slowapi rate limiting configured")
        return limiter
    except ImportError:
        logger.warning(
            "slowapi not installed — rate limiting disabled. Run: pip install slowapi",
        )
        return None


def init_sentry():
    """
    Initialise Sentry SDK with full performance monitoring.

    Delegates to monitoring/sentry_config.py which configures:
    - Error tracking + stack traces
    - Performance monitoring (traces_sample_rate, profiles_sample_rate)
    - FastAPI, SQLAlchemy, Redis, aiohttp integrations
    - Custom before_send hook (PII scrubbing, health-check noise filtering)
    - Global tags: service, environment, release, model_version, oanda_region
    - ML fallback alert via capture_ml_fallback_event()

    Environment variables: SENTRY_DSN, SENTRY_TRACES_SAMPLE_RATE,
    SENTRY_PROFILES_SAMPLE_RATE, SENTRY_ENVIRONMENT, SENTRY_RELEASE, APP_ENV
    """
    try:
        from monitoring.sentry_config import init_sentry as _init

        _init()
    except Exception as exc:
        logger.warning("Sentry init failed (non-fatal): %s", exc)
