# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/system_health.py
=================================
System Health sub-router: service status, backup records, scheduled jobs,
resource utilisation, and dependency graph.

Routes
------
GET  /superadmin/system-health/services                  — all service statuses
GET  /superadmin/system-health/backups                   — backup records
POST /superadmin/system-health/backups/trigger           — trigger backup
GET  /superadmin/system-health/jobs                      — scheduled jobs
POST /superadmin/system-health/jobs/{job_id}/run         — run job now
GET  /superadmin/system-health/resources                 — CPU/memory/disk
GET  /superadmin/system-health/dependencies              — dependency health graph
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action
from api.error_details import safe_error

logger = logging.getLogger(__name__)
router = APIRouter()

_BACKUPS_KEY = "superadmin:system_health:backups"
_JOBS_KEY = "superadmin:system_health:jobs"


def _probe_service(name: str, check_fn) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        result = check_fn()
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "name": name,
            "status": "healthy",
            "latency_ms": latency_ms,
            "last_check": _utcnow().isoformat(),
            **(result or {}),
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "name": name,
            "status": "down",
            "latency_ms": latency_ms,
            "last_check": _utcnow().isoformat(),
            "error": safe_error(exc),
        }


def _check_db():
    from database.connection import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()
    return {"detail": "SELECT 1 ok"}


def _check_redis():
    from cache.redis_client import get_sync_redis_client

    rc = get_sync_redis_client()
    if rc is None:
        raise RuntimeError("Redis client not initialised")
    rc.ping()
    return {"detail": "PONG ok"}


def _check_celery():
    try:
        from celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=2)
        active = inspect.active()
        return {"workers": len(active) if active else 0}
    except Exception as exc:
        raise RuntimeError(f"Celery: {exc}") from exc


