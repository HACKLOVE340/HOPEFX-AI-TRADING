"""
Prometheus metrics and health monitoring.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from prometheus_client.registry import CollectorRegistry

from src.core.config import settings

# Custom registry
REGISTRY = CollectorRegistry()

# Application info
APP_INFO = Info(
    "hopefx_app",
    "Application information",
    registry=REGISTRY
)
APP_INFO.info({
    "version": settings.app_version,
    "environment": settings.environment.value,
    "trading_mode": settings.trading_mode.value,
})

# Trading metrics
ORDERS_SUBMITTED = Counter(
    "hopefx_orders_submitted_total",
    "Total orders submitted",
    ["symbol", "direction", "order_type"],
    registry=REGISTRY
)

ORDERS_FILLED = Counter(
    "hopefx_orders_filled_total",
    "Total orders filled",
    ["symbol", "direction"],
    registry=REGISTRY
)

POSITIONS_OPEN = Gauge(
    "hopefx_positions_open",
    "Current open positions",
    ["symbol", "direction"],
    registry=REGISTRY
)

PNL_REALIZED = Gauge(
    "hopefx_pnl_realized",
    "Realized P&L",
    ["symbol"],
    registry=REGISTRY
)

PNL_UNREALIZED = Gauge(
    "hopefx_pnl_unrealized",
    "Unrealized P&L",
    ["symbol"],
    registry=REGISTRY
)

EQUITY = Gauge(
    "hopefx_equity",
    "Account equity",
    ["account_id"],
    registry=REGISTRY
)

DRAWDOWN = Gauge(
    "hopefx_drawdown_current",
    "Current drawdown percentage",
    ["account_id"],
    registry=REGISTRY
)

# Latency metrics
LATENCY_ORDER_SUBMIT = Histogram(
    "hopefx_latency_order_submit_seconds",
    "Order submission latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    registry=REGISTRY
)

LATENCY_MARKET_DATA = Histogram(
    "hopefx_latency_market_data_seconds",
    "Market data processing latency",
    buckets=[0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01],
    registry=REGISTRY
)

# ML metrics
PREDICTION_LATENCY = Histogram(
    "hopefx_prediction_latency_seconds",
    "ML prediction latency",
    registry=REGISTRY
)

MODEL_DRIFT = Gauge(
    "hopefx_model_drift_score",
    "Current model drift score",
    ["model_name"],
    registry=REGISTRY
)

# Risk metrics
RISK_EVENTS = Counter(
    "hopefx_risk_events_total",
    "Risk events triggered",
    ["level", "rule"],
    registry=REGISTRY
)

KILL_SWITCH_ACTIVE = Gauge(
    "hopefx_kill_switch_active",
    "Kill switch state (1=active)",
    registry=REGISTRY
)

DB_CONNECTIONS_ACTIVE = Gauge(
    "hopefx_db_connections_active",
    "Number of active database connections",
    registry=REGISTRY
)

DB_QUERY_DURATION = Histogram(
    "hopefx_db_query_duration_seconds",
    "Database query duration in seconds",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    registry=REGISTRY
)

CACHE_HITS = Counter(
    "hopefx_cache_hits_total",
    "Total cache hits",
    registry=REGISTRY
)

CACHE_MISSES = Counter(
    "hopefx_cache_misses_total",
    "Total cache misses",
    registry=REGISTRY
)


def get_metrics() -> bytes:
    """Export metrics in Prometheus format."""
    return generate_latest(REGISTRY)


class HealthChecker:
    """System health monitoring."""
    
    def __init__(self):
        self._checks: dict[str, callable] = {}
        self._status: dict[str, bool] = {}
    
    def register(self, name: str, check_fn: callable) -> None:
        """Register health check."""
        self._checks[name] = check_fn
    
    async def check(self) -> dict[str, Any]:
        """Run all health checks."""
        results = {}
        healthy = True
        
        for name, check_fn in self._checks.items():
            try:
                result = await check_fn()
                self._status[name] = bool(result)
                results[name] = "healthy" if result else "unhealthy"
                if not result:
                    healthy = False
            except Exception as e:
                self._status[name] = False
                results[name] = f"error: {e}"
                healthy = False
        
        return {
            "status": "healthy" if healthy else "unhealthy",
            "checks": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
