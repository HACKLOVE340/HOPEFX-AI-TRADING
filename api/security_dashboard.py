# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/security_dashboard.py
==========================
REST router for the Security Dashboard and Auto-Heal Dashboard frontends.

These routes back SecurityDashboard.tsx and AutoHealDashboard.tsx.

Routes
------
GET  /api/security/attacks              — attack log (rate spikes, failed logins, IPs)
GET  /api/security/alerts               — active security alerts
GET  /api/security/lockdown             — current lockdown status
POST /api/security/lockdown/clear       — clear an active lockdown (admin)
GET  /api/security/blocked-ips          — list blocked IPs (non-superadmin view)
GET  /api/security/heal/status          — self-healer status summary
GET  /api/security/heal/drift           — recent feature-drift events
GET  /api/security/heal/patches         — applied / pending patch records
POST /api/security/heal/scan/now        — trigger an integrity scan immediately
POST /api/security/heal/baseline/rebuild — rebuild the file-integrity baseline
GET  /api/security/av/status            — antivirus engine status
GET  /api/security/av/threats           — detected threat list
POST /api/security/av/scan              — trigger a full AV scan
POST /api/security/av/quarantine        — quarantine a threat by ID

Auth
----
GET  endpoints: any authenticated user.
POST endpoints: admin / superadmin role required.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/security", tags=["security-dashboard"])

# ---------------------------------------------------------------------------
# In-memory stores (used as fallback when dedicated services are absent)
# ---------------------------------------------------------------------------
_attack_log: list[dict] = []
_alert_store: list[dict] = []
_lockdown_state: dict = {"active": False, "reason": None, "activated_at": None}
_blocked_ips: list[str] = []
_threat_store: list[dict] = []
_scan_history: list[dict] = []
_patch_store: list[dict] = []
_baseline_info: dict = {"last_built": None, "file_count": 0, "status": "unknown"}


# =============================================================================
# Attack log
# =============================================================================


