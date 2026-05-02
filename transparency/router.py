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

    @router.get("/summary")
    async def get_summary(days: int = 30):
        """High-level execution quality summary for the last N days."""
        from datetime import datetime, timedelta

        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        report = engine.generate_report(start, end)
        total = len(engine.executions) if hasattr(engine, "executions") else 0
        if report is None:
            return {
                "total_executions": total,
                "avg_slippage": 0.0,
                "avg_latency_ms": 0.0,
                "avg_fill_ratio": 1.0,
                "overall_quality": "no_data",
                "period_days": days,
            }
        return {
            "total_executions": report.total_executions,
            "avg_slippage": report.avg_slippage,
            "max_slippage": report.max_slippage,
            "avg_latency_ms": report.avg_latency_ms,
            "avg_fill_ratio": report.avg_fill_ratio,
            "overall_quality": report.execution_quality.value,
            "period_days": days,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
        }

    @router.get("/orders/{order_id}")
    async def get_order_execution(order_id: str):
        """Get execution details for a specific order."""
        records = engine.get_execution_audit_trail(order_id=order_id, limit=1)
        if not records:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"No execution found for order {order_id}")
        return records[0]

    @router.get("/best-execution")
    async def get_best_execution(days: int = 30):
        """Best-execution compliance metrics for the last N days."""
        from datetime import datetime, timedelta

        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        dist = engine.get_slippage_distribution(start, end)
        trend = engine.get_latency_trend(start, end)
        return {
            "slippage_distribution": dist,
            "latency_trend": trend,
            "period_days": days,
        }

    @router.get("/slippage")
    async def get_slippage(days: int = 30):
        """Slippage report for the last N days (alias for /slippage/distribution)."""
        from datetime import datetime, timedelta

        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        return engine.get_slippage_distribution(start, end)

    @router.get("/venues")
    async def get_venue_analysis():
        """Per-venue execution quality breakdown."""
        records = engine.get_execution_audit_trail(limit=1000)
        venues: dict[str, dict] = {}
        for r in records:
            broker = r.get("broker", "unknown")
            if broker not in venues:
                venues[broker] = {"executions": 0, "total_slippage": 0.0, "total_latency": 0.0}
            venues[broker]["executions"] += 1
            venues[broker]["total_slippage"] += float(r.get("slippage", 0.0))
            venues[broker]["total_latency"] += float(r.get("latency_ms", 0.0))
        result = []
        for name, stats in venues.items():
            n = stats["executions"] or 1
            result.append({
                "venue": name,
                "executions": stats["executions"],
                "avg_slippage": stats["total_slippage"] / n,
                "avg_latency_ms": stats["total_latency"] / n,
            })
        return result

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
