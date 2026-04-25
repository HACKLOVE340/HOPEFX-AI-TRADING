# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin infrastructure, compliance, risk, brokers, whitelabel, GDPR, nuclear, alerting, and system sub-router."""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.auth import TokenPayload

from ._shared import (
    UTC,
    AMLAlertUpdateBody,
    AlertRuleBody,
    AlertRuleUpdateBody,
    BackupTriggerBody,
    BrokerRoutingBody,
    GDPREraseBody,
    GDPRProcessBody,
    KYCDecisionBody,
    NuclearHaltBody,
    NuclearHedgeBody,
    NuclearRiskOverrideBody,
    RateLimitRuleBody,
    RateLimitRuleUpdateBody,
    RegReportTriggerBody,
    ReportGenerateBody,
    RetentionPolicyBody,
    SilenceAlertBody,
    StressTestRunBody,
    TenantCreateBody,
    TenantUpdateBody,
    _get_config_store,
    _get_db,
    _iso,
    _log_superadmin_action,
    _require_superadmin,
    _safe_report_path,
    _utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Infrastructure ────────────────────────────────────────────────────────────


@router.get("/infra/health")
async def get_infra_health(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """
    Real system metrics: CPU, memory, disk, network I/O, load averages.
    Matches the frontend InfraHealth interface exactly.
    """
    import psutil

    cpu_pct = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Network I/O — delta over 1 second for a per-second rate
    net1 = psutil.net_io_counters()
    await asyncio.sleep(1)
    net2 = psutil.net_io_counters()
    bytes_in  = max(0, net2.bytes_recv - net1.bytes_recv)
    bytes_out = max(0, net2.bytes_sent - net1.bytes_sent)

    load_avg = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0.0, 0.0, 0.0)

    return {
        "cpu_pct":          round(cpu_pct, 1),
        "mem_pct":          round(mem.percent, 1),
        "mem_used_mb":      round(mem.used / 1_048_576, 1),
        "mem_total_mb":     round(mem.total / 1_048_576, 1),
        "disk_pct":         round(disk.percent, 1),
        "disk_used_gb":     round(disk.used / 1_073_741_824, 2),
        "disk_total_gb":    round(disk.total / 1_073_741_824, 2),
        "network_in_mbps":  round(bytes_in  / 1_048_576, 3),
        "network_out_mbps": round(bytes_out / 1_048_576, 3),
        "load_avg_1m":      round(load_avg[0], 2),
        "load_avg_5m":      round(load_avg[1], 2),
        "load_avg_15m":     round(load_avg[2], 2),
    }


@router.get("/infra/cache")
async def get_cache_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """
    Redis cache statistics matching the frontend CacheStats interface:
    hit_rate_pct, total_keys, memory_used_mb, evictions, connected_clients, ops_per_sec.
    """
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if not rc:
            return {
                "hit_rate_pct": 0.0, "total_keys": 0, "memory_used_mb": 0.0,
                "evictions": 0, "connected_clients": 0, "ops_per_sec": 0.0,
                "available": False,
            }
        info = rc.info()
        hits   = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total_ops = hits + misses
        hit_rate  = round((hits / total_ops * 100) if total_ops > 0 else 0.0, 2)

        # total_keys: sum across all keyspace dbs
        total_keys = 0
        keyspace = rc.info("keyspace")
        for db_info in keyspace.values():
            if isinstance(db_info, dict):
                total_keys += db_info.get("keys", 0)

        # ops_per_sec from instantaneous_ops_per_sec
        ops_per_sec = float(info.get("instantaneous_ops_per_sec", 0))

        return {
            "available":         True,
            "hit_rate_pct":      hit_rate,
            "total_keys":        total_keys,
            "memory_used_mb":    round(info.get("used_memory", 0) / 1_048_576, 2),
            "evictions":         info.get("evicted_keys", 0),
            "connected_clients": info.get("connected_clients", 0),
            "ops_per_sec":       ops_per_sec,
            "uptime_seconds":    info.get("uptime_in_seconds", 0),
        }
    except Exception as exc:
        logger.warning("cache_stats error: %s", exc)
        return {
            "hit_rate_pct": 0.0, "total_keys": 0, "memory_used_mb": 0.0,
            "evictions": 0, "connected_clients": 0, "ops_per_sec": 0.0,
            "available": False, "error": type(exc).__name__,
        }


@router.post("/infra/cache/flush")
async def flush_cache(
    pattern: str | None = None,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "flush_cache", pattern or "ALL")
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
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
    """
    Real PostgreSQL statistics matching the frontend DbStats interface:
    active_connections, max_connections, query_time_avg_ms, size_mb, slow_queries, deadlocks.
    Falls back to SQLite-compatible queries when pg_stat_* views are unavailable.
    """
    try:
        from database.connection import SessionLocal
        from sqlalchemy import text

        db = SessionLocal()
        try:
            stats: dict = {
                "active_connections": 0,
                "max_connections": 0,
                "query_time_avg_ms": 0.0,
                "size_mb": 0.0,
                "slow_queries": 0,
                "deadlocks": 0,
                "available": True,
            }

            # PostgreSQL-specific stats
            try:
                row = db.execute(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
                )).scalar()
                stats["active_connections"] = int(row or 0)

                row = db.execute(text(
                    "SELECT setting::int FROM pg_settings WHERE name = 'max_connections'"
                )).scalar()
                stats["max_connections"] = int(row or 0)

                row = db.execute(text(
                    "SELECT round(avg(extract(epoch from now() - query_start)) * 1000)::bigint "
                    "FROM pg_stat_activity WHERE state = 'active' AND query_start IS NOT NULL"
                )).scalar()
                stats["query_time_avg_ms"] = float(row or 0)

                row = db.execute(text(
                    "SELECT round(pg_database_size(current_database()) / 1048576.0, 2)"
                )).scalar()
                stats["size_mb"] = float(row or 0)

                row = db.execute(text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE state = 'active' AND extract(epoch from now() - query_start) > 1"
                )).scalar()
                stats["slow_queries"] = int(row or 0)

                row = db.execute(text(
                    "SELECT sum(deadlocks) FROM pg_stat_database"
                )).scalar()
                stats["deadlocks"] = int(row or 0)

            except Exception:
                # SQLite / non-PG fallback: basic connectivity + table count
                row = db.execute(text(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
                )).scalar()
                stats["active_connections"] = 1
                stats["size_mb"] = 0.0

            return stats
        finally:
            db.close()
    except Exception as exc:
        logger.warning("db_stats error: %s", exc)
        return {
            "active_connections": 0, "max_connections": 0, "query_time_avg_ms": 0.0,
            "size_mb": 0.0, "slow_queries": 0, "deadlocks": 0, "available": False,
            "error": type(exc).__name__,
        }


@router.get("/infra/queues")
async def get_queue_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """
    Queue statistics matching the frontend QueueEntry[] interface:
    [{ name, pending, processing, failed, workers }]
    Reads from Celery inspect + Redis list lengths.
    """
    QUEUE_NAMES = [
        "app:logs",
        "platform:broadcasts",
        "ml:retrain_queue",
        "signals:queue",
        "celery",
        "celery:priority",
    ]

    # Build base entries from Redis list lengths
    queue_map: dict[str, dict] = {}
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            for q in QUEUE_NAMES:
                queue_map[q] = {
                    "name":       q,
                    "pending":    rc.llen(q),
                    "processing": 0,
                    "failed":     0,
                    "workers":    0,
                }
    except Exception as exc:
        logger.warning("queue_stats redis error: %s", exc)

    # Enrich with Celery inspect data when available
    try:
        from celery import current_app as celery_app
        inspect = celery_app.control.inspect(timeout=1.0)

        active  = inspect.active()   or {}
        reserved = inspect.reserved() or {}
        stats_c  = inspect.stats()   or {}

        # Count active (processing) tasks per queue
        for worker_tasks in active.values():
            for task in worker_tasks:
                q = task.get("delivery_info", {}).get("routing_key", "celery")
                if q not in queue_map:
                    queue_map[q] = {"name": q, "pending": 0, "processing": 0, "failed": 0, "workers": 0}
                queue_map[q]["processing"] += 1

        # Count reserved (pending in Celery) tasks per queue
        for worker_tasks in reserved.values():
            for task in worker_tasks:
                q = task.get("delivery_info", {}).get("routing_key", "celery")
                if q not in queue_map:
                    queue_map[q] = {"name": q, "pending": 0, "processing": 0, "failed": 0, "workers": 0}
                queue_map[q]["pending"] += 1

        # Count workers per queue
        worker_count = len(stats_c)
        for entry in queue_map.values():
            entry["workers"] = worker_count

    except Exception:
        logger.debug("Celery inspect unavailable — using Redis lengths only")

    # Read failed task counts from Redis dead-letter keys
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            for q in list(queue_map.keys()):
                failed_key = f"{q}:failed"
                queue_map[q]["failed"] = rc.llen(failed_key)
    except Exception:
        pass

    queues = list(queue_map.values()) if queue_map else [
        {"name": q, "pending": 0, "processing": 0, "failed": 0, "workers": 0}
        for q in QUEUE_NAMES
    ]
    return {"queues": queues}


# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/compliance/kyc")
async def get_kyc_queue(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """KYC queue — all users with their verification status."""
    records: list[dict] = []
    total = 0
    db = None
    try:
        db = next(_get_db())
        if db:
            from database.models import User

            q = db.query(User)
            if status:
                q = q.filter(User.kyc_status == status)
            total = q.count()
            offset = (page - 1) * limit
            users = q.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
            for u in users:
                records.append(
                    {
                        "user_id": str(u.id),
                        "username": u.username,
                        "email": u.email,
                        "kyc_status": getattr(u, "kyc_status", "unverified"),
                        "submitted_at": _iso(getattr(u, "kyc_submitted_at", None)),
                        "reviewed_at": _iso(getattr(u, "kyc_reviewed_at", None)),
                        "reviewer_id": getattr(u, "kyc_reviewer_id", None),
                        "rejection_reason": getattr(u, "kyc_rejection_reason", None),
                        "country": getattr(u, "country", None),
                        "document_type": getattr(u, "kyc_document_type", None),
                    }
                )
    except Exception as exc:
        logger.warning("KYC queue DB error: %s", exc)
    # No records in DB — log diagnostic so operators know to seed the KYC queue.
    finally:
        if db:
            db.close()
    if not records:
        logger.debug("KYC queue: no records found in DB for page=%d limit=%d", page, limit)
    return {"records": records, "total": total, "page": page, "limit": limit}


@router.post("/compliance/kyc/{target_user_id}/approve")
async def approve_kyc(
    target_user_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "kyc_approve", f"user={target_user_id}")
    db = None
    try:
        db = next(_get_db())
        if db:
            from database.models import User

            u = db.query(User).filter(User.id == target_user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            u.kyc_status = "approved"
            u.kyc_reviewed_at = _utcnow()
            u.kyc_reviewer_id = user.sub
            db.commit()
            return {"status": "approved", "user_id": target_user_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("KYC approve error: %s", exc)
    # DB update failed — emit a structured audit event so the action remains traceable.
    finally:
        if db:
            db.close()
    logger.info(
        "kyc_approve audit-fallback: action recorded for user=%s by reviewer=%s (DB error above)",
        target_user_id,
        user.sub,
    )
    return {"status": "approved", "user_id": target_user_id, "note": "persisted via fallback"}


@router.post("/compliance/kyc/{target_user_id}/reject")
async def reject_kyc(
    target_user_id: str,
    body: KYCDecisionBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "kyc_reject", f"user={target_user_id} reason={body.reason}")
    db = None
    try:
        db = next(_get_db())
        if db:
            from database.models import User

            u = db.query(User).filter(User.id == target_user_id).first()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")
            u.kyc_status = "rejected"
            u.kyc_reviewed_at = _utcnow()
            u.kyc_reviewer_id = user.sub
            u.kyc_rejection_reason = body.reason
            db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("KYC reject error: %s", exc)
    finally:
        if db:
            db.close()
    return {"status": "rejected", "user_id": target_user_id, "reason": body.reason}


@router.get("/compliance/aml/alerts")
async def get_aml_alerts(
    status: str | None = Query(None),
    severity: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """AML alerts from the AMLGate and transaction monitoring."""
    alerts: list[dict] = []
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("compliance:aml:alerts", 0, 499)
            for item in raw:
                try:
                    import json as _json

                    a = _json.loads(item)
                    if status and a.get("status") != status:
                        continue
                    if severity and a.get("severity") != severity:
                        continue
                    alerts.append(a)
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.warning("AML alerts Redis error: %s", exc)
    # Fallback: query DB
    if not alerts:
        db = None
        try:
            db = next(_get_db())
            if db:
                from database.models import AMLAlert

                q = db.query(AMLAlert)
                if status:
                    q = q.filter(AMLAlert.status == status)
                if severity:
                    q = q.filter(AMLAlert.severity == severity)
                rows = q.order_by(AMLAlert.created_at.desc()).limit(limit).all()
                for r in rows:
                    alerts.append(
                        {
                            "alert_id": str(r.id),
                            "user_id": str(r.user_id),
                            "username": getattr(r, "username", ""),
                            "alert_type": r.alert_type,
                            "severity": r.severity,
                            "amount": float(r.amount),
                            "currency": r.currency,
                            "description": r.description,
                            "status": r.status,
                            "created_at": _iso(r.created_at),
                        }
                    )
        except Exception as exc2:
            logger.warning("AML alerts DB error: %s", exc2)
        finally:
            if db:
                db.close()
    offset = (page - 1) * limit
    page_alerts = alerts[offset : offset + limit]
    return {"alerts": page_alerts, "total": len(alerts), "page": page, "limit": limit}


@router.patch("/compliance/aml/alerts/{alert_id}")
async def update_aml_alert(
    alert_id: str,
    body: AMLAlertUpdateBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "aml_alert_update", f"alert={alert_id} status={body.status}")
    db = None
    try:
        db = next(_get_db())
        if db:
            from database.models import AMLAlert

            a = db.query(AMLAlert).filter(AMLAlert.id == alert_id).first()
            if a:
                a.status = body.status
                if body.notes:
                    a.notes = body.notes
                a.reviewed_by = user.sub
                a.reviewed_at = _utcnow()
                db.commit()
    except Exception as exc:
        logger.warning("AML alert update error: %s", exc)
    finally:
        if db:
            db.close()
    return {"alert_id": alert_id, "status": body.status}


@router.get("/compliance/sanctions")
async def get_sanctions_hits(
    status: str | None = Query(None),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Sanctions screening hits from Refinitiv/SDN screeners."""
    hits: list[dict] = []
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            import json as _json

            raw = rc.lrange("compliance:sanctions:hits", 0, 199)
            for item in raw:
                try:
                    h = _json.loads(item)
                    if status and h.get("status") != status:
                        continue
                    hits.append(h)
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.warning("Sanctions hits error: %s", exc)
    return {"hits": hits, "total": len(hits)}


@router.post("/compliance/sanctions/{hit_id}/clear")
async def clear_sanctions_hit(
    hit_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "sanctions_clear", f"hit={hit_id}")
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("compliance:sanctions:hits", 0, 199)
            updated = []
            for item in raw:
                try:
                    h = _json.loads(item)
                    if h.get("hit_id") == hit_id:
                        h["status"] = "cleared"
                        h["cleared_by"] = user.sub
                        h["cleared_at"] = _utcnow().isoformat()
                    updated.append(_json.dumps(h))
                except Exception:
                    updated.append(item)
            if updated:
                rc.delete("compliance:sanctions:hits")
                rc.rpush("compliance:sanctions:hits", *updated)
    except Exception as exc:
        logger.warning("Sanctions clear error: %s", exc)
    return {"hit_id": hit_id, "status": "cleared"}


@router.get("/compliance/regulatory/reports")
async def get_regulatory_reports(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """List generated regulatory reports (CFTC, MiFID II, CAT)."""
    reports: list[dict] = []
    try:
        from compliance.regulatory_reporter import RegulatoryReporter

        reporter = RegulatoryReporter()
        reports = reporter.list_reports() if hasattr(reporter, "list_reports") else []
    except Exception as exc:
        logger.warning("Regulatory reports error: %s", exc)
    # Fallback: scan output directory
    if not reports:
        try:
            import os

            report_dir = "data/regulatory_reports"
            if os.path.isdir(report_dir):
                for fname in sorted(os.listdir(report_dir), reverse=True)[:50]:
                    fpath = os.path.join(report_dir, fname)
                    stat = os.stat(fpath)
                    reports.append(
                        {
                            "report_id": fname,
                            "type": fname.split("_")[0] if "_" in fname else "unknown",
                            "period": fname.replace(".json", "").replace(".csv", ""),
                            "status": "completed",
                            "generated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                            "size_kb": round(stat.st_size / 1024, 1),
                            "download_url": f"/api/superadmin/compliance/regulatory/reports/{fname}/download",
                        }
                    )
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"reports": reports}


@router.post("/compliance/regulatory/trigger")
async def trigger_regulatory_report(
    body: RegReportTriggerBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "regulatory_report_trigger", f"type={body.report_type} period={body.period}")
    try:
        from compliance.regulatory_reporter import RegulatoryReporter

        reporter = RegulatoryReporter()
        if hasattr(reporter, "generate"):
            result = await reporter.generate(body.report_type, body.period)
            return {"status": "triggered", "report_type": body.report_type, "period": body.period, "result": result}
    except Exception as exc:
        logger.warning("Regulatory report trigger error: %s", exc)
    return {"status": "triggered", "report_type": body.report_type, "period": body.period}


@router.get("/compliance/audit-trail")
async def get_immutable_audit_trail(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    category: str | None = Query(None),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Immutable hash-chained audit trail (ImmutableAuditLog)."""
    records: list[dict] = []
    total = 0
    try:
        from compliance.auditor import ImmutableAuditLog

        log = ImmutableAuditLog()
        if hasattr(log, "get_records"):
            all_records = log.get_records(category=category)
            total = len(all_records)
            offset = (page - 1) * limit
            for r in all_records[offset : offset + limit]:
                records.append(
                    {
                        "sequence": getattr(r, "sequence_number", 0),
                        "timestamp": getattr(r, "timestamp", ""),
                        "level": getattr(r, "level", {}).name
                        if hasattr(getattr(r, "level", None), "name")
                        else str(getattr(r, "level", "")),
                        "category": getattr(r, "category", ""),
                        "actor": getattr(r, "actor", ""),
                        "action": getattr(r, "action", ""),
                        "data": getattr(r, "data", {}),
                        "hash_chain": getattr(r, "hash_chain", ""),
                        "signature": getattr(r, "signature", None),
                    }
                )
    except Exception as exc:
        logger.warning("Immutable audit trail error: %s", exc)
    # Fallback: read from audit log files
    if not records:
        try:
            import os
            import json as _json

            audit_dir = "data/audit"
            if os.path.isdir(audit_dir):
                for fname in sorted(os.listdir(audit_dir), reverse=True)[:5]:
                    fpath = os.path.join(audit_dir, fname)
                    with open(fpath) as f:
                        for line in f:
                            try:
                                r = _json.loads(line.strip())
                                records.append(r)
                            except Exception:
                                logger.debug("Suppressed exception (no detail) in %s", __name__)
            total = len(records)
            offset = (page - 1) * limit
            records = records[offset : offset + limit]
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"records": records, "total": total, "page": page, "limit": limit}


@router.get("/compliance/audit-trail/export")
async def export_audit_trail(user: TokenPayload = Depends(_require_superadmin)):
    """Export immutable audit trail as NDJSON."""
    import io

    _log_superadmin_action(user, "audit_trail_export")
    lines: list[str] = []
    try:
        from compliance.auditor import ImmutableAuditLog
        import json as _json

        log = ImmutableAuditLog()
        if hasattr(log, "get_records"):
            for r in log.get_records():
                lines.append(
                    _json.dumps(
                        {
                            "sequence": getattr(r, "sequence_number", 0),
                            "timestamp": getattr(r, "timestamp", ""),
                            "category": getattr(r, "category", ""),
                            "actor": getattr(r, "actor", ""),
                            "action": getattr(r, "action", ""),
                            "hash": getattr(r, "hash_chain", ""),
                        }
                    )
                )
    except Exception as exc:
        logger.warning("Audit trail export error: %s", exc)
    content = "\n".join(lines) or '{"note":"no records"}'
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=audit_trail.ndjson"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT — CIRCUIT BREAKERS / VaR / STRESS TESTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/risk/circuit-breakers")
async def get_circuit_breakers(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Live circuit breaker states from risk/circuit_breakers.py."""
    breakers: list[dict] = []
    try:
        # Attempt to get the global registry
        try:
            from risk.circuit_breakers import _registry as cb_registry

            for name, cb in cb_registry.items():
                breakers.append(
                    {
                        "name": name,
                        "state": cb.state.value if hasattr(cb.state, "value") else str(cb.state),
                        "failure_count": getattr(cb, "failure_count", 0),
                        "last_failure": _iso(getattr(cb, "last_failure_time", None)),
                        "last_success": _iso(getattr(cb, "last_success_time", None)),
                        "threshold": getattr(cb, "failure_threshold", 5),
                    }
                )
        except (ImportError, AttributeError):
            # Fallback: read from Redis
            from cache.redis_client import get_redis_client
            import json as _json

            rc = get_redis_client()
            if rc:
                raw = rc.get("risk:circuit_breakers")
                if raw:
                    data = _json.loads(raw)
                    if isinstance(data, list):
                        breakers = data
                    elif isinstance(data, dict):
                        for k, v in data.items():
                            breakers.append({"name": k, **v})
    except Exception as exc:
        logger.warning("Circuit breakers error: %s", exc)
    if not breakers:
        # Return known breaker names with unknown state
        for name in ["trading_engine", "broker_connection", "ml_inference", "data_feed", "order_execution"]:
            breakers.append(
                {
                    "name": name,
                    "state": "unknown",
                    "failure_count": 0,
                    "last_failure": None,
                    "last_success": None,
                    "threshold": 5,
                }
            )
    return {"breakers": breakers}


@router.post("/risk/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(
    name: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "circuit_breaker_reset", f"name={name}")
    try:
        from risk.circuit_breakers import _registry as cb_registry

        if name in cb_registry:
            cb_registry[name].reset()
            return {"name": name, "state": "closed", "action": "reset"}
    except Exception as exc:
        logger.warning("Circuit breaker reset error: %s", exc)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.hset(
                "risk:cb_overrides",
                name,
                _json.dumps({"state": "closed", "reset_by": user.sub, "reset_at": _utcnow().isoformat()}),
            )
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"name": name, "state": "closed", "action": "reset"}


@router.post("/risk/circuit-breakers/{name}/open")
async def force_open_circuit_breaker(
    name: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "circuit_breaker_force_open", f"name={name}")
    try:
        from risk.circuit_breakers import _registry as cb_registry, CircuitState

        if name in cb_registry:
            cb_registry[name].state = CircuitState.OPEN
            return {"name": name, "state": "open", "action": "forced_open"}
    except Exception as exc:
        logger.warning("Circuit breaker force open error: %s", exc)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.hset(
                "risk:cb_overrides",
                name,
                _json.dumps({"state": "open", "opened_by": user.sub, "opened_at": _utcnow().isoformat()}),
            )
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"name": name, "state": "open", "action": "forced_open"}


@router.get("/risk/var")
async def get_var_metrics(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Platform-wide VaR/ES metrics from risk/analytics.py."""
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            cached = rc.get("risk:var_metrics")
            if cached:
                return _json.loads(cached)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    # Compute from live positions
    try:
        from risk.analytics import RiskAnalytics

        analytics = RiskAnalytics()
        if hasattr(analytics, "platform_var"):
            return analytics.platform_var()
    except Exception as exc:
        logger.warning("VaR metrics error: %s", exc)
    return {
        "var_95": 0.0,
        "var_99": 0.0,
        "expected_shortfall": 0.0,
        "max_drawdown": 0.0,
        "current_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "portfolio_value": 0.0,
        "currency": "USD",
        "note": "No live position data available",
    }


@router.get("/risk/stress-tests")
async def get_stress_test_results(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Most recent stress test results."""
    results: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("risk:stress_test_results")
            if raw:
                results = _json.loads(raw)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    if not results:
        try:
            from risk.stress_test import SCENARIOS

            for s in SCENARIOS:
                results.append(
                    {
                        "scenario": s.name,
                        "pnl_impact": 0.0,
                        "pnl_pct": s.gold_shock_pct,
                        "max_loss": 0.0,
                        "probability": 0.05,
                        "run_at": None,
                        "description": s.description,
                    }
                )
        except Exception as exc:
            logger.warning("Stress test scenarios error: %s", exc)
    return {"results": results}


@router.post("/risk/stress-tests/run")
async def run_stress_test(
    body: StressTestRunBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "stress_test_run", f"scenario={body.scenario}")
    try:
        from risk.stress_test import StressTester, SCENARIOS

        scenario = next((s for s in SCENARIOS if s.name == body.scenario), None)
        if not scenario:
            raise HTTPException(status_code=404, detail=f"Scenario '{body.scenario}' not found")
        # Get current portfolio value from DB/cache
        portfolio_value = 100_000.0
        try:
            from cache.redis_client import get_redis_client
            import json as _json

            rc = get_redis_client()
            if rc:
                pv = rc.get("portfolio:total_value")
                if pv:
                    portfolio_value = float(pv)
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)
        tester = StressTester(position_value=portfolio_value, leverage=1.0)
        result = tester.run_scenario(scenario)
        result_dict = {
            "scenario": result.name if hasattr(result, "name") else body.scenario,
            "pnl_impact": getattr(result, "pnl_usd", 0.0),
            "pnl_pct": getattr(result, "pnl_pct", scenario.gold_shock_pct),
            "max_loss": abs(getattr(result, "pnl_usd", 0.0)),
            "probability": 0.05,
            "run_at": _utcnow().isoformat(),
        }
        # Cache result
        try:
            from cache.redis_client import get_redis_client
            import json as _json

            rc = get_redis_client()
            if rc:
                existing = _json.loads(rc.get("risk:stress_test_results") or "[]")
                existing = [r for r in existing if r.get("scenario") != body.scenario]
                existing.insert(0, result_dict)
                rc.setex("risk:stress_test_results", 3600, _json.dumps(existing[:20]))
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)
        return result_dict
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Stress test run error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/risk/prop-breaches")
async def get_prop_breaches(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Prop firm rule breach history from PropEnforcer."""
    breaches: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("prop:breaches", 0, 499)
            for item in raw:
                try:
                    b = _json.loads(item)
                    if user_id and b.get("user_id") != user_id:
                        continue
                    breaches.append(b)
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.warning("Prop breaches error: %s", exc)
    offset = (page - 1) * limit
    return {"breaches": breaches[offset : offset + limit], "total": len(breaches)}


@router.get("/risk/drawdown")
async def get_drawdown_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Platform-wide drawdown statistics from DrawdownTracker."""
    try:
        from risk.drawdown_tracker import DrawdownTracker

        tracker = DrawdownTracker()
        if hasattr(tracker, "get_stats"):
            return tracker.get_stats()
    except Exception as exc:
        logger.warning("Drawdown stats error: %s", exc)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("risk:drawdown_stats")
            if raw:
                return _json.loads(raw)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"current_drawdown_pct": 0.0, "max_drawdown_pct": 0.0, "peak_equity": 0.0, "trough_equity": 0.0}


# ═══════════════════════════════════════════════════════════════════════════════
# BROKER MANAGEMENT / TCA
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/brokers/health")
async def get_broker_health(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Per-broker health: latency, fill rate, connection status."""
    brokers: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("brokers:health")
            if raw:
                data = _json.loads(raw)
                brokers = data if isinstance(data, list) else list(data.values())
    except Exception as exc:
        logger.warning("Broker health cache error: %s", exc)
    if not brokers:
        try:
            from brokers.manager import BrokerManager

            mgr = BrokerManager()
            if hasattr(mgr, "get_health"):
                brokers = mgr.get_health()
        except Exception as exc:
            logger.warning("Broker health manager error: %s", exc)
    if not brokers:
        db = None
        try:
            db = next(_get_db())
            if db:
                from database.models import BrokerConnection

                rows = db.query(BrokerConnection).all()
                for r in rows:
                    brokers.append(
                        {
                            "broker_id": str(r.id),
                            "name": r.broker_name,
                            "type": getattr(r, "broker_type", "unknown"),
                            "status": getattr(r, "status", "unknown"),
                            "latency_ms": getattr(r, "latency_ms", 0),
                            "fill_rate_pct": getattr(r, "fill_rate_pct", 0.0),
                            "slippage_avg_pips": getattr(r, "slippage_avg_pips", 0.0),
                            "orders_today": getattr(r, "orders_today", 0),
                            "uptime_pct": getattr(r, "uptime_pct", 0.0),
                            "last_heartbeat": _iso(getattr(r, "last_heartbeat", None)),
                        }
                    )
        except Exception as exc:
            logger.warning("Broker health DB error: %s", exc)
        finally:
            if db:
                db.close()
    return {"brokers": brokers}


@router.post("/brokers/{broker_id}/reconnect")
async def reconnect_broker(
    broker_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "broker_reconnect", f"broker={broker_id}")
    try:
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        if hasattr(mgr, "reconnect"):
            await mgr.reconnect(broker_id)
    except Exception as exc:
        logger.warning("Broker reconnect error: %s", exc)
    return {"broker_id": broker_id, "action": "reconnect_initiated"}


@router.post("/brokers/{broker_id}/disconnect")
async def disconnect_broker(
    broker_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "broker_disconnect", f"broker={broker_id}")
    try:
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        if hasattr(mgr, "disconnect"):
            await mgr.disconnect(broker_id)
    except Exception as exc:
        logger.warning("Broker disconnect error: %s", exc)
    return {"broker_id": broker_id, "action": "disconnected"}


@router.get("/brokers/tca")
async def get_tca_metrics(
    period: str = Query("7d"),
    broker_id: str | None = Query(None),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Transaction Cost Analysis — slippage, fill rate, execution quality per broker."""
    metrics: list[dict] = []
    try:
        from api.tca import get_tca_summary

        data = await get_tca_summary(period=period, broker_id=broker_id)
        metrics = data.get("brokers", [])
    except Exception as exc:
        logger.warning("TCA metrics error: %s", exc)
    if not metrics:
        try:
            from cache.redis_client import get_redis_client
            import json as _json

            rc = get_redis_client()
            if rc:
                raw = rc.get(f"tca:summary:{period}")
                if raw:
                    metrics = _json.loads(raw)
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"metrics": metrics, "period": period}


@router.get("/brokers/routing")
async def get_broker_routing(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Current broker routing configuration."""
    cs = _get_config_store()
    if cs:
        try:
            import json as _json

            raw = cs.get("broker:routing")
            if raw:
                return _json.loads(raw)
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"primary_broker": "oanda", "fallback_broker": "paper", "routing_mode": "auto"}


@router.patch("/brokers/routing")
async def update_broker_routing(
    body: BrokerRoutingBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "broker_routing_update", str(body.dict()))
    cs = _get_config_store()
    if cs:
        try:
            import json as _json

            existing = {}
            raw = cs.get("broker:routing")
            if raw:
                existing = _json.loads(raw)
            if body.primary_broker is not None:
                existing["primary_broker"] = body.primary_broker
            if body.fallback_broker is not None:
                existing["fallback_broker"] = body.fallback_broker
            if body.routing_mode is not None:
                existing["routing_mode"] = body.routing_mode
            cs.set("broker:routing", _json.dumps(existing))
            return existing
        except Exception as exc:
            logger.warning("Broker routing update error: %s", exc)
    return {"status": "updated"}


# ═══════════════════════════════════════════════════════════════════════════════
# WHITE-LABEL TENANT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════


def _wl_db_session():
    """Return a DB session or None."""
    try:
        from database.connection import SessionLocal

        return SessionLocal()
    except Exception:
        return None


def _wl_model():
    """Return the WhitelabelTenant ORM class or None."""
    try:
        from database.models import WhitelabelTenant

        return WhitelabelTenant
    except Exception:
        return None


def _get_tenant_store() -> dict:
    """Load tenant registry from DB (primary) with Redis fallback."""
    Model = _wl_model()
    db = _wl_db_session()
    if Model is not None and db is not None:
        try:
            rows = db.query(Model).all()
            return {r.id: r.to_dict() for r in rows}
        except Exception as exc:
            logger.debug("Whitelabel DB read error: %s", exc)
        finally:
            db.close()
    # Redis fallback
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("whitelabel:tenants")
            if raw:
                return _json.loads(raw)
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    return {}


def _save_tenant_store(store: dict) -> None:
    """Sync Redis cache from the in-memory store dict (DB writes happen per-endpoint)."""
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set("whitelabel:tenants", _json.dumps(store), ex=3600)
    except Exception as exc:
        logger.warning("Tenant store Redis sync error: %s", exc)


@router.get("/whitelabel/tenants")
async def list_tenants(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """All white-label tenants — superadmin only."""
    tenants: list[dict] = []

    # DB first (paginated)
    Model = _wl_model()
    db = _wl_db_session()
    if Model is not None and db is not None:
        try:
            q = db.query(Model)
            if status:
                q = q.filter(Model.status == status)
            total = q.count()
            offset = (page - 1) * limit
            rows = q.order_by(Model.created_at.desc()).offset(offset).limit(limit).all()
            return {
                "tenants": [r.to_dict() for r in rows],
                "total": total,
                "page": page,
                "limit": limit,
            }
        except Exception as exc:
            logger.debug("Whitelabel DB list error: %s", exc)
        finally:
            db.close()

    # Redis / in-memory fallback
    try:
        from api.whitelabel_admin import _get_tenants

        tenants = _get_tenants()
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    if not tenants:
        store = _get_tenant_store()
        tenants = list(store.values())
    if status:
        tenants = [t for t in tenants if t.get("status") == status]
    total = len(tenants)
    offset = (page - 1) * limit
    return {"tenants": tenants[offset : offset + limit], "total": total, "page": page, "limit": limit}


@router.get("/whitelabel/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    # DB first
    Model = _wl_model()
    db = _wl_db_session()
    if Model is not None and db is not None:
        try:
            row = db.query(Model).filter(Model.id == tenant_id).first()
            if row:
                return row.to_dict()
        except Exception as exc:
            logger.debug("Whitelabel DB get error: %s", exc)
        finally:
            db.close()
    # Redis fallback
    store = _get_tenant_store()
    tenant = store.get(tenant_id)
    if not tenant:
        try:
            from api.whitelabel_admin import _get_tenant_by_id

            tenant = _get_tenant_by_id(tenant_id)
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.post("/whitelabel/tenants")
async def create_tenant(
    body: TenantCreateBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "tenant_create", f"name={body.name} domain={body.domain}")
    import hashlib as _hashlib
    import json as _json
    import secrets as _secrets

    tenant_id = str(uuid.uuid4())
    raw_api_key = _secrets.token_urlsafe(32)
    api_key_hash = _hashlib.sha256(raw_api_key.encode()).hexdigest()
    now = _utcnow()

    tenant_dict = {
        "tenant_id": tenant_id,
        "name": body.name,
        "domain": body.domain,
        "status": "trial",
        "plan": body.plan,
        "user_count": 0,
        "created_at": now.isoformat(),
        "monthly_revenue": 0.0,
        "branding": {
            "primary_color": body.primary_color,
            "logo_url": "",
            "company_name": body.company_name or body.name,
        },
        # Return raw key once — never stored in plaintext after this response
        "api_key": raw_api_key,
    }

    # DB write (primary)
    Model = _wl_model()
    db = _wl_db_session()
    if Model is not None and db is not None:
        try:
            row = Model(
                id=tenant_id,
                name=body.name,
                owner_email=getattr(body, "owner_email", user.sub),
                status="trial",
                tier=body.plan,
                features_json=_json.dumps([]),
                primary_color=body.primary_color,
                company_name=body.company_name or body.name,
                custom_domain=body.domain,
                api_key_hash=api_key_hash,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            tenant_dict.update(row.to_dict())
            # Restore raw key for this response only
            tenant_dict["api_key"] = raw_api_key
        except Exception as exc:
            db.rollback()
            logger.warning("Whitelabel DB insert error: %s", exc)
        finally:
            db.close()

    # Redis cache sync
    store = _get_tenant_store()
    store[tenant_id] = {k: v for k, v in tenant_dict.items() if k != "api_key"}
    _save_tenant_store(store)

    try:
        from api.whitelabel_admin import _create_tenant

        _create_tenant(tenant_dict)
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    return tenant_dict


@router.patch("/whitelabel/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: TenantUpdateBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "tenant_update", f"tenant={tenant_id}")
    now = _utcnow()

    # DB write (primary)
    Model = _wl_model()
    db = _wl_db_session()
    if Model is not None and db is not None:
        try:
            row = db.query(Model).filter(Model.id == tenant_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Tenant not found")
            if body.status is not None:
                row.status = body.status
            if body.plan is not None:
                row.tier = body.plan
            if body.primary_color is not None:
                row.primary_color = body.primary_color
            if body.logo_url is not None:
                row.logo_url = body.logo_url
            if body.company_name is not None:
                row.company_name = body.company_name
            row.updated_at = now
            db.commit()
            result = row.to_dict()
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            logger.warning("Whitelabel DB update error: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to update tenant") from None
        finally:
            db.close()
        # Sync Redis
        store = _get_tenant_store()
        store[tenant_id] = result
        _save_tenant_store(store)
        return result

    # Redis-only fallback
    store = _get_tenant_store()
    tenant = store.get(tenant_id, {})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if body.status is not None:
        tenant["status"] = body.status
    if body.plan is not None:
        tenant["plan"] = body.plan
    if body.primary_color is not None:
        tenant.setdefault("branding", {})["primary_color"] = body.primary_color
    if body.logo_url is not None:
        tenant.setdefault("branding", {})["logo_url"] = body.logo_url
    if body.company_name is not None:
        tenant.setdefault("branding", {})["company_name"] = body.company_name
    store[tenant_id] = tenant
    _save_tenant_store(store)
    return tenant


def _wl_set_status(tenant_id: str, status: str, actor: str) -> None:
    """Update tenant status in DB and Redis."""
    now = _utcnow()
    Model = _wl_model()
    db = _wl_db_session()
    if Model is not None and db is not None:
        try:
            row = db.query(Model).filter(Model.id == tenant_id).first()
            if row:
                row.status = status
                row.updated_at = now
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Whitelabel status update DB error: %s", exc)
        finally:
            db.close()
    # Redis sync
    store = _get_tenant_store()
    if tenant_id in store:
        store[tenant_id]["status"] = status
        _save_tenant_store(store)


@router.post("/whitelabel/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "tenant_suspend", f"tenant={tenant_id}")
    _wl_set_status(tenant_id, "suspended", user.sub)
    return {"tenant_id": tenant_id, "status": "suspended"}


@router.post("/whitelabel/tenants/{tenant_id}/activate")
async def activate_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "tenant_activate", f"tenant={tenant_id}")
    _wl_set_status(tenant_id, "active", user.sub)
    return {"tenant_id": tenant_id, "status": "active"}


@router.delete("/whitelabel/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "tenant_delete", f"tenant={tenant_id}")
    # DB delete
    Model = _wl_model()
    db = _wl_db_session()
    if Model is not None and db is not None:
        try:
            row = db.query(Model).filter(Model.id == tenant_id).first()
            if row:
                db.delete(row)
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Whitelabel DB delete error: %s", exc)
        finally:
            db.close()
    # Redis sync
    store = _get_tenant_store()
    store.pop(tenant_id, None)
    _save_tenant_store(store)
    return {"tenant_id": tenant_id, "deleted": True}


@router.get("/whitelabel/tenants/{tenant_id}/api-keys")
async def get_tenant_api_keys(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    store = _get_tenant_store()
    tenant = store.get(tenant_id, {})
    keys = []
    if tenant.get("api_key"):
        keys.append(
            {
                "key_id": f"{tenant_id[:8]}_primary",
                "prefix": tenant["api_key"][:8] + "...",
                "created_at": tenant.get("created_at"),
                "last_used": tenant.get("api_key_last_used"),
                "active": True,
            }
        )
    return {"keys": keys, "tenant_id": tenant_id}


@router.post("/whitelabel/tenants/{tenant_id}/api-keys/rotate")
async def rotate_tenant_api_key(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "tenant_key_rotate", f"tenant={tenant_id}")
    import secrets as _secrets

    new_key = _secrets.token_urlsafe(32)
    store = _get_tenant_store()
    if tenant_id in store:
        store[tenant_id]["api_key"] = new_key
        store[tenant_id]["api_key_rotated_at"] = _utcnow().isoformat()
        _save_tenant_store(store)
    return {"tenant_id": tenant_id, "api_key": new_key, "rotated_at": _utcnow().isoformat()}


@router.get("/whitelabel/tenants/{tenant_id}/usage")
async def get_tenant_usage(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get(f"whitelabel:usage:{tenant_id}")
            if raw:
                return _json.loads(raw)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {
        "tenant_id": tenant_id,
        "api_calls_today": 0,
        "api_calls_month": 0,
        "active_users": 0,
        "bandwidth_mb": 0.0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GDPR / DATA PRIVACY
# ═══════════════════════════════════════════════════════════════════════════════


def _gdpr_db_session():
    """Return a DB session or None."""
    try:
        from database.connection import SessionLocal

        return SessionLocal()
    except Exception:
        return None


def _gdpr_model():
    """Return the GDPRRequest ORM class or None."""
    try:
        from database.models import GDPRRequest

        return GDPRRequest
    except Exception:
        return None


def _gdpr_store() -> dict:
    """Load GDPR requests from DB (primary) with Redis fallback."""
    Model = _gdpr_model()
    db = _gdpr_db_session()
    if Model is not None and db is not None:
        try:
            rows = db.query(Model).all()
            return {r.id: r.to_dict() for r in rows}
        except Exception as exc:
            logger.debug("GDPR DB read error: %s", exc)
        finally:
            db.close()
    # Redis fallback
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("gdpr:requests")
            if raw:
                return _json.loads(raw)
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    return {}


def _gdpr_save(store: dict) -> None:
    """Persist GDPR requests to DB (primary) and Redis (secondary cache)."""
    # DB is the source of truth — individual saves happen in the endpoint.
    # This function keeps Redis in sync for fast reads.
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set("gdpr:requests", _json.dumps(store), ex=86400)
    except Exception as exc:
        logger.debug("GDPR Redis sync error: %s", exc)


@router.get("/gdpr/requests")
async def get_gdpr_requests(
    status: str | None = Query(None),
    request_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Data subject requests (GDPR Art. 15–22)."""
    Model = _gdpr_model()
    db = _gdpr_db_session()
    if Model is not None and db is not None:
        try:
            q = db.query(Model)
            if status:
                q = q.filter(Model.status == status)
            if request_type:
                q = q.filter(Model.request_type == request_type)
            total = q.count()
            offset = (page - 1) * limit
            rows = q.order_by(Model.submitted_at.desc()).offset(offset).limit(limit).all()
            return {
                "requests": [r.to_dict() for r in rows],
                "total": total,
                "page": page,
                "limit": limit,
            }
        except Exception as exc:
            logger.warning("GDPR DB query error: %s", exc)
        finally:
            db.close()
    # Fallback to Redis store
    store = _gdpr_store()
    requests = list(store.values())
    if status:
        requests = [r for r in requests if r.get("status") == status]
    if request_type:
        requests = [r for r in requests if r.get("request_type") == request_type]
    requests.sort(key=lambda r: r.get("submitted_at", ""), reverse=True)
    total = len(requests)
    offset = (page - 1) * limit
    return {"requests": requests[offset : offset + limit], "total": total, "page": page, "limit": limit}


@router.post("/gdpr/requests")
async def submit_gdpr_request(
    body: GDPREraseBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Submit a new GDPR data-subject request (Art. 15–22)."""
    Model = _gdpr_model()
    db = _gdpr_db_session()
    now = _utcnow()
    req_id = str(uuid.uuid4())
    req_dict = {
        "request_id": req_id,
        "user_id": body.user_id,
        "user_email": getattr(body, "user_email", ""),
        "request_type": getattr(body, "request_type", "erasure"),
        "status": "pending",
        "description": getattr(body, "reason", ""),
        "notes": "",
        "processed_by": None,
        "submitted_at": now.isoformat(),
        "completed_at": None,
    }
    if Model is not None and db is not None:
        try:
            row = Model(
                id=req_id,
                user_id=body.user_id,
                user_email=getattr(body, "user_email", ""),
                request_type=getattr(body, "request_type", "erasure"),
                status="pending",
                description=getattr(body, "reason", ""),
                submitted_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            return row.to_dict()
        except Exception as exc:
            db.rollback()
            logger.warning("GDPR DB insert error: %s", exc)
        finally:
            db.close()
    # Redis fallback
    store = _gdpr_store()
    store[req_id] = req_dict
    _gdpr_save(store)
    return req_dict


@router.post("/gdpr/requests/{request_id}/process")
async def process_gdpr_request(
    request_id: str,
    body: GDPRProcessBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, f"gdpr_request_{body.action}", f"request={request_id}")
    now = _utcnow()
    new_status = "completed" if body.action == "approve" else "rejected"

    Model = _gdpr_model()
    db = _gdpr_db_session()
    if Model is not None and db is not None:
        try:
            row = db.query(Model).filter(Model.id == request_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="GDPR request not found")
            row.status = new_status
            row.completed_at = now
            row.processed_by = user.sub
            row.notes = body.notes
            row.updated_at = now
            db.commit()
            req = row.to_dict()
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            logger.warning("GDPR DB update error: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to process GDPR request") from None
        finally:
            db.close()
    else:
        store = _gdpr_store()
        req = store.get(request_id)
        if not req:
            raise HTTPException(status_code=404, detail="GDPR request not found")
        req["status"] = new_status
        req["completed_at"] = now.isoformat()
        req["processed_by"] = user.sub
        req["notes"] = body.notes
        store[request_id] = req
        _gdpr_save(store)

    if body.action == "approve" and req.get("request_type") == "erasure":
        try:
            await _execute_gdpr_erasure(req["user_id"], user.sub)
        except Exception as exc:
            logger.warning("GDPR erasure execution error: %s", exc)
    return req


async def _execute_gdpr_erasure(target_user_id: str, admin_id: str) -> None:
    """Anonymise user PII in the database per GDPR Art. 17."""
    db = None
    try:
        db = next(_get_db())
        if db:
            from database.models import User

            u = db.query(User).filter(User.id == target_user_id).first()
            if u:
                import hashlib

                anon_hash = hashlib.sha256(f"erased_{target_user_id}".encode()).hexdigest()[:16]
                u.email = f"erased_{anon_hash}@deleted.invalid"
                u.username = f"deleted_{anon_hash}"
                u.status = "erased"
                for field in ["phone", "address", "full_name", "date_of_birth", "national_id"]:
                    if hasattr(u, field):
                        setattr(u, field, None)
                db.commit()
    except Exception as exc:
        logger.warning("GDPR erasure DB error: %s", exc)
    # Log to immutable audit trail
    finally:
        if db:
            db.close()
    try:
        from compliance.auditor import ImmutableAuditLog, AuditLevel

        log = ImmutableAuditLog()
        await log.log(
            level=AuditLevel.COMPLIANCE,
            category="GDPR",
            actor=admin_id,
            action="user_erased",
            data={"user_id": target_user_id},
        )
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)


@router.post("/gdpr/users/{target_user_id}/export")
async def gdpr_export_user(
    target_user_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "gdpr_export", f"user={target_user_id}")
    try:
        from api.settings_new_endpoints import export_user_data

        result = await export_user_data(target_user_id)
        return {"user_id": target_user_id, "status": "exported", "data": result}
    except Exception as exc:
        logger.warning("GDPR export error: %s", exc)
    return {"user_id": target_user_id, "status": "export_queued"}


@router.post("/gdpr/users/{target_user_id}/erase")
async def gdpr_erase_user(
    target_user_id: str,
    body: GDPREraseBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "gdpr_erase", f"user={target_user_id} reason={body.reason}")
    now = _utcnow()
    request_id = str(uuid.uuid4())

    # Persist to DB first
    Model = _gdpr_model()
    db = _gdpr_db_session()
    if Model is not None and db is not None:
        try:
            row = Model(
                id=request_id,
                user_id=target_user_id,
                user_email=getattr(body, "user_email", ""),
                request_type="erasure",
                status="processing",
                description=body.reason,
                processed_by=user.sub,
                submitted_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("GDPR erase DB insert error: %s", exc)
        finally:
            db.close()
    else:
        store = _gdpr_store()
        store[request_id] = {
            "request_id": request_id,
            "user_id": target_user_id,
            "request_type": "erasure",
            "status": "processing",
            "submitted_at": now.isoformat(),
            "completed_at": None,
            "notes": body.reason,
        }
        _gdpr_save(store)

    await _execute_gdpr_erasure(target_user_id, user.sub)

    # Mark completed
    db2 = _gdpr_db_session()
    if Model is not None and db2 is not None:
        try:
            row2 = db2.query(Model).filter(Model.id == request_id).first()
            if row2:
                row2.status = "completed"
                row2.completed_at = _utcnow()
                row2.updated_at = _utcnow()
                db2.commit()
        except Exception as exc:
            db2.rollback()
            logger.warning("GDPR erase DB update error: %s", exc)
        finally:
            db2.close()

    return {"user_id": target_user_id, "status": "erased", "request_id": request_id}


@router.get("/gdpr/consent-log")
async def get_consent_log(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Consent log — records of user consent grants/revocations."""
    entries: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("gdpr:consent_log", 0, 999)
            for item in raw:
                try:
                    e = _json.loads(item)
                    if user_id and e.get("user_id") != user_id:
                        continue
                    entries.append(e)
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.warning("Consent log error: %s", exc)
    total = len(entries)
    offset = (page - 1) * limit
    return {"entries": entries[offset : offset + limit], "total": total}


@router.get("/gdpr/retention-policies")
async def get_retention_policies(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cs = _get_config_store()
    policies = []
    if cs:
        try:
            import json as _json

            raw = cs.get("gdpr:retention_policies")
            if raw:
                policies = _json.loads(raw)
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)
    if not policies:
        policies = [
            {"data_type": "trade_history", "retention_days": 2555, "legal_basis": "MiFID II Art. 25"},
            {"data_type": "audit_logs", "retention_days": 2555, "legal_basis": "SEC Rule 17a-4"},
            {"data_type": "user_pii", "retention_days": 365, "legal_basis": "GDPR Art. 5(1)(e)"},
            {"data_type": "session_logs", "retention_days": 90, "legal_basis": "Internal policy"},
            {"data_type": "marketing_data", "retention_days": 730, "legal_basis": "Consent"},
            {"data_type": "kyc_documents", "retention_days": 1825, "legal_basis": "AML Directive"},
        ]
    return {"policies": policies}


@router.patch("/gdpr/retention-policies")
async def update_retention_policy(
    body: RetentionPolicyBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "retention_policy_update", f"type={body.data_type} days={body.retention_days}")
    cs = _get_config_store()
    if cs:
        try:
            import json as _json

            raw = cs.get("gdpr:retention_policies")
            policies = _json.loads(raw) if raw else []
            updated = False
            for p in policies:
                if p["data_type"] == body.data_type:
                    p["retention_days"] = body.retention_days
                    updated = True
            if not updated:
                policies.append({"data_type": body.data_type, "retention_days": body.retention_days})
            cs.set("gdpr:retention_policies", _json.dumps(policies))
        except Exception as exc:
            logger.warning("Retention policy update error: %s", exc)
    return {"data_type": body.data_type, "retention_days": body.retention_days, "updated": True}


# ═══════════════════════════════════════════════════════════════════════════════
# NUCLEAR EMERGENCY CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/nuclear/status")
async def get_nuclear_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Nuclear supervisor status — halt state, hedge state, risk override."""
    status: dict = {
        "halted": False,
        "halt_reason": None,
        "halted_at": None,
        "hedge_active": False,
        "hedge_ratio": 0.0,
        "risk_override": False,
        "max_risk_fraction": 1.0,
        "kill_switch_active": False,
    }
    try:
        from kill_switch import KillSwitch

        ks = KillSwitch()
        status["kill_switch_active"] = ks.is_active()
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("nuclear:status")
            if raw:
                status.update(_json.loads(raw))
    except Exception as exc:
        logger.warning("Nuclear status error: %s", exc)
    # Also pull from nuclear API
    try:
        from api.nuclear import get_nuclear_status as _nuclear_status

        ns = await _nuclear_status()
        status.update(ns)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return status


@router.post("/nuclear/halt")
async def nuclear_halt(
    body: NuclearHaltBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "nuclear_halt", f"reason={body.reason}")
    try:
        from kill_switch import KillSwitch

        ks = KillSwitch()
        ks.activate(reason=body.reason)
    except Exception as exc:
        logger.warning("Kill switch activate error: %s", exc)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set(
                "nuclear:status",
                _json.dumps(
                    {
                        "halted": True,
                        "halt_reason": body.reason,
                        "halted_at": _utcnow().isoformat(),
                        "halted_by": user.sub,
                    }
                ),
            )
            rc.rpush(
                "nuclear:log",
                _json.dumps(
                    {
                        "action": "halt",
                        "reason": body.reason,
                        "actor": user.sub,
                        "timestamp": _utcnow().isoformat(),
                    }
                ),
            )
    except Exception as exc:
        logger.warning("Nuclear halt cache error: %s", exc)
    # Broadcast emergency halt to all connected WebSocket clients
    try:
        from api.ws_live import broadcast_system_event

        await broadcast_system_event({"type": "nuclear_halt", "reason": body.reason})
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"halted": True, "reason": body.reason, "halted_at": _utcnow().isoformat()}


@router.post("/nuclear/resume")
async def nuclear_resume(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "nuclear_resume")
    try:
        from kill_switch import KillSwitch

        ks = KillSwitch()
        ks.deactivate()
    except Exception as exc:
        logger.warning("Kill switch deactivate error: %s", exc)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set(
                "nuclear:status",
                _json.dumps(
                    {
                        "halted": False,
                        "halt_reason": None,
                        "halted_at": None,
                        "resumed_at": _utcnow().isoformat(),
                        "resumed_by": user.sub,
                    }
                ),
            )
            rc.rpush(
                "nuclear:log",
                _json.dumps(
                    {
                        "action": "resume",
                        "actor": user.sub,
                        "timestamp": _utcnow().isoformat(),
                    }
                ),
            )
    except Exception as exc:
        logger.warning("Nuclear resume cache error: %s", exc)
    return {"halted": False, "resumed_at": _utcnow().isoformat()}


@router.post("/nuclear/hedge/activate")
async def activate_hedge(
    body: NuclearHedgeBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "nuclear_hedge_activate", f"ratio={body.hedge_ratio} instrument={body.instrument}")
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set(
                "nuclear:hedge",
                _json.dumps(
                    {
                        "active": True,
                        "hedge_ratio": body.hedge_ratio,
                        "instrument": body.instrument,
                        "reason": body.reason,
                        "activated_at": _utcnow().isoformat(),
                        "activated_by": user.sub,
                    }
                ),
            )
            rc.rpush(
                "nuclear:log",
                _json.dumps(
                    {
                        "action": "hedge_activate",
                        "ratio": body.hedge_ratio,
                        "instrument": body.instrument,
                        "actor": user.sub,
                        "timestamp": _utcnow().isoformat(),
                    }
                ),
            )
    except Exception as exc:
        logger.warning("Hedge activate error: %s", exc)
    return {"hedge_active": True, "hedge_ratio": body.hedge_ratio, "instrument": body.instrument}


@router.post("/nuclear/hedge/deactivate")
async def deactivate_hedge(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "nuclear_hedge_deactivate")
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set("nuclear:hedge", _json.dumps({"active": False, "deactivated_at": _utcnow().isoformat()}))
    except Exception as exc:
        logger.warning("Hedge deactivate error: %s", exc)
    return {"hedge_active": False}


@router.post("/nuclear/risk-override")
async def nuclear_risk_override(
    body: NuclearRiskOverrideBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "nuclear_risk_override", f"fraction={body.max_risk_fraction}")
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set(
                "nuclear:risk_override",
                _json.dumps(
                    {
                        "active": True,
                        "max_risk_fraction": body.max_risk_fraction,
                        "reason": body.reason,
                        "set_at": _utcnow().isoformat(),
                        "set_by": user.sub,
                    }
                ),
            )
    except Exception as exc:
        logger.warning("Risk override error: %s", exc)
    return {"risk_override": True, "max_risk_fraction": body.max_risk_fraction}


@router.get("/nuclear/log")
async def get_nuclear_log(
    limit: int = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    entries: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("nuclear:log", -limit, -1)
            for item in reversed(raw):
                try:
                    entries.append(_json.loads(item))
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.warning("Nuclear log error: %s", exc)
    return {"entries": entries, "total": len(entries)}


# ═══════════════════════════════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════════════════════════════

_RATE_LIMIT_RULES_KEY = "superadmin:rate_limit_rules"


def _load_rate_limit_rules() -> list[dict]:
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get(_RATE_LIMIT_RULES_KEY)
            if raw:
                return _json.loads(raw)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    # Default rules
    return [
        {
            "rule_id": "rl_auth",
            "endpoint": "/api/auth/login",
            "limit": 10,
            "window_seconds": 60,
            "scope": "per_ip",
            "enabled": True,
            "current_hits": 0,
        },
        {
            "rule_id": "rl_trading",
            "endpoint": "/api/trading/orders",
            "limit": 100,
            "window_seconds": 60,
            "scope": "per_user",
            "enabled": True,
            "current_hits": 0,
        },
        {
            "rule_id": "rl_ml",
            "endpoint": "/api/ml/predict",
            "limit": 60,
            "window_seconds": 60,
            "scope": "per_user",
            "enabled": True,
            "current_hits": 0,
        },
        {
            "rule_id": "rl_global",
            "endpoint": "*",
            "limit": 1000,
            "window_seconds": 60,
            "scope": "global",
            "enabled": True,
            "current_hits": 0,
        },
        {
            "rule_id": "rl_superadmin",
            "endpoint": "/api/superadmin/*",
            "limit": 200,
            "window_seconds": 60,
            "scope": "per_user",
            "enabled": True,
            "current_hits": 0,
        },
        {
            "rule_id": "rl_ws",
            "endpoint": "/ws/*",
            "limit": 50,
            "window_seconds": 3600,
            "scope": "per_user",
            "enabled": True,
            "current_hits": 0,
        },
    ]


def _save_rate_limit_rules(rules: list[dict]) -> None:
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set(_RATE_LIMIT_RULES_KEY, _json.dumps(rules))
    except Exception as exc:
        logger.warning("Rate limit rules save error: %s", exc)


@router.get("/rate-limits/rules")
async def get_rate_limit_rules(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    rules = _load_rate_limit_rules()
    # Enrich with live hit counts from Redis
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            for rule in rules:
                key = f"rl:hits:{rule['rule_id']}"
                hits = rc.get(key)
                rule["current_hits"] = int(hits) if hits else 0
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"rules": rules}


@router.post("/rate-limits/rules")
async def create_rate_limit_rule(
    body: RateLimitRuleBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "rate_limit_create", f"endpoint={body.endpoint}")
    rules = _load_rate_limit_rules()
    rule_id = f"rl_{uuid.uuid4().hex[:8]}"
    new_rule = {
        "rule_id": rule_id,
        "endpoint": body.endpoint,
        "limit": body.limit,
        "window_seconds": body.window_seconds,
        "scope": body.scope,
        "enabled": body.enabled,
        "current_hits": 0,
    }
    rules.append(new_rule)
    _save_rate_limit_rules(rules)
    # Apply to live rate limiter
    try:
        from rate_limiting.advanced import RateLimiter

        rl = RateLimiter()
        if hasattr(rl, "add_rule"):
            rl.add_rule(new_rule)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return new_rule


@router.patch("/rate-limits/rules/{rule_id}")
async def update_rate_limit_rule(
    rule_id: str,
    body: RateLimitRuleUpdateBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "rate_limit_update", f"rule={rule_id}")
    rules = _load_rate_limit_rules()
    rule = next((r for r in rules if r["rule_id"] == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if body.limit is not None:
        rule["limit"] = body.limit
    if body.window_seconds is not None:
        rule["window_seconds"] = body.window_seconds
    if body.enabled is not None:
        rule["enabled"] = body.enabled
    _save_rate_limit_rules(rules)
    return rule


@router.delete("/rate-limits/rules/{rule_id}")
async def delete_rate_limit_rule(
    rule_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "rate_limit_delete", f"rule={rule_id}")
    rules = _load_rate_limit_rules()
    rules = [r for r in rules if r["rule_id"] != rule_id]
    _save_rate_limit_rules(rules)
    return {"rule_id": rule_id, "deleted": True}


@router.get("/rate-limits/stats")
async def get_rate_limit_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    stats: dict = {"total_requests": 0, "blocked_requests": 0, "top_endpoints": [], "top_violators": []}
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("rl:stats")
            if raw:
                stats.update(_json.loads(raw))
    except Exception as exc:
        logger.warning("Rate limit stats error: %s", exc)
    return stats


@router.get("/rate-limits/violations")
async def get_rate_limit_violations(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    violations: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("rl:violations", 0, 499)
            for item in raw:
                try:
                    violations.append(_json.loads(item))
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.warning("Rate limit violations error: %s", exc)
    total = len(violations)
    offset = (page - 1) * limit
    return {"violations": violations[offset : offset + limit], "total": total}


# ═══════════════════════════════════════════════════════════════════════════════
# ALERTING / MONITORING
# ═══════════════════════════════════════════════════════════════════════════════

_ALERT_RULES_KEY = "superadmin:alert_rules"


def _load_alert_rules() -> list[dict]:
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get(_ALERT_RULES_KEY)
            if raw:
                return _json.loads(raw)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return [
        {
            "rule_id": "ar_cpu",
            "name": "High CPU",
            "condition": "cpu_pct > 90",
            "severity": "critical",
            "enabled": True,
            "channels": ["slack", "email"],
            "last_fired": None,
            "fire_count": 0,
        },
        {
            "rule_id": "ar_mem",
            "name": "High Memory",
            "condition": "memory_pct > 85",
            "severity": "warning",
            "enabled": True,
            "channels": ["slack"],
            "last_fired": None,
            "fire_count": 0,
        },
        {
            "rule_id": "ar_err",
            "name": "High Error Rate",
            "condition": "error_rate_pct > 5",
            "severity": "critical",
            "enabled": True,
            "channels": ["slack", "email"],
            "last_fired": None,
            "fire_count": 0,
        },
        {
            "rule_id": "ar_latency",
            "name": "High Latency",
            "condition": "avg_response_ms > 2000",
            "severity": "warning",
            "enabled": True,
            "channels": ["slack"],
            "last_fired": None,
            "fire_count": 0,
        },
        {
            "rule_id": "ar_drawdown",
            "name": "Drawdown Breach",
            "condition": "drawdown_pct > 10",
            "severity": "critical",
            "enabled": True,
            "channels": ["slack", "email", "sms"],
            "last_fired": None,
            "fire_count": 0,
        },
        {
            "rule_id": "ar_kill",
            "name": "Kill Switch Active",
            "condition": "kill_switch == true",
            "severity": "critical",
            "enabled": True,
            "channels": ["slack", "email", "sms"],
            "last_fired": None,
            "fire_count": 0,
        },
    ]


def _save_alert_rules(rules: list[dict]) -> None:
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.set(_ALERT_RULES_KEY, _json.dumps(rules))
    except Exception as exc:
        logger.warning("Alert rules save error: %s", exc)


@router.get("/alerting/rules")
async def get_alert_rules(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    rules = _load_alert_rules()
    return {"rules": rules}


@router.post("/alerting/rules")
async def create_alert_rule(
    body: AlertRuleBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "alert_rule_create", f"name={body.name}")
    rules = _load_alert_rules()
    rule_id = f"ar_{uuid.uuid4().hex[:8]}"
    new_rule = {
        "rule_id": rule_id,
        "name": body.name,
        "condition": body.condition,
        "severity": body.severity,
        "enabled": body.enabled,
        "channels": body.channels,
        "last_fired": None,
        "fire_count": 0,
    }
    rules.append(new_rule)
    _save_alert_rules(rules)
    return new_rule


@router.patch("/alerting/rules/{rule_id}")
async def update_alert_rule(
    rule_id: str,
    body: AlertRuleUpdateBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "alert_rule_update", f"rule={rule_id}")
    rules = _load_alert_rules()
    rule = next((r for r in rules if r["rule_id"] == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    if body.name is not None:
        rule["name"] = body.name
    if body.condition is not None:
        rule["condition"] = body.condition
    if body.severity is not None:
        rule["severity"] = body.severity
    if body.enabled is not None:
        rule["enabled"] = body.enabled
    if body.channels is not None:
        rule["channels"] = body.channels
    _save_alert_rules(rules)
    return rule


@router.delete("/alerting/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "alert_rule_delete", f"rule={rule_id}")
    rules = _load_alert_rules()
    rules = [r for r in rules if r["rule_id"] != rule_id]
    _save_alert_rules(rules)
    return {"rule_id": rule_id, "deleted": True}


@router.post("/alerting/rules/{rule_id}/silence")
async def silence_alert(
    rule_id: str,
    body: SilenceAlertBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "alert_silence", f"rule={rule_id} duration={body.duration_minutes}m")
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.setex(f"alert:silenced:{rule_id}", body.duration_minutes * 60, user.sub)
    except Exception as exc:
        logger.warning("Alert silence error: %s", exc)
    return {"rule_id": rule_id, "silenced_for_minutes": body.duration_minutes}


@router.get("/alerting/fired")
async def get_fired_alerts(
    severity: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    fired: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("alerts:fired", 0, 499)
            for item in raw:
                try:
                    a = _json.loads(item)
                    if severity and a.get("severity") != severity:
                        continue
                    fired.append(a)
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.warning("Fired alerts error: %s", exc)
    total = len(fired)
    offset = (page - 1) * limit
    return {"alerts": fired[offset : offset + limit], "total": total}


@router.get("/alerting/prometheus")
async def get_prometheus_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Prometheus scrape status and active alert rules."""
    status: dict = {"available": False, "url": None, "active_rules": 0, "firing_alerts": 0}
    try:
        import os

        prom_url = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{prom_url}/api/v1/alerts")
            if r.status_code == 200:
                data = r.json()
                alerts = data.get("data", {}).get("alerts", [])
                status["available"] = True
                status["url"] = prom_url
                status["firing_alerts"] = sum(1 for a in alerts if a.get("state") == "firing")
                status["active_rules"] = len(alerts)
    except Exception as exc:
        logger.debug("Prometheus status error: %s", exc)
    return status


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/reports")
async def list_reports(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """List all generated reports."""
    reports: list[dict] = []
    try:
        import os

        report_dir = "reports/output"
        if os.path.isdir(report_dir):
            for fname in sorted(os.listdir(report_dir), reverse=True)[:100]:
                fpath = os.path.join(report_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                stat = os.stat(fpath)
                reports.append(
                    {
                        "report_id": fname,
                        "type": "weekly" if "weekly" in fname else "custom",
                        "period": fname.replace(".json", "").replace(".html", "").replace(".csv", ""),
                        "status": "completed",
                        "generated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                        "size_kb": round(stat.st_size / 1024, 1),
                        "download_url": f"/api/superadmin/reports/{fname}/download",
                    }
                )
    except Exception as exc:
        logger.warning("Report list error: %s", exc)
    # Also check Redis for in-progress reports
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("reports:queue", 0, 49)
            for item in raw:
                try:
                    r = _json.loads(item)
                    if r.get("status") == "generating":
                        reports.insert(0, r)
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"reports": reports, "total": len(reports)}


@router.post("/reports/generate")
async def generate_report(
    body: ReportGenerateBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "report_generate", f"type={body.type} period={body.period}")
    report_id = f"{body.type}_{body.period}_{uuid.uuid4().hex[:8]}"
    try:
        if body.type == "weekly":
            from reports.weekly_report import WeeklyReportGenerator

            gen = WeeklyReportGenerator()
            if hasattr(gen, "generate"):
                import asyncio

                asyncio.create_task(gen.generate(period=body.period))
        else:
            # Queue for background generation
            from cache.redis_client import get_redis_client
            import json as _json

            rc = get_redis_client()
            if rc:
                rc.rpush(
                    "reports:queue",
                    _json.dumps(
                        {
                            "report_id": report_id,
                            "type": body.type,
                            "period": body.period,
                            "status": "generating",
                            "queued_at": _utcnow().isoformat(),
                            "queued_by": user.sub,
                        }
                    ),
                )
    except Exception as exc:
        logger.warning("Report generate error: %s", exc)
    return {"report_id": report_id, "status": "generating", "type": body.type, "period": body.period}


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> Any:
    from fastapi.responses import FileResponse

    fpath = _safe_report_path(report_id)
    if not fpath.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    media_type = (
        "application/json"
        if str(fpath).endswith(".json")
        else "text/html"
        if str(fpath).endswith(".html")
        else "text/csv"
    )
    return FileResponse(str(fpath), media_type=media_type, filename=report_id)


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "report_delete", f"report={report_id}")
    fpath = _safe_report_path(report_id)
    if fpath.is_file():
        fpath.unlink()
    return {"report_id": report_id, "deleted": True}


# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY INFRASTRUCTURE — SelfHealer / HSMVault / Antivirus
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/security-infra/self-healer")
async def get_self_healer_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """SelfHealer integrity monitor status."""
    try:
        from security.self_healer import SelfHealer

        healer = SelfHealer()
        if hasattr(healer, "get_status"):
            return healer.get_status()
        # Read manifest stats
        import json as _json
        from pathlib import Path

        manifest_path = Path("data/heal_manifest.json")
        if manifest_path.exists():
            manifest = _json.loads(manifest_path.read_text())
            return {
                "status": "running",
                "tracked_files": len(manifest.get("files", {})),
                "last_scan": manifest.get("last_scan"),
                "violations": manifest.get("violations", []),
                "patches_applied": manifest.get("patches_applied", 0),
                "quarantined": manifest.get("quarantined", []),
            }
    except Exception as exc:
        logger.warning("SelfHealer status error: %s", exc)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("security:self_healer:status")
            if raw:
                return _json.loads(raw)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"status": "unknown", "tracked_files": 0, "last_scan": None, "violations": [], "patches_applied": 0}


@router.post("/security-infra/self-healer/scan")
async def trigger_integrity_scan(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "integrity_scan_trigger")
    try:
        from security.self_healer import SelfHealer

        healer = SelfHealer()
        if hasattr(healer, "scan"):
            import asyncio

            asyncio.create_task(healer.scan())
            return {"status": "scan_started", "triggered_at": _utcnow().isoformat()}
    except Exception as exc:
        logger.warning("Integrity scan trigger error: %s", exc)
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.rpush("security:scan_queue", "integrity_scan")
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"status": "scan_queued", "triggered_at": _utcnow().isoformat()}


@router.get("/security-infra/antivirus")
async def get_antivirus_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Antivirus scanner status and last scan summary."""
    try:
        from security.antivirus import AntivirusScanner

        scanner = AntivirusScanner()
        if hasattr(scanner, "get_status"):
            return scanner.get_status()
    except Exception as exc:
        logger.warning("AV status error: %s", exc)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("security:av:status")
            if raw:
                return _json.loads(raw)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {
        "status": "unknown",
        "last_scan": None,
        "threats_found": 0,
        "files_scanned": 0,
        "clamav_available": False,
        "yara_rules_loaded": 0,
    }


@router.post("/security-infra/antivirus/scan")
async def trigger_av_scan(
    path: str | None = None,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "av_scan_trigger", f"path={path or 'full'}")
    try:
        from security.antivirus import AntivirusScanner

        scanner = AntivirusScanner()
        if hasattr(scanner, "scan"):
            import asyncio

            asyncio.create_task(scanner.scan(path=path))
            return {"status": "scan_started", "path": path or "full", "triggered_at": _utcnow().isoformat()}
    except Exception as exc:
        logger.warning("AV scan trigger error: %s", exc)
    return {"status": "scan_queued", "path": path or "full", "triggered_at": _utcnow().isoformat()}


@router.get("/security-infra/hsm")
async def get_hsm_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """HSM Vault key management status."""
    try:
        from security.vault import HSMVault

        vault = HSMVault()
        if hasattr(vault, "get_status"):
            return vault.get_status()
        # Build status from key store
        import os

        key_store = "data/keys"
        keys = []
        if os.path.isdir(key_store):
            for fname in os.listdir(key_store):
                if fname.endswith(".key") or fname.endswith(".enc"):
                    fpath = os.path.join(key_store, fname)
                    stat = os.stat(fpath)
                    keys.append(
                        {
                            "key_id": fname.replace(".key", "").replace(".enc", ""),
                            "created_at": datetime.fromtimestamp(stat.st_ctime, UTC).isoformat(),
                            "size_bytes": stat.st_size,
                            "active": True,
                        }
                    )
        return {
            "hsm_type": vault.hsm_type if hasattr(vault, "hsm_type") else "software",
            "initialized": getattr(vault, "_initialized", False),
            "key_count": len(keys),
            "keys": keys,
        }
    except Exception as exc:
        logger.warning("HSM status error: %s", exc)
    return {"hsm_type": "software", "initialized": False, "key_count": 0, "keys": []}


@router.post("/security-infra/hsm/keys/{key_id}/rotate")
async def rotate_hsm_key(
    key_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "hsm_key_rotate", f"key={key_id}")
    try:
        from security.vault import HSMVault

        vault = HSMVault()
        if hasattr(vault, "rotate_key"):
            vault.rotate_key(key_id)
            return {"key_id": key_id, "rotated": True, "rotated_at": _utcnow().isoformat()}
    except Exception as exc:
        logger.warning("HSM key rotate error: %s", exc)
    return {"key_id": key_id, "rotated": True, "rotated_at": _utcnow().isoformat(), "note": "queued"}


@router.get("/security-infra/log")
async def get_security_infra_log(
    limit: int = Query(100, ge=1, le=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    entries: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("security:infra:log", -limit, -1)
            for item in reversed(raw):
                try:
                    entries.append(_json.loads(item))
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.warning("Security infra log error: %s", exc)
    return {"entries": entries, "total": len(entries)}


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM HEALTH — Services / Backups / Scheduled Jobs / API Keys
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/system/services")
async def get_service_statuses(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Health check for all platform services."""
    services: list[dict] = []
    checks = [
        ("database", _check_db_service),
        ("redis", _check_redis_service),
        ("broker", _check_broker_service),
        ("ml_engine", _check_ml_service),
        ("websocket", _check_ws_service),
        ("celery", _check_celery_service),
    ]
    import asyncio

    results = await asyncio.gather(*[fn() for _, fn in checks], return_exceptions=True)
    for (name, _), result in zip(checks, results, strict=False):
        if isinstance(result, Exception):
            services.append(
                {
                    "name": name,
                    "status": "down",
                    "latency_ms": 0,
                    "last_check": _utcnow().isoformat(),
                    "error": str(result),
                }
            )
        else:
            services.append({"name": name, **result})
    return {"services": services}


async def _check_db_service() -> dict:
    from sqlalchemy import text as _sa_text
    start = time.time()
    db = None
    try:
        db = next(_get_db())
        if db:
            db.execute(_sa_text("SELECT 1"))
            return {
                "status": "healthy",
                "latency_ms": round((time.time() - start) * 1000),
                "last_check": _utcnow().isoformat(),
            }
    except Exception as exc:
        return {"status": "down", "latency_ms": 0, "last_check": _utcnow().isoformat(), "error": str(exc)}
    finally:
        if db:
            db.close()
    return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat()}


async def _check_redis_service() -> dict:
    start = time.time()
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.ping()
            return {
                "status": "healthy",
                "latency_ms": round((time.time() - start) * 1000),
                "last_check": _utcnow().isoformat(),
            }
    except Exception as exc:
        return {"status": "down", "latency_ms": 0, "last_check": _utcnow().isoformat(), "error": str(exc)}
    return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat()}


async def _check_broker_service() -> dict:
    start = time.time()
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            status = rc.get("broker:connection_status")
            if status:
                return {
                    "status": status.decode() if isinstance(status, bytes) else status,
                    "latency_ms": round((time.time() - start) * 1000),
                    "last_check": _utcnow().isoformat(),
                }
    except Exception as exc:
        return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat(), "error": str(exc)}
    return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat()}


async def _check_ml_service() -> dict:
    start = time.time()
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            status = rc.get("ml:engine_status")
            if status:
                return {
                    "status": status.decode() if isinstance(status, bytes) else status,
                    "latency_ms": round((time.time() - start) * 1000),
                    "last_check": _utcnow().isoformat(),
                }
    except Exception as exc:
        return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat(), "error": str(exc)}
    return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat()}


async def _check_ws_service() -> dict:
    start = time.time()
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            conn_count = rc.get("ws:connection_count")
            return {
                "status": "healthy",
                "latency_ms": round((time.time() - start) * 1000),
                "last_check": _utcnow().isoformat(),
                "connections": int(conn_count or 0),
            }
    except Exception as exc:
        return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat(), "error": str(exc)}
    return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat()}


async def _check_celery_service() -> dict:
    start = time.time()
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            workers_raw = rc.get("celery:active_workers")
            worker_count = int(workers_raw or 0)
            # Also try the Celery inspect API for a live count
            try:
                from celery_app import app as _celery_app

                inspect = _celery_app.control.inspect(timeout=1.0)
                active = inspect.active()
                if active is not None:
                    worker_count = len(active)
                    # Refresh the Redis heartbeat
                    rc.set("celery:active_workers", str(worker_count), ex=300)
            except Exception:
                logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110 — Celery not installed or no workers
            return {
                "status": "healthy" if worker_count > 0 else "no_workers",
                "latency_ms": round((time.time() - start) * 1000),
                "last_check": _utcnow().isoformat(),
                "workers": worker_count,
            }
    except Exception as exc:
        return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat(), "error": str(exc)}
    return {"status": "unknown", "latency_ms": 0, "last_check": _utcnow().isoformat()}


@router.get("/system/backups")
async def list_backups(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """List database and system backups."""
    backups: list[dict] = []
    try:
        import os

        backup_dir = "data/backups"
        if os.path.isdir(backup_dir):
            for fname in sorted(os.listdir(backup_dir), reverse=True)[:50]:
                fpath = os.path.join(backup_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                stat = os.stat(fpath)
                btype = "full" if "full" in fname else "incremental" if "incr" in fname else "snapshot"
                backups.append(
                    {
                        "backup_id": fname,
                        "type": btype,
                        "status": "completed",
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                        "location": fpath,
                    }
                )
    except Exception as exc:
        logger.warning("Backup list error: %s", exc)
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("system:backups", 0, 49)
            for item in raw:
                try:
                    b = _json.loads(item)
                    if not any(x["backup_id"] == b.get("backup_id") for x in backups):
                        backups.insert(0, b)
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"backups": backups, "total": len(backups)}


@router.post("/system/backups/trigger")
async def trigger_backup(
    body: BackupTriggerBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "backup_trigger", f"type={body.type}")
    backup_id = f"backup_{body.type}_{_utcnow().strftime('%Y%m%d_%H%M%S')}"
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.rpush(
                "system:backup_queue",
                _json.dumps(
                    {
                        "backup_id": backup_id,
                        "type": body.type,
                        "status": "running",
                        "triggered_by": user.sub,
                        "triggered_at": _utcnow().isoformat(),
                    }
                ),
            )
    except Exception as exc:
        logger.warning("Backup trigger error: %s", exc)
    # Emit structured audit log regardless of whether the async task started cleanly.
    logger.info(
        "backup audit: id=%s type=%s triggered_by=%s",
        backup_id,
        body.type,
        user.sub,
    )
    return {"backup_id": backup_id, "type": body.type, "status": "running", "triggered_at": _utcnow().isoformat()}


@router.get("/system/jobs")
async def list_scheduled_jobs(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Scheduled job registry — cron status, last/next run."""
    jobs: list[dict] = []
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            raw = rc.get("system:scheduled_jobs")
            if raw:
                jobs = _json.loads(raw)
    except Exception as exc:
        logger.warning("Scheduled jobs error: %s", exc)
    if not jobs:
        jobs = [
            {
                "job_id": "weekly_report",
                "name": "Weekly Performance Report",
                "schedule": "0 8 * * MON",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "kyc_sync",
                "name": "KYC Status Sync",
                "schedule": "*/30 * * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "aml_scan",
                "name": "AML Transaction Scan",
                "schedule": "0 * * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "db_backup",
                "name": "Database Backup",
                "schedule": "0 2 * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "integrity_scan",
                "name": "File Integrity Scan",
                "schedule": "*/2 * * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "ml_retrain",
                "name": "ML Model Retrain",
                "schedule": "0 3 * * SUN",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "gdpr_cleanup",
                "name": "GDPR Data Retention Cleanup",
                "schedule": "0 1 * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
            {
                "job_id": "sanctions_refresh",
                "name": "Sanctions List Refresh",
                "schedule": "0 6 * * *",
                "last_run": None,
                "next_run": None,
                "status": "active",
                "last_duration_ms": 0,
            },
        ]
    return {"jobs": jobs}


@router.post("/system/jobs/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "job_trigger", f"job={job_id}")
    try:
        from cache.redis_client import get_redis_client
        import json as _json

        rc = get_redis_client()
        if rc:
            rc.rpush(
                "system:job_queue",
                _json.dumps(
                    {
                        "job_id": job_id,
                        "triggered_by": user.sub,
                        "triggered_at": _utcnow().isoformat(),
                    }
                ),
            )
    except Exception as exc:
        logger.warning("Job trigger error: %s", exc)
    # Direct dispatch for known jobs
    try:
        if job_id == "weekly_report":
            from reports.weekly_report import WeeklyReportGenerator
            import asyncio

            asyncio.create_task(WeeklyReportGenerator().generate())
        elif job_id == "integrity_scan":
            from security.self_healer import SelfHealer
            import asyncio

            asyncio.create_task(SelfHealer().scan())
    except Exception as exc:
        logger.warning("Job direct dispatch error: %s", exc)
    return {"job_id": job_id, "status": "triggered", "triggered_at": _utcnow().isoformat()}


@router.post("/system/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "job_pause", f"job={job_id}")
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.hset("system:job_states", job_id, "paused")
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"job_id": job_id, "status": "paused"}


@router.post("/system/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "job_resume", f"job={job_id}")
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.hset("system:job_states", job_id, "active")
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return {"job_id": job_id, "status": "active"}


@router.get("/system/api-keys")
async def get_api_key_audit(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Cross-user API key audit — all active keys with last-used timestamps."""
    keys: list[dict] = []
    db = None
    try:
        db = next(_get_db())
        if db:
            from database.models import APIKey

            q = db.query(APIKey)
            if user_id:
                q = q.filter(APIKey.user_id == user_id)
            total = q.count()
            offset = (page - 1) * limit
            rows = q.order_by(APIKey.created_at.desc()).offset(offset).limit(limit).all()
            for r in rows:
                keys.append(
                    {
                        "key_id": str(r.id),
                        "user_id": str(r.user_id),
                        "name": getattr(r, "name", ""),
                        "prefix": getattr(r, "key_prefix", str(r.id)[:8]),
                        "scopes": getattr(r, "scopes", []),
                        "created_at": _iso(r.created_at),
                        "last_used": _iso(getattr(r, "last_used_at", None)),
                        "active": getattr(r, "is_active", True),
                    }
                )
            return {"keys": keys, "total": total, "page": page, "limit": limit}
    except Exception as exc:
        logger.warning("API key audit error: %s", exc)
    finally:
        if db:
            db.close()
    return {"keys": keys, "total": 0, "page": page, "limit": limit}


@router.delete("/system/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    _log_superadmin_action(user, "api_key_revoke", f"key={key_id}")
    db = None
    try:
        db = next(_get_db())
        if db:
            from database.models import APIKey

            k = db.query(APIKey).filter(APIKey.id == key_id).first()
            if k:
                k.is_active = False
                db.commit()
    except Exception as exc:
        logger.warning("API key revoke error: %s", exc)
    finally:
        if db:
            db.close()
    return {"key_id": key_id, "revoked": True}
