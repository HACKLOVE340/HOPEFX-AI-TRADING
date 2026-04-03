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
            "overall_quality": report.overall_quality.value,
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
