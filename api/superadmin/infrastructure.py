# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin infrastructure sub-router — /infra/* routes only.

Compliance, risk, brokers, whitelabel, GDPR, nuclear, alerting, rate-limits,
reports, security-infra and system routes have been moved to dedicated
sub-modules (compliance.py, risk_management.py, etc.) which provide richer
implementations, better Redis key namespacing, and additional endpoints.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload

from ._shared import (
    _log_superadmin_action,
    _require_superadmin,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Infrastructure ────────────────────────────────────────────────────────────


@router.get("/infra/health")
async def get_infra_health(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import asyncio as _asyncio
    import os as _os

    # ── Service connectivity ──────────────────────────────────────────────────
    svc: dict = {"db": "unknown", "redis": "unknown", "api": "healthy"}
    try:
        from database.connection import SessionLocal
        from sqlalchemy import text as _text
        _db = SessionLocal()
        _db.execute(_text("SELECT 1"))
        _db.close()
        svc["db"] = "healthy"
    except Exception:
        svc["db"] = "error"
    try:
        from cache.redis_client import get_sync_redis_client
        _rc = get_sync_redis_client()
        svc["redis"] = "healthy" if (_rc and _rc.ping()) else "error"
    except Exception:
        svc["redis"] = "error"

    # ── System resources (run in thread to avoid blocking event loop) ─────────
    def _read_sys() -> dict:
        try:
            import psutil
            cpu   = psutil.cpu_percent(interval=0.1)
            mem   = psutil.virtual_memory()
            disk  = psutil.disk_usage("/")
            net   = psutil.net_io_counters()
            load  = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0.0, 0.0, 0.0)
            return {
                "cpu_pct":           round(cpu, 1),
                "mem_pct":           round(mem.percent, 1),
                "disk_pct":          round(disk.percent, 1),
                "network_in_mbps":   round(net.bytes_recv / 1_048_576, 2),
                "network_out_mbps":  round(net.bytes_sent / 1_048_576, 2),
                "load_avg_1m":       round(load[0], 2),
                "load_avg_5m":       round(load[1], 2),
                "load_avg_15m":      round(load[2], 2),
            }
        except Exception:
            return {
                "cpu_pct": 0.0, "mem_pct": 0.0, "disk_pct": 0.0,
                "network_in_mbps": 0.0, "network_out_mbps": 0.0,
                "load_avg_1m": 0.0, "load_avg_5m": 0.0, "load_avg_15m": 0.0,
            }

    _loop = _asyncio.get_running_loop()
    sys_metrics = await _loop.run_in_executor(None, _read_sys)
    return {**svc, **sys_metrics}


@router.get("/infra/cache")
async def get_cache_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    # Try Redis first
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            info = rc.info()
            hits = info.get("keyspace_hits", 0)
            misses = info.get("keyspace_misses", 0)
            total = hits + misses
            hit_rate = round(hits / total * 100, 1) if total > 0 else 0.0
            # Count total keys across all DBs
            total_keys = sum(
                int(v.get("keys", 0))
                for v in (info.get(k, {}) for k in info if k.startswith("db"))
                if isinstance(v, dict)
            )
            return {
                "available": True,
                "backend": "redis",
                "hit_rate_pct": hit_rate,
                "total_keys": total_keys,
                "memory_used_mb": round(info.get("used_memory", 0) / 1_048_576, 2),
                "evictions": info.get("evicted_keys", 0),
                "connected_clients": info.get("connected_clients", 0),
                "ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "redis_version": info.get("redis_version", "?"),
            }
    except Exception:
        pass

    # Fallback: in-process db_store stats
    try:
        from api.db_store import _store  # type: ignore[attr-defined]
        key_count = len(_store) if hasattr(_store, "__len__") else 0
        return {
            "available": True,
            "backend": "in-process",
            "hit_rate_pct": 0.0,
            "total_keys": key_count,
            "memory_used_mb": 0.0,
            "evictions": 0,
            "connected_clients": 0,
            "ops_per_sec": 0,
            "note": "Redis unavailable — using in-process fallback",
        }
    except Exception:
        pass

    return {
        "available": False,
        "backend": "none",
        "hit_rate_pct": 0.0,
        "total_keys": 0,
        "memory_used_mb": 0.0,
        "evictions": 0,
        "connected_clients": 0,
        "ops_per_sec": 0,
        "note": "No cache backend available",
    }


@router.post("/infra/cache/flush")
async def flush_cache(
    pattern: str | None = None,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "flush_cache", pattern or "ALL")
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if not rc:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        if pattern:
            keys = rc.keys(pattern)
            if keys:
                rc.delete(*keys)
            return {"ok": True, "deleted": len(keys)}
        else:
            rc.flushdb()
            return {"ok": True, "deleted": "all"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/infra/db")
async def get_db_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import os as _os
    try:
        from database.connection import SessionLocal, _get_or_init_manager
        from sqlalchemy import inspect as _inspect, text

        db = SessionLocal()
        try:
            db_url = _os.getenv("DATABASE_URL", "sqlite:///hopefx.db")
            is_sqlite = "sqlite" in db_url

            # Table count — works on both SQLite and PostgreSQL
            mgr = _get_or_init_manager()
            inspector = _inspect(mgr._engine)
            tables = inspector.get_table_names()
            table_count = len(tables)

            # Row counts for key tables
            row_counts: dict = {}
            for tbl in ["users", "trades", "orders", "signals", "audit_log"]:
                if tbl in tables:
                    try:
                        from sqlalchemy.sql import quoted_name
                        safe = quoted_name(tbl, quote=True)
                        row_counts[tbl] = db.execute(text(f"SELECT COUNT(*) FROM {safe}")).scalar() or 0  # nosec B608
                    except Exception:
                        row_counts[tbl] = 0

            # DB file size for SQLite
            db_size_mb = 0.0
            if is_sqlite:
                db_path = db_url.replace("sqlite:///", "")
                if not db_path.startswith("/"):
                    db_path = _os.path.join(_os.getcwd(), db_path)
                try:
                    db_size_mb = round(_os.path.getsize(db_path) / 1_048_576, 2)
                except Exception:
                    pass

            # Active connections (PostgreSQL only)
            active_connections = 0
            if not is_sqlite:
                try:
                    active_connections = db.execute(
                        text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                    ).scalar() or 0
                except Exception:
                    pass

            return {
                "available": True,
                "engine": "sqlite" if is_sqlite else "postgresql",
                "table_count": table_count,
                "tables": tables,
                "row_counts": row_counts,
                "db_size_mb": db_size_mb,
                "active_connections": active_connections,
                "max_connections": 1 if is_sqlite else 100,
                "query_time_avg_ms": 0,
                "slow_queries": 0,
                "deadlocks": 0,
            }
        finally:
            db.close()
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__, "detail": str(exc)[:200]}


@router.get("/infra/queues")
async def get_queue_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import os as _os
    queue_names = ["app:logs", "platform:broadcasts", "ml:retrain_queue", "signals:queue",
                   "celery", "hopefx:tasks", "hopefx:priority"]
    queues: list[dict] = []

    # Try Redis queue lengths
    redis_available = False
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            redis_available = True
            for q in queue_names:
                length = rc.llen(q)
                queues.append({
                    "name": q,
                    "pending": length,
                    "processing": 0,
                    "failed": 0,
                    "workers": 0,
                })
    except Exception:
        pass

    # Try Celery inspect if available
    try:
        from celery_app import celery_app as _celery
        inspect = _celery.control.inspect(timeout=1.0)
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        total_active = sum(len(v) for v in active.values())
        total_reserved = sum(len(v) for v in reserved.values())
        if not queues:
            queues.append({
                "name": "celery",
                "pending": total_reserved,
                "processing": total_active,
                "failed": 0,
                "workers": len(active),
            })
    except Exception:
        pass

    if not queues:
        # No Redis, no Celery — show placeholder with real worker count
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


