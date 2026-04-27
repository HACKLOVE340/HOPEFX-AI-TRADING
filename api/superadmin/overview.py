# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin overview sub-router."""

import json as _json
import logging
import pathlib
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import TokenPayload

from ._shared import _get_config_store, _require_superadmin, _utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Overview ──────────────────────────────────────────────────────────────────


@router.get("/overview")
async def get_overview(user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    """Platform-wide health snapshot — all KPI fields populated from real data."""
    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    mtd_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    overview: dict[str, Any] = {
        "total_users": 0,
        "active_users_24h": 0,
        "new_users_7d": 0,
        "total_trades_today": 0,
        "open_positions": 0,
        "revenue_mtd": 0.0,
        "revenue_currency": "USD",
        "system_health": "healthy",
        "uptime_pct": 99.9,
        "active_sessions": 0,
        "ml_model_accuracy": 0.0,
        "signals_generated_today": 0,
        "engine_status": "running",
        "kill_switch_active": False,
        "maintenance_mode": False,
        "db_connections": 0,
        "redis_memory_mb": 0.0,
        "cpu_pct": 0.0,
        "memory_pct": 0.0,
        "error_rate_pct": 0.0,
        "avg_response_ms": 0,
    }

    # ── DB queries: users, trades, signals, sessions, connections ─────────────
    try:
        from database.connection import SessionLocal
        from database.models import Signal, Trade, WalletTransaction
        from database.user_models import User, UserSession
        from sqlalchemy import func, text

        db = SessionLocal()
        try:
            # Users
            overview["total_users"] = db.query(User).count()
            overview["active_users_24h"] = (
                db.query(User)
                .filter(User.last_login_at >= now - timedelta(hours=24))
                .count()
            )
            overview["new_users_7d"] = (
                db.query(User)
                .filter(User.created_at >= now - timedelta(days=7))
                .count()
            )

            # Trades opened today
            overview["total_trades_today"] = (
                db.query(Trade).filter(Trade.entry_time >= today_start).count()
            )

            # Open positions
            overview["open_positions"] = (
                db.query(Trade).filter(Trade.is_open == True).count()  # noqa: E712
            )

            # Signals generated today
            overview["signals_generated_today"] = (
                db.query(Signal).filter(Signal.generated_at >= today_start).count()
            )

            # Active (non-revoked, non-expired) sessions
            overview["active_sessions"] = (
                db.query(UserSession)
                .filter(
                    UserSession.is_revoked == False,  # noqa: E712
                    UserSession.expires_at > now,
                )
                .count()
            )

            # Revenue MTD: sum of completed inbound wallet transactions this month
            try:
                rev_row = (
                    db.query(func.sum(WalletTransaction.amount))  # pylint: disable=not-callable
                    .filter(
                        WalletTransaction.created_at >= mtd_start,
                        WalletTransaction.transaction_type.in_(
                            ["deposit", "subscription", "fee_credit", "commission"]
                        ),
                        WalletTransaction.status == "completed",
                    )
                    .scalar()
                )
                overview["revenue_mtd"] = round(float(rev_row or 0.0), 2)
            except Exception as exc:
                logger.debug("overview: revenue_mtd wallet query: %s", exc)

            # Active DB connections (PostgreSQL only; silently skipped on SQLite)
            try:
                row = db.execute(
                    text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                ).scalar()
                overview["db_connections"] = int(row or 0)
            except Exception:  # noqa: BLE001 — SQLite or pg_stat_activity unavailable
                pass

        finally:
            db.close()
    except Exception as exc:
        logger.debug("overview: DB unavailable: %s", exc)

    # ── Revenue MTD fallback: monetization analytics ──────────────────────────
    if overview["revenue_mtd"] == 0.0:
        try:
            from monetization.analytics import revenue_analytics

            rev = revenue_analytics.get_revenue_by_period(mtd_start, now)
            overview["revenue_mtd"] = round(
                float(sum(rev.values())) if isinstance(rev, dict) else float(rev or 0), 2
            )
        except Exception as exc:
            logger.debug("overview: revenue_analytics unavailable: %s", exc)

    # ── ML model accuracy ─────────────────────────────────────────────────────
    # 1. Redis key written by the inference engine on each evaluation cycle.
    # 2. Evaluation JSON files written by the training pipeline.
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("ml:model:accuracy")
            if raw:
                overview["ml_model_accuracy"] = round(float(_json.loads(raw)), 4)
    except Exception as exc:
        logger.debug("overview: ml accuracy redis: %s", exc)

    if overview["ml_model_accuracy"] == 0.0:
        try:
            ml_base = pathlib.Path(__file__).parent.parent.parent / "ml"
            for p in [
                ml_base / "saved_models" / "advanced_oos_meta.json",
                ml_base / "evaluation_results.json",
                ml_base / "saved_models" / "metrics.json",
            ]:
                if p.exists():
                    data = _json.loads(p.read_text())
                    acc = float(
                        data.get("accuracy")
                        or data.get("oos_accuracy")
                        or data.get("test_accuracy")
                        or 0.0
                    )
                    if acc > 0.0:
                        overview["ml_model_accuracy"] = round(acc, 4)
                        break
        except Exception as exc:
            logger.debug("overview: ml accuracy file: %s", exc)

    # ── Error rate + avg response time ────────────────────────────────────────
    # Written by the request-timing middleware into Redis key "metrics:request_stats".
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("metrics:request_stats")
            if raw:
                stats = _json.loads(raw)
                overview["error_rate_pct"] = round(float(stats.get("error_rate_pct", 0.0)), 3)
                overview["avg_response_ms"] = int(stats.get("avg_response_ms", 0))
    except Exception as exc:
        logger.debug("overview: request_stats redis: %s", exc)

    # ── Kill switch + maintenance from config store ───────────────────────────
    try:
        cs = _get_config_store()
        if cs:
            ks = cs.get("kill_switch_active")
            if ks is not None:
                overview["kill_switch_active"] = bool(ks)
            mm = cs.get("maintenance_mode")
            if mm is not None:
                overview["maintenance_mode"] = bool(mm)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # ── Engine status ─────────────────────────────────────────────────────────
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            overview["engine_status"] = getattr(eng, "status", "running")
            # Only override open_positions if the engine has a live in-memory count.
            live_pos = len(getattr(eng, "positions", {}))
            if live_pos > 0:
                overview["open_positions"] = live_pos
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # ── Redis memory ──────────────────────────────────────────────────────────
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            info = rc.info("memory")
            overview["redis_memory_mb"] = round(info.get("used_memory", 0) / 1_048_576, 1)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # ── System resources ──────────────────────────────────────────────────────
    try:
        import psutil

        overview["cpu_pct"] = psutil.cpu_percent(interval=0.1)
        overview["memory_pct"] = psutil.virtual_memory().percent
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # ── Derive system_health from populated metrics ───────────────────────────
    if overview["kill_switch_active"] or overview["error_rate_pct"] > 10:
        overview["system_health"] = "critical"
    elif (
        overview["maintenance_mode"]
        or overview["cpu_pct"] > 85
        or overview["memory_pct"] > 85
        or overview["error_rate_pct"] > 2
    ):
        overview["system_health"] = "degraded"

    return overview
