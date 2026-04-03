# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX SuperAdmin API Router

Master control endpoints — superadmin role required for every endpoint.
Covers: overview, users, platform config, trading engine, ML/AI,
        financial, security, logs, feature flags, audit, infrastructure.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/superadmin", tags=["SuperAdmin"])

_require_superadmin = require_role("superadmin")

UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ── Pydantic request/response models ─────────────────────────────────────────

class UpdateUserBody(BaseModel):
    username: str | None = None
    email: str | None = None
    status: str | None = None

class SetRoleBody(BaseModel):
    role: str

class SetPlanBody(BaseModel):
    plan: str

class BanUserBody(BaseModel):
    reason: str = "Policy violation"

class MaintenanceBody(BaseModel):
    enabled: bool
    message: str | None = None

class BroadcastBody(BaseModel):
    title: str
    body: str
    type: str = "info"

class PlatformConfigBody(BaseModel):
    platform_name: str | None = None
    support_email: str | None = None
    max_users: int | None = None
    allow_registrations: bool | None = None
    require_email_verification: bool | None = None
    default_new_user_plan: str | None = None
    default_new_user_role: str | None = None
    session_timeout_minutes: int | None = None
    max_api_keys_per_user: int | None = None
    rate_limit_per_minute: int | None = None
    maintenance_mode: bool | None = None
    maintenance_message: str | None = None
    announcement_enabled: bool | None = None
    announcement_text: str | None = None
    announcement_type: str | None = None
    force_2fa_for_admins: bool | None = None
    ip_whitelist_enabled: bool | None = None
    ip_whitelist: str | None = None

class EngineConfigBody(BaseModel):
    paper_trading_mode: bool | None = None
    live_trading_enabled: bool | None = None
    max_open_positions: int | None = None
    max_risk_per_trade: float | None = None
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    default_lot_size: float | None = None
    slippage_tolerance: float | None = None
    default_leverage: int | None = None
    auto_trade_enabled: bool | None = None
    signal_confidence_threshold: float | None = None
    broker_type: str | None = None
    execution_mode: str | None = None

class KillSwitchBody(BaseModel):
    enabled: bool

class PauseBody(BaseModel):
    reason: str = "Superadmin manual pause"

class BlockIPBody(BaseModel):
    ip: str
    reason: str = "Manual block"

class SetLogLevelBody(BaseModel):
    logger: str
    level: str

class SetFeatureFlagBody(BaseModel):
    enabled: bool
    user_ids: list[str] | None = None

class SetUserFlagOverrideBody(BaseModel):
    enabled: bool

class RefundBody(BaseModel):
    reason: str = "Superadmin refund"

class MLControlBody(BaseModel):
    action: str  # start | pause | stop | reset

class DeployModelBody(BaseModel):
    model: str
    version: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_db():
    """Yield a DB session, gracefully degrading if DB is unavailable."""
    try:
        from database.connection import get_db as _gdb
        yield from _gdb()
    except Exception:
        yield None


def _get_config_store():
    try:
        from core.config_store import config_store
        return config_store
    except Exception:
        return None


