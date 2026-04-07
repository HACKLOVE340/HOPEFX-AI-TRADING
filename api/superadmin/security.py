# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin security sub-router."""

import logging

from fastapi import APIRouter, Depends, Query

from api.auth import TokenPayload

from ._shared import BlockIPBody, _iso, _log_superadmin_action, _require_superadmin, _utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

_BLOCKED_IPS_KEY = "superadmin:blocked_ips"

# ── Security ──────────────────────────────────────────────────────────────────


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
