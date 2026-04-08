# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""transparency/engine.py — ExecutionTransparencyEngine."""

import logging
import statistics
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

# Pip multipliers: 1 pip = 0.0001 for FX pairs, 0.01 for metals/indices

# ── Module constants ─────────────────────────────────────────────────────────
_PERCENTILE_99 = 99
_PERCENTILE_95 = 95
_PERCENTILE_90 = 90
_PERCENTILE_75 = 75
_PERCENTILE_60 = 60
_PERCENTILE_40 = 40
_SLIPPAGE_HALF = 0.5
_SLIPPAGE_BARS = 5
_LATENCY_P99_MS = 500
_LATENCY_P95_MS = 200
_LATENCY_P90_MS = 100
_FILL_RATE_THRESHOLD = 0.95
_SPREAD_COST_FACTOR = 2
_IMPACT_THRESHOLD = 90
_IMPACT_SEVERE = -2

FOREX_PIP_MULTIPLIER: float = 10_000.0  # e.g. EURUSD: 1 pip = 0.0001
METAL_PIP_MULTIPLIER: float = 100.0  # e.g. XAUUSD: 1 pip = 0.01

from transparency.models import (
    ExecutionQuality,
    ExecutionRecord,
    ExecutionReport,
)

logger = logging.getLogger(__name__)


