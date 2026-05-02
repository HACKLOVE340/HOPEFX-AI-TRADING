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

    # ── Additional endpoints used by the frontend transparencyApi ────────────

    @router.get("/best-execution")
    async def get_best_execution(days: int = 30, symbol: str | None = None):
        """Best-execution summary — average slippage, fill ratio, latency per broker."""
        from datetime import datetime, timedelta
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        executions = [
            e for e in engine.executions
            if start <= e.timestamp <= end
            and (symbol is None or e.symbol == symbol)
        ]
        if not executions:
            return {"brokers": [], "summary": {"avg_slippage": 0, "avg_fill_ratio": 1.0, "avg_latency_ms": 0}}
        import statistics as _stats
        by_broker: dict = {}
        for e in executions:
            b = e.broker
            if b not in by_broker:
                by_broker[b] = {"slippages": [], "fill_ratios": [], "latencies": [], "count": 0}
            by_broker[b]["slippages"].append(e.slippage)
            by_broker[b]["fill_ratios"].append(e.fill_ratio)
            by_broker[b]["latencies"].append(e.latency_ms)
            by_broker[b]["count"] += 1
        brokers = [
            {
                "broker": b,
                "count": v["count"],
                "avg_slippage": _stats.mean(v["slippages"]),
                "avg_fill_ratio": _stats.mean(v["fill_ratios"]),
                "avg_latency_ms": _stats.mean(v["latencies"]),
            }
            for b, v in by_broker.items()
        ]
        all_slippages = [e.slippage for e in executions]
        all_fills = [e.fill_ratio for e in executions]
        all_latencies = [e.latency_ms for e in executions]
        return {
            "brokers": brokers,
            "period_days": days,
            "total_executions": len(executions),
            "summary": {
                "avg_slippage": _stats.mean(all_slippages),
                "avg_fill_ratio": _stats.mean(all_fills),
                "avg_latency_ms": _stats.mean(all_latencies),
            },
        }

    @router.get("/slippage")
    async def get_slippage_summary(days: int = 30):
        """Slippage summary and distribution for the given period."""
        from datetime import datetime, timedelta
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        distribution = engine.get_slippage_distribution(start, end)
        executions = [e for e in engine.executions if start <= e.timestamp <= end]
        import statistics as _stats
        slippages = [e.slippage for e in executions]
        return {
            "distribution": distribution,
            "period_days": days,
            "total_executions": len(executions),
            "avg_slippage": _stats.mean(slippages) if slippages else 0,
            "median_slippage": _stats.median(slippages) if slippages else 0,
            "positive_slippage_pct": (sum(1 for s in slippages if s > 0) / len(slippages) * 100) if slippages else 0,
        }

    @router.get("/venues")
    async def get_venue_analysis(days: int = 30):
        """Venue (broker) analysis — execution quality broken down by venue."""
        from datetime import datetime, timedelta
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        executions = [e for e in engine.executions if start <= e.timestamp <= end]
        if not executions:
            return {"venues": [], "period_days": days}
        import statistics as _stats
        by_venue: dict = {}
        for e in executions:
            v = e.broker
            if v not in by_venue:
                by_venue[v] = {"slippages": [], "fill_ratios": [], "latencies": [], "count": 0, "symbols": set()}
            by_venue[v]["slippages"].append(e.slippage)
            by_venue[v]["fill_ratios"].append(e.fill_ratio)
            by_venue[v]["latencies"].append(e.latency_ms)
            by_venue[v]["count"] += 1
            by_venue[v]["symbols"].add(e.symbol)
        return {
            "venues": [
                {
                    "venue": name,
                    "execution_count": d["count"],
                    "symbols": sorted(d["symbols"]),
                    "avg_slippage_bps": round(_stats.mean(d["slippages"]) * 10000, 2),
                    "avg_fill_ratio": round(_stats.mean(d["fill_ratios"]), 4),
                    "avg_latency_ms": round(_stats.mean(d["latencies"]), 2),
                    "quality_score": max(0.0, min(1.0, _stats.mean(d["fill_ratios"]) - abs(_stats.mean(d["slippages"])) / 10)),
                }
                for name, d in by_venue.items()
            ],
            "period_days": days,
        }

    @router.get("/orders/{order_id}")
    async def get_order_execution(order_id: str):
        """Get execution record(s) for a specific order ID."""
        records = engine.get_execution_audit_trail(order_id=order_id)
        if not records:
            from fastapi import HTTPException as _HTTPException
            raise _HTTPException(status_code=404, detail=f"No executions found for order {order_id!r}")
        return {"order_id": order_id, "executions": records, "count": len(records)}

    @router.get("/summary")
    async def get_transparency_summary(days: int = 30):
        """High-level execution transparency summary for the dashboard."""
        from datetime import datetime, timedelta
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        report = engine.generate_report(start, end)
        executions = [e for e in engine.executions if start <= e.timestamp <= end]
        import statistics as _stats
        slippages = [e.slippage for e in executions]
        return {
            "period_days": days,
            "total_executions": len(executions),
            "avg_slippage": _stats.mean(slippages) if slippages else 0,
            "avg_fill_ratio": report.avg_fill_ratio if report else 1.0,
            "avg_latency_ms": report.avg_latency_ms if report else 0,
            "overall_quality": report.execution_quality.value if report else "unknown",
            "report_available": report is not None,
        }

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