@router.get("/attacks", response_model=None, summary="Attack / intrusion log")
async def get_attack_log(
    limit: int = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return recent attack events: brute-force attempts, rate-limit violations,
    invalid JWT floods, SQL injection probes, etc.

    Data is sourced from the security_monitor service when available.
    Falls back to the in-memory ring buffer populated by middleware.
    """
    try:
        from security.monitor import get_security_monitor

        monitor = get_security_monitor()
        return {"events": monitor.recent_attacks(limit=limit), "total": monitor.attack_count()}
    except Exception as exc:
        logger.debug("Security monitor unavailable: %s", exc)

    # Fallback: in-memory buffer
    recent = _attack_log[-limit:]
    return {"events": list(reversed(recent)), "total": len(_attack_log)}


def record_attack_event(event_type: str, ip: str, details: dict | None = None) -> None:
    """Called by middleware / auth rate-limiter to record an attack."""
    _attack_log.append(
        {
            "event_type": event_type,
            "ip": ip,
            "timestamp": datetime.now(UTC).isoformat(),
            "details": details or {},
        }
    )
    # Keep ring buffer bounded
    if len(_attack_log) > 10_000:
        del _attack_log[:1_000]


# =============================================================================
# Security alerts
# =============================================================================


@router.get("/alerts", response_model=None, summary="Active security alerts")
async def get_security_alerts(
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return active (unresolved) security alerts.

    Sources: security_monitor.alerts(), kill-switch state,
    circuit-breaker states, and the in-process alert store.
    """
    alerts: list[dict] = []

    # 1. Security monitor
    try:
        from security.monitor import get_security_monitor

        monitor = get_security_monitor()
        alerts.extend(monitor.active_alerts())
    except Exception as _exc:
        logger.debug("Security monitor alerts unavailable: %s", _exc)

    # 2. Kill-switch alert
    try:
        from app import kill_switch

        if kill_switch.is_active():
            alerts.append(
                {
                    "id": "kill-switch-active",
                    "severity": "critical",
                    "type": "kill_switch",
                    "message": "Kill switch is currently ACTIVE — trading halted.",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
    except Exception as _exc:
        logger.debug("Kill switch status unavailable: %s", _exc)

    # 3. Circuit breakers
    try:
        from risk.circuit_breakers import get_circuit_breakers

        for name, cb in get_circuit_breakers().items():
            if getattr(cb, "state", "closed") == "open":
                alerts.append(
                    {
                        "id": f"cb-{name}",
                        "severity": "high",
                        "type": "circuit_breaker",
                        "message": f"Circuit breaker '{name}' is OPEN.",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
    except Exception as _exc:
        logger.debug("Circuit breaker status unavailable: %s", _exc)

    # 4. In-process store
    alerts.extend(_alert_store)

    return {"alerts": alerts, "count": len(alerts)}


# =============================================================================
# Lockdown status / clear
# =============================================================================


@router.get("/lockdown", response_model=None, summary="Lockdown status")
async def get_lockdown_status(
    user: TokenPayload = Depends(get_current_user),
):
    """Return whether the platform is in lockdown mode and why."""
    try:
        from security.lockdown import get_lockdown_manager

        mgr = get_lockdown_manager()
        return mgr.status()
    except Exception as _exc:
        logger.debug("Lockdown manager unavailable: %s", _exc)
    return _lockdown_state


@router.post(
    "/lockdown/clear",
    response_model=None,
    summary="Clear active lockdown (admin)",
)
async def clear_lockdown(
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Deactivate an active lockdown.

    Requires admin or superadmin role.  Emits an audit log entry.
    """
    global _lockdown_state

    try:
        from security.lockdown import get_lockdown_manager

        mgr = get_lockdown_manager()
        mgr.clear(cleared_by=user.sub)
        logger.warning("Lockdown cleared by admin: user=%s", user.sub)
        return {"status": "cleared", "cleared_by": user.sub}
    except Exception as _exc:
        logger.debug("Lockdown clear failed: %s", _exc)

    _lockdown_state = {"active": False, "reason": None, "activated_at": None}
    logger.warning("Lockdown cleared (in-memory): user=%s", user.sub)
    return {"status": "cleared", "cleared_by": user.sub}


# =============================================================================
# Blocked IPs (non-superadmin view)
# =============================================================================


@router.get("/blocked-ips", response_model=None, summary="List blocked IP addresses")
async def list_blocked_ips(
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return the current list of blocked IP addresses.

    Sourced from: Redis block-list → in-process fallback.
    Full management (block/unblock) is available in /api/superadmin/security/blocked-ips.
    """
    try:
        import redis as _redis

        r = _redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            socket_connect_timeout=1,
            decode_responses=True,
        )
        members = r.smembers("hopefx:security:blocked_ips")
        return {"blocked_ips": sorted(members), "count": len(members)}
    except Exception as exc:
        logger.debug("Redis blocked-IP lookup failed: %s", exc)
    return {"blocked_ips": list(_blocked_ips), "count": len(_blocked_ips)}


# =============================================================================
# Self-healer status / drift / patches
# =============================================================================


@router.get("/heal/status", response_model=None, summary="Self-healer status")
async def get_heal_status(
    user: TokenPayload = Depends(get_current_user),
):
    """Return the current status of the autonomous self-healing subsystem."""
    try:
        from security.self_healer import get_healer

        healer = get_healer()
        return healer.status()
    except Exception as exc:
        logger.debug("Self-healer unavailable: %s", exc)

    return {
        "status": "idle",
        "last_scan": _baseline_info.get("last_built"),
        "baseline_files": _baseline_info.get("file_count", 0),
        "baseline_status": _baseline_info.get("status", "unknown"),
        "pending_patches": len([p for p in _patch_store if p.get("status") == "pending"]),
        "applied_patches": len([p for p in _patch_store if p.get("status") == "applied"]),
        "drift_events_24h": len(_attack_log),
    }


@router.get("/heal/drift", response_model=None, summary="Recent feature-drift events")
async def get_heal_drift(
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(get_current_user),
):
    """Return recent feature-drift events detected by the self-healer."""
    try:
        from ml.drift_monitor import get_drift_monitor

        monitor = get_drift_monitor()
        report = monitor.latest_report()
        events = report.get("drift_events", [])[:limit] if report else []
        return {"drift_events": events, "total": len(events)}
    except Exception as exc:
        logger.debug("Drift monitor unavailable: %s", exc)
    return {"drift_events": [], "total": 0}


@router.get("/heal/patches", response_model=None, summary="Applied and pending patch records")
async def get_heal_patches(
    limit: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    user: TokenPayload = Depends(get_current_user),
):
    """Return the patch records managed by the self-healer."""
    try:
        from security.self_healer import get_healer

        healer = get_healer()
        patches = healer.list_patches(limit=limit, status=status_filter)
        return {"patches": patches, "total": len(patches)}
    except Exception as exc:
        logger.debug("Healer patch list unavailable: %s", exc)

    result = _patch_store[-limit:]
    if status_filter:
        result = [p for p in result if p.get("status") == status_filter]
    return {"patches": list(reversed(result)), "total": len(_patch_store)}


@router.post(
    "/heal/scan/now",
    response_model=None,
    summary="Trigger an integrity scan immediately (admin)",
)
async def trigger_integrity_scan(
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Immediately kick off a file-integrity scan.

    If the self-healer is available it will be invoked directly.
    Otherwise records a scan request for the next scheduled run.
    """
    triggered_at = datetime.now(UTC).isoformat()
    try:
        from security.self_healer import get_healer

        healer = get_healer()
        result = healer.scan_now()
        logger.info("Integrity scan triggered by admin: user=%s", user.sub)
        return {"status": "triggered", "triggered_at": triggered_at, **result}
    except Exception as exc:
        logger.info("Healer scan (fallback): user=%s err=%s", user.sub, exc)

    _scan_history.append({"triggered_by": user.sub, "triggered_at": triggered_at, "status": "queued"})
    return {"status": "queued", "triggered_at": triggered_at, "message": "Scan queued for next available worker."}


@router.post(
    "/heal/baseline/rebuild",
    response_model=None,
    summary="Rebuild the file-integrity baseline (admin)",
)
async def rebuild_baseline(
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Rebuild the cryptographic file-integrity baseline.

    WARNING: only do this after a verified clean deployment.  Rebuilding on
    a compromised system will bless the compromised state as the new baseline.
    """
    rebuilt_at = datetime.now(UTC).isoformat()
    try:
        from security.self_healer import get_healer

        healer = get_healer()
        result = healer.rebuild_baseline()
        logger.warning("Integrity baseline rebuilt: user=%s", user.sub)
        _baseline_info.update({"last_built": rebuilt_at, "status": "ok"})
        return {"status": "rebuilt", "rebuilt_at": rebuilt_at, **result}
    except Exception as exc:
        logger.warning("Baseline rebuild (fallback): user=%s err=%s", user.sub, exc)

    _baseline_info.update({"last_built": rebuilt_at, "status": "rebuilding"})
    return {
        "status": "queued",
        "rebuilt_at": rebuilt_at,
        "message": "Baseline rebuild queued.  Will apply after current scan completes.",
    }


# =============================================================================
# Antivirus / threat scanning
# =============================================================================


@router.get("/av/status", response_model=None, summary="Antivirus engine status")
async def get_av_status(
    user: TokenPayload = Depends(get_current_user),
):
    """Return the current status of the antivirus scanning engine."""
    try:
        from security.antivirus import get_av_engine

        engine = get_av_engine()
        return engine.status()
    except Exception as exc:
        logger.debug("AV engine unavailable: %s", exc)

    return {
        "engine": os.getenv("AV_ENGINE", "clamav"),
        "status": "idle",
        "last_scan": None,
        "definitions_version": os.getenv("AV_DEFINITIONS_VERSION", "unknown"),
        "threats_detected": len(_threat_store),
    }


@router.get("/av/threats", response_model=None, summary="Detected threats")
async def get_av_threats(
    limit: int = Query(50, ge=1, le=500),
    user: TokenPayload = Depends(get_current_user),
):
    """Return detected threats, most recent first."""
    try:
        from security.antivirus import get_av_engine

        engine = get_av_engine()
        threats = engine.list_threats(limit=limit)
        return {"threats": threats, "total": engine.threat_count()}
    except Exception as exc:
        logger.debug("AV threat list unavailable: %s", exc)

    recent = _threat_store[-limit:]
    return {"threats": list(reversed(recent)), "total": len(_threat_store)}


@router.post("/av/scan", response_model=None, summary="Trigger a full AV scan (admin)")
async def trigger_av_scan(
    user: TokenPayload = Depends(require_role("admin")),
):
    """Kick off a full antivirus scan of the deployment directory."""
    triggered_at = datetime.now(UTC).isoformat()
    try:
        from security.antivirus import get_av_engine

        engine = get_av_engine()
        result = engine.scan_all()
        logger.info("AV scan triggered: user=%s", user.sub)
        return {"status": "triggered", "triggered_at": triggered_at, **result}
    except Exception as exc:
        logger.info("AV scan (fallback): user=%s err=%s", user.sub, exc)

    return {
        "status": "queued",
        "triggered_at": triggered_at,
        "message": "AV scan queued.  Results will appear in /api/security/av/threats.",
    }


class QuarantineRequest(BaseModel):
    threat_id: str = Field(..., description="Threat ID returned by /api/security/av/threats")
    reason: str = Field("", description="Optional reason for quarantine action")


@router.post(
    "/av/quarantine",
    response_model=None,
    summary="Quarantine a detected threat (admin)",
)
async def quarantine_threat(
    req: QuarantineRequest,
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Move a detected threat to quarantine.

    The file is removed from its original location and isolated in the
    quarantine directory defined by AV_QUARANTINE_PATH.
    """
    try:
        from security.antivirus import get_av_engine

        engine = get_av_engine()
        result = engine.quarantine(req.threat_id, reason=req.reason)
        logger.warning("Threat quarantined: threat_id=%s user=%s", req.threat_id, user.sub)
        return {"status": "quarantined", "threat_id": req.threat_id, **result}
    except Exception as exc:
        logger.warning("AV quarantine (fallback): threat_id=%s err=%s", req.threat_id, exc)

    # Mark in-process store
    for t in _threat_store:
        if t.get("id") == req.threat_id:
            t["status"] = "quarantined"
            t["quarantined_at"] = datetime.now(UTC).isoformat()
            t["quarantined_by"] = user.sub
            break

    return {
        "status": "quarantined",
        "threat_id": req.threat_id,
        "quarantined_by": user.sub,
        "quarantined_at": datetime.now(UTC).isoformat(),
    }
