# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin infrastructure sub-router — /infra/* endpoints only.

All other sections (compliance, risk, brokers, whitelabel, GDPR, nuclear,
alerting, rate-limiting, reporting, security-infra, system-health) are
handled by their dedicated sub-routers mounted in __init__.py.
This file retains only the unique /infra/* routes to avoid duplicate
route registration.
"""

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import TokenPayload

from ._shared import (
    _require_superadmin,
    _utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Infrastructure health / cache / db / queues ───────────────────────────────


def _get_cpu_pct() -> float:
    try:
        import psutil

        return round(psutil.cpu_percent(interval=0.1), 1)
    except Exception:
        return 0.0


def _get_mem_pct() -> float:
    try:
        import psutil

        return round(psutil.virtual_memory().percent, 1)
    except Exception:
        return 0.0


@router.get("/infra/health")
async def get_infra_health(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    results: dict[str, Any] = {}

    # ── Database ──────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        from database.connection import SessionLocal
        from sqlalchemy import text as _sa_text

        db = SessionLocal()
        try:
            db.execute(_sa_text("SELECT 1"))
        finally:
            db.close()
        results["database"] = {"status": "ok", "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as exc:
        results["database"] = {
            "status": "error",
            "detail": str(exc),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    # ── Redis ─────────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.ping()
            results["redis"] = {"status": "ok", "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
        else:
            results["redis"] = {"status": "unavailable", "latency_ms": 0}
    except Exception as exc:
        results["redis"] = {
            "status": "error",
            "detail": str(exc),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    # ── Broker ────────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        from brokers.factory import get_broker

        broker = get_broker()
        if broker:
            results["broker"] = {"status": "ok", "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
        else:
            results["broker"] = {"status": "unavailable", "latency_ms": 0}
    except Exception as exc:
        results["broker"] = {
            "status": "error",
            "detail": str(exc),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    overall = "ok" if all(v.get("status") == "ok" for v in results.values()) else "degraded"
    return {
        "overall": overall,
        "components": results,
        "checked_at": _utcnow(),
        "cpu_pct": _get_cpu_pct(),
        "mem_pct": _get_mem_pct(),
    }


@router.get("/infra/cache")
async def get_cache_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from cache.redis_client import get_sync_redis_client, get_connection_mode

        rc = get_sync_redis_client()
        if rc is None:
            return {"available": False, "mode": "none"}
        mode = get_connection_mode()
        info: dict[str, Any] = {}
        try:  # noqa: SIM105
            info = rc.info()
        except Exception:  # nosec B110
            pass
        return {
            "available": True,
            "mode": mode,
            "hit_rate_pct": round(
                (info.get("keyspace_hits", 0) / max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1), 1))
                * 100,
                2,
            ),
            "total_keys": sum(v.get("keys", 0) for k, v in info.items() if k.startswith("db") and isinstance(v, dict)),
            "memory_used_mb": round(info.get("used_memory", 0) / 1_048_576, 2),
            "evictions": info.get("evicted_keys", 0),
            "connected_clients": info.get("connected_clients", 0),
            "ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
            "uptime_seconds": info.get("uptime_in_seconds", 0),
            "redis_version": info.get("redis_version", "unknown"),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@router.post("/infra/cache/flush")
async def flush_cache(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc is None:
            return {"ok": False, "detail": "Redis not available"}
        rc.flushdb()
        logger.warning("Cache flushed by superadmin %s", user.sub)
        return {"ok": True, "flushed_at": _utcnow()}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


@router.get("/infra/db")
async def get_db_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from database.connection import SessionLocal, engine
        from sqlalchemy import text as _sa_text

        db = SessionLocal()
        try:
            active_conns = 0
            try:
                result = db.execute(_sa_text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"))
                active_conns = result.scalar() or 0
            except Exception:  # nosec B110
                pass

            size_mb = 0.0
            try:
                result = db.execute(_sa_text("SELECT pg_database_size(current_database()) / 1048576.0"))
                size_mb = round(float(result.scalar() or 0), 2)
            except Exception:  # nosec B110
                pass

            slow_queries = 0
            try:
                result = db.execute(_sa_text("SELECT count(*) FROM pg_stat_statements WHERE mean_exec_time > 1000"))
                slow_queries = result.scalar() or 0
            except Exception:  # nosec B110
                pass

            pool = engine.pool
            return {
                "active_connections": active_conns,
                "pool_size": getattr(pool, "size", lambda: 0)(),
                "pool_checked_out": getattr(pool, "checkedout", lambda: 0)(),
                "pool_overflow": getattr(pool, "overflow", lambda: 0)(),
                "size_mb": size_mb,
                "slow_queries": slow_queries,
                "dialect": engine.dialect.name,
            }
        finally:
            db.close()
    except Exception as exc:
        return {"error": str(exc), "active_connections": 0, "size_mb": 0}


@router.get("/infra/queues")
async def get_queue_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import os as _os

    queues: list[dict] = []
    redis_available = False

    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            redis_available = True
            queue_names = ["default", "trading", "ml", "notifications", "reports"]
            for qname in queue_names:
                pending = rc.llen(f"celery:{qname}") or 0
                processing = rc.llen(f"celery:{qname}:unacked") or 0
                failed = rc.llen(f"celery:{qname}:failed") or 0
                queues.append(
                    {
                        "name": qname,
                        "pending": pending,
                        "processing": processing,
                        "failed": failed,
                        "workers": 0,
                    }
                )
    except Exception:  # nosec B110
        pass

    if not queues:
        worker_count = _os.cpu_count() or 1
        queues = [
            {"name": "default", "pending": 0, "processing": 0, "failed": 0, "workers": worker_count},
        ]

    return {
        "queues": queues,
        "redis_available": redis_available,
        "total_pending": sum(q["pending"] for q in queues),
        "total_processing": sum(q["processing"] for q in queues),
    }
