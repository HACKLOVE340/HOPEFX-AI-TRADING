# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin users sub-router."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.auth import TokenPayload

from ._shared import (
    BanUserBody,
    BulkUserBody,
    SetPlanBody,
    SetRoleBody,
    UpdateUserBody,
    _iso,
    _log_superadmin_action,
    _require_superadmin,
)

logger = logging.getLogger(__name__)

router = APIRouter()

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
        import secrets

        from database.connection import SessionLocal
        from database.user_models import User

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
        import os
        import time as _time

        import jwt as pyjwt

        from database.connection import SessionLocal
        from database.user_models import User

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

    db = SessionLocal()
    try:
        q = db.query(User)
        if body.user_ids:
            q = q.filter(User.id.in_(body.user_ids))
        rows = q.order_by(User.created_at.desc()).all()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["user_id", "username", "email", "role", "status", "totp_enabled", "created_at", "last_login"]
        )
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