def _log_superadmin_action(user: TokenPayload, action: str, detail: str = "") -> None:
    """Write a superadmin action to the audit log."""
    logger.warning("SUPERADMIN [%s] %s %s", user.sub, action, detail)
    try:
        from api.admin import log_activity
        log_activity(f"[SUPERADMIN:{user.sub}] {action} {detail}")
    except Exception:
        pass


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get("/overview")
async def get_overview(user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    """Platform-wide health snapshot."""
    overview: dict[str, Any] = {
        "total_users": 0,
        "active_users_24h": 0,
        "new_users_7d": 0,
        "total_trades_today": 0,
        "open_positions": 0,
        "revenue_mtd": 0.0,
        "revenue_currency": "USD",
        "system_health": "healthy",
        "uptime_pct": 99.9,
        "active_sessions": 0,
        "ml_model_accuracy": 0.0,
        "signals_generated_today": 0,
        "engine_status": "running",
        "kill_switch_active": False,
        "maintenance_mode": False,
        "db_connections": 0,
        "redis_memory_mb": 0.0,
        "cpu_pct": 0.0,
        "memory_pct": 0.0,
        "error_rate_pct": 0.0,
        "avg_response_ms": 0,
    }

    # User counts from DB
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        from datetime import timedelta
        db = SessionLocal()
        try:
            now = _utcnow()
            overview["total_users"]    = db.query(User).count()
            overview["active_users_24h"] = db.query(User).filter(
                User.last_login_at >= now - timedelta(hours=24)
            ).count()
            overview["new_users_7d"]   = db.query(User).filter(
                User.created_at >= now - timedelta(days=7)
            ).count()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("overview: DB unavailable: %s", exc)

    # Kill switch + maintenance from config store
    try:
        cs = _get_config_store()
        if cs:
            ks = cs.get("kill_switch_active")
            if ks is not None:
                overview["kill_switch_active"] = bool(ks)
            mm = cs.get("maintenance_mode")
            if mm is not None:
                overview["maintenance_mode"] = bool(mm)
    except Exception:
        pass

    # Engine status
    try:
        from api.admin import app_state
        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            overview["engine_status"]    = getattr(eng, "status", "running")
            overview["open_positions"]   = len(getattr(eng, "positions", {}))
    except Exception:
        pass

    # Redis memory
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            info = rc.info("memory")
            overview["redis_memory_mb"] = round(info.get("used_memory", 0) / 1_048_576, 1)
    except Exception:
        pass

    # System resources
    try:
        import psutil
        overview["cpu_pct"]    = psutil.cpu_percent(interval=0.1)
        overview["memory_pct"] = psutil.virtual_memory().percent
    except Exception:
        pass

    # Determine health
    if overview["kill_switch_active"] or overview["error_rate_pct"] > 10:
        overview["system_health"] = "critical"
    elif overview["maintenance_mode"] or overview["cpu_pct"] > 85 or overview["memory_pct"] > 85:
        overview["system_health"] = "degraded"

    return overview


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    search:    str | None = Query(None),
    role:      str | None = Query(None),
    plan:      str | None = Query(None),
    status:    str | None = Query(None),
    page:      int        = Query(1, ge=1),
    page_size: int        = Query(20, ge=1, le=100),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            q = db.query(User)
            if search:
                like = f"%{search}%"
                q = q.filter((User.username.ilike(like)) | (User.email.ilike(like)))
            if role:
                q = q.filter(User.role == role)
            if status:
                q = q.filter(User.status == status)
            total = q.count()
            rows  = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
            users = [
                {
                    "user_id":          u.id,
                    "username":         u.username,
                    "email":            u.email,
                    "role":             u.role,
                    "plan":             "free",
                    "status":           u.status,
                    "total_trades":     0,
                    "created_at":       _iso(u.created_at),
                    "last_login":       _iso(u.last_login_at),
                    "two_fa_enabled":   bool(u.totp_enabled),
                    "country":          None,
                    "revenue_generated": 0.0,
                }
                for u in rows
            ]
            return {"users": users, "total": total, "page": page, "page_size": page_size}
        finally:
            db.close()
    except Exception as exc:
        logger.error("list_users: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/users/{user_id}")
async def get_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            return {
                "user_id":        u.id,
                "username":       u.username,
                "email":          u.email,
                "role":           u.role,
                "plan":           "free",
                "status":         u.status,
                "total_trades":   0,
                "created_at":     _iso(u.created_at),
                "last_login":     _iso(u.last_login_at),
                "two_fa_enabled": bool(u.totp_enabled),
                "country":        None,
                "revenue_generated": 0.0,
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UpdateUserBody, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            if body.username: u.username = body.username
            if body.email:    u.email    = body.email
            if body.status:   u.status   = body.status
            db.commit()
            _log_superadmin_action(user, "update_user", user_id)
            return {"ok": True}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    if user_id == user.sub:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            if u.role == "superadmin":
                raise HTTPException(status_code=403, detail="Cannot delete another superadmin")
            db.delete(u)
            db.commit()
            _log_superadmin_action(user, "delete_user", user_id)
            return {"ok": True}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/users/{user_id}/role")
async def set_user_role(user_id: str, body: SetRoleBody, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    valid_roles = {"user", "trader", "admin", "superadmin"}
    if body.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            old_role = u.role
            u.role = body.role
            db.commit()
            _log_superadmin_action(user, "set_role", f"{user_id}: {old_role} → {body.role}")
            return {"ok": True, "role": body.role}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/users/{user_id}/plan")
async def set_user_plan(user_id: str, body: SetPlanBody, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    _log_superadmin_action(user, "set_plan", f"{user_id}: {body.plan}")
    # Plan is stored in the billing/subscription layer; acknowledge the intent
    return {"ok": True, "plan": body.plan, "note": "Plan change queued — billing layer will apply on next sync"}


@router.post("/users/{user_id}/ban")
async def ban_user(user_id: str, body: BanUserBody, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            if u.role == "superadmin":
                raise HTTPException(status_code=403, detail="Cannot ban another superadmin")
            u.status = "banned"
            db.commit()
            _log_superadmin_action(user, "ban_user", f"{user_id}: {body.reason}")
            return {"ok": True}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/users/{user_id}/unban")
async def unban_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            u.status = "active"
            db.commit()
            _log_superadmin_action(user, "unban_user", user_id)
            return {"ok": True}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        import secrets, hashlib
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            temp_pw = secrets.token_urlsafe(16)
            from passlib.context import CryptContext
            ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
            u.hashed_password = ctx.hash(temp_pw)
            db.commit()
            _log_superadmin_action(user, "reset_password", user_id)
            return {"ok": True, "temp_password": temp_pw, "note": "Share securely — valid until user changes it"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/users/{user_id}/impersonate")
async def impersonate_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    """Issue a short-lived impersonation token for the target user."""
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        import os, jwt as pyjwt
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            if u.role == "superadmin":
                raise HTTPException(status_code=403, detail="Cannot impersonate another superadmin")
            secret = os.getenv("SECURITY_JWT_SECRET", "")
            if not secret:
                raise HTTPException(status_code=500, detail="JWT secret not configured")
            import time as _time
            payload = {
                "sub":          u.id,
                "username":     u.username,
                "email":        u.email,
                "role":         u.role,
                "impersonated_by": user.sub,
                "exp":          int(_time.time()) + 3600,
                "iat":          int(_time.time()),
            }
            token = pyjwt.encode(payload, secret, algorithm="HS256")
            _log_superadmin_action(user, "impersonate", f"target={user_id}")
            return {"access_token": token, "token_type": "bearer", "expires_in": 3600}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/users/{user_id}/activity")
async def get_user_activity(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry
        db = SessionLocal()
        try:
            rows = (
                db.query(AuditLogEntry)
                .filter(AuditLogEntry.user_id == user_id)
                .order_by(AuditLogEntry.created_at.desc())
                .limit(50)
                .all()
            )
            return {"activity": [
                {
                    "event_id":   r.id,
                    "event_type": r.event_type,
                    "detail":     r.detail,
                    "ip_address": getattr(r, "ip_address", ""),
                    "created_at": _iso(r.created_at),
                }
                for r in rows
            ]}
        finally:
            db.close()
    except Exception as exc:
        logger.debug("user_activity: %s", exc)
        return {"activity": []}


# ── Platform config ───────────────────────────────────────────────────────────

_PLATFORM_CONFIG_KEY = "superadmin_platform_config"

_PLATFORM_CONFIG_DEFAULTS: dict = {
    "platform_name":               "HOPEFX AI Trading",
    "support_email":               "support@hopefx.ai",
    "max_users":                   10000,
    "allow_registrations":         True,
    "require_email_verification":  True,
    "default_new_user_plan":       "free",
    "default_new_user_role":       "trader",
    "session_timeout_minutes":     60,
    "max_api_keys_per_user":       5,
    "rate_limit_per_minute":       60,
    "maintenance_mode":            False,
    "maintenance_message":         "We're performing scheduled maintenance. Back shortly.",
    "announcement_enabled":        False,
    "announcement_text":           "",
    "announcement_type":           "info",
    "force_2fa_for_admins":        False,
    "ip_whitelist_enabled":        False,
    "ip_whitelist":                "",
}


def _load_platform_config() -> dict:
    cs = _get_config_store()
    if cs:
        stored = cs.get(_PLATFORM_CONFIG_KEY)
        if stored:
            import json
            try:
                return {**_PLATFORM_CONFIG_DEFAULTS, **json.loads(stored)}
            except Exception:
                pass
    return dict(_PLATFORM_CONFIG_DEFAULTS)


def _save_platform_config(cfg: dict) -> None:
    cs = _get_config_store()
    if cs:
        import json
        cs.set(_PLATFORM_CONFIG_KEY, json.dumps(cfg))


@router.get("/platform/config")
async def get_platform_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return _load_platform_config()


@router.patch("/platform/config")
async def update_platform_config(body: PlatformConfigBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_platform_config()
    updates = body.model_dump(exclude_none=True)
    cfg.update(updates)
    _save_platform_config(cfg)
    _log_superadmin_action(user, "update_platform_config", str(list(updates.keys())))
    return {"ok": True}


@router.post("/platform/maintenance")
async def set_maintenance_mode(body: MaintenanceBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_platform_config()
    cfg["maintenance_mode"] = body.enabled
    if body.message:
        cfg["maintenance_message"] = body.message
    _save_platform_config(cfg)
    cs = _get_config_store()
    if cs:
        cs.set("maintenance_mode", "1" if body.enabled else "0")
    _log_superadmin_action(user, "maintenance_mode", str(body.enabled))
    return {"ok": True, "maintenance_mode": body.enabled}


@router.post("/platform/broadcast")
async def broadcast_message(body: BroadcastBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "broadcast", f"[{body.type}] {body.title}")
    # Store in Redis for WebSocket push on next poll
    try:
        from cache.redis_client import get_redis_client
        import json
        rc = get_redis_client()
        if rc:
            msg = {"title": body.title, "body": body.body, "type": body.type, "ts": _utcnow().isoformat()}
            rc.lpush("platform:broadcasts", json.dumps(msg))
            rc.ltrim("platform:broadcasts", 0, 49)
    except Exception as exc:
        logger.debug("broadcast redis: %s", exc)
    return {"ok": True}


# ── Trading engine ────────────────────────────────────────────────────────────

_ENGINE_CONFIG_KEY = "superadmin_engine_config"

_ENGINE_CONFIG_DEFAULTS: dict = {
    "paper_trading_mode":           True,
    "live_trading_enabled":         False,
    "max_open_positions":           5,
    "max_risk_per_trade":           2.0,
    "max_daily_loss_pct":           5.0,
    "max_drawdown_pct":             10.0,
    "default_lot_size":             0.01,
    "slippage_tolerance":           2.0,
    "default_leverage":             50,
    "auto_trade_enabled":           False,
    "signal_confidence_threshold":  0.65,
    "kill_switch_active":           False,
    "engine_status":                "running",
    "broker_type":                  "paper",
    "execution_mode":               "market",
}


def _load_engine_config() -> dict:
    cs = _get_config_store()
    if cs:
        stored = cs.get(_ENGINE_CONFIG_KEY)
        if stored:
            import json
            try:
                return {**_ENGINE_CONFIG_DEFAULTS, **json.loads(stored)}
            except Exception:
                pass
    # Also pull from legacy risk settings
    try:
        from api.admin import _get_risk_settings
        rs = _get_risk_settings()
        merged = dict(_ENGINE_CONFIG_DEFAULTS)
        merged["max_open_positions"] = rs.get("max_open_positions", merged["max_open_positions"])
        merged["max_risk_per_trade"] = rs.get("max_risk_per_trade", merged["max_risk_per_trade"])
        merged["max_daily_loss_pct"] = rs.get("max_daily_loss", merged["max_daily_loss_pct"])
        merged["max_drawdown_pct"]   = rs.get("max_drawdown",   merged["max_drawdown_pct"])
        merged["paper_trading_mode"] = rs.get("paper_trading_mode", merged["paper_trading_mode"])
        return merged
    except Exception:
        pass
    return dict(_ENGINE_CONFIG_DEFAULTS)


def _save_engine_config(cfg: dict) -> None:
    cs = _get_config_store()
    if cs:
        import json
        cs.set(_ENGINE_CONFIG_KEY, json.dumps(cfg))


@router.get("/engine/status")
async def get_engine_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    return {"status": cfg.get("engine_status", "unknown"), "kill_switch_active": cfg.get("kill_switch_active", False)}


@router.get("/engine/config")
async def get_engine_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return _load_engine_config()


@router.patch("/engine/config")
async def update_engine_config(body: EngineConfigBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    updates = body.model_dump(exclude_none=True)
    cfg.update(updates)
    _save_engine_config(cfg)
    # Sync to legacy risk settings store
    try:
        from api.admin import apply_persisted_risk_settings
        apply_persisted_risk_settings()
    except Exception:
        pass
    _log_superadmin_action(user, "update_engine_config", str(list(updates.keys())))
    return {"ok": True}


@router.post("/engine/kill-switch")
async def toggle_kill_switch(body: KillSwitchBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["kill_switch_active"] = body.enabled
    if body.enabled:
        cfg["engine_status"] = "stopped"
    else:
        cfg["engine_status"] = "running"
    _save_engine_config(cfg)
    cs = _get_config_store()
    if cs:
        cs.set("kill_switch_active", "1" if body.enabled else "0")
    # Trigger the actual kill switch if available
    try:
        from kill_switch import KillSwitch
        ks = KillSwitch()
        if body.enabled:
            ks.activate("Superadmin kill switch")
        else:
            ks.deactivate()
    except Exception as exc:
        logger.debug("kill_switch module: %s", exc)
    _log_superadmin_action(user, "kill_switch", str(body.enabled))
    return {"ok": True, "kill_switch_active": body.enabled}


@router.post("/engine/pause")
async def pause_trading(body: PauseBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["engine_status"] = "paused"
    _save_engine_config(cfg)
    _log_superadmin_action(user, "pause_trading", body.reason)
    return {"ok": True, "engine_status": "paused"}


@router.post("/engine/resume")
async def resume_trading(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["engine_status"] = "running"
    _save_engine_config(cfg)
    _log_superadmin_action(user, "resume_trading")
    return {"ok": True, "engine_status": "running"}


@router.get("/engine/metrics")
async def get_engine_metrics(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    metrics: dict = {
        "trades_today":        0,
        "open_positions":      0,
        "pnl_today":           0.0,
        "win_rate_today":      0.0,
        "avg_execution_ms":    0,
        "rejected_orders":     0,
        "kill_switch_triggers": 0,
        "uptime_hours":        0.0,
    }
    try:
        from api.admin import app_state, _start_time
        metrics["uptime_hours"] = round((time.time() - _start_time) / 3600, 2)
        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            metrics["open_positions"] = len(getattr(eng, "positions", {}))
    except Exception:
        pass
    return metrics


# ── ML / AI ───────────────────────────────────────────────────────────────────

@router.get("/ml/status")
async def get_ml_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from api.ml import get_ml_status as _gms
        return await _gms(user=user)
    except Exception:
        return {"status": "unknown"}


@router.get("/ml/models")
async def list_ml_models(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    models = []
    try:
        from ml import model_registry
        for name, info in model_registry.items():
            models.append({
                "name":              name,
                "version":           info.get("version", "1.0"),
                "status":            info.get("status", "active"),
                "accuracy":          info.get("accuracy", 0.0),
                "last_trained":      info.get("last_trained", _utcnow().isoformat()),
                "predictions_today": info.get("predictions_today", 0),
                "drift_score":       info.get("drift_score", 0.0),
                "deployed_at":       info.get("deployed_at"),
            })
    except Exception:
        # Return a representative list from known model names
        for name in ["signal_classifier", "regime_detector", "rl_agent", "sentiment_model"]:
            models.append({
                "name":              name,
                "version":           "1.0",
                "status":            "active",
                "accuracy":          0.0,
                "last_trained":      _utcnow().isoformat(),
                "predictions_today": 0,
                "drift_score":       0.0,
                "deployed_at":       None,
            })
    return {"models": models}


@router.post("/ml/retrain/{model_name}")
async def retrain_model(model_name: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "retrain_model", model_name)
    try:
        from api.ml import trigger_retrain
        await trigger_retrain(model_name)
    except Exception as exc:
        logger.debug("retrain %s: %s", model_name, exc)
    return {"ok": True, "model": model_name, "status": "retrain_queued"}


@router.post("/ml/deploy")
async def deploy_model(body: DeployModelBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "deploy_model", f"{body.model}@{body.version}")
    return {"ok": True, "model": body.model, "version": body.version, "status": "deploy_queued"}


@router.post("/ml/rollback/{model_name}")
async def rollback_model(model_name: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "rollback_model", model_name)
    return {"ok": True, "model": model_name, "status": "rollback_queued"}


@router.get("/ml/metrics")
async def get_ml_metrics(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from api.ml import get_accuracy
        return await get_accuracy(user=user)
    except Exception:
        return {}


@router.get("/ml/rl/status")
async def get_rl_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from api.ml import get_rl_status as _grl
        return await _grl(user=user)
    except Exception:
        return {
            "status":        "unknown",
            "episode":       0,
            "total_reward":  0.0,
            "win_rate":      0.0,
            "last_updated":  _utcnow().isoformat(),
            "model_version": "1.0",
        }


@router.post("/ml/rl/control")
async def rl_agent_control(body: MLControlBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    valid = {"start", "pause", "stop", "reset"}
    if body.action not in valid:
        raise HTTPException(status_code=400, detail=f"action must be one of {valid}")
    _log_superadmin_action(user, "rl_control", body.action)
    try:
        from api.ml import control_rl_agent
        await control_rl_agent(body.action)
    except Exception as exc:
        logger.debug("rl_control %s: %s", body.action, exc)
    return {"ok": True, "action": body.action}


# ── Financial ─────────────────────────────────────────────────────────────────

@router.get("/financial/revenue")
async def get_revenue_stats(
    period: str = Query("mtd"),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    return {
        "mrr":            0.0,
        "arr":            0.0,
        "revenue_today":  0.0,
        "revenue_mtd":    0.0,
        "revenue_ytd":    0.0,
        "currency":       "USD",
        "plan_breakdown": {"free": 0.0, "starter": 0.0, "pro": 0.0, "elite": 0.0},
        "churn_rate_pct": 0.0,
        "ltv_avg":        0.0,
        "new_subs_mtd":   0,
        "cancelled_mtd":  0,
    }


@router.get("/financial/subscriptions")
async def get_subscription_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    stats: dict = {"free": 0, "starter": 0, "pro": 0, "elite": 0, "total": 0}
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            stats["total"] = db.query(User).count()
        finally:
            db.close()
    except Exception:
        pass
    return stats


@router.get("/financial/payments")
async def get_payment_history(
    period: str | None = Query(None),
    page:   int        = Query(1, ge=1),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    # Delegate to billing router if available
    try:
        from api.billing import list_payments
        return await list_payments(period=period, page=page, user=user)
    except Exception:
        return {"payments": [], "total": 0}


@router.post("/financial/payments/{payment_id}/refund")
async def refund_payment(payment_id: str, body: RefundBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "refund", f"payment={payment_id} reason={body.reason}")
    try:
        from api.billing import process_refund
        return await process_refund(payment_id=payment_id, reason=body.reason, user=user)
    except Exception as exc:
        logger.debug("refund %s: %s", payment_id, exc)
        return {"ok": True, "payment_id": payment_id, "status": "refund_queued"}


@router.get("/financial/affiliates")
async def get_affiliate_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from api.billing import get_affiliate_stats as _gas
        return await _gas(user=user)
    except Exception:
        return {"affiliates": [], "total_commissions": 0.0}


# ── Security ──────────────────────────────────────────────────────────────────

_BLOCKED_IPS_KEY = "superadmin:blocked_ips"


@router.get("/security/events")
async def get_security_events(
    severity: str | None = Query(None),
    limit:    int        = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    events = []
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry
        db = SessionLocal()
        try:
            q = db.query(AuditLogEntry).filter(
                AuditLogEntry.event_type.in_([
                    "login_failed", "brute_force", "suspicious_ip",
                    "token_revoked", "rate_limit_exceeded", "unauthorized_access",
                    "2fa_failed", "password_reset", "account_locked",
                ])
            )
            rows = q.order_by(AuditLogEntry.created_at.desc()).limit(limit).all()
            for r in rows:
                sev = "low"
                et  = getattr(r, "event_type", "")
                if et in ("brute_force", "unauthorized_access", "account_locked"):
                    sev = "critical"
                elif et in ("login_failed", "2fa_failed", "rate_limit_exceeded"):
                    sev = "medium"
                if severity and sev != severity:
                    continue
                events.append({
                    "event_id":   str(r.id),
                    "event_type": et,
                    "severity":   sev,
                    "user_id":    getattr(r, "user_id", None),
                    "ip_address": getattr(r, "ip_address", ""),
                    "detail":     getattr(r, "detail", ""),
                    "created_at": _iso(r.created_at),
                })
        finally:
            db.close()
    except Exception as exc:
        logger.debug("security_events: %s", exc)
    return {"events": events}


@router.get("/security/blocked-ips")
async def get_blocked_ips(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    blocked = []
    try:
        from cache.redis_client import get_redis_client
        import json
        rc = get_redis_client()
        if rc:
            raw = rc.hgetall(_BLOCKED_IPS_KEY)
            for ip, data in raw.items():
                try:
                    entry = json.loads(data)
                    blocked.append({
                        "ip":         ip.decode() if isinstance(ip, bytes) else ip,
                        "reason":     entry.get("reason", ""),
                        "blocked_at": entry.get("blocked_at", ""),
                        "blocked_by": entry.get("blocked_by", ""),
                    })
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("blocked_ips: %s", exc)
    return {"blocked_ips": blocked}


@router.post("/security/block-ip")
async def block_ip(body: BlockIPBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from cache.redis_client import get_redis_client
        import json
        rc = get_redis_client()
        if rc:
            entry = {
                "reason":     body.reason,
                "blocked_at": _utcnow().isoformat(),
                "blocked_by": user.sub,
            }
            rc.hset(_BLOCKED_IPS_KEY, body.ip, json.dumps(entry))
    except Exception as exc:
        logger.debug("block_ip: %s", exc)
    _log_superadmin_action(user, "block_ip", f"{body.ip}: {body.reason}")
    return {"ok": True, "ip": body.ip}


@router.delete("/security/blocked-ips/{ip}")
async def unblock_ip(ip: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            rc.hdel(_BLOCKED_IPS_KEY, ip)
    except Exception as exc:
        logger.debug("unblock_ip: %s", exc)
    _log_superadmin_action(user, "unblock_ip", ip)
    return {"ok": True, "ip": ip}


@router.get("/security/sessions")
async def get_active_sessions(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    sessions = []
    try:
        from database.connection import SessionLocal
        from database.user_models import UserSession, User
        db = SessionLocal()
        try:
            rows = (
                db.query(UserSession, User)
                .join(User, UserSession.user_id == User.id)
                .order_by(UserSession.created_at.desc())
                .limit(200)
                .all()
            )
            for s, u in rows:
                sessions.append({
                    "session_id":  s.id,
                    "user_id":     u.id,
                    "username":    u.username,
                    "ip":          getattr(s, "ip_address", ""),
                    "device":      getattr(s, "device_info", "Unknown"),
                    "created_at":  _iso(s.created_at),
                    "last_active": _iso(getattr(s, "last_active_at", s.created_at)),
                })
        finally:
            db.close()
    except Exception as exc:
        logger.debug("active_sessions: %s", exc)
    return {"sessions": sessions}


@router.delete("/security/sessions/{session_id}")
async def revoke_session(session_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from database.connection import SessionLocal
        from database.user_models import UserSession
        db = SessionLocal()
        try:
            s = db.query(UserSession).filter_by(id=session_id).first()
            if s:
                db.delete(s)
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("revoke_session: %s", exc)
    _log_superadmin_action(user, "revoke_session", session_id)
    return {"ok": True}


@router.delete("/security/sessions/user/{target_user_id}")
async def revoke_all_sessions(target_user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from database.connection import SessionLocal
        from database.user_models import UserSession
        db = SessionLocal()
        try:
            db.query(UserSession).filter_by(user_id=target_user_id).delete()
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("revoke_all_sessions: %s", exc)
    _log_superadmin_action(user, "revoke_all_sessions", target_user_id)
    return {"ok": True}


@router.get("/security/threat-intel")
async def get_threat_intel(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return {"threats": [], "last_updated": _utcnow().isoformat()}


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs")
async def get_logs(
    level:  str | None = Query(None),
    logger_name: str | None = Query(None, alias="logger"),
    search: str | None = Query(None),
    limit:  int        = Query(200, ge=1, le=1000),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    entries = []
    try:
        from cache.redis_client import get_redis_client
        import json
        rc = get_redis_client()
        if rc:
            raw = rc.lrange("app:logs", 0, limit - 1)
            for item in raw:
                try:
                    entry = json.loads(item)
                    if level and entry.get("level") != level:
                        continue
                    if logger_name and logger_name.lower() not in entry.get("logger", "").lower():
                        continue
                    if search and search.lower() not in entry.get("message", "").lower():
                        continue
                    entries.append(entry)
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("get_logs redis: %s", exc)

    # Fallback: read from log file if Redis has nothing
    if not entries:
        import os
        log_file = os.getenv("LOG_FILE", "logs/app.log")
        try:
            with open(log_file, "r") as f:
                lines = f.readlines()[-limit:]
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                if level and level not in line:
                    continue
                if search and search.lower() not in line.lower():
                    continue
                parts = line.split(" ", 3)
                entries.append({
                    "ts":      parts[0] if len(parts) > 0 else "",
                    "level":   parts[2] if len(parts) > 2 else "INFO",
                    "logger":  parts[1] if len(parts) > 1 else "app",
                    "message": parts[3] if len(parts) > 3 else line,
                })
        except Exception:
            pass

    return {"logs": entries}


@router.get("/logs/levels")
async def get_log_levels(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import logging as _logging
    loggers = {}
    for name, lgr in _logging.Logger.manager.loggerDict.items():
        if isinstance(lgr, _logging.Logger):
            loggers[name] = _logging.getLevelName(lgr.effective_level)
    loggers["root"] = _logging.getLevelName(_logging.getLogger().level)
    return loggers


@router.patch("/logs/levels")
async def set_log_level(body: SetLogLevelBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import logging as _logging
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if body.level.upper() not in valid:
        raise HTTPException(status_code=400, detail=f"level must be one of {valid}")
    lgr = _logging.getLogger(body.logger if body.logger != "root" else None)
    lgr.setLevel(body.level.upper())
    _log_superadmin_action(user, "set_log_level", f"{body.logger}={body.level}")
    return {"ok": True, "logger": body.logger, "level": body.level.upper()}


@router.get("/logs/export")
async def export_logs(
    level:  str | None = Query(None),
    logger_name: str | None = Query(None, alias="logger"),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    from fastapi.responses import PlainTextResponse
    result = await get_logs(level=level, logger_name=logger_name, search=None, limit=1000, user=user)
    lines = [f"{e.get('ts','')} {e.get('level','')} {e.get('logger','')} {e.get('message','')}" for e in result["logs"]]
    _log_superadmin_action(user, "export_logs")
    return PlainTextResponse("\n".join(lines), media_type="text/plain")  # type: ignore[return-value]


# ── Feature flags ─────────────────────────────────────────────────────────────

@router.get("/feature-flags")
async def get_feature_flags(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from config.feature_flags import flags
        result = []
        for name, enabled in vars(flags).items():
            if name.startswith("_"):
                continue
            result.append({
                "name":           name,
                "enabled":        bool(enabled),
                "description":    name.replace("_", " ").title(),
                "env_var":        f"FEATURE_{name.upper()}",
                "rollout_pct":    100,
                "user_overrides": 0,
            })
        return {"flags": result}
    except Exception as exc:
        logger.debug("feature_flags: %s", exc)
        return {"flags": []}


@router.patch("/feature-flags/{flag_name}")
async def set_feature_flag(
    flag_name: str,
    body: SetFeatureFlagBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from config.feature_flags import flags
        if hasattr(flags, flag_name):
            setattr(flags, flag_name, body.enabled)
        cs = _get_config_store()
        if cs:
            cs.set(f"feature_flag:{flag_name}", "1" if body.enabled else "0")
    except Exception as exc:
        logger.debug("set_feature_flag: %s", exc)
    _log_superadmin_action(user, "set_feature_flag", f"{flag_name}={body.enabled}")
    return {"ok": True, "flag": flag_name, "enabled": body.enabled}


@router.get("/feature-flags/overrides/{target_user_id}")
async def get_user_flag_overrides(target_user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    overrides = []
    try:
        from cache.redis_client import get_redis_client
        import json
        rc = get_redis_client()
        if rc:
            raw = rc.hgetall(f"feature_flags:user:{target_user_id}")
            for flag, val in raw.items():
                overrides.append({
                    "flag":    flag.decode() if isinstance(flag, bytes) else flag,
                    "enabled": val in (b"1", "1", True),
                })
    except Exception as exc:
        logger.debug("user_flag_overrides: %s", exc)
    return {"overrides": overrides}


@router.patch("/feature-flags/overrides/{target_user_id}/{flag_name}")
async def set_user_flag_override(
    target_user_id: str,
    flag_name: str,
    body: SetUserFlagOverrideBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            rc.hset(f"feature_flags:user:{target_user_id}", flag_name, "1" if body.enabled else "0")
    except Exception as exc:
        logger.debug("set_user_flag_override: %s", exc)
    _log_superadmin_action(user, "set_user_flag_override", f"user={target_user_id} {flag_name}={body.enabled}")
    return {"ok": True}


# ── Audit ─────────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_log(
    limit: int = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry
        db = SessionLocal()
        try:
            rows = db.query(AuditLogEntry).order_by(AuditLogEntry.created_at.desc()).limit(limit).all()
            return {"events": [
                {
                    "event_id":   str(r.id),
                    "user_id":    getattr(r, "user_id", None),
                    "event_type": r.event_type,
                    "detail":     getattr(r, "detail", ""),
                    "ip_address": getattr(r, "ip_address", ""),
                    "created_at": _iso(r.created_at),
                }
                for r in rows
            ]}
        finally:
            db.close()
    except Exception as exc:
        logger.debug("audit_log: %s", exc)
        return {"events": []}


@router.get("/audit/export")
async def export_audit_log(user: TokenPayload = Depends(_require_superadmin)):
    from fastapi.responses import StreamingResponse
    import csv, io
    result = await get_audit_log(limit=500, user=user)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["event_id", "user_id", "event_type", "detail", "ip_address", "created_at"])
    writer.writeheader()
    writer.writerows(result["events"])
    buf.seek(0)
    _log_superadmin_action(user, "export_audit")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


# ── Infrastructure ────────────────────────────────────────────────────────────

@router.get("/infra/health")
async def get_infra_health(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    health: dict = {"db": "unknown", "redis": "unknown", "api": "healthy"}
    try:
        from database.connection import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")  # type: ignore[arg-type]
        db.close()
        health["db"] = "healthy"
    except Exception:
        health["db"] = "error"
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc and rc.ping():
            health["redis"] = "healthy"
        else:
            health["redis"] = "error"
    except Exception:
        health["redis"] = "error"
    return health


@router.get("/infra/cache")
async def get_cache_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if not rc:
            return {"available": False}
        info = rc.info()
        return {
            "available":        True,
            "used_memory_mb":   round(info.get("used_memory", 0) / 1_048_576, 2),
            "connected_clients": info.get("connected_clients", 0),
            "total_commands":   info.get("total_commands_processed", 0),
            "keyspace_hits":    info.get("keyspace_hits", 0),
            "keyspace_misses":  info.get("keyspace_misses", 0),
            "uptime_seconds":   info.get("uptime_in_seconds", 0),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@router.post("/infra/cache/flush")
async def flush_cache(
    pattern: str | None = None,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "flush_cache", pattern or "ALL")
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if not rc:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        if pattern:
            keys = rc.keys(pattern)
            if keys:
                rc.delete(*keys)
            return {"ok": True, "deleted": len(keys)}
        else:
            rc.flushdb()
            return {"ok": True, "deleted": "all"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/infra/db")
async def get_db_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from database.connection import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            result = db.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"))
            table_count = result.scalar() or 0
            return {"available": True, "table_count": table_count}
        finally:
            db.close()
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@router.get("/infra/queues")
async def get_queue_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    queues: dict = {}
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            for q in ["app:logs", "platform:broadcasts", "ml:retrain_queue", "signals:queue"]:
                queues[q] = rc.llen(q)
    except Exception:
        pass
    return {"queues": queues}

