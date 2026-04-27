# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/diagnostics.py
==============================
SuperAdmin REST endpoints for the advanced DiagnosticsEngine.

Routes
------
POST /superadmin/diagnostics/run
    Trigger a full diagnostic run (all 10 checks) and return the report.
    Runs in the background; returns immediately with a job ID.

GET  /superadmin/diagnostics/report
    Return the most recent diagnostics report from the live engine or Redis.

GET  /superadmin/diagnostics/results
    Return individual DiagnosticResult entries, filterable by status/check.

POST /superadmin/diagnostics/remediate
    Trigger auto-remediation for all current critical/error findings.

GET  /superadmin/diagnostics/remediation-log
    Return the auto-remediation action history.

GET  /superadmin/diagnostics/checks
    List all available check names with descriptions.

POST /superadmin/diagnostics/checks/{check_name}/run
    Run a single named check and return its result immediately.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import TokenPayload
from ._shared import _log_superadmin_action, _require_superadmin, _utcnow

UTC = timezone.utc
logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Redis key for persisting the last report across restarts
# ---------------------------------------------------------------------------
_REDIS_REPORT_KEY = "heal:diagnostics:last_report"
_REDIS_REMEDIATION_KEY = "heal:diagnostics:remediation_log"

# ---------------------------------------------------------------------------
# Available check descriptions (for the /checks listing endpoint)
# ---------------------------------------------------------------------------
_CHECK_DESCRIPTIONS: dict[str, str] = {
    "env_vars_required": "Verify all required environment variables are set",
    "env_vars_optional": "Warn about missing optional environment variables",
    "import_chain": "Subprocess-import every core package to detect broken imports",
    "database": "Probe database connectivity with a SELECT 1 query",
    "redis": "Probe Redis connectivity and verify key namespaces exist",
    "frontend_build": "Check that static/index.html exists and is not stale",
    "route_health": "HTTP-test all registered FastAPI endpoints for 5xx errors",
    "spa_routing": "Verify SPA routes (/dashboard, /superadmin, etc.) return HTML",
    "auth_flow": "End-to-end login → protected-route → verify token flow",
    "data_feeds_redis": "Check Redis data-feed keys for staleness",
    "data_feeds_module": "Probe the data_feed module health status",
    "log_patterns": "Scan recent logs for known error patterns with root-cause mapping",
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DiagnosticRunResponse(BaseModel):
    job_id: str
    status: str
    triggered_at: str
    message: str


class RemediateResponse(BaseModel):
    actions_taken: int
    actions: list[dict]
    triggered_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_engine():
    """Return the DiagnosticsEngine singleton."""
    from security.diagnostics import get_diagnostics_engine

    return get_diagnostics_engine()


def _get_healer():
    """Return the SelfHealer singleton (may be None if not started)."""
    try:
        from security.self_healer import get_healer

        return get_healer()
    except Exception:
        return None


async def _load_report_from_redis() -> dict[str, Any] | None:
    """Load the last diagnostics report from Redis as a fallback."""
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_REDIS_REPORT_KEY)
            if raw:
                return json.loads(raw)
    except Exception as exc:
        logger.debug("diagnostics: redis report load: %s", exc)
    return None


async def _load_remediation_log_from_redis() -> list[dict[str, Any]]:
    """Load the remediation log from Redis as a fallback."""
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_REDIS_REMEDIATION_KEY)
            if raw:
                return json.loads(raw)
    except Exception as exc:
        logger.debug("diagnostics: redis remediation log load: %s", exc)
    return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/diagnostics/run")
