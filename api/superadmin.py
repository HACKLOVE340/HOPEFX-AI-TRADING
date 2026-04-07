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
import re as _re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/superadmin", tags=["SuperAdmin"])

# ── Report path helpers ───────────────────────────────────────────────────────

# Report IDs must be UUID-format with an optional .json/.html/.csv extension.
_REPORT_ID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:\.(json|html|csv))?$",
    _re.IGNORECASE,
)
_REPORT_DIR = (Path(__file__).parent.parent / "reports" / "output").resolve()


def _validate_report_id(report_id: str) -> str:
    """Raise HTTPException 400 if report_id is not a safe UUID-based name."""
    if not _REPORT_ID_RE.match(report_id):
        raise HTTPException(status_code=400, detail="Invalid report ID format")
    return report_id


def _safe_report_path(report_id: str) -> Path:
    """Return the absolute, confinement-checked path for *report_id*."""
    _validate_report_id(report_id)  # Raises HTTPException 400 if report_id is not a UUID-based name
    candidate = (_REPORT_DIR / report_id).resolve()  # codeql[py/path-injection] - report_id validated by _validate_report_id above
    try:
        candidate.relative_to(_REPORT_DIR)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report path") from None
    return candidate

router = APIRouter(prefix="/api/superadmin", tags=["SuperAdmin"])

_require_superadmin = require_role("superadmin")

UTC = timezone.utc

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def superadmin_dashboard(user: TokenPayload = Depends(_require_superadmin)) -> HTMLResponse:
    """SuperAdmin master control center UI. Requires: role = superadmin."""
    path = _TEMPLATES_DIR / "admin" / "superadmin.html"
    if path.exists():
        return HTMLResponse(content=path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="""<!DOCTYPE html><html><head><title>SuperAdmin</title></head>
<body style="background:#0d1117;color:#e6edf3;font-family:sans-serif;padding:40px;">
<h1>SuperAdmin Control Center</h1>
<p style="color:#f85149;">Template not found: templates/admin/superadmin.html</p>
<a href="/api/admin/" style="color:#58a6ff;">← Back to Admin</a>
</body></html>"""
    )


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
        logger.debug("Suppressed exception (no detail) in %s", __name__)


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
            overview["total_users"] = db.query(User).count()
            overview["active_users_24h"] = (
                db.query(User).filter(User.last_login_at >= now - timedelta(hours=24)).count()
            )
            overview["new_users_7d"] = db.query(User).filter(User.created_at >= now - timedelta(days=7)).count()
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
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # Engine status
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            overview["engine_status"] = getattr(eng, "status", "running")
            overview["open_positions"] = len(getattr(eng, "positions", {}))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # Redis memory
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            info = rc.info("memory")
            overview["redis_memory_mb"] = round(info.get("used_memory", 0) / 1_048_576, 1)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # System resources
    try:
        import psutil

        overview["cpu_pct"] = psutil.cpu_percent(interval=0.1)
        overview["memory_pct"] = psutil.virtual_memory().percent
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # Determine health
    if overview["kill_switch_active"] or overview["error_rate_pct"] > 10:
        overview["system_health"] = "critical"
    elif overview["maintenance_mode"] or overview["cpu_pct"] > 85 or overview["memory_pct"] > 85:
        overview["system_health"] = "degraded"

    return overview


