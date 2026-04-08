# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin audit sub-router."""

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from api.auth import TokenPayload

from ._shared import _iso, _log_superadmin_action, _require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter()

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
