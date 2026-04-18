# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin audit sub-router."""

import logging
import math

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from api.auth import TokenPayload

from ._shared import _iso, _log_superadmin_action, _require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Audit ─────────────────────────────────────────────────────────────────────


@router.get("/audit")
async def get_audit_log(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    user_id: str | None = Query(None),
    event_type: str | None = Query(None),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry

        db = SessionLocal()
        try:
            q = db.query(AuditLogEntry).order_by(AuditLogEntry.created_at.desc())
            if user_id:
                q = q.filter(AuditLogEntry.user_id == user_id)
            if event_type:
                q = q.filter(AuditLogEntry.event_type.ilike(f"%{event_type}%"))
            total = q.count()
            offset = (page - 1) * limit
            rows = q.offset(offset).limit(limit).all()
            pages = max(1, math.ceil(total / limit))
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
                ],
                "total": total,
                "page": page,
                "pages": pages,
            }
        finally:
            db.close()
    except Exception as exc:
        logger.debug("audit_log: %s", exc)
        return {"events": [], "total": 0, "page": 1, "pages": 1}


@router.get("/audit/export")
async def export_audit_log(user: TokenPayload = Depends(_require_superadmin)):
    import csv
    import io

    result = await get_audit_log(page=1, limit=500, user=user)
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