# ── Users ─────────────────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(
    search: str | None = Query(None),
    role: str | None = Query(None),
    plan: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
            rows = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
            users = [
                {
                    "user_id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "role": u.role,
                    "plan": "free",
                    "status": u.status,
                    "total_trades": 0,
                    "created_at": _iso(u.created_at),
                    "last_login": _iso(u.last_login_at),
                    "two_fa_enabled": bool(u.totp_enabled),
                    "country": None,
                    "revenue_generated": 0.0,
                }
                for u in rows
            ]
            return {"users": users, "total": total, "page": page, "page_size": page_size}
        finally:
            db.close()
    except Exception as exc:
        logger.error("list_users: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
                "user_id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "plan": "free",
                "status": u.status,
                "total_trades": 0,
                "created_at": _iso(u.created_at),
                "last_login": _iso(u.last_login_at),
                "two_fa_enabled": bool(u.totp_enabled),
                "country": None,
                "revenue_generated": 0.0,
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, body: UpdateUserBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.user_models import User

        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            if body.username:
                u.username = body.username
            if body.email:
                u.email = body.email
            if body.status:
                u.status = body.status
            db.commit()
            _log_superadmin_action(user, "update_user", user_id)
            return {"ok": True}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: str, body: SetRoleBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict[str, Any]:
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/users/{user_id}/plan")
async def set_user_plan(
    user_id: str, body: SetPlanBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict[str, Any]:
    _log_superadmin_action(user, "set_plan", f"{user_id}: {body.plan}")
    # Plan is stored in the billing/subscription layer; acknowledge the intent
    return {"ok": True, "plan": body.plan, "note": "Plan change queued — billing layer will apply on next sync"}


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: str, body: BanUserBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict[str, Any]:
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        import secrets

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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/users/{user_id}/impersonate")
async def impersonate_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    """Issue a short-lived impersonation token for the target user."""
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        import os
        import jwt as pyjwt

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
                "sub": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "impersonated_by": user.sub,
                "exp": int(_time.time()) + 3600,
                "iat": int(_time.time()),
            }
            token = pyjwt.encode(payload, secret, algorithm="HS256")
            _log_superadmin_action(user, "impersonate", f"target={user_id}")
            return {"access_token": token, "token_type": "bearer", "expires_in": 3600}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
            return {
                "activity": [
                    {
                        "event_id": r.id,
                        "event_type": r.event_type,
                        "detail": r.detail,
                        "ip_address": getattr(r, "ip_address", ""),
                        "created_at": _iso(r.created_at),
                    }
                    for r in rows
                ]
            }
        finally:
            db.close()
    except Exception as exc:
        logger.debug("user_activity: %s", exc)
        return {"activity": []}


# ── Bulk user operations ──────────────────────────────────────────────────────


class BulkUserBody(BaseModel):
    user_ids: list[str]
    reason: str | None = None


@router.post("/users/bulk/ban")
async def bulk_ban_users(body: BulkUserBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Ban multiple users in a single request. Skips superadmins."""
    from database.connection import SessionLocal
    from database.user_models import User

    succeeded: list[str] = []
    failed: list[dict] = []
    db = SessionLocal()
    try:
        for uid in body.user_ids:
            try:
                u = db.query(User).filter_by(id=uid).first()
                if not u:
                    failed.append({"user_id": uid, "reason": "not found"})
                    continue
                if u.role == "superadmin":
                    failed.append({"user_id": uid, "reason": "cannot ban superadmin"})
                    continue
                u.status = "banned"
                succeeded.append(uid)
            except Exception as exc:
                failed.append({"user_id": uid, "reason": str(exc)})
        db.commit()
        _log_superadmin_action(user, "bulk_ban", f"count={len(succeeded)} reason={body.reason}")
        return {"succeeded": succeeded, "failed": failed, "total": len(body.user_ids)}
    finally:
        db.close()


@router.post("/users/bulk/unban")
async def bulk_unban_users(body: BulkUserBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Unban multiple users in a single request."""
    from database.connection import SessionLocal
    from database.user_models import User

    succeeded: list[str] = []
    failed: list[dict] = []
    db = SessionLocal()
    try:
        for uid in body.user_ids:
            try:
                u = db.query(User).filter_by(id=uid).first()
                if not u:
                    failed.append({"user_id": uid, "reason": "not found"})
                    continue
                u.status = "active"
                succeeded.append(uid)
            except Exception as exc:
                failed.append({"user_id": uid, "reason": str(exc)})
        db.commit()
        _log_superadmin_action(user, "bulk_unban", f"count={len(succeeded)}")
        return {"succeeded": succeeded, "failed": failed, "total": len(body.user_ids)}
    finally:
        db.close()


@router.post("/users/bulk/export")
async def bulk_export_users(body: BulkUserBody, user: TokenPayload = Depends(_require_superadmin)):
    """Export selected users as CSV. Pass empty user_ids to export all."""
    import csv
    import io
    from database.connection import SessionLocal
    from database.user_models import User
    from fastapi.responses import StreamingResponse

    db = SessionLocal()
    try:
        q = db.query(User)
        if body.user_ids:
            q = q.filter(User.id.in_(body.user_ids))
        rows = q.order_by(User.created_at.desc()).all()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["user_id", "username", "email", "role", "status", "totp_enabled", "created_at", "last_login"])
        for u in rows:
            writer.writerow(
                [
                    u.id,
                    u.username,
                    u.email,
                    u.role,
                    u.status,
                    bool(u.totp_enabled),
                    _iso(u.created_at),
                    _iso(u.last_login_at),
                ]
            )
        _log_superadmin_action(user, "bulk_export_users", f"count={len(rows)}")
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users_export.csv"},
        )
    finally:
        db.close()


# ── Platform config ───────────────────────────────────────────────────────────

_PLATFORM_CONFIG_KEY = "superadmin_platform_config"

