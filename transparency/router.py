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
# Map these to the canonical engine routes.

@router.get("/best-execution", summary="Best-execution report (alias)")
async def get_best_execution():
    """Best-execution report — alias for /report with frontend-expected key names."""
    engine = _get_transparency_engine()
    try:
        report = engine.get_transparency_report()
        return {
            "best_execution_score": report.get("best_execution_score", 0),
            "avg_slippage_bps": report.get("avg_slippage_bps", 0),
            "fill_rate": report.get("fill_rate", 1.0),
            "venues": report.get("venues", []),
            "executions": report.get("executions", []),
        }
    except Exception:
        return {"best_execution_score": 0, "avg_slippage_bps": 0, "fill_rate": 1.0, "venues": [], "executions": []}


@router.get("/slippage", summary="Slippage distribution (alias)")
async def get_slippage_alias():
    """Slippage distribution — alias for /slippage/distribution."""
    engine = _get_transparency_engine()
    try:
        return engine.get_slippage_distribution()
    except Exception:
        return {"distribution": [], "mean_bps": 0, "p95_bps": 0}


@router.get("/summary", summary="Execution transparency summary")
async def get_transparency_summary():
    """High-level transparency summary combining report, slippage, and venue stats."""
    engine = _get_transparency_engine()
    try:
        report = engine.get_transparency_report()
        return {
            "total_executions": report.get("total_executions", 0),
            "avg_slippage_bps": report.get("avg_slippage_bps", 0),
            "best_execution_score": report.get("best_execution_score", 0),
            "fill_rate": report.get("fill_rate", 1.0),
            "period_days": report.get("period_days", 30),
        }
    except Exception:
        return {"total_executions": 0, "avg_slippage_bps": 0, "best_execution_score": 0, "fill_rate": 1.0, "period_days": 30}


@router.get("/venues", summary="Trading venue performance")
async def get_venues():
    """Return per-venue execution quality metrics."""
    engine = _get_transparency_engine()
    try:
        report = engine.get_transparency_report()
        return {"venues": report.get("venues", [])}
    except Exception:
        return {"venues": []}
