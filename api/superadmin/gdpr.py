# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/gdpr.py
=======================
GDPR / Data Privacy sub-router.

Routes
------
GET  /superadmin/gdpr/requests                           — data subject requests
POST /superadmin/gdpr/requests/{req_id}/process          — approve/reject request
POST /superadmin/gdpr/users/{user_id}/export             — export user data
POST /superadmin/gdpr/users/{user_id}/erase              — erase user data
GET  /superadmin/gdpr/consent-log                        — consent log
GET  /superadmin/gdpr/retention-policies                 — retention policies
PATCH /superadmin/gdpr/retention-policies                — update retention policies
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()

_GDPR_REQUESTS_KEY   = "superadmin:gdpr:requests"
_CONSENT_LOG_KEY     = "superadmin:gdpr:consent_log"
_RETENTION_KEY       = "superadmin:gdpr:retention_policies"


def _load_gdpr_requests() -> list[dict]:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_GDPR_REQUESTS_KEY)
            if raw:
                return json.loads(raw)
    except Exception:  # nosec B110
        pass
    return []


def _save_gdpr_requests(reqs: list[dict]) -> None:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            rc.set(_GDPR_REQUESTS_KEY, json.dumps(reqs), ex=86400 * 365)
    except Exception:  # nosec B110
        pass