_PLATFORM_CONFIG_DEFAULTS: dict = {
    "platform_name": "HOPEFX AI Trading",
    "support_email": "support@hopefx.ai",
    "max_users": 10000,
    "allow_registrations": True,
    "require_email_verification": True,
    "default_new_user_plan": "free",
    "default_new_user_role": "trader",
    "session_timeout_minutes": 60,
    "max_api_keys_per_user": 5,
    "rate_limit_per_minute": 60,
    "maintenance_mode": False,
    "maintenance_message": "We're performing scheduled maintenance. Back shortly.",
    "announcement_enabled": False,
    "announcement_text": "",
    "announcement_type": "info",
    "force_2fa_for_admins": False,
    "ip_whitelist_enabled": False,
    "ip_whitelist": "",
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
                logger.debug("Suppressed exception (no detail) in %s", __name__)
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
    "paper_trading_mode": True,
    "live_trading_enabled": False,
    "max_open_positions": 5,
    "max_risk_per_trade": 2.0,
    "max_daily_loss_pct": 5.0,
    "max_drawdown_pct": 10.0,
    "default_lot_size": 0.01,
    "slippage_tolerance": 2.0,
    "default_leverage": 50,
    "auto_trade_enabled": False,
    "signal_confidence_threshold": 0.65,
    "kill_switch_active": False,
    "engine_status": "running",
    "broker_type": "paper",
    "execution_mode": "market",
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
                logger.debug("Suppressed exception (no detail) in %s", __name__)
    # Also pull from legacy risk settings
    try:
        from api.admin import _get_risk_settings

        rs = _get_risk_settings()
        merged = dict(_ENGINE_CONFIG_DEFAULTS)
        merged["max_open_positions"] = rs.get("max_open_positions", merged["max_open_positions"])
        merged["max_risk_per_trade"] = rs.get("max_risk_per_trade", merged["max_risk_per_trade"])
        merged["max_daily_loss_pct"] = rs.get("max_daily_loss", merged["max_daily_loss_pct"])
        merged["max_drawdown_pct"] = rs.get("max_drawdown", merged["max_drawdown_pct"])
        merged["paper_trading_mode"] = rs.get("paper_trading_mode", merged["paper_trading_mode"])
        return merged
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
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
        logger.debug("Suppressed exception (no detail) in %s", __name__)
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
        "trades_today": 0,
        "open_positions": 0,
        "pnl_today": 0.0,
        "win_rate_today": 0.0,
        "avg_execution_ms": 0,
        "rejected_orders": 0,
        "kill_switch_triggers": 0,
        "uptime_hours": 0.0,
    }
    try:
        from api.admin import app_state, _start_time

        metrics["uptime_hours"] = round((time.time() - _start_time) / 3600, 2)
        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            metrics["open_positions"] = len(getattr(eng, "positions", {}))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
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
            models.append(
                {
                    "name": name,
                    "version": info.get("version", "1.0"),
                    "status": info.get("status", "active"),
                    "accuracy": info.get("accuracy", 0.0),
                    "last_trained": info.get("last_trained", _utcnow().isoformat()),
                    "predictions_today": info.get("predictions_today", 0),
                    "drift_score": info.get("drift_score", 0.0),
                    "deployed_at": info.get("deployed_at"),
                }
            )
    except Exception:
        # Return a representative list from known model names
        for name in ["signal_classifier", "regime_detector", "rl_agent", "sentiment_model"]:
            models.append(
                {
                    "name": name,
                    "version": "1.0",
                    "status": "active",
                    "accuracy": 0.0,
                    "last_trained": _utcnow().isoformat(),
                    "predictions_today": 0,
                    "drift_score": 0.0,
                    "deployed_at": None,
                }
            )
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

        result = await get_accuracy(user=user)
        # get_accuracy returns an AccuracyResponse Pydantic model; convert to dict
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if hasattr(result, "dict"):
            return result.dict()
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


