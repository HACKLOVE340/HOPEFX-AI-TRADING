# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin users sub-router."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func

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
from api.error_details import safe_error

logger = logging.getLogger(__name__)

# Module-level imports so tests can patch "api.superadmin.users.SessionLocal"
# and "api.superadmin.users.User" without needing to reach into database.*
try:
    from database.connection import SessionLocal
    from database.user_models import User
    from database.models import Account, Trade, WalletTransaction, AuditLogEntry
except Exception:  # pragma: no cover — database package absent in unit-test venv
    SessionLocal = None  # type: ignore[assignment,misc]
    User = None  # type: ignore[assignment,misc]
    Account = Trade = WalletTransaction = AuditLogEntry = None  # type: ignore[assignment,misc]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _user_stats(db, user_id: str) -> dict:
    """Return real trade count and revenue for a user.

    Join path: users.id (str) → accounts.user_id (int, cast) → trades.account_id.
    Revenue is the sum of wallet deposits (WalletTransaction.amount where
    transaction_type='deposit') which is the authoritative revenue figure
    available without a broker connection.  Trade P&L (Trade.total_pnl) is
    summed separately and returned as realized_pnl.
    """

    # Accounts belonging to this user (cast str UUID → int for the FK join)
    try:
        uid_int = int(user_id)
    except (ValueError, TypeError):
        uid_int = None

    total_trades = 0
    revenue_generated = 0.0

    if uid_int is not None:
        # Count all trades across all accounts owned by this user
        account_ids = [row[0] for row in db.query(Account.id).filter(Account.user_id == uid_int).all()]
        if account_ids:
            total_trades = db.query(func.count(Trade.id)).filter(Trade.account_id.in_(account_ids)).scalar() or 0  # pylint: disable=not-callable
            revenue_generated = (
                db.query(func.coalesce(func.sum(Trade.total_pnl), 0.0))  # pylint: disable=not-callable
                .filter(Trade.account_id.in_(account_ids))
                .scalar()
                or 0.0
            )

    # Wallet deposits as an additional revenue signal (user_id is String here)
    wallet_deposits = (
        db.query(func.coalesce(func.sum(WalletTransaction.amount), 0.0))  # pylint: disable=not-callable
        .filter(
            WalletTransaction.user_id == user_id,
            WalletTransaction.transaction_type == "deposit",
            WalletTransaction.status == "completed",
        )
        .scalar()
        or 0.0
    )

    return {
        "total_trades": int(total_trades),
        # Revenue = realised P&L + confirmed deposits (gross inflow)
        "revenue_generated": round(float(revenue_generated) + float(wallet_deposits), 2),
    }


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
        db = SessionLocal()
        try:
            q = db.query(User)
            if search:
                like = f"%{search}%"
                q = q.filter((User.username.ilike(like)) | (User.email.ilike(like)))
            if role:
                q = q.filter(User.role == role)
            if plan:
                q = q.filter(User.plan == plan)
            if status:
                q = q.filter(User.status == status)
            total = q.count()
            rows = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
            users = []
            for u in rows:
                stats = _user_stats(db, u.id)
                users.append(
                    {
                        "user_id": u.id,
                        "username": u.username,
                        "email": u.email,
                        "role": u.role,
                        "plan": u.plan,
                        "status": u.status,
                        "total_trades": stats["total_trades"],
                        "created_at": _iso(u.created_at),
                        "last_login": _iso(u.last_login_at),
                        "two_fa_enabled": bool(u.totp_enabled),
                        "country": u.country,
                        "revenue_generated": stats["revenue_generated"],
                    }
                )
            return {"users": users, "total": total, "page": page, "page_size": page_size}
        finally:
            db.close()
    except Exception as exc:
        logger.error("list_users: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.get("/users/{user_id}")
async def get_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            stats = _user_stats(db, u.id)
            return {
                "user_id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "plan": u.plan,
                "status": u.status,
                "total_trades": stats["total_trades"],
                "created_at": _iso(u.created_at),
                "last_login": _iso(u.last_login_at),
                "two_fa_enabled": bool(u.totp_enabled),
                "country": u.country,
                "revenue_generated": stats["revenue_generated"],
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, body: UpdateUserBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict[str, Any]:
    try:
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
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    if user_id == user.sub:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    try:
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
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: str, body: SetRoleBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict[str, Any]:
    valid_roles = {"user", "trader", "admin", "superadmin"}
    if body.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")
    try:
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
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.patch("/users/{user_id}/plan")
async def set_user_plan(
    user_id: str, body: SetPlanBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict[str, Any]:
    """Persist a plan change immediately on the User row.

    Valid plans: free, starter, professional, enterprise.
    The billing layer reads ``User.plan`` on the next sync cycle; writing it
    here ensures the superadmin dashboard reflects the change instantly.
    """
    valid_plans = {"free", "starter", "professional", "enterprise"}
    if body.plan not in valid_plans:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan. Must be one of: {sorted(valid_plans)}",
        )
    try:
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            old_plan = u.plan
            u.plan = body.plan
            db.commit()
            _log_superadmin_action(user, "set_plan", f"{user_id}: {old_plan} → {body.plan}")
            return {"ok": True, "plan": body.plan}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: str, body: BanUserBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict[str, Any]:
    try:
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
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.post("/users/{user_id}/unban")
async def unban_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
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
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    """Generate a temporary password and store it using the canonical hash scheme.

    Uses ``auth.jwt.hash_password`` (BLAKE2b pre-hash + bcrypt, cost 12) — the
    same function used at registration and in ``AuthService.login`` — so the
    temporary password verifies correctly at the next login attempt.

    Previously this endpoint called ``passlib.CryptContext.hash`` directly,
    which bypasses the BLAKE2b pre-hash step and produces a hash that
    ``auth.jwt.verify_password`` can never match.
    """
    try:
        import secrets

        from auth.jwt import hash_password

        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            temp_pw = secrets.token_urlsafe(16)
            # hash_password applies BLAKE2b pre-hash then bcrypt (cost 12),
            # matching the scheme used at registration and login verification.
            u.hashed_password = hash_password(temp_pw)
            db.commit()
            _log_superadmin_action(user, "reset_password", user_id)
            return {"ok": True, "temp_password": temp_pw, "note": "Share securely — valid until user changes it"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.post("/users/{user_id}/impersonate")
async def impersonate_user(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    """Issue a short-lived impersonation token for the target user.

    The token is structurally identical to a normal access token (same claims,
    same ``type``/``jti`` fields) so that ``decode_access_token()`` accepts it
    and it can be revoked via the standard blacklist on logout.
    """
    try:
        import time as _time
        import uuid as _uuid

        import jwt as pyjwt

        from auth.jwt import _get_secret

        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            if u.role == "superadmin":
                raise HTTPException(status_code=403, detail="Cannot impersonate another superadmin")

            secret = _get_secret()
            now = int(_time.time())
            # 1-hour impersonation window — shorter than the normal 60-min access
            # token so the window is bounded even if the superadmin forgets to log out.
            expires_in = 3600
            jti = str(_uuid.uuid4())

            payload = {
                # Standard JWT claims
                "sub": u.id,
                "exp": now + expires_in,
                "iat": now,
                "jti": jti,
                # HOPEFX access-token discriminator — required by decode_access_token()
                "type": "access",
                # User identity claims
                "username": u.username,
                "email": u.email,
                "role": u.role,
                # Audit trail — who initiated the impersonation
                "impersonated_by": user.sub,
            }
            token = pyjwt.encode(payload, secret, algorithm="HS256")
            _log_superadmin_action(user, "impersonate", f"target={user_id} jti={jti}")
            return {"access_token": token, "token_type": "bearer", "expires_in": expires_in}  # nosec B105
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error.") from exc


@router.get("/users/{user_id}/activity")
async def get_user_activity(user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    try:
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
                failed.append({"user_id": uid, "reason": safe_error(exc)})
        db.commit()
        _log_superadmin_action(user, "bulk_ban", f"count={len(succeeded)} reason={body.reason}")
        return {"succeeded": succeeded, "failed": failed, "total": len(body.user_ids)}
    finally:
        db.close()


@router.post("/users/bulk/unban")
async def bulk_unban_users(body: BulkUserBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Unban multiple users in a single request."""

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
                failed.append({"user_id": uid, "reason": safe_error(exc)})
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

    db = SessionLocal()
    try:
        q = db.query(User)
        if body.user_ids:
            q = q.filter(User.id.in_(body.user_ids))
        rows = q.order_by(User.created_at.desc()).all()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "user_id",
                "username",
                "email",
                "role",
                "plan",
                "status",
                "country",
                "totp_enabled",
                "total_trades",
                "revenue_generated",
                "created_at",
                "last_login",
            ]
        )
        for u in rows:
            stats = _user_stats(db, u.id)
            writer.writerow(
                [
                    u.id,
                    u.username,
                    u.email,
                    u.role,
                    u.plan,
                    u.status,
                    u.country or "",
                    bool(u.totp_enabled),
                    stats["total_trades"],
                    stats["revenue_generated"],
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
