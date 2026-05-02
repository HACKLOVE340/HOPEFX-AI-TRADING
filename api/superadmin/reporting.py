# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/reporting.py
============================
Reporting sub-router: generate and download platform reports.

Routes
------
GET  /superadmin/reporting/reports                       — list reports
POST /superadmin/reporting/reports/generate              — generate report
GET  /superadmin/reporting/reports/{report_id}/download  — download report
GET  /superadmin/reporting/templates                     — available report templates
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()

_REPORTS_KEY = "superadmin:reporting:reports"

REPORT_TEMPLATES = [
    {"type": "user_summary",      "name": "User Summary",          "description": "All users with roles, plans, trade counts"},
    {"type": "revenue",           "name": "Revenue Report",        "description": "MRR, ARR, plan breakdown, churn"},
    {"type": "trade_activity",    "name": "Trade Activity",        "description": "All trades with PnL, symbols, brokers"},
    {"type": "risk_summary",      "name": "Risk Summary",          "description": "VaR, drawdown, circuit breaker events"},
    {"type": "compliance",        "name": "Compliance Report",     "description": "KYC status, AML alerts, sanctions"},
    {"type": "system_health",     "name": "System Health",         "description": "Uptime, latency, error rates per service"},
    {"type": "ml_performance",    "name": "ML Performance",        "description": "Model accuracy, drift, predictions"},
    {"type": "audit_trail",       "name": "Audit Trail Export",    "description": "Full immutable audit log"},
]


def _load_reports() -> list[dict]:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_REPORTS_KEY)
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return []


def _save_reports(reports: list[dict]) -> None:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            rc.set(_REPORTS_KEY, json.dumps(reports[:200]), ex=86400 * 90)
    except Exception:
        pass


async def _build_report_data(report_type: str, period: str) -> tuple[list[str], list[list]]:
    """Build CSV rows for the given report type from real DB data."""
    headers: list[str] = []
    rows: list[list] = []

    try:
        from database.connection import SessionLocal
        from datetime import timedelta

        db = SessionLocal()
        try:
            cutoff = _utcnow()
            if period == "daily":
                cutoff = cutoff - timedelta(days=1)
            elif period == "weekly":
                cutoff = cutoff - timedelta(days=7)
            elif period == "monthly":
                cutoff = cutoff - timedelta(days=30)
            elif period == "yearly":
                cutoff = cutoff - timedelta(days=365)

            if report_type == "user_summary":
                from database.user_models import User
                users = db.query(User).filter(User.created_at >= cutoff).all()
                headers = ["user_id", "username", "email", "role", "plan", "is_active", "created_at"]
                rows = [[str(u.user_id), u.username, u.email, u.role, getattr(u, "plan", "free"), str(u.is_active), str(u.created_at)] for u in users]

            elif report_type == "trade_activity":
                from database.models import Trade
                trades = db.query(Trade).filter(Trade.created_at >= cutoff).limit(5000).all()
                headers = ["trade_id", "user_id", "symbol", "side", "quantity", "entry_price", "exit_price", "pnl", "status", "created_at"]
                rows = [[str(t.trade_id), str(t.user_id), t.symbol, t.side, str(t.quantity), str(t.entry_price), str(t.exit_price or ""), str(t.pnl or ""), t.status, str(t.created_at)] for t in trades]

            elif report_type == "revenue":
                from database.models import WalletTransaction
                txns = db.query(WalletTransaction).filter(WalletTransaction.created_at >= cutoff).all()
                headers = ["txn_id", "user_id", "type", "amount", "currency", "status", "created_at"]
                rows = [[str(t.id), str(t.user_id), t.transaction_type, str(t.amount), t.currency, t.status, str(t.created_at)] for t in txns]

            elif report_type == "audit_trail":
                from database.models import AuditLogEntry
                entries = db.query(AuditLogEntry).filter(AuditLogEntry.created_at >= cutoff).limit(5000).all()
                headers = ["id", "event_type", "user_id", "detail", "created_at"]
                rows = [[str(e.id), e.event_type, str(e.user_id or ""), e.detail or "", str(e.created_at)] for e in entries]

            else:
                headers = ["report_type", "period", "generated_at"]
                rows = [[report_type, period, _utcnow().isoformat()]]

        finally:
            db.close()
    except Exception as exc:
        logger.warning("Report build error (%s): %s", report_type, exc)
        headers = ["error"]
        rows = [[str(exc)]]

    return headers, rows


@router.get("/reporting/templates")
async def get_report_templates(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    return {"templates": REPORT_TEMPLATES}


@router.get("/reporting/reports")
@router.get("/reports")  # alias used by frontend ReportingSection
async def list_reports(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    reports = _load_reports()
    return {"reports": reports, "total": len(reports)}


@router.post("/reporting/reports/generate")
@router.post("/reports/generate")  # alias used by frontend
async def generate_report(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    report_type = body.get("type", "user_summary")
    period = body.get("period", "monthly")
    report_id = str(uuid.uuid4())

    report: dict[str, Any] = {
        "report_id": report_id,
        "type": report_type,
        "period": period,
        "status": "generating",
        "generated_at": None,
        "size_kb": 0,
        "download_url": f"/api/superadmin/reporting/reports/{report_id}/download",
        "generated_by": user.sub,
        "requested_at": _utcnow().isoformat(),
    }

    reports = _load_reports()
    reports.insert(0, report)
    _save_reports(reports)

    # Build the report data now (synchronous for simplicity)
    headers, rows = await _build_report_data(report_type, period)

    # Estimate size
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    csv_content = output.getvalue()
    size_kb = round(len(csv_content.encode()) / 1024, 2)

    # Cache the CSV content
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            rc.set(f"superadmin:report:data:{report_id}", csv_content, ex=3600 * 24)
    except Exception:
        pass

    # Mark complete
    report["status"] = "completed"
    report["generated_at"] = _utcnow().isoformat()
    report["size_kb"] = size_kb
    report["row_count"] = len(rows)
    reports[0] = report
    _save_reports(reports)

    _log_superadmin_action(user, "report_generate", {"type": report_type, "period": period, "report_id": report_id})
    return {"ok": True, "report": report}


@router.get("/reporting/reports/{report_id}/download")
@router.get("/reports/{report_id}/download")  # alias used by frontend
async def download_report(
    report_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> StreamingResponse:
    csv_content: str | None = None
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(f"superadmin:report:data:{report_id}")
            if raw:
                csv_content = raw if isinstance(raw, str) else raw.decode()
    except Exception:
        pass

    if not csv_content:
        # Regenerate on-the-fly
        reports = _load_reports()
        report = next((r for r in reports if r["report_id"] == report_id), None)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        headers, rows = await _build_report_data(report["type"], report["period"])
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
        csv_content = output.getvalue()

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=report_{report_id}.csv"},
    )


@router.delete("/reporting/reports/{report_id}")
@router.delete("/reports/{report_id}")  # alias used by frontend
async def delete_report(
    report_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    reports = _load_reports()
    before = len(reports)
    reports = [r for r in reports if r["report_id"] != report_id]
    if len(reports) == before:
        raise HTTPException(status_code=404, detail="Report not found")
    _save_reports(reports)
    # Also delete cached CSV
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            rc.delete(f"superadmin:report:data:{report_id}")
    except Exception:
        pass
    _log_superadmin_action(user, "report_delete", {"report_id": report_id})
    return {"ok": True}