@router.get("/gdpr/requests")
async def get_gdpr_requests(
    status: str | None = Query(None),
    request_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    reqs = _load_gdpr_requests()

    # Pull from DB audit log
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry
        db = SessionLocal()
        try:
            rows = (
                db.query(AuditLogEntry)
                .filter(AuditLogEntry.event_type.in_(["gdpr_request", "data_export_request", "erasure_request"]))
                .order_by(AuditLogEntry.created_at.desc())
                .limit(limit)
                .all()
            )
            existing_ids = {r["request_id"] for r in reqs}
            for row in rows:
                rid = f"gdpr_{row.id}"
                if rid not in existing_ids:
                    meta = json.loads(row.metadata or "{}") if row.metadata else {}
                    reqs.append({
                        "request_id": rid,
                        "user_id": str(row.user_id) if row.user_id else "unknown",
                        "username": meta.get("username", "unknown"),
                        "email": meta.get("email", ""),
                        "request_type": meta.get("request_type", "export"),
                        "status": "pending",
                        "submitted_at": row.created_at.isoformat() if row.created_at else _utcnow().isoformat(),
                        "completed_at": None,
                        "notes": row.detail or "",
                    })
        finally:
            db.close()
    except Exception as exc:
        logger.debug("GDPR requests DB: %s", exc)

    if status:
        reqs = [r for r in reqs if r.get("status") == status]
    if request_type:
        reqs = [r for r in reqs if r.get("request_type") == request_type]
    return {"requests": reqs[:limit], "total": len(reqs)}


@router.post("/gdpr/requests/{req_id}/process")
async def process_gdpr_request(
    req_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    action = body.get("action", "approve")
    notes = body.get("notes", "")
    reqs = _load_gdpr_requests()
    found = False
    for r in reqs:
        if r["request_id"] == req_id:
            r["status"] = "completed" if action == "approve" else "rejected"
            r["completed_at"] = _utcnow().isoformat()
            r["processed_by"] = user.sub
            r["notes"] = notes
            found = True
            break
    if not found:
        reqs.append({
            "request_id": req_id,
            "status": "completed" if action == "approve" else "rejected",
            "completed_at": _utcnow().isoformat(),
            "processed_by": user.sub,
            "notes": notes,
        })
    _save_gdpr_requests(reqs)
    _log_superadmin_action(user, f"gdpr_request_{action}", {"req_id": req_id, "notes": notes})
    return {"ok": True, "req_id": req_id, "status": "completed" if action == "approve" else "rejected"}


@router.post("/gdpr/users/{user_id}/export")
async def export_user_data(
    user_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    export_data: dict[str, Any] = {"user_id": user_id, "exported_at": _utcnow().isoformat()}
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        from database.models import Trade, AuditLogEntry
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.user_id == user_id).first()
            if u:
                export_data["profile"] = {
                    "username": u.username,
                    "email": u.email,
                    "role": u.role,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "country": getattr(u, "country", None),
                }
            trades = db.query(Trade).filter(Trade.user_id == user_id).limit(1000).all()
            export_data["trades"] = [
                {"trade_id": str(t.trade_id), "symbol": t.symbol, "side": t.side,
                 "quantity": float(t.quantity or 0), "pnl": float(t.pnl or 0),
                 "created_at": t.created_at.isoformat() if t.created_at else None}
                for t in trades
            ]
            audit = db.query(AuditLogEntry).filter(AuditLogEntry.user_id == user_id).limit(500).all()
            export_data["audit_log"] = [
                {"event_type": a.event_type, "detail": a.detail,
                 "created_at": a.created_at.isoformat() if a.created_at else None}
                for a in audit
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("GDPR export error: %s", exc)
    _log_superadmin_action(user, "gdpr_user_export", {"user_id": user_id})
    return {"ok": True, "data": export_data}


@router.post("/gdpr/users/{user_id}/erase")
async def erase_user_data(
    user_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    reason = body.get("reason", "GDPR erasure request")
    erased: list[str] = []
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.user_id == user_id).first()
            if u:
                # Anonymise PII — do not hard-delete to preserve audit integrity
                u.email = f"erased_{user_id[:8]}@deleted.invalid"  # type: ignore[assignment]
                u.username = f"deleted_{user_id[:8]}"  # type: ignore[assignment]
                u.is_active = False  # type: ignore[assignment]
                db.commit()
                erased.append("profile_pii")
        finally:
            db.close()
    except Exception as exc:
        logger.error("GDPR erase error: %s", exc)
        return {"ok": False, "error": str(exc)}
    _log_superadmin_action(user, "gdpr_user_erase", {"user_id": user_id, "reason": reason})
    return {"ok": True, "erased": erased, "user_id": user_id}


@router.get("/gdpr/consent-log")
async def get_consent_log(
    user_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    entries: list[dict] = []
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry
        db = SessionLocal()
        try:
            q = db.query(AuditLogEntry).filter(
                AuditLogEntry.event_type.in_(["consent_given", "consent_withdrawn", "terms_accepted"])
            )
            if user_id:
                q = q.filter(AuditLogEntry.user_id == user_id)
            rows = q.order_by(AuditLogEntry.created_at.desc()).limit(limit).all()
            for r in rows:
                meta = json.loads(r.metadata or "{}") if r.metadata else {}
                entries.append({
                    "entry_id": str(r.id),
                    "user_id": str(r.user_id) if r.user_id else None,
                    "event_type": r.event_type,
                    "consent_type": meta.get("consent_type", "terms"),
                    "version": meta.get("version", "1.0"),
                    "ip_address": getattr(r, "ip_address", None),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Consent log DB: %s", exc)
    return {"entries": entries, "total": len(entries)}


_DEFAULT_RETENTION = {
    "trade_records_days": 2555,   # 7 years (regulatory)
    "audit_log_days": 2555,
    "user_pii_days": 365,
    "session_logs_days": 90,
    "market_data_days": 730,
    "ml_predictions_days": 365,
}


@router.get("/gdpr/retention-policies")
async def get_retention_policies(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    policies = _DEFAULT_RETENTION.copy()
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_RETENTION_KEY)
            if raw:
                policies.update(json.loads(raw))
    except Exception:  # nosec B110
        pass
    return {"policies": policies}


@router.patch("/gdpr/retention-policies")
async def update_retention_policies(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_RETENTION_KEY)
            policies = json.loads(raw) if raw else _DEFAULT_RETENTION.copy()
            policies.update({k: v for k, v in body.items() if isinstance(v, int)})
            rc.set(_RETENTION_KEY, json.dumps(policies), ex=86400 * 365)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    _log_superadmin_action(user, "gdpr_retention_update", body)
    return {"ok": True}