async def run_diagnostics(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Trigger a full diagnostic run (all 10 checks) in the background.

    Returns immediately with a job reference. Poll GET /diagnostics/report
    to retrieve results once complete.
    """
    _log_superadmin_action(user, "diagnostics_run_triggered")
    job_id = f"diag_{int(_utcnow().timestamp())}"

    async def _run_bg() -> None:
        try:
            engine = _get_engine()
            report = await engine.run_full_diagnostic(parallel=True)
            logger.info(
                "diagnostics: background run complete — %s (job=%s)",
                report.summary(),
                job_id,
            )
            # Also push to healer state if available
            healer = _get_healer()
            if healer:
                healer._last_diag_report = report.to_dict()
                healer._last_diag_ts = _utcnow().timestamp()
        except Exception as exc:
            logger.warning("diagnostics: background run failed (job=%s): %s", job_id, exc)

    asyncio.create_task(_run_bg())

    return DiagnosticRunResponse(
        job_id=job_id,
        status="running",
        triggered_at=_utcnow().isoformat(),
        message="Diagnostic run started. Poll GET /superadmin/diagnostics/report for results.",
    ).model_dump()


@router.get("/diagnostics/report")
async def get_diagnostics_report(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return the most recent full diagnostics report."""
    # Try live healer first
    healer = _get_healer()
    if healer:
        report = healer.get_last_diagnostic_report()
        if report:
            return report

    # Redis fallback
    report = await _load_report_from_redis()
    if report:
        return report

    return {
        "message": "No diagnostics report available yet.",
        "hint": "Trigger one via POST /superadmin/diagnostics/run",
        "started_at": None,
        "completed_at": None,
        "counts": {},
        "has_critical": False,
        "has_errors": False,
        "results": [],
    }


@router.get("/diagnostics/results")
async def get_diagnostics_results(
    status: str | None = Query(None, description="Filter by status: ok|warning|error|critical"),
    check: str | None = Query(None, description="Filter by check_name"),
    limit: int = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Return individual DiagnosticResult entries from the last report,
    optionally filtered by status or check name.
    """
    report: dict[str, Any] = {}

    healer = _get_healer()
    if healer:
        report = healer.get_last_diagnostic_report()

    if not report:
        report = await _load_report_from_redis() or {}

    results: list[dict[str, Any]] = report.get("results", [])

    if status:
        results = [r for r in results if r.get("status") == status]
    if check:
        results = [r for r in results if r.get("check_name") == check]

    results = results[:limit]

    return {
        "total": len(results),
        "filters": {"status": status, "check": check},
        "results": results,
        "report_completed_at": report.get("completed_at"),
    }


@router.post("/diagnostics/remediate")
async def trigger_remediation(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Trigger auto-remediation for all current critical/error findings.

    Runs synchronously (waits for completion) since remediation actions
    are fast (enqueue to Claude queue, trigger npm build, etc.).
    """
    _log_superadmin_action(user, "diagnostics_remediate_triggered")

    try:
        engine = _get_engine()
        last = engine.get_last_report()
        if last is None:
            # Run a fresh diagnostic first
            last = await engine.run_full_diagnostic(parallel=True)

        actions = await engine.auto_remediate(last)

        # Persist to healer state
        healer = _get_healer()
        if healer and actions:
            healer._diag_remediation_log.extend(actions)
            healer._diag_remediation_log = healer._diag_remediation_log[-100:]

        return RemediateResponse(
            actions_taken=len(actions),
            actions=actions,
            triggered_at=_utcnow().isoformat(),
        ).model_dump()

    except Exception as exc:
        logger.warning("diagnostics: remediation failed: %s", exc)
        return {
            "actions_taken": 0,
            "actions": [],
            "triggered_at": _utcnow().isoformat(),
            "error": str(exc),
        }


@router.get("/diagnostics/remediation-log")
async def get_remediation_log(
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return the auto-remediation action history."""
    healer = _get_healer()
    if healer:
        entries = healer.get_diagnostics_remediation_log()[-limit:]
        return {"entries": entries, "total": len(healer._diag_remediation_log)}

    # Redis fallback
    entries = await _load_remediation_log_from_redis()
    return {"entries": entries[-limit:], "total": len(entries)}


@router.get("/diagnostics/checks")
async def list_checks(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """List all available diagnostic check names with descriptions."""
    return {
        "checks": [{"name": name, "description": desc} for name, desc in _CHECK_DESCRIPTIONS.items()],
        "total": len(_CHECK_DESCRIPTIONS),
    }


@router.post("/diagnostics/checks/{check_name}/run")
async def run_single_check(
    check_name: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Run a single named diagnostic check and return its result immediately.

    Useful for targeted investigation without running the full suite.
    """
    if check_name not in _CHECK_DESCRIPTIONS:
        return {
            "error": f"Unknown check: {check_name!r}",
            "available": list(_CHECK_DESCRIPTIONS.keys()),
        }

    _log_superadmin_action(user, "diagnostics_single_check", f"check={check_name}")

    try:
        engine = _get_engine()

        # Map check name to the engine method
        _check_map: dict[str, Any] = {
            "env_vars_required": engine._check_env_vars,
            "env_vars_optional": engine._check_env_vars,
            "import_chain": engine._check_import_chain,
            "database": engine._check_database,
            "redis": engine._check_redis,
            "frontend_build": engine._check_frontend_build,
            "route_health": engine._check_route_health,
            "spa_routing": engine._check_spa_routing,
            "auth_flow": engine._check_auth_flow,
            "data_feeds_redis": engine._check_data_feeds,
            "data_feeds_module": engine._check_data_feeds,
            "log_patterns": engine._check_log_patterns,
        }

        check_fn = _check_map.get(check_name)
        if check_fn is None:
            return {"error": f"No implementation for check: {check_name}"}

        result = await check_fn()

        # Normalise to list
        if not isinstance(result, list):
            result = [result]

        # Filter to the specific check if the method returns multiple
        filtered = [r for r in result if r.check_name == check_name or check_name in r.check_name]
        if not filtered:
            filtered = result  # return all if no exact match

        return {
            "check_name": check_name,
            "results": [r.to_dict() for r in filtered],
            "ran_at": _utcnow().isoformat(),
        }

    except Exception as exc:
        logger.warning("diagnostics: single check %s failed: %s", check_name, exc)
        return {
            "check_name": check_name,
            "error": str(exc),
            "ran_at": _utcnow().isoformat(),
        }


@router.get("/diagnostics/summary")
async def get_diagnostics_summary(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Return a concise health summary combining healer status and diagnostics.

    Designed for dashboard widgets that need a quick health indicator.
    """
    healer = _get_healer()
    healer_status: dict[str, Any] = {}
    if healer:
        healer_status = healer.get_full_status()

    diag_report: dict[str, Any] = {}
    if healer:
        diag_report = healer.get_last_diagnostic_report()
    if not diag_report:
        diag_report = await _load_report_from_redis() or {}

    counts = diag_report.get("counts", {})
    total_checks = sum(counts.values())
    ok_checks = counts.get("ok", 0)
    health_pct = round((ok_checks / total_checks * 100) if total_checks else 0, 1)

    # Collect top issues
    top_issues = [r for r in diag_report.get("results", []) if r.get("status") in ("critical", "error")][:5]

    return {
        "health_score": health_pct,
        "total_checks": total_checks,
        "counts": counts,
        "has_critical": diag_report.get("has_critical", False),
        "has_errors": diag_report.get("has_errors", False),
        "top_issues": top_issues,
        "last_diagnostic_run": diag_report.get("completed_at"),
        "healer_running": healer_status.get("running", False),
        "healer_baseline_files": healer_status.get("baseline_files", 0),
        "healer_drift_events": healer_status.get("drift_events", 0),
        "healer_patches_applied": healer_status.get("patches_applied", 0),
        "code_issues_critical": healer_status.get("code_issues_critical", 0),
        "code_issues_high": healer_status.get("code_issues_high", 0),
        "claude_queue_depth": healer_status.get("claude_fix_queue_depth", 0),
        "generated_at": _utcnow().isoformat(),
    }
