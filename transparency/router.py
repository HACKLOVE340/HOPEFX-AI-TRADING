# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""transparency/router.py — FastAPI router for execution transparency."""

from datetime import timezone

UTC = timezone.utc

from transparency.engine import ExecutionTransparencyEngine


def create_transparency_router(engine: "ExecutionTransparencyEngine"):
    """
    Create a FastAPI router for the Execution Transparency module.

    Args:
        engine: ExecutionTransparencyEngine instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/transparency", tags=["Transparency"])

    class RecordExecutionRequest(BaseModel):
        order_id: str
        symbol: str
        side: str
        requested_price: float
        executed_price: float
        requested_size: float
        executed_size: float
        latency_ms: float = 0.0
        broker: str = "unknown"

    @router.post("/executions")
    async def record_execution(req: RecordExecutionRequest):
        """Record a trade execution for transparency tracking."""
        record = engine.record_execution(
            order_id=req.order_id,
            symbol=req.symbol,
            side=req.side,
            requested_price=req.requested_price,
            executed_price=req.executed_price,
            requested_size=req.requested_size,
            executed_size=req.executed_size,
            latency_ms=req.latency_ms,
            broker=req.broker,
        )
        return {
            "execution_id": record.execution_id,
            "slippage": record.slippage,
            "slippage_cost": record.slippage_cost,
            "fill_ratio": record.fill_ratio,
            "timestamp": record.timestamp.isoformat(),
        }

    @router.get("/report")
    async def get_report(days: int = 30):
        """Generate an execution quality report for the last N days."""
        from datetime import datetime, timedelta

        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        report = engine.generate_report(start, end)
        if report is None:
            return {"message": "No execution data available", "executions": 0}
        return {
            "report_id": report.report_id,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "total_executions": report.total_executions,
            "avg_slippage": report.avg_slippage,
            "max_slippage": report.max_slippage,
            "min_slippage": report.min_slippage,
            "avg_latency_ms": report.avg_latency_ms,
            "avg_fill_ratio": report.avg_fill_ratio,
            "overall_quality": report.execution_quality.value,
        }

    @router.get("/slippage/distribution")
    async def get_slippage_distribution(days: int = 30):
        """Get slippage distribution data for charting."""
        from datetime import datetime, timedelta

        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        return engine.get_slippage_distribution(start, end)

    @router.get("/latency/trend")
    async def get_latency_trend(days: int = 30):
        """Get daily latency trend data."""
        from datetime import datetime, timedelta

        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        return engine.get_latency_trend(start, end)

    @router.get("/audit")
    async def get_audit_trail(order_id: str | None = None, limit: int = 100):
        """Get execution audit trail, optionally filtered by order ID."""
        return engine.get_execution_audit_trail(order_id=order_id, limit=limit)

    return router


# Module exports

# Module-level router — imported by core.router_registry
_transparency_engine_instance = None


def _get_transparency_engine():
    global _transparency_engine_instance
    if _transparency_engine_instance is None:
        _transparency_engine_instance = ExecutionTransparencyEngine()
    return _transparency_engine_instance


router = create_transparency_router(_get_transparency_engine())


# ── Frontend-expected aliases ──────────────────────────────────────────────────
# TCADashboard.tsx calls /transparency/best-execution, /slippage, /summary, /venues.
# All delegate to the real ExecutionTransparencyEngine methods:
#   generate_report()         → best-execution, summary
#   get_slippage_distribution() → slippage
#   broker_comparison field   → venues

import logging as _logging

_alias_logger = _logging.getLogger(__name__)

# Map ExecutionQuality enum values to a 0-100 score for the frontend.
_QUALITY_SCORE: dict[str, int] = {
    "excellent": 95,
    "good": 80,
    "average": 60,
    "poor": 40,
    "very_poor": 20,
}


def _broker_comparison_to_venues(broker_comparison: dict) -> list:
    """Convert broker_comparison mapping to a frontend-friendly venue list."""
    return [
        {
            "name": broker,
            "avg_slippage": round(float(stats.get("avg_slippage", 0)), 4),
            "avg_latency_ms": round(float(stats.get("avg_latency_ms", 0)), 2),
            "avg_fill_ratio": round(float(stats.get("avg_fill_ratio", 100)), 2),
            "total_executions": int(stats.get("total_executions", 0)),
        }
        for broker, stats in (broker_comparison or {}).items()
    ]


@router.get("/best-execution", summary="Best-execution report (alias)")
async def get_best_execution(days: int = 30):
    """
    Best-execution report in the shape expected by TCADashboard.tsx.
    Calls engine.generate_report() for the last *days* days.
    """
    from datetime import datetime, timedelta

    engine = _get_transparency_engine()
    try:
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        report = engine.generate_report(start, end)
        quality_name = report.execution_quality.value if report.execution_quality else "average"
        return {
            "best_execution_score": _QUALITY_SCORE.get(quality_name, 60),
            "avg_slippage_bps": round(report.avg_slippage, 4),
            "fill_rate": round(report.avg_fill_ratio / 100.0, 4),
            "venues": _broker_comparison_to_venues(report.broker_comparison),
            "executions": report.total_executions,
        }
    except Exception as exc:
        _alias_logger.warning("best-execution alias failed: %s", exc)
        return {"best_execution_score": 0, "avg_slippage_bps": 0, "fill_rate": 1.0, "venues": [], "executions": 0}


@router.get("/slippage", summary="Slippage distribution (alias)")
async def get_slippage_alias(days: int = 30):
    """
    Slippage distribution — alias for /slippage/distribution.
    Accepts the same ``days`` query param and forwards correct datetime bounds.
    """
    from datetime import datetime, timedelta

    engine = _get_transparency_engine()
    try:
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        return engine.get_slippage_distribution(start, end)
    except Exception as exc:
        _alias_logger.warning("slippage alias failed: %s", exc)
        return {"buckets": [], "counts": [], "total": 0, "mean": 0, "median": 0, "std_dev": 0}


@router.get("/summary", summary="Execution transparency summary")
async def get_transparency_summary(days: int = 30):
    """
    High-level transparency summary derived from engine.generate_report().
    Calls generate_report() so real execution data is always returned.
    """
    from datetime import datetime, timedelta

    engine = _get_transparency_engine()
    try:
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        report = engine.generate_report(start, end)
        quality_name = report.execution_quality.value if report.execution_quality else "average"
        return {
            "total_executions": report.total_executions,
            "avg_slippage_bps": round(report.avg_slippage, 4),
            "best_execution_score": _QUALITY_SCORE.get(quality_name, 60),
            "fill_rate": round(report.avg_fill_ratio / 100.0, 4),
            "period_days": days,
        }
    except Exception as exc:
        _alias_logger.warning("transparency summary failed: %s", exc)
        return {"total_executions": 0, "avg_slippage_bps": 0, "best_execution_score": 0, "fill_rate": 1.0, "period_days": days}


@router.get("/venues", summary="Trading venue performance")
async def get_venues(days: int = 30):
    """
    Per-venue execution quality metrics derived from broker_comparison
    in engine.generate_report().
    """
    from datetime import datetime, timedelta

    engine = _get_transparency_engine()
    try:
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        report = engine.generate_report(start, end)
        return {"venues": _broker_comparison_to_venues(report.broker_comparison)}
    except Exception as exc:
        _alias_logger.warning("venues failed: %s", exc)
        return {"venues": []}