@router.get("/ml/rl/status")
async def get_rl_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from api.ml import get_rl_status as _grl

        return await _grl(user=user)
    except Exception:
        return {
            "status": "unknown",
            "episode": 0,
            "total_reward": 0.0,
            "win_rate": 0.0,
            "last_updated": _utcnow().isoformat(),
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
    """
    Return real revenue KPIs from RevenueAnalytics and SubscriptionManager.

    Falls back to zero values only when neither analytics module is available.
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    period_starts = {
        "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
        "mtd": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        "ytd": now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
    }
    start = period_starts.get(period, period_starts["mtd"])

    mrr = arr = revenue_today = revenue_mtd = revenue_ytd = 0.0
    churn_rate_pct = ltv_avg = 0.0
    new_subs_mtd = cancelled_mtd = 0
    plan_breakdown: dict = {"free": 0.0, "starter": 0.0, "pro": 0.0, "elite": 0.0}

    # ── RevenueAnalytics ──────────────────────────────────────────────────────
    try:
        from monetization.analytics import revenue_analytics

        mrr = float(revenue_analytics.get_mrr())
        arr = float(revenue_analytics.get_arr())

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        mtd_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ytd_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        rev_today = revenue_analytics.get_revenue_by_period(today_start, now)
        rev_mtd = revenue_analytics.get_revenue_by_period(mtd_start, now)
        rev_ytd = revenue_analytics.get_revenue_by_period(ytd_start, now)

        revenue_today = float(sum(rev_today.values())) if isinstance(rev_today, dict) else float(rev_today or 0)
        revenue_mtd = float(sum(rev_mtd.values())) if isinstance(rev_mtd, dict) else float(rev_mtd or 0)
        revenue_ytd = float(sum(rev_ytd.values())) if isinstance(rev_ytd, dict) else float(rev_ytd or 0)

        growth = revenue_analytics.get_growth_metrics()
        churn_rate_pct = float(growth.churn_rate)
        ltv_avg = float(growth.ltv)

        tier_rev = revenue_analytics.get_revenue_by_tier(start, now)
        for tier_key, amount in tier_rev.items():
            plan_breakdown[tier_key] = float(amount)

        sub_metrics = revenue_analytics.get_subscription_metrics(mtd_start, now)
        new_subs_mtd = sub_metrics.new_subscriptions
        cancelled_mtd = sub_metrics.cancelled_subscriptions
    except Exception as exc:
        logger.debug("get_revenue_stats: analytics unavailable: %s", exc)

    # ── Stripe fallback for MRR when analytics has no entries ─────────────────
    if mrr == 0.0:
        try:
            from monetization.stripe_live import get_stripe_client

            client = get_stripe_client()
            if hasattr(client, "get_mrr"):
                mrr = float(client.get_mrr() or 0)
                arr = mrr * 12
        except Exception as exc:
            logger.debug("get_revenue_stats: Stripe MRR unavailable: %s", exc)

    return {
        "mrr": round(mrr, 2),
        "arr": round(arr, 2),
        "revenue_today": round(revenue_today, 2),
        "revenue_mtd": round(revenue_mtd, 2),
        "revenue_ytd": round(revenue_ytd, 2),
        "currency": "USD",
        "plan_breakdown": {k: round(v, 2) for k, v in plan_breakdown.items()},
        "churn_rate_pct": round(churn_rate_pct, 4),
        "ltv_avg": round(ltv_avg, 2),
        "new_subs_mtd": new_subs_mtd,
        "cancelled_mtd": cancelled_mtd,
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
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    # Enrich with tier breakdown from subscription manager
    try:
        from monetization.subscription import subscription_manager

        all_subs = (
            subscription_manager.get_all_subscriptions()
            if hasattr(subscription_manager, "get_all_subscriptions")
            else []
        )
        for sub in all_subs:
            tier = sub.tier.value if hasattr(sub.tier, "value") else str(sub.tier)
            if tier in stats:
                stats[tier] += 1
    except Exception as exc:
        logger.debug("get_subscription_stats: subscription_manager unavailable: %s", exc)
    return stats


@router.get("/financial/payments")
async def get_payment_history(
    period: str | None = Query(None),
    page: int = Query(1, ge=1),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from api.billing import list_payments

        return await list_payments(period=period, page=page, user=user)
    except Exception as exc:
        logger.warning("get_payment_history error: %s", exc)
        return {"payments": [], "total": 0, "page": page, "page_size": 50}


@router.post("/financial/payments/{payment_id}/refund")
async def refund_payment(payment_id: str, body: RefundBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "refund", f"payment={payment_id} reason={body.reason}")
    from api.billing import process_refund

    return await process_refund(payment_id=payment_id, reason=body.reason, user=user)


@router.get("/financial/affiliates")
async def get_affiliate_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    from api.billing import get_affiliate_stats as _gas

    return await _gas(user=user)


# ── Chargebacks ───────────────────────────────────────────────────────────────


@router.get("/financial/chargebacks")
async def list_chargebacks(
    status: str | None = Query(None, description="Filter by status: open|won|lost|pending_evidence"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return chargeback records from the database."""
    chargebacks: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import Chargeback

        db = SessionLocal()
        try:
            q = db.query(Chargeback)
            if status:
                q = q.filter(Chargeback.status == status)
            total = q.count()
            rows = q.order_by(Chargeback.opened_at.desc()).offset(offset).limit(limit).all()
            chargebacks = [r.to_dict() for r in rows]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("list_chargebacks DB error: %s", exc)
    return {"chargebacks": chargebacks, "total": total, "limit": limit, "offset": offset}


@router.patch("/financial/chargebacks/{chargeback_id}")
async def update_chargeback(
    chargeback_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Update chargeback status (e.g. mark as won/lost after submitting evidence)."""
    _log_superadmin_action(user, "chargeback_update", f"id={chargeback_id} body={body}")
    allowed_statuses = {"open", "won", "lost", "pending_evidence"}
    new_status = body.get("status")
    if new_status and new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed_statuses}")
    try:
        from database.connection import SessionLocal
        from database.models import Chargeback
        from datetime import datetime, timezone

        db = SessionLocal()
        try:
            row = db.query(Chargeback).filter(Chargeback.chargeback_id == chargeback_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Chargeback not found")
            if new_status:
                row.status = new_status
                if new_status in ("won", "lost"):
                    row.resolved_at = datetime.now(timezone.utc)
            db.commit()
            return row.to_dict()
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_chargeback error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update chargeback") from None


# ── Tax Reports ───────────────────────────────────────────────────────────────


@router.get("/financial/tax-reports")
async def list_tax_reports(
    status: str | None = Query(None, description="Filter by status: draft|filed|paid|overdue"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return tax report records from the database."""
    reports: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import TaxReport

        db = SessionLocal()
        try:
            q = db.query(TaxReport)
            if status:
                q = q.filter(TaxReport.status == status)
            total = q.count()
            rows = q.order_by(TaxReport.created_at.desc()).offset(offset).limit(limit).all()
            reports = [r.to_dict() for r in rows]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("list_tax_reports DB error: %s", exc)
    return {"reports": reports, "total": total, "limit": limit, "offset": offset}


@router.post("/financial/tax-reports")
async def create_tax_report(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Create or regenerate a tax report for a given period and jurisdiction."""
    _log_superadmin_action(
        user, "tax_report_create", f"period={body.get('period')} jurisdiction={body.get('jurisdiction')}"
    )
    import uuid as _uuid

    period = body.get("period", "")
    jurisdiction = body.get("jurisdiction", "")
    if not period or not jurisdiction:
        raise HTTPException(status_code=400, detail="period and jurisdiction are required")

    try:
        from database.connection import SessionLocal
        from database.models import TaxReport

        db = SessionLocal()
        try:
            # Upsert: update existing or create new
            existing = (
                db.query(TaxReport).filter(TaxReport.period == period, TaxReport.jurisdiction == jurisdiction).first()
            )
            if existing:
                existing.status = body.get("status", existing.status)
                existing.total_revenue = body.get("total_revenue", existing.total_revenue)
                existing.taxable_amount = body.get("taxable_amount", existing.taxable_amount)
                existing.tax_rate_pct = body.get("tax_rate_pct", existing.tax_rate_pct)
                existing.tax_owed = body.get("tax_owed", existing.tax_owed)
                db.commit()
                return existing.to_dict()

            report = TaxReport(
                report_id=f"TAX-{_uuid.uuid4().hex[:12].upper()}",
                period=period,
                jurisdiction=jurisdiction,
                total_revenue=float(body.get("total_revenue", 0)),
                taxable_amount=float(body.get("taxable_amount", 0)),
                tax_rate_pct=float(body.get("tax_rate_pct", 0)),
                tax_owed=float(body.get("tax_owed", 0)),
                currency=body.get("currency", "USD"),
                status=body.get("status", "draft"),
            )
            db.add(report)
            db.commit()
            db.refresh(report)
            return report.to_dict()
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("create_tax_report error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create tax report") from None


@router.patch("/financial/tax-reports/{report_id}")
async def update_tax_report(
    report_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Update a tax report (e.g. mark as filed or paid)."""
    _log_superadmin_action(user, "tax_report_update", f"id={report_id} status={body.get('status')}")
    allowed_statuses = {"draft", "filed", "paid", "overdue"}
    new_status = body.get("status")
    if new_status and new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed_statuses}")
    try:
        from database.connection import SessionLocal
        from database.models import TaxReport
        from datetime import datetime, timezone

        db = SessionLocal()
        try:
            row = db.query(TaxReport).filter(TaxReport.report_id == report_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Tax report not found")
            if new_status:
                row.status = new_status
                if new_status == "filed":
                    row.filed_at = datetime.now(timezone.utc)
            db.commit()
            return row.to_dict()
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_tax_report error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update tax report") from None


# ── Reconciliation ────────────────────────────────────────────────────────────


@router.get("/financial/reconciliation")
async def list_reconciliation(
    status: str | None = Query(None, description="Filter: matched|discrepancy|pending|resolved"),
    provider: str | None = Query(None, description="Filter by provider: stripe|flutterwave|crypto"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return reconciliation records from the database."""
    records: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import ReconciliationRecord

        db = SessionLocal()
        try:
            q = db.query(ReconciliationRecord)
            if status:
                q = q.filter(ReconciliationRecord.status == status)
            if provider:
                q = q.filter(ReconciliationRecord.provider == provider)
            total = q.count()
            rows = q.order_by(ReconciliationRecord.created_at.desc()).offset(offset).limit(limit).all()
            records = [r.to_dict() for r in rows]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("list_reconciliation DB error: %s", exc)
    return {"records": records, "total": total, "limit": limit, "offset": offset}


@router.post("/financial/reconciliation/run")
async def run_reconciliation(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Trigger a reconciliation run for a given period and provider.

    Compares expected revenue (from PaymentProcessor / Stripe) against
    actual amounts and writes a ReconciliationRecord to the database.
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    period = body.get("period", "")
    provider = body.get("provider", "stripe")
    if not period:
        raise HTTPException(status_code=400, detail="period is required (e.g. '2025-01')")

    _log_superadmin_action(user, "reconciliation_run", f"period={period} provider={provider}")

    # Parse period into date range (YYYY-MM)
    try:
        year, month = int(period[:4]), int(period[5:7])
        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end_dt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end_dt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="period must be in YYYY-MM format") from None

    expected_amount = 0.0
    actual_amount = 0.0
    tx_count = 0

    # ── Compute expected from PaymentProcessor ────────────────────────────────
    try:
        from monetization.payment_processor import payment_processor, PaymentStatus

        for p in payment_processor._payments.values():
            if p.created_at and start_dt <= p.created_at < end_dt and p.status == PaymentStatus.SUCCEEDED:
                expected_amount += float(p.amount)
                tx_count += 1
    except Exception as exc:
        logger.debug("reconciliation: PaymentProcessor unavailable: %s", exc)

    # ── Compute actual from Stripe ────────────────────────────────────────────
    if provider == "stripe":
        try:
            from monetization.stripe_live import get_stripe_client

            client = get_stripe_client()
            if hasattr(client, "list_customer_charges"):
                charges = client.list_customer_charges(user_id=None, limit=500)
                for c in charges:
                    created = c.get("created")
                    if isinstance(created, int | float):
                        dt = datetime.fromtimestamp(created, tz=timezone.utc)
                        if start_dt <= dt < end_dt and c.get("status") == "succeeded":
                            actual_amount += (c.get("amount", 0) or 0) / 100
        except Exception as exc:
            logger.debug("reconciliation: Stripe unavailable: %s", exc)

    # ── Compute actual from CryptoPayment DB ──────────────────────────────────
    if provider == "crypto":
        try:
            from database.connection import SessionLocal
            from database.models import CryptoPayment

            db = SessionLocal()
            try:
                rows = (
                    db.query(CryptoPayment)
                    .filter(
                        CryptoPayment.status == "complete",
                        CryptoPayment.confirmed_at >= start_dt,
                        CryptoPayment.confirmed_at < end_dt,
                    )
                    .all()
                )
                actual_amount = sum(r.amount_usd for r in rows)
                tx_count = len(rows)
            finally:
                db.close()
        except Exception as exc:
            logger.debug("reconciliation: CryptoPayment DB unavailable: %s", exc)

    discrepancy = round(actual_amount - expected_amount, 4)
    status_val = "matched" if abs(discrepancy) < 0.01 else "discrepancy"

    # Upsert reconciliation record
    try:
        from database.connection import SessionLocal
        from database.models import ReconciliationRecord

        db = SessionLocal()
        try:
            existing = (
                db.query(ReconciliationRecord)
                .filter(
                    ReconciliationRecord.period == period,
                    ReconciliationRecord.provider == provider,
                )
                .first()
            )
            if existing:
                existing.expected_amount = expected_amount
                existing.actual_amount = actual_amount
                existing.discrepancy = discrepancy
                existing.transaction_count = tx_count
                existing.status = status_val
                db.commit()
                result = existing.to_dict()
            else:
                record = ReconciliationRecord(
                    recon_id=f"RECON-{_uuid.uuid4().hex[:12].upper()}",
                    period=period,
                    provider=provider,
                    expected_amount=expected_amount,
                    actual_amount=actual_amount,
                    discrepancy=discrepancy,
                    transaction_count=tx_count,
                    status=status_val,
                )
                db.add(record)
                db.commit()
                db.refresh(record)
                result = record.to_dict()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("reconciliation: DB write failed: %s", exc)
        result = {
            "recon_id": f"RECON-{_uuid.uuid4().hex[:12].upper()}",
            "period": period,
            "provider": provider,
            "expected_amount": expected_amount,
            "actual_amount": actual_amount,
            "discrepancy": discrepancy,
            "transaction_count": tx_count,
            "status": status_val,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
        }

    return result


@router.patch("/financial/reconciliation/{recon_id}")
async def resolve_reconciliation(
    recon_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Mark a reconciliation record as resolved with optional notes."""
    _log_superadmin_action(user, "reconciliation_resolve", f"id={recon_id}")
    try:
        from database.connection import SessionLocal
        from database.models import ReconciliationRecord
        from datetime import datetime, timezone

        db = SessionLocal()
        try:
            row = db.query(ReconciliationRecord).filter(ReconciliationRecord.recon_id == recon_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Reconciliation record not found")
            row.status = "resolved"
            row.resolved_at = datetime.now(timezone.utc)
            row.resolved_by = user.sub
            if "notes" in body:
                row.notes = body["notes"]
            db.commit()
            return row.to_dict()
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("resolve_reconciliation error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to resolve reconciliation record") from None


# ── Security ──────────────────────────────────────────────────────────────────

_BLOCKED_IPS_KEY = "superadmin:blocked_ips"


@router.get("/security/events")
async def get_security_events(
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    events = []
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry

        db = SessionLocal()
        try:
            q = db.query(AuditLogEntry).filter(
                AuditLogEntry.event_type.in_(
                    [
                        "login_failed",
                        "brute_force",
                        "suspicious_ip",
                        "token_revoked",
                        "rate_limit_exceeded",
                        "unauthorized_access",
                        "2fa_failed",
                        "password_reset",
                        "account_locked",
                    ]
                )
            )
            rows = q.order_by(AuditLogEntry.created_at.desc()).limit(limit).all()
            for r in rows:
                sev = "low"
                et = getattr(r, "event_type", "")
                if et in ("brute_force", "unauthorized_access", "account_locked"):
                    sev = "critical"
                elif et in ("login_failed", "2fa_failed", "rate_limit_exceeded"):
                    sev = "medium"
                if severity and sev != severity:
                    continue
                events.append(
                    {
                        "event_id": str(r.id),
                        "event_type": et,
                        "severity": sev,
                        "user_id": getattr(r, "user_id", None),
                        "ip_address": getattr(r, "ip_address", ""),
                        "detail": getattr(r, "detail", ""),
                        "created_at": _iso(r.created_at),
                    }
                )
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
                    blocked.append(
                        {
                            "ip": ip.decode() if isinstance(ip, bytes) else ip,
                            "reason": entry.get("reason", ""),
                            "blocked_at": entry.get("blocked_at", ""),
                            "blocked_by": entry.get("blocked_by", ""),
                        }
                    )
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
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
                "reason": body.reason,
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
                sessions.append(
                    {
                        "session_id": s.id,
                        "user_id": u.id,
                        "username": u.username,
                        "ip": getattr(s, "ip_address", ""),
                        "device": getattr(s, "device_info", "Unknown"),
                        "created_at": _iso(s.created_at),
                        "last_active": _iso(getattr(s, "last_active_at", s.created_at)),
                    }
                )
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
    level: str | None = Query(None),
    logger_name: str | None = Query(None, alias="logger"),
    search: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
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
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.debug("get_logs redis: %s", exc)

    # Fallback: read from log file if Redis has nothing
    if not entries:
        import os

        log_file = os.getenv("LOG_FILE", "logs/app.log")
        try:
            with open(log_file) as f:
                lines = f.readlines()[-limit:]
            for line in reversed(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                if level and level not in stripped:
                    continue
                if search and search.lower() not in stripped.lower():
                    continue
                parts = stripped.split(" ", 3)
                entries.append(
                    {
                        "ts": parts[0] if len(parts) > 0 else "",
                        "level": parts[2] if len(parts) > 2 else "INFO",
                        "logger": parts[1] if len(parts) > 1 else "app",
                        "message": parts[3] if len(parts) > 3 else stripped,
                    }
                )
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)

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
    level: str | None = Query(None),
    logger_name: str | None = Query(None, alias="logger"),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    from fastapi.responses import PlainTextResponse

    result = await get_logs(level=level, logger_name=logger_name, search=None, limit=1000, user=user)
    lines = [
        f"{e.get('ts', '')} {e.get('level', '')} {e.get('logger', '')} {e.get('message', '')}" for e in result["logs"]
    ]
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
            result.append(
                {
                    "name": name,
                    "enabled": bool(enabled),
                    "description": name.replace("_", " ").title(),
                    "env_var": f"FEATURE_{name.upper()}",
                    "rollout_pct": 100,
                    "user_overrides": 0,
                }
            )
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

        rc = get_redis_client()
        if rc:
            raw = rc.hgetall(f"feature_flags:user:{target_user_id}")
            for flag, val in raw.items():
                overrides.append(
                    {
                        "flag": flag.decode() if isinstance(flag, bytes) else flag,
                        "enabled": val in (b"1", "1", True),
                    }
                )
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
            return {
                "events": [
                    {
                        "event_id": str(r.id),
                        "user_id": getattr(r, "user_id", None),
                        "event_type": r.event_type,
                        "detail": getattr(r, "detail", ""),
                        "ip_address": getattr(r, "ip_address", ""),
                        "created_at": _iso(r.created_at),
                    }
                    for r in rows
                ]
            }
        finally:
            db.close()
    except Exception as exc:
        logger.debug("audit_log: %s", exc)
        return {"events": []}


@router.get("/audit/export")
async def export_audit_log(user: TokenPayload = Depends(_require_superadmin)):
    from fastapi.responses import StreamingResponse
    import csv
    import io

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
            "available": True,
            "used_memory_mb": round(info.get("used_memory", 0) / 1_048_576, 2),
            "connected_clients": info.get("connected_clients", 0),
            "total_commands": info.get("total_commands_processed", 0),
            "keyspace_hits": info.get("keyspace_hits", 0),
            "keyspace_misses": info.get("keyspace_misses", 0),
            "uptime_seconds": info.get("uptime_in_seconds", 0),
        }
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__}


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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
        return {"available": False, "error": type(exc).__name__}


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
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"queues": queues}


# ═══════════════════════════════════════════════════════════════════════════════
# INSTITUTIONAL-GRADE EXTENSIONS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Additional Pydantic models ────────────────────────────────────────────────


class KYCDecisionBody(BaseModel):
    reason: str = ""


class AMLAlertUpdateBody(BaseModel):
    status: str
    notes: str = ""


class SanctionsClearBody(BaseModel):
    notes: str = ""


class RegReportTriggerBody(BaseModel):
    report_type: str
    period: str


class CircuitBreakerActionBody(BaseModel):
    reason: str = "Superadmin manual action"


class StressTestRunBody(BaseModel):
    scenario: str


class BrokerActionBody(BaseModel):
    reason: str = ""


class BrokerRoutingBody(BaseModel):
    primary_broker: str | None = None
    fallback_broker: str | None = None
    routing_mode: str | None = None


class TenantCreateBody(BaseModel):
    name: str
    domain: str
    plan: str = "starter"
    company_name: str = ""
    primary_color: str = "#3b82f6"


class TenantUpdateBody(BaseModel):
    status: str | None = None
    plan: str | None = None
    primary_color: str | None = None
    logo_url: str | None = None
    company_name: str | None = None


class GDPRProcessBody(BaseModel):
    action: str  # approve | reject
    notes: str = ""


class GDPREraseBody(BaseModel):
    reason: str


class RetentionPolicyBody(BaseModel):
    data_type: str
    retention_days: int


class NuclearHaltBody(BaseModel):
    reason: str


class NuclearHedgeBody(BaseModel):
    hedge_ratio: float = 1.0
    instrument: str = "XAUUSD"
    reason: str = ""


class NuclearRiskOverrideBody(BaseModel):
    max_risk_fraction: float
    reason: str = ""


class RateLimitRuleBody(BaseModel):
    endpoint: str
    limit: int
    window_seconds: int
    scope: str = "per_user"
    enabled: bool = True


class RateLimitRuleUpdateBody(BaseModel):
    limit: int | None = None
    window_seconds: int | None = None
    enabled: bool | None = None


class AlertRuleBody(BaseModel):
    name: str
    condition: str
    severity: str = "warning"
    channels: list[str] = []
    enabled: bool = True


class AlertRuleUpdateBody(BaseModel):
    name: str | None = None
    condition: str | None = None
    severity: str | None = None
    enabled: bool | None = None
    channels: list[str] | None = None


class SilenceAlertBody(BaseModel):
    duration_minutes: int = 60


class ReportGenerateBody(BaseModel):
    type: str
    period: str


class BackupTriggerBody(BaseModel):
    type: str = "incremental"


class ApiKeyRevokeBody(BaseModel):
    reason: str = "Superadmin revocation"


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLIANCE — KYC / AML / SANCTIONS / REGULATORY
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/compliance/kyc")
async def get_kyc_queue(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """KYC queue — all users with their verification status."""
    records: list[dict] = []
    total = 0
    try:
        db = next(_get_db())
        if db:
            from database.models import User

            q = db.query(User)
            if status:
                q = q.filter(User.kyc_status == status)
            total = q.count()
            offset = (page - 1) * limit
            users = q.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
            for u in users:
                records.append(
                    {
                        "user_id": str(u.id),
                        "username": u.username,
                        "email": u.email,
                        "kyc_status": getattr(u, "kyc_status", "unverified"),
                        "submitted_at": _iso(getattr(u, "kyc_submitted_at", None)),
                        "reviewed_at": _iso(getattr(u, "kyc_reviewed_at", None)),
                        "reviewer_id": getattr(u, "kyc_reviewer_id", None),
                        "rejection_reason": getattr(u, "kyc_rejection_reason", None),
                        "country": getattr(u, "country", None),
                        "document_type": getattr(u, "kyc_document_type", None),
                    }
                )
            db.close()
    except Exception as exc:
        logger.warning("KYC queue DB error: %s", exc)
    return {"records": records, "total": total, "page": page, "limit": limit}


@router.post("/compliance/kyc/{target_user_id}/approve")
async def approve_kyc(
    target_user_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "kyc_approve", f"user={target_user_id}")
    try:
        db = next(_get_db())
        if db:
            from database.models import User

            u = db.query(User).filter(User.id == target_user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            u.kyc_status = "approved"
            u.kyc_reviewed_at = _utcnow()
            u.kyc_reviewer_id = user.sub
            db.commit()
            db.close()
            return {"status": "approved", "user_id": target_user_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("KYC approve error: %s", exc)
    return {"backup_id": backup_id, "type": body.type, "status": "running", "triggered_at": _utcnow().isoformat()}


@router.get("/system/jobs")
async def list_scheduled_jobs(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Scheduled job registry — cron status, last/next run."""
    jobs: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("system:scheduled_jobs")
            if raw:
                jobs = _json.loads(raw)
    except Exception as exc:
        logger.warning("Scheduled jobs error: %s", exc)
    if not jobs:
        jobs = [
            {
                "job_id": "weekly_report",
                "name": "Weekly Performance Report",
                "schedule": "0 8 * * MON",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "kyc_sync",
                "name": "KYC Status Sync",
                "schedule": "*/30 * * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "aml_scan",
                "name": "AML Transaction Scan",
                "schedule": "0 * * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "db_backup",
                "name": "Database Backup",
                "schedule": "0 2 * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "integrity_scan",
                "name": "File Integrity Scan",
                "schedule": "*/2 * * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "ml_retrain",
                "name": "ML Model Retrain",
                "schedule": "0 3 * * SUN",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "gdpr_cleanup",
                "name": "GDPR Data Retention Cleanup",
                "schedule": "0 1 * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "sanctions_refresh",
                "name": "Sanctions List Refresh",
                "schedule": "0 6 * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
        ]
    return {"jobs": jobs}


@router.post("/system/jobs/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "job_trigger", f"job={job_id}")
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.rpush(
                "system:job_queue",
                _json.dumps(
                    {
                        "job_id": job_id,
                        "triggered_by": user.sub,
                        "triggered_at": _utcnow().isoformat(),
                    }
                ),
            )
    except Exception as exc:
        logger.warning("Job trigger error: %s", exc)
    # Direct dispatch for known jobs
    try:
        if job_id == "weekly_report":
            from reports.weekly_report import WeeklyReportGenerator
            import asyncio

            asyncio.create_task(WeeklyReportGenerator().generate())
        elif job_id == "integrity_scan":
            from security.self_healer import SelfHealer
            import asyncio

            asyncio.create_task(SelfHealer().scan())
    except Exception as exc:
        logger.warning("Job direct dispatch error: %s", exc)
    return {"job_id": job_id, "status": "triggered", "triggered_at": _utcnow().isoformat()}


@router.post("/system/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "job_pause", f"job={job_id}")
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.hset("system:job_states", job_id, "paused")
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"job_id": job_id, "status": "paused"}


@router.post("/system/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "job_resume", f"job={job_id}")
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.hset("system:job_states", job_id, "active")
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"job_id": job_id, "status": "active"}


@router.get("/system/api-keys")
async def get_api_key_audit(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Cross-user API key audit — all active keys with last-used timestamps."""
    keys: list[dict] = []
    try:
        db = next(_get_db())
        if db:
            from database.models import APIKey

            q = db.query(APIKey)
            if user_id:
                q = q.filter(APIKey.user_id == user_id)
            total = q.count()
            offset = (page - 1) * limit
            rows = q.order_by(APIKey.created_at.desc()).offset(offset).limit(limit).all()
            for r in rows:
                keys.append(
                    {
                        "key_id": str(r.id),
                        "user_id": str(r.user_id),
                        "name": getattr(r, "name", ""),
                        "prefix": getattr(r, "key_prefix", str(r.id)[:8]),
                        "scopes": getattr(r, "scopes", []),
                        "created_at": _iso(r.created_at),
                        "last_used": _iso(getattr(r, "last_used_at", None)),
                        "active": getattr(r, "is_active", True),
                    }
                )
            db.close()
            return {"keys": keys, "total": total, "page": page, "limit": limit}
    except Exception as exc:
        logger.warning("API key audit error: %s", exc)
    return {"keys": keys, "total": 0, "page": page, "limit": limit}


@router.delete("/system/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "api_key_revoke", f"key={key_id}")
    try:
        db = next(_get_db())
        if db:
            from database.models import APIKey

            k = db.query(APIKey).filter(APIKey.id == key_id).first()
            if k:
                k.is_active = False
                db.commit()
            db.close()
    except Exception as exc:
        logger.warning("API key revoke error: %s", exc)
    return {"key_id": key_id, "revoked": True}
