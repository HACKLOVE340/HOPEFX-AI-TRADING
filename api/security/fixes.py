# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/security/fixes.py
=====================
Standalone REST router for the LLM auto-heal fix queue.

This router is separate from security/global_fortress.py so it can be
mounted independently, tested in isolation, and versioned without
touching the brain's core loop.

Routes
------
GET  /api/security/fixes              — pending fix queue
GET  /api/security/fixes/approved     — approved fixes with PR metadata
GET  /api/security/fixes/declined     — declined fixes
POST /api/security/fixes/approve      — approve a fix → triggers GitHub PR
POST /api/security/fixes/decline      — decline a fix
POST /api/security/fixes/scan         — push a vulnerability to the scan queue
GET  /api/security/fixes/stats        — queue statistics

Auth
----
All write endpoints require admin or superadmin role.
Read endpoints require any authenticated user.

Wiring
------
Register in core/router_registry.py::

    from api.security.fixes import router as fixes_router
    app.include_router(fixes_router)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/security/fixes", tags=["security-fixes"])


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _require_auth(request: Request) -> dict[str, Any]:
    """Require any authenticated user."""
    try:
        from auth.jwt_handler import verify_token as decode_token

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Missing token")
        _creds_exc = HTTPException(status_code=401, detail="Invalid token")
        return decode_token(token, _creds_exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Security auth token decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


def _require_admin(request: Request) -> dict[str, Any]:
    """Require admin or superadmin role."""
    payload = _require_auth(request)
    if payload.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return payload


# ── Redis helper ──────────────────────────────────────────────────────────────


async def _get_redis() -> Any | None:
    try:
        from cache.redis_client import get_redis

        return await get_redis()
    except Exception as exc:
        logger.debug("fixes router: Redis unavailable: %s", exc)
        return None


# ── Request/response models ───────────────────────────────────────────────────


class ApproveFixRequest(BaseModel):
    endpoint: str = Field(..., description="API endpoint path of the fix to approve")
    approved_by: str = Field(default="dashboard", description="Identifier of the approver")


class DeclineFixRequest(BaseModel):
    endpoint: str = Field(..., description="API endpoint path of the fix to decline")
    declined_by: str = Field(default="dashboard", description="Identifier of the decliner")
    reason: str | None = Field(default=None, description="Optional decline reason")


class ScanEntryRequest(BaseModel):
    endpoint: str = Field(..., description="API endpoint path with the vulnerability")
    code: str = Field(..., description="Vulnerable code snippet")
    severity: str = Field(default="medium", description="high | medium | low")
    rule: str = Field(default="manual", description="Scanner rule ID or 'manual'")


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("")
async def get_pending_fixes(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Return pending fix queue (most recent first)."""
    _require_auth(request)
    redis = await _get_redis()
    if not redis:
        return []
    raw = await redis.lrange("fixes:queue", 0, limit - 1)
    records = []
    for r in raw:
        try:
            records.append(json.loads(r))
        except json.JSONDecodeError:
            continue
    return records


@router.get("/approved")
async def get_approved_fixes(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Return recently approved fixes with PR metadata."""
    _require_auth(request)
    redis = await _get_redis()
    if not redis:
        return []
    raw = await redis.lrange("fixes:approved", -limit, -1)
    records = []
    for r in raw:
        try:
            records.append(json.loads(r))
        except json.JSONDecodeError:
            continue
    return list(reversed(records))


@router.get("/declined")
async def get_declined_fixes(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Return recently declined fixes."""
    _require_auth(request)
    redis = await _get_redis()
    if not redis:
        return []
    raw = await redis.lrange("fixes:declined", -limit, -1)
    records = []
    for r in raw:
        try:
            records.append(json.loads(r))
        except json.JSONDecodeError:
            continue
    return list(reversed(records))


@router.get("/stats")
async def get_fix_stats(request: Request) -> dict[str, Any]:
    """Return fix queue statistics."""
    _require_auth(request)
    redis = await _get_redis()
    if not redis:
        return {"error": "Redis unavailable"}

    pending_count = await redis.llen("fixes:queue")
    approved_count = await redis.llen("fixes:approved")
    declined_count = await redis.llen("fixes:declined")
    scan_queue_count = await redis.llen("scan:vuln_queue")

    # Count approved fixes that have a PR
    approved_raw = await redis.lrange("fixes:approved", -200, -1)
    pr_created = 0
    pr_errors = 0
    for r in approved_raw:
        try:
            rec = json.loads(r)
            if rec.get("pr_url"):
                pr_created += 1
            elif rec.get("pr_status") == "error":
                pr_errors += 1
        except json.JSONDecodeError:
            continue

    return {
        "pending": pending_count,
        "approved": approved_count,
        "declined": declined_count,
        "scan_queue_depth": scan_queue_count,
        "prs_created": pr_created,
        "pr_errors": pr_errors,
    }


@router.post("/approve")
async def approve_fix(
    body: ApproveFixRequest,
    request: Request,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Approve an LLM-generated fix and trigger the GitHub PR pipeline.

    Finds the matching pending record in fixes:queue, calls
    GitHubPRPublisher.publish(), and archives the result in fixes:approved.
    """
    payload = _require_admin(request)
    approved_by = body.approved_by or payload.get("sub", "dashboard")
    endpoint = body.endpoint

    redis = await _get_redis()

    # Find matching pending record
    fix_record: dict[str, Any] | None = None
    if redis:
        raw_list = await redis.lrange("fixes:queue", 0, 199)
        for raw in raw_list:
            try:
                rec = json.loads(raw)
                if rec.get("endpoint") == endpoint and rec.get("status") == "pending":
                    fix_record = rec
                    await redis.lrem("fixes:queue", 1, raw)
                    break
            except json.JSONDecodeError:
                continue

    if fix_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No pending fix found for endpoint '{endpoint}'",
        )

    # Trigger GitHub PR pipeline
    pr_result: dict[str, Any] = {"status": "skipped"}
    try:
        from security.github_pr_publisher import get_pr_publisher

        pr_result = await get_pr_publisher().publish(
            endpoint=endpoint,
            original_code=fix_record.get("original", ""),
            fix_code=fix_record.get("fix", ""),
            approved_by=approved_by,
            fix_ts=fix_record.get("ts"),
        )
    except Exception as exc:
        logger.error("fixes router: PR publisher error for %s: %s", endpoint, exc)
        pr_result = {"status": "error", "error": "PR publish failed — check server logs"}

    # Archive approved record
    approved_record = {
        **fix_record,
        "status": "approved",
        "approved_by": approved_by,
        "approved_at": datetime.now(UTC).isoformat(),
        "pr_url": pr_result.get("pr_url"),
        "pr_number": pr_result.get("pr_number"),
        "pr_branch": pr_result.get("branch"),
        "pr_file": pr_result.get("file_path"),
        "pr_status": pr_result.get("status"),
        "pr_error": pr_result.get("error"),
    }
    if redis:
        await redis.rpush("fixes:approved", json.dumps(approved_record))
        await redis.ltrim("fixes:approved", -500, -1)

    logger.info(
        "fixes router: approved endpoint=%s pr_status=%s pr_url=%s by=%s",
        endpoint,
        pr_result.get("status"),
        pr_result.get("pr_url"),
        approved_by,
    )

    return {
        "status": "approved",
        "endpoint": endpoint,
        "pr_url": pr_result.get("pr_url"),
        "pr_number": pr_result.get("pr_number"),
        "pr_branch": pr_result.get("branch"),
        "pr_file": pr_result.get("file_path"),
        "pr_status": pr_result.get("status"),
        "pr_error": pr_result.get("error"),
    }


@router.post("/decline")
async def decline_fix(
    body: DeclineFixRequest,
    request: Request,
) -> dict[str, Any]:
    """
    Decline an LLM-generated fix.

    Removes from fixes:queue and archives in fixes:declined.
    """
    payload = _require_admin(request)
    declined_by = body.declined_by or payload.get("sub", "dashboard")
    endpoint = body.endpoint

    redis = await _get_redis()
    found = False

    if redis:
        raw_list = await redis.lrange("fixes:queue", 0, 199)
        for raw in raw_list:
            try:
                rec = json.loads(raw)
                if rec.get("endpoint") == endpoint and rec.get("status") == "pending":
                    await redis.lrem("fixes:queue", 1, raw)
                    declined_record = {
                        **rec,
                        "status": "declined",
                        "declined_by": declined_by,
                        "declined_at": datetime.now(UTC).isoformat(),
                        "reason": body.reason,
                    }
                    await redis.rpush("fixes:declined", json.dumps(declined_record))
                    await redis.ltrim("fixes:declined", -500, -1)
                    found = True
                    break
            except json.JSONDecodeError:
                continue

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"No pending fix found for endpoint '{endpoint}'",
        )

    logger.info(
        "fixes router: declined endpoint=%s by=%s reason=%s",
        endpoint,
        declined_by,
        body.reason,
    )
    return {"status": "declined", "endpoint": endpoint}


@router.post("/scan")
async def push_scan_entry(
    body: ScanEntryRequest,
    request: Request,
) -> dict[str, Any]:
    """
    Push a vulnerability entry to the scan queue for auto-heal processing.

    Used by CI/CD pipelines, static analysis tools (bandit, semgrep), or
    manual operator submissions. HOPEFXBrain drains this queue every
    HEAL_INTERVAL seconds and generates LLM fixes.
    """
    _require_admin(request)
    redis = await _get_redis()

    entry = {
        "endpoint": body.endpoint,
        "code": body.code,
        "severity": body.severity,
        "rule": body.rule,
        "submitted_at": datetime.now(UTC).isoformat(),
    }

    if redis:
        await redis.rpush("scan:vuln_queue", json.dumps(entry))
        queue_depth = await redis.llen("scan:vuln_queue")
        logger.info(
            "fixes router: scan entry queued endpoint=%s severity=%s rule=%s depth=%d",
            body.endpoint,
            body.severity,
            body.rule,
            queue_depth,
        )
        return {
            "status": "queued",
            "endpoint": body.endpoint,
            "queue_depth": queue_depth,
        }

    return {"status": "queued_in_memory", "endpoint": body.endpoint}