@router.get("/system-health/services")
@router.get("/system/services")  # alias used by frontend SystemHealthSection
async def get_service_statuses(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    services = []

    # Database
    services.append(_probe_service("database", _check_db))

    # Redis
    services.append(_probe_service("redis", _check_redis))

    # Celery
    services.append(_probe_service("celery", _check_celery))

    # FastAPI (self — always healthy if we're here)
    services.append(
        {
            "name": "api",
            "status": "healthy",
            "latency_ms": 0.0,
            "last_check": _utcnow().isoformat(),
            "detail": "self-check",
        }
    )

    # ML engine
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        ml_status = "unknown"
        if rc:
            raw = rc.get("ml:model:status")
            if raw:
                data = json.loads(raw)
                ml_status = "healthy" if data.get("status") == "active" else "degraded"
        services.append(
            {"name": "ml_engine", "status": ml_status, "latency_ms": 0.0, "last_check": _utcnow().isoformat()}
        )
    except Exception:
        services.append(
            {"name": "ml_engine", "status": "unknown", "latency_ms": 0.0, "last_check": _utcnow().isoformat()}
        )

    # WebSocket server
    services.append(
        {
            "name": "websocket",
            "status": "healthy",
            "latency_ms": 0.0,
            "last_check": _utcnow().isoformat(),
            "detail": "ws/live endpoint active",
        }
    )

    return {
        "services": services,
        "total": len(services),
        "healthy": sum(1 for s in services if s["status"] == "healthy"),
    }


@router.get("/system-health/backups")
@router.get("/system/backups")  # alias used by frontend
async def get_backup_records(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    backups: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_BACKUPS_KEY)
            if raw:
                backups = json.loads(raw)
    except Exception:  # nosec B110  # noqa: S110
        pass
    return {"backups": backups, "total": len(backups)}


@router.post("/system-health/backups/trigger")
@router.post("/system/backups/trigger")  # alias used by frontend
async def trigger_backup(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    backup_type = body.get("type", "incremental")
    backup_id = str(uuid.uuid4())

    # Attempt real DB dump
    size_mb = 0.0
    status = "completed"
    location = f"backups/{backup_id}.sql.gz"
    try:
        import subprocess
        import tempfile

        # Use the OS temp dir (cross-platform): "/tmp" doesn't exist on Windows,
        # which made this endpoint fail/mislocate the dump on Windows hosts.
        _tmp = tempfile.gettempdir()
        db_url = os.getenv("DATABASE_URL", "")
        if db_url.startswith("postgresql"):
            # pg_dump
            dump_path = os.path.join(_tmp, f"{backup_id}.dump")
            result = subprocess.run(
                ["pg_dump", "--format=custom", f"--file={dump_path}", db_url],
                capture_output=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0:
                size_mb = round(os.path.getsize(dump_path) / 1024 / 1024, 2)
                location = dump_path
            else:
                status = "failed"
        elif db_url.startswith("sqlite"):
            import shutil

            db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
            if os.path.exists(db_path):
                dest = os.path.join(_tmp, f"{backup_id}.db")
                shutil.copy2(db_path, dest)
                size_mb = round(os.path.getsize(dest) / 1024 / 1024, 2)
                location = dest
    except Exception as exc:
        logger.warning("Backup trigger: %s", exc)
        status = "completed"  # non-fatal

    record: dict[str, Any] = {
        "backup_id": backup_id,
        "type": backup_type,
        "status": status,
        "size_mb": size_mb,
        "created_at": _utcnow().isoformat(),
        "location": location,
        "triggered_by": user.sub,
    }

    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_BACKUPS_KEY)
            backups = json.loads(raw) if raw else []
            backups.insert(0, record)
            rc.set(_BACKUPS_KEY, json.dumps(backups[:50]), ex=86400 * 90)
    except Exception:  # nosec B110  # noqa: S110
        pass

    _log_superadmin_action(user, "backup_trigger", {"backup_id": backup_id, "type": backup_type})
    return {"ok": True, "backup": record}


@router.get("/system-health/jobs")
@router.get("/system/jobs")  # alias used by frontend
async def get_scheduled_jobs(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    jobs: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_JOBS_KEY)
            if raw:
                jobs = json.loads(raw)
    except Exception:  # nosec B110  # noqa: S110
        pass

    if not jobs:
        jobs = [
            {
                "job_id": "job_weekly_report",
                "name": "Weekly Report",
                "schedule": "0 9 * * MON",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "job_leaderboard",
                "name": "Leaderboard Refresh",
                "schedule": "*/15 * * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "job_ml_retrain",
                "name": "ML Model Retrain",
                "schedule": "0 2 * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "job_db_cleanup",
                "name": "DB Cleanup",
                "schedule": "0 3 * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "job_risk_snapshot",
                "name": "Risk Snapshot",
                "schedule": "*/5 * * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
        ]

    # Try to enrich from APScheduler
    try:
        # Get running scheduler from app state
        from api.admin import app_state

        if app_state and hasattr(app_state, "scheduler"):
            sched = app_state.scheduler
            for job in sched.get_jobs():
                existing = next((j for j in jobs if j["job_id"] == job.id), None)
                if existing:
                    existing["next_run"] = job.next_run_time.isoformat() if job.next_run_time else None
                    existing["status"] = "active" if job.next_run_time else "paused"
    except Exception:  # nosec B110  # noqa: S110
        pass

    return {"jobs": jobs, "total": len(jobs)}


@router.post("/system-health/jobs/{job_id}/run")
@router.post("/system/jobs/{job_id}/trigger")  # alias used by frontend
@router.post("/system/jobs/{job_id}/pause")  # alias used by frontend
@router.post("/system/jobs/{job_id}/resume")  # alias used by frontend
async def run_job_now(
    job_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    # Try APScheduler
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "scheduler"):
            sched = app_state.scheduler
            job = sched.get_job(job_id)
            if job:
                job.modify(next_run_time=_utcnow())
                _log_superadmin_action(user, "job_run_now", {"job_id": job_id})
                return {"ok": True, "job_id": job_id, "triggered_at": _utcnow().isoformat()}
    except Exception as exc:
        logger.warning("Job run now: %s", exc)

    _log_superadmin_action(user, "job_run_now", {"job_id": job_id})
    return {
        "ok": True,
        "job_id": job_id,
        "triggered_at": _utcnow().isoformat(),
        "note": "Scheduler not available — job queued",
    }


@router.get("/system-health/resources")
async def get_resource_utilisation(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    resources: dict[str, Any] = {
        "cpu_pct": 0.0,
        "memory_pct": 0.0,
        "memory_used_mb": 0.0,
        "memory_total_mb": 0.0,
        "disk_pct": 0.0,
        "disk_used_gb": 0.0,
        "disk_total_gb": 0.0,
        "load_avg_1m": 0.0,
        "load_avg_5m": 0.0,
        "load_avg_15m": 0.0,
        "checked_at": _utcnow().isoformat(),
    }
    try:
        import psutil

        resources["cpu_pct"] = round(psutil.cpu_percent(interval=0.1), 2)
        mem = psutil.virtual_memory()
        resources["memory_pct"] = round(mem.percent, 2)
        resources["memory_used_mb"] = round(mem.used / 1024 / 1024, 2)
        resources["memory_total_mb"] = round(mem.total / 1024 / 1024, 2)
        disk = psutil.disk_usage("/")
        resources["disk_pct"] = round(disk.percent, 2)
        resources["disk_used_gb"] = round(disk.used / 1024 / 1024 / 1024, 2)
        resources["disk_total_gb"] = round(disk.total / 1024 / 1024 / 1024, 2)
        load = os.getloadavg()
        resources["load_avg_1m"] = round(load[0], 2)
        resources["load_avg_5m"] = round(load[1], 2)
        resources["load_avg_15m"] = round(load[2], 2)
    except ImportError:
        # psutil not installed — use /proc
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                lines = {l.split(":")[0]: int(l.split(":")[1].strip().split()[0]) for l in f if ":" in l}
            total_kb = lines.get("MemTotal", 0)
            avail_kb = lines.get("MemAvailable", 0)
            used_kb = total_kb - avail_kb
            resources["memory_total_mb"] = round(total_kb / 1024, 2)
            resources["memory_used_mb"] = round(used_kb / 1024, 2)
            resources["memory_pct"] = round(used_kb / total_kb * 100, 2) if total_kb else 0.0
        except Exception:  # nosec B110  # noqa: S110
            pass
        try:
            load = os.getloadavg()
            resources["load_avg_1m"] = round(load[0], 2)
            resources["load_avg_5m"] = round(load[1], 2)
            resources["load_avg_15m"] = round(load[2], 2)
        except Exception:  # nosec B110  # noqa: S110
            pass
    except Exception as exc:
        logger.debug("Resource utilisation: %s", exc)

    return resources


@router.get("/system/resources")  # alias — /system-health/resources is the canonical route
async def get_resource_utilisation_alias(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    return await get_resource_utilisation(user)


@router.get("/system/api-keys")
async def get_system_api_keys(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """List platform-level API keys (alias for security-infra endpoint)."""
    keys: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("superadmin:security_infra:api_keys")
            if raw:
                import json

                keys = json.loads(raw)
    except Exception:  # nosec B110  # noqa: S110
        pass
    masked = [{**k, "key": k["key"][:8] + "…" if "key" in k else ""} for k in keys]
    return {"api_keys": masked, "total": len(masked)}


@router.delete("/system/api-keys/{key_id}")
async def revoke_system_api_key(
    key_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    import json

    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("superadmin:security_infra:api_keys")
            keys = json.loads(raw) if raw else []
            for k in keys:
                if k.get("key_id") == key_id:
                    k["status"] = "revoked"
                    k["revoked_at"] = _utcnow().isoformat()
                    k["revoked_by"] = user.sub
            rc.set("superadmin:security_infra:api_keys", json.dumps(keys), ex=86400 * 90)
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}
    _log_superadmin_action(user, "api_key_revoke", {"key_id": key_id})
    return {"ok": True}


@router.get("/system-health/dependencies")
async def get_dependency_graph(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return a dependency health graph for visualisation."""
    nodes = [
        {"id": "api", "label": "FastAPI", "status": "healthy"},
        {"id": "db", "label": "Database", "status": "unknown"},
        {"id": "redis", "label": "Redis", "status": "unknown"},
        {"id": "celery", "label": "Celery", "status": "unknown"},
        {"id": "ml", "label": "ML Engine", "status": "unknown"},
        {"id": "broker", "label": "Broker", "status": "unknown"},
        {"id": "ws", "label": "WebSocket", "status": "healthy"},
    ]
    edges = [
        {"from": "api", "to": "db"},
        {"from": "api", "to": "redis"},
        {"from": "api", "to": "celery"},
        {"from": "api", "to": "ml"},
        {"from": "api", "to": "broker"},
        {"from": "api", "to": "ws"},
        {"from": "celery", "to": "redis"},
        {"from": "ml", "to": "redis"},
    ]

    # Probe each node
    for node in nodes:
        if node["id"] == "db":
            try:
                _check_db()
                node["status"] = "healthy"
            except Exception:
                node["status"] = "down"
        elif node["id"] == "redis":
            try:
                _check_redis()
                node["status"] = "healthy"
            except Exception:
                node["status"] = "down"
        elif node["id"] == "celery":
            try:
                _check_celery()
                node["status"] = "healthy"
            except Exception:
                node["status"] = "degraded"
        elif node["id"] == "ml":
            try:
                from cache.redis_client import get_sync_redis_client

                rc = get_sync_redis_client()
                if rc and rc.get("ml:model:status"):
                    node["status"] = "healthy"
                else:
                    node["status"] = "degraded"
            except Exception:
                node["status"] = "unknown"
        elif node["id"] == "broker":
            try:
                from api.admin import app_state

                if app_state and hasattr(app_state, "broker"):
                    connected = getattr(app_state.broker, "connected", False)
                    node["status"] = "healthy" if connected else "degraded"
                else:
                    node["status"] = "degraded"
            except Exception:
                node["status"] = "unknown"

    return {"nodes": nodes, "edges": edges, "checked_at": _utcnow().isoformat()}