class ExecutionTransparencyEngine:
    """
    Execution Transparency Engine

    Tracks and analyzes trade execution quality to provide
    transparency and insights on fill quality, slippage, and latency.

    Features:
    - Slippage analysis
    - Fill quality metrics
    - Latency statistics
    - Broker comparison
    - Execution audit trail
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize execution transparency engine."""
        self.config = config or {}
        self.executions: list[ExecutionRecord] = []
        self.reports: dict[str, ExecutionReport] = {}

        logger.info("Execution Transparency Engine initialized")

    def record_execution(
        self,
        order_id: str,
        symbol: str,
        side: str,
        requested_price: float,
        executed_price: float,
        requested_size: float,
        executed_size: float,
        latency_ms: float,
        broker: str,
        market_conditions: dict[str, Any] | None = None,
    ) -> ExecutionRecord:
        """
        Record a trade execution for analysis.

        Args:
            order_id: Order identifier
            symbol: Trading symbol
            side: BUY or SELL
            requested_price: Price requested
            executed_price: Actual execution price
            requested_size: Size requested
            executed_size: Size actually filled
            latency_ms: Execution latency in milliseconds
            broker: Broker name
            market_conditions: Optional market conditions at execution

        Returns:
            Execution record
        """
        # Calculate slippage
        # Positive slippage = worse fill; direction depends on side
        slippage = executed_price - requested_price if side == "BUY" else requested_price - executed_price

        # Convert slippage to pips using appropriate multiplier
        slippage_pips = slippage * FOREX_PIP_MULTIPLIER if "USD" in symbol else slippage * METAL_PIP_MULTIPLIER

        # Calculate slippage cost
        slippage_cost = slippage * executed_size

        # Calculate fill ratio
        fill_ratio = (executed_size / requested_size * 100) if requested_size > 0 else 100

        execution = ExecutionRecord(
            execution_id=f"exec_{len(self.executions) + 1}_{int(datetime.now(UTC).timestamp())}",
            order_id=order_id,
            symbol=symbol,
            side=side,
            requested_price=requested_price,
            executed_price=executed_price,
            requested_size=requested_size,
            executed_size=executed_size,
            slippage=slippage_pips,
            slippage_cost=slippage_cost,
            latency_ms=latency_ms,
            fill_ratio=fill_ratio,
            timestamp=datetime.now(UTC),
            broker=broker,
            market_conditions=market_conditions or {},
        )

        self.executions.append(execution)
        logger.info("Recorded execution %s: slippage=%s pips", execution.execution_id, slippage_pips)

        return execution

    def generate_report(
        self,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        symbol: str | None = None,
        broker: str | None = None,
    ) -> ExecutionReport:
        """
        Generate execution quality report.

        Args:
            period_start: Start of analysis period
            period_end: End of analysis period
            symbol: Filter by symbol (optional)
            broker: Filter by broker (optional)

        Returns:
            Execution report
        """
        period_end = period_end or datetime.now(UTC)
        period_start = period_start or (period_end - timedelta(days=30))

        # Ensure both bounds are timezone-aware (UTC) for safe comparison.
        if period_start.tzinfo is None:
            period_start = period_start.replace(tzinfo=UTC)
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=UTC)

        def _ts(dt: datetime) -> datetime:
            """Return dt as UTC-aware, converting naive datetimes."""
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        # Filter executions
        filtered = [e for e in self.executions if period_start <= _ts(e.timestamp) <= period_end]

        if symbol:
            filtered = [e for e in filtered if e.symbol == symbol]
        if broker:
            filtered = [e for e in filtered if e.broker == broker]

        if not filtered:
            logger.warning("No executions found for the specified criteria")
            # Return empty report
            return ExecutionReport(
                report_id=f"report_{int(datetime.now(UTC).timestamp())}",
                period_start=period_start,
                period_end=period_end,
                total_executions=0,
                avg_slippage=0,
                max_slippage=0,
                min_slippage=0,
                positive_slippage_count=0,
                negative_slippage_count=0,
                zero_slippage_count=0,
                avg_latency_ms=0,
                avg_fill_ratio=100,
                total_slippage_cost=0,
                execution_quality=ExecutionQuality.AVERAGE,
                broker_comparison={},
            )

        # Calculate metrics
        slippages = [e.slippage for e in filtered]
        latencies = [e.latency_ms for e in filtered]
        fill_ratios = [e.fill_ratio for e in filtered]

        avg_slippage = statistics.mean(slippages)
        max_slippage = max(slippages)
        min_slippage = min(slippages)

        positive_count = sum(1 for s in slippages if s < 0)  # Better than requested
        negative_count = sum(1 for s in slippages if s > 0)  # Worse than requested
        zero_count = sum(1 for s in slippages if s == 0)

        avg_latency = statistics.mean(latencies)
        avg_fill_ratio = statistics.mean(fill_ratios)
        total_cost = sum(e.slippage_cost for e in filtered)

        # Determine execution quality
        quality = self._calculate_quality(avg_slippage, avg_latency, avg_fill_ratio)

        # Broker comparison
        broker_comparison = self._compare_brokers(filtered)

        report = ExecutionReport(
            report_id=f"report_{int(datetime.now(UTC).timestamp())}",
            period_start=period_start,
            period_end=period_end,
            total_executions=len(filtered),
            avg_slippage=avg_slippage,
            max_slippage=max_slippage,
            min_slippage=min_slippage,
            positive_slippage_count=positive_count,
            negative_slippage_count=negative_count,
            zero_slippage_count=zero_count,
            avg_latency_ms=avg_latency,
            avg_fill_ratio=avg_fill_ratio,
            total_slippage_cost=total_cost,
            execution_quality=quality,
            broker_comparison=broker_comparison,
        )

        self.reports[report.report_id] = report
        logger.info("Generated report %s: %s executions analyzed", report.report_id, len(filtered))

        return report

    def _calculate_quality(self, avg_slippage: float, avg_latency: float, avg_fill_ratio: float) -> ExecutionQuality:
        """Calculate overall execution quality rating."""
        score = 100

        # Slippage impact (higher slippage = lower score)
        if avg_slippage > 5:
            score -= 30
        elif avg_slippage > 2:
            score -= 15
        elif avg_slippage > 0.5:
            score -= 5
        elif avg_slippage < 0:  # Positive slippage (improvement)
            score += 5

        # Latency impact
        if avg_latency > 500:
            score -= 20
        elif avg_latency > 200:
            score -= 10
        elif avg_latency > 100:
            score -= 5

        # Fill ratio impact
        if avg_fill_ratio < 90:
            score -= 20
        elif avg_fill_ratio < 95:
            score -= 10
        elif avg_fill_ratio < 99:
            score -= 5

        if score >= 90:
            return ExecutionQuality.EXCELLENT
        if score >= 75:
            return ExecutionQuality.GOOD
        if score >= 60:
            return ExecutionQuality.AVERAGE
        if score >= 40:
            return ExecutionQuality.POOR
        return ExecutionQuality.VERY_POOR

    def _compare_brokers(self, executions: list[ExecutionRecord]) -> dict[str, dict[str, float]]:
        """Compare execution quality across brokers."""
        broker_data: dict[str, list[ExecutionRecord]] = {}

        for ex in executions:
            if ex.broker not in broker_data:
                broker_data[ex.broker] = []
            broker_data[ex.broker].append(ex)

        comparison = {}
        for broker, execs in broker_data.items():
            slippages = [e.slippage for e in execs]
            latencies = [e.latency_ms for e in execs]
            fill_ratios = [e.fill_ratio for e in execs]

            comparison[broker] = {
                "total_executions": len(execs),
                "avg_slippage": statistics.mean(slippages),
                "avg_latency_ms": statistics.mean(latencies),
                "avg_fill_ratio": statistics.mean(fill_ratios),
                "max_slippage": max(slippages),
                "min_slippage": min(slippages),
            }

        return comparison

    def get_slippage_distribution(
        self,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> dict[str, Any]:
        """Get slippage distribution data for visualization."""
        period_end = period_end or datetime.now(UTC)
        period_start = period_start or (period_end - timedelta(days=30))

        filtered = [e for e in self.executions if period_start <= e.timestamp <= period_end]

        if not filtered:
            return {"buckets": [], "counts": []}

        slippages = [e.slippage for e in filtered]

        # Create histogram buckets
        buckets = ["< -2", "-2 to -1", "-1 to 0", "0", "0 to 1", "1 to 2", "> 2"]
        counts = [0] * 7

        for s in slippages:
            if s < -2:
                counts[0] += 1
            elif s < -1:
                counts[1] += 1
            elif s < 0:
                counts[2] += 1
            elif s == 0:
                counts[3] += 1
            elif s < 1:
                counts[4] += 1
            elif s < 2:
                counts[5] += 1
            else:
                counts[6] += 1

        return {
            "buckets": buckets,
            "counts": counts,
            "total": len(slippages),
            "mean": statistics.mean(slippages),
            "median": statistics.median(slippages),
            "std_dev": statistics.stdev(slippages) if len(slippages) > 1 else 0,
        }

    def get_latency_trend(
        self,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> dict[str, Any]:
        """Get latency trend over time."""
        period_end = period_end or datetime.now(UTC)
        period_start = period_start or (period_end - timedelta(days=30))

        filtered = sorted(
            [e for e in self.executions if period_start <= e.timestamp <= period_end],
            key=lambda x: x.timestamp,
        )

        # Group by day
        daily_latencies: dict[str, list[float]] = {}
        for e in filtered:
            day = e.timestamp.strftime("%Y-%m-%d")
            if day not in daily_latencies:
                daily_latencies[day] = []
            daily_latencies[day].append(e.latency_ms)

        dates = list(daily_latencies.keys())
        avg_latencies = [statistics.mean(v) for v in daily_latencies.values()]

        return {
            "dates": dates,
            "latencies": avg_latencies,
            "trend": "improving" if len(avg_latencies) > 1 and avg_latencies[-1] < avg_latencies[0] else "stable",
        }

    def get_execution_audit_trail(self, order_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get execution audit trail."""
        filtered = [e for e in self.executions if e.order_id == order_id] if order_id else self.executions[-limit:]

        return [
            {
                "execution_id": e.execution_id,
                "order_id": e.order_id,
                "symbol": e.symbol,
                "side": e.side,
                "requested_price": e.requested_price,
                "executed_price": e.executed_price,
                "slippage": e.slippage,
                "slippage_cost": e.slippage_cost,
                "latency_ms": e.latency_ms,
                "fill_ratio": e.fill_ratio,
                "timestamp": e.timestamp.isoformat(),
                "broker": e.broker,
            }
            for e in filtered
        ]
