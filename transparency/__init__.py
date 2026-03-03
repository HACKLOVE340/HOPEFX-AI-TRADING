"""
Phase 23: Execution Transparency Module

Provides detailed analytics and transparency for trade execution quality.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
import statistics

logger = logging.getLogger(__name__)

# Pip calculation multipliers for different asset types
FOREX_PIP_MULTIPLIER = 10000  # For currency pairs with 4 decimal places
METAL_PIP_MULTIPLIER = 100    # For precious metals and other 2 decimal assets


class ExecutionQuality(Enum):
    """Execution quality ratings"""
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"
    VERY_POOR = "very_poor"


@dataclass
class ExecutionRecord:
    """Record of a single trade execution"""
    execution_id: str
    order_id: str
    symbol: str
    side: str  # BUY or SELL
    requested_price: float
    executed_price: float
    requested_size: float
    executed_size: float
    slippage: float  # In pips/points
    slippage_cost: float  # In account currency
    latency_ms: float  # Execution latency in milliseconds
    fill_ratio: float  # Percentage filled
    timestamp: datetime
    broker: str
    market_conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionReport:
    """Summary report of execution quality"""
    report_id: str
    period_start: datetime
    period_end: datetime
    total_executions: int
    avg_slippage: float
    max_slippage: float
    min_slippage: float
    positive_slippage_count: int  # Better than requested
    negative_slippage_count: int  # Worse than requested
    zero_slippage_count: int
    avg_latency_ms: float
    avg_fill_ratio: float
    total_slippage_cost: float
    execution_quality: ExecutionQuality
    broker_comparison: Dict[str, Dict[str, float]]


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
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize execution transparency engine."""
        self.config = config or {}
        self.executions: List[ExecutionRecord] = []
        self.reports: Dict[str, ExecutionReport] = {}
        
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
        market_conditions: Optional[Dict[str, Any]] = None
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
        if side == "BUY":
            slippage = executed_price - requested_price  # Positive = worse
        else:
            slippage = requested_price - executed_price  # Positive = worse
        
        # Convert slippage to pips using appropriate multiplier
        slippage_pips = slippage * FOREX_PIP_MULTIPLIER if 'USD' in symbol else slippage * METAL_PIP_MULTIPLIER
        
        # Calculate slippage cost
        slippage_cost = slippage * executed_size
        
        # Calculate fill ratio
        fill_ratio = (executed_size / requested_size * 100) if requested_size > 0 else 100
        
        execution = ExecutionRecord(
            execution_id=f"exec_{len(self.executions) + 1}_{int(datetime.now().timestamp())}",
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
            timestamp=datetime.now(),
            broker=broker,
            market_conditions=market_conditions or {}
        )
        
        self.executions.append(execution)
        logger.info(f"Recorded execution {execution.execution_id}: slippage={slippage_pips:.2f} pips")
        return execution
    
    def generate_report(
        self,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        symbol: Optional[str] = None,
        broker: Optional[str] = None
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
        period_end = period_end or datetime.now()
        period_start = period_start or (period_end - timedelta(days=30))
        
        # Filter executions
        filtered = [
            e for e in self.executions
            if period_start <= e.timestamp <= period_end
        ]
        
        if symbol:
            filtered = [e for e in filtered if e.symbol == symbol]
        if broker:
            filtered = [e for e in filtered if e.broker == broker]
        
        if not filtered:
            logger.warning("No executions found for the specified criteria")
            # Return empty report
            return ExecutionReport(
                report_id=f"report_{int(datetime.now().timestamp())}",
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
                broker_comparison={}
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
            report_id=f"report_{int(datetime.now().timestamp())}",
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
            broker_comparison=broker_comparison
        )
        
        self.reports[report.report_id] = report
        logger.info(f"Generated report {report.report_id}: {len(filtered)} executions analyzed")
        return report
    
    def _calculate_quality(
        self,
        avg_slippage: float,
        avg_latency: float,
        avg_fill_ratio: float
    ) -> ExecutionQuality:
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
        elif score >= 75:
            return ExecutionQuality.GOOD
        elif score >= 60:
            return ExecutionQuality.AVERAGE
        elif score >= 40:
            return ExecutionQuality.POOR
        else:
            return ExecutionQuality.VERY_POOR
    
    def _compare_brokers(self, executions: List[ExecutionRecord]) -> Dict[str, Dict[str, float]]:
        """Compare execution quality across brokers."""
        broker_data: Dict[str, List[ExecutionRecord]] = {}
        
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
                'total_executions': len(execs),
                'avg_slippage': statistics.mean(slippages),
                'avg_latency_ms': statistics.mean(latencies),
                'avg_fill_ratio': statistics.mean(fill_ratios),
                'max_slippage': max(slippages),
                'min_slippage': min(slippages),
            }
        
        return comparison
    
    def get_slippage_distribution(
        self,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get slippage distribution data for visualization."""
        period_end = period_end or datetime.now()
        period_start = period_start or (period_end - timedelta(days=30))
        
        filtered = [
            e for e in self.executions
            if period_start <= e.timestamp <= period_end
        ]
        
        if not filtered:
            return {'buckets': [], 'counts': []}
        
        slippages = [e.slippage for e in filtered]
        
        # Create histogram buckets
        buckets = ['< -2', '-2 to -1', '-1 to 0', '0', '0 to 1', '1 to 2', '> 2']
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
            'buckets': buckets,
            'counts': counts,
            'total': len(slippages),
            'mean': statistics.mean(slippages),
            'median': statistics.median(slippages),
            'std_dev': statistics.stdev(slippages) if len(slippages) > 1 else 0
        }
    
    def get_latency_trend(
        self,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get latency trend over time."""
        period_end = period_end or datetime.now()
        period_start = period_start or (period_end - timedelta(days=30))
        
        filtered = sorted([
            e for e in self.executions
            if period_start <= e.timestamp <= period_end
        ], key=lambda x: x.timestamp)
        
        # Group by day
        daily_latencies: Dict[str, List[float]] = {}
        for e in filtered:
            day = e.timestamp.strftime('%Y-%m-%d')
            if day not in daily_latencies:
                daily_latencies[day] = []
            daily_latencies[day].append(e.latency_ms)
        
        dates = list(daily_latencies.keys())
        avg_latencies = [statistics.mean(v) for v in daily_latencies.values()]
        
        return {
            'dates': dates,
            'latencies': avg_latencies,
            'trend': 'improving' if len(avg_latencies) > 1 and avg_latencies[-1] < avg_latencies[0] else 'stable'
        }
    
    def get_execution_audit_trail(
        self,
        order_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get execution audit trail."""
        if order_id:
            filtered = [e for e in self.executions if e.order_id == order_id]
        else:
            filtered = self.executions[-limit:]
        
        return [
            {
                'execution_id': e.execution_id,
                'order_id': e.order_id,
                'symbol': e.symbol,
                'side': e.side,
                'requested_price': e.requested_price,
                'executed_price': e.executed_price,
                'slippage': e.slippage,
                'slippage_cost': e.slippage_cost,
                'latency_ms': e.latency_ms,
                'fill_ratio': e.fill_ratio,
                'timestamp': e.timestamp.isoformat(),
                'broker': e.broker,
            }
            for e in filtered
        ]


def create_transparency_router(engine: 'ExecutionTransparencyEngine'):
    """
    Create a FastAPI router for the Execution Transparency module.

    Args:
        engine: ExecutionTransparencyEngine instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    from typing import Optional

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
        end = datetime.now()
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
        end = datetime.now()
        start = end - timedelta(days=days)
        return engine.get_slippage_distribution(start, end)

    @router.get("/latency/trend")
    async def get_latency_trend(days: int = 30):
        """Get daily latency trend data."""
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=days)
        return engine.get_latency_trend(start, end)

    @router.get("/audit")
    async def get_audit_trail(order_id: Optional[str] = None, limit: int = 100):
        """Get execution audit trail, optionally filtered by order ID."""
        return engine.get_execution_audit_trail(order_id=order_id, limit=limit)

    return router


# Module exports
__all__ = [
    'ExecutionTransparencyEngine',
    'ExecutionRecord',
    'ExecutionReport',
    'ExecutionQuality',
    'create_transparency_router',
]
