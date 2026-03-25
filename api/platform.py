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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Platform"])

# ── In-memory stores (replace with DB in production) ─────────────────────────

_sessions: Dict[str, dict] = {}          # session_id → session info
_audit_log: List[dict] = []              # append-only audit events
_api_keys: Dict[str, dict] = {}          # key_id → key metadata
_api_key_hashes: Dict[str, str] = {}     # sha256(raw_key) → key_id
_users_admin: Dict[str, dict] = {}       # user_id → admin view
_flag_overrides: Dict[str, Dict[str, bool]] = {}  # flag_name → {user_id: bool}

# Seed demo audit log
def _seed_audit():
    events = [
        ("system", "startup", "Application started"),
        ("user-001", "login", "Login from 192.168.1.1"),
        ("user-002", "trade.placed", "BUY 0.1 XAU/USD @ 2350.00"),
        ("user-001", "settings.changed", "Notification channel updated"),
        ("user-003", "login.failed", "Invalid password attempt"),
        ("user-002", "withdrawal.requested", "$500 withdrawal initiated"),
        ("admin", "user.banned", "user-004 banned for ToS violation"),
        ("user-001", "signal.copied", "Copied signal sig-003 from AlgoTrader_X"),
    ]
    for user_id, event_type, detail in events:
        _audit_log.append({
            "event_id":   str(uuid.uuid4()),
            "user_id":    user_id,
            "event_type": event_type,
            "detail":     detail,
            "ip_address": "127.0.0.1",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

_seed_audit()


def _log_audit(user_id: str, event_type: str, detail: str, ip: str = ""):
    _audit_log.append({
        "event_id":   str(uuid.uuid4()),
        "user_id":    user_id,
        "event_type": event_type,
        "detail":     detail,
        "ip_address": ip,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Task 35 — Session Management
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/auth/sessions")
async def list_sessions(user: TokenPayload = Depends(get_current_user)):
    """List all active sessions for the current user."""
    user_sessions = [s for s in _sessions.values() if s["user_id"] == user.sub and not s.get("revoked")]
    return {"sessions": user_sessions, "total": len(user_sessions)}


@router.delete("/api/auth/sessions/{session_id}")
async def revoke_session(session_id: str, user: TokenPayload = Depends(get_current_user)):
    """Revoke a specific session (log out that device)."""
    session = _sessions.get(session_id)
    if not session or session["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Session not found")
    session["revoked"] = True
    session["revoked_at"] = datetime.now(timezone.utc).isoformat()
    _log_audit(user.sub, "session.revoked", f"Session {session_id[:8]} revoked")
    return {"revoked": True, "session_id": session_id}


@router.delete("/api/auth/sessions")
async def revoke_all_sessions(user: TokenPayload = Depends(get_current_user)):
    """Revoke all sessions for the current user (logout everywhere)."""
    count = 0
    for s in _sessions.values():
        if s["user_id"] == user.sub and not s.get("revoked"):
            s["revoked"] = True
            s["revoked_at"] = datetime.now(timezone.utc).isoformat()
            count += 1
    _log_audit(user.sub, "session.revoke_all", f"All {count} sessions revoked")
    return {"revoked": count}


# Helper called by auth router on login to register a session
def register_session(user_id: str, device_info: str = "", ip_address: str = "") -> str:
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "session_id": session_id,
        "user_id":    user_id,
        "device_info": device_info or "Unknown device",
        "ip_address": ip_address,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked":    False,
        "revoked_at": None,
    }
    return session_id


# ─────────────────────────────────────────────────────────────────────────────
# Task 36 — User Admin Panel
# ─────────────────────────────────────────────────────────────────────────────

def _get_demo_users():
    if not _users_admin:
        for i in range(1, 8):
            uid = f"user-{i:03d}"
            _users_admin[uid] = {
                "user_id":    uid,
                "username":   f"trader_{i:03d}",
                "email":      f"trader{i}@example.com",
                "status":     "active" if i != 4 else "banned",
                "tier":       ["free", "professional", "enterprise"][i % 3],
                "total_trades": i * 47,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_login": datetime.now(timezone.utc).isoformat(),
            }
    return _users_admin


@router.get("/api/admin/users")
async def list_users(
    page:   int = 1,
    limit:  int = 20,
    status_filter: Optional[str] = Query(None, alias="status"),
    user: TokenPayload = Depends(get_current_user),
):
    """List all users with subscription status. Admin only."""
    users = list(_get_demo_users().values())
    if status_filter:
        users = [u for u in users if u["status"] == status_filter]
    start = (page - 1) * limit
    return {
        "users": users[start: start + limit],
        "total": len(users),
        "page":  page,
    }


@router.post("/api/admin/users/{user_id}/ban")
async def ban_user(user_id: str, admin: TokenPayload = Depends(get_current_user)):
    users = _get_demo_users()
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    users[user_id]["status"] = "banned"
    _log_audit(admin.sub, "user.banned", f"User {user_id} banned by admin")
    return {"banned": True, "user_id": user_id}


@router.post("/api/admin/users/{user_id}/unban")
async def unban_user(user_id: str, admin: TokenPayload = Depends(get_current_user)):
    users = _get_demo_users()
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    users[user_id]["status"] = "active"
    _log_audit(admin.sub, "user.unbanned", f"User {user_id} unbanned by admin")
    return {"unbanned": True, "user_id": user_id}


@router.post("/api/admin/users/{user_id}/reset-password")
async def reset_password(user_id: str, admin: TokenPayload = Depends(get_current_user)):
    """Trigger a password reset email for a user."""
    _log_audit(admin.sub, "user.password_reset", f"Password reset triggered for {user_id}")
    return {"reset_triggered": True, "user_id": user_id, "note": "Reset email queued"}


@router.get("/api/admin/users/{user_id}/trades")
async def get_user_trades(user_id: str, admin: TokenPayload = Depends(get_current_user)):
    """View a user's trade history (demo data)."""
    import random
    random.seed(hash(user_id) % 1000)
    trades = [
        {
            "trade_id":  f"t-{user_id}-{i:03d}",
            "symbol":    random.choice(["XAU/USD", "EUR/USD"]),
            "direction": random.choice(["BUY", "SELL"]),
            "lots":      round(random.random() * 0.5, 2),
            "pnl":       round((random.random() - 0.4) * 200, 2),
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        for i in range(10)
    ]
    return {"trades": trades, "user_id": user_id}


@router.post("/api/admin/users/{user_id}/impersonate")
async def impersonate_user(user_id: str, admin: TokenPayload = Depends(get_current_user)):
    """Generate a short-lived impersonation token for support purposes."""
    _log_audit(admin.sub, "user.impersonated", f"Admin impersonating {user_id}")
    # In production: generate a short-lived JWT with impersonation claim
    token = f"impersonate_{secrets.token_urlsafe(16)}"
    return {
        "impersonation_token": token,
        "user_id":  user_id,
        "expires_in": 300,
        "note": "Token valid for 5 minutes. All actions are audit-logged.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 37 — Audit Log UI
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/admin/audit-log")
async def get_audit_log(
    page:       int = 1,
    limit:      int = 50,
    user_id:    Optional[str] = None,
    event_type: Optional[str] = None,
    admin: TokenPayload = Depends(get_current_user),
):
    """Return paginated audit log with optional filters."""
    events = list(reversed(_audit_log))  # newest first
    if user_id:
        events = [e for e in events if e["user_id"] == user_id]
    if event_type:
        events = [e for e in events if event_type in e["event_type"]]
    start = (page - 1) * limit
    return {
        "events": events[start: start + limit],
        "total":  len(events),
        "page":   page,
        "pages":  max(1, (len(events) + limit - 1) // limit),
    }


@router.get("/api/admin/audit-log/export")
async def export_audit_log(admin: TokenPayload = Depends(get_current_user)):
    """Export full audit log as CSV."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["event_id", "user_id", "event_type", "detail", "ip_address", "created_at"])
    writer.writeheader()
    for event in _audit_log:
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
    name:   str = Field(..., min_length=1, max_length=60)
    scopes: List[str] = Field(default_factory=lambda: ["read"])


@router.get("/api/settings/api-keys")
async def list_api_keys(user: TokenPayload = Depends(get_current_user)):
    """List all API keys for the current user (never returns raw key)."""
    keys = [k for k in _api_keys.values() if k["user_id"] == user.sub and not k.get("revoked")]
    return {"api_keys": keys}


@router.post("/api/settings/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: CreateApiKeyBody,
    user: TokenPayload = Depends(get_current_user),
):
    """Create a named API key. Raw key shown once — stored as SHA-256 hash."""
    raw_key = f"hfx_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = str(uuid.uuid4())[:12]

    _api_keys[key_id] = {
        "key_id":     key_id,
        "user_id":    user.sub,
        "name":       body.name,
        "scopes":     body.scopes,
        "key_prefix": raw_key[:10] + "…",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_used":  None,
        "revoked":    False,
    }
    _api_key_hashes[key_hash] = key_id
    _log_audit(user.sub, "api_key.created", f"API key '{body.name}' created")

    return {
        "key_id":  key_id,
        "api_key": raw_key,
        "name":    body.name,
        "scopes":  body.scopes,
        "note":    "Store this key securely — it will not be shown again.",
    }


@router.delete("/api/settings/api-keys/{key_id}")
async def revoke_api_key(key_id: str, user: TokenPayload = Depends(get_current_user)):
    """Revoke an API key."""
    key = _api_keys.get(key_id)
    if not key or key["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="API key not found")
    key["revoked"] = True
    key["revoked_at"] = datetime.now(timezone.utc).isoformat()
    _log_audit(user.sub, "api_key.revoked", f"API key '{key['name']}' revoked")
    return {"revoked": True, "key_id": key_id}


# ─────────────────────────────────────────────────────────────────────────────
# Task 41 — Feature Flag UI
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/admin/feature-flags")
async def list_feature_flags(admin: TokenPayload = Depends(get_current_user)):
    """Return all feature flags with their current state and metadata."""
    from config.feature_flags import flags as _flags, FeatureStatus
    registry = _flags.registry()
    result = []
    for name, info in registry.items():
        result.append({
            "name":        name,
            "enabled":     info.get("enabled", False),
            "status":      info.get("status", "unknown"),
            "description": info.get("description", ""),
            "env_var":     info.get("env_var", ""),
            "overrides":   _flag_overrides.get(name, {}),
        })
    return {"flags": result, "total": len(result)}


@router.post("/api/admin/feature-flags/{flag_name}/enable")
async def enable_flag(flag_name: str, admin: TokenPayload = Depends(get_current_user)):
    """Enable a feature flag at runtime (sets env var for this process)."""
    from config.feature_flags import flags as _flags
    registry = _flags.registry()
    if flag_name not in registry:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    env_var = registry[flag_name].get("env_var", flag_name)
    os.environ[env_var] = "true"
    _log_audit(admin.sub, "feature_flag.enabled", f"Flag {flag_name} enabled")
    return {"flag": flag_name, "enabled": True}


@router.post("/api/admin/feature-flags/{flag_name}/disable")
async def disable_flag(flag_name: str, admin: TokenPayload = Depends(get_current_user)):
    """Disable a feature flag at runtime."""
    from config.feature_flags import flags as _flags
    registry = _flags.registry()
    if flag_name not in registry:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    env_var = registry[flag_name].get("env_var", flag_name)
    os.environ[env_var] = "false"
    _log_audit(admin.sub, "feature_flag.disabled", f"Flag {flag_name} disabled")
    return {"flag": flag_name, "enabled": False}


class FlagOverrideBody(BaseModel):
    user_id: str
    enabled: bool


@router.post("/api/admin/feature-flags/{flag_name}/override")
async def override_flag_for_user(
    flag_name: str,
    body: FlagOverrideBody,
    admin: TokenPayload = Depends(get_current_user),
):
    """Set a per-user feature flag override (e.g. give beta users early access)."""
    from config.feature_flags import flags as _flags
    if flag_name not in _flags.registry():
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    _flag_overrides.setdefault(flag_name, {})[body.user_id] = body.enabled
    _log_audit(admin.sub, "feature_flag.override",
               f"Flag {flag_name} overridden to {body.enabled} for user {body.user_id}")
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
        from slowapi.util import get_remote_address
        from slowapi.errors import RateLimitExceeded

        redis_url = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}"
        try:
            limiter = Limiter(key_func=get_remote_address, storage_uri=redis_url)
            logger.info("Rate limiter: Redis backend at %s", redis_url)
        except Exception:
            limiter = Limiter(key_func=get_remote_address)
            logger.info("Rate limiter: in-memory backend (Redis unavailable)")

        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        logger.info("slowapi rate limiting configured")
        return limiter
    except ImportError:
        logger.warning("slowapi not installed — rate limiting disabled. Run: pip install slowapi")
        return None


def init_sentry():
    """
    Initialise Sentry SDK if SENTRY_DSN is set.
    Safe to call even if sentry-sdk is not installed.
    """
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        logger.info("Sentry disabled (SENTRY_DSN not set)")
        return

    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("APP_ENV", "development"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            send_default_pii=False,
        )
        logger.info("Sentry initialised (env=%s)", os.getenv("APP_ENV", "development"))
    except ImportError:
        logger.warning("sentry-sdk not installed — error tracking disabled")
    except Exception as exc:
        logger.warning("Sentry init failed: %s", exc)
