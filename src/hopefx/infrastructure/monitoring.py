# src/hopefx/infrastructure/monitoring.py
"""
Production monitoring with Prometheus metrics and health probes.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Literal

import structlog
from prometheus_client import Counter, Gauge, Histogram, Info, generate_latest, CONTENT_TYPE_LATEST

logger = structlog.get_logger()

# Prometheus metrics
METRICS = {
    # System
    "info": Info("hopefx", "Application information"),
    "uptime_seconds": Gauge("hopefx_uptime_seconds", "Application uptime"),
    
    # Trading
    "orders_total": Counter(
        "hopefx_orders_total",
        "Total orders",
        ["status", "side", "symbol"]
    ),
    "position_size": Gauge(
        "hopefx_position_size_lots",
        "Current position size",
        ["symbol", "direction"]
    ),
    "unrealized_pnl": Gauge(
        "hopefx_unrealized_pnl_usd",
        "Unrealized P&L",
        ["symbol"]
    ),
    "equity": Gauge("hopefx_equity_usd", "Account equity"),
    "margin_used": Gauge("hopefx_margin_used_pct", "Margin utilization"),
    
    # Performance
    "order_latency": Histogram(
        "hopefx_order_latency_ms",
        "Order round-trip latency",
        buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
    ),
    "fill_slippage": Histogram(
        "hopefx_fill_slippage_bps",
        "Execution slippage in basis points",
        buckets=[0.5, 1, 2, 5, 10, 25, 50, 100]
    ),
    
    # ML
    "prediction_latency": Histogram(
        "hopefx_prediction_latency_ms",
        "ML inference latency",
        buckets=[1, 5, 10, 25, 50, 100]
    ),
    "model_drift": Gauge(
        "hopefx_model_drift_score",
        "Data drift detection score",
        ["model"]
    ),
    "prediction_confidence": Histogram(
        "hopefx_prediction_confidence",
        "Model confidence scores",
        buckets=[0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]
    ),
    
    # Risk
    "var_95": Gauge("hopefx_var_95_usd", "95% Value at Risk"),
    "current_drawdown": Gauge("hopefx_current_drawdown_pct", "Current drawdown"),
    "risk_level": Gauge("hopefx_risk_level", "Current risk level (0-4)"),
    
    # Infrastructure
    "redis_ops_total": Counter(
        "hopefx_redis_ops_total",
        "Redis operations",
        ["operation", "status"]
    ),
    "db_connections": Gauge("hopefx_db_connections_active", "Active DB connections"),
    "event_queue_depth": Gauge(
        "hopefx_event_queue_depth",
        "Event bus queue depth",
        ["priority"]
    ),
}


class HealthChecker:
    """
    Kubernetes-compatible health probes.
    """
    
    def __init__(self) -> None:
        self._start_time = time.time()
        self._last_tick: float = 0
        self._last_order: float = 0
        self._is_healthy = True
        self._readiness_checks: dict[str, bool] = {
            "database": False,
            "redis": False,
            "broker": False,
            "ml_model": False,
        }
    
    def record_tick(self) -> None:
        """Record market data receipt."""
        self._last_tick = time.time()
    
    def record_order(self) -> None:
        """Record order execution."""
        self._last_order = time.time()
    
    def set_ready(self, component: str, ready: bool) -> None:
        """Update readiness status."""
        self._readiness_checks[component] = ready
    
    def liveness_check(self) -> tuple[bool, dict]:
        """
        Liveness probe: Is the process running?
        Fails if no market data for 60 seconds.
        """
        tick_age = time.time() - self._last_tick
        
        alive = tick_age < 60 and self._is_healthy
        
        return alive, {
            "status": "alive" if alive else "dead",
            "tick_age_seconds": tick_age,
            "uptime_seconds": time.time() - self._start_time
        }
    
    def readiness_check(self) -> tuple[bool, dict]:
        """
        Readiness probe: Is the service ready to accept traffic?
        """
        ready = all(self._readiness_checks.values())
        
        return ready, {
            "status": "ready" if ready else "not_ready",
            "checks": self._readiness_checks
        }
    
    def startup_check(self) -> tuple[bool, dict]:
        """
        Startup probe: Has the application started successfully?
        """
        started = time.time() - self._start_time > 10  # Min 10s startup
        
        return started, {
            "status": "started" if started else "starting",
            "elapsed_seconds": time.time() - self._start_time
        }


class MetricsExporter:
    """
    Prometheus metrics export.
    """
    
    def __init__(self) -> None:
        self._health = HealthChecker()
        
        # Set static info
        METRICS["info"].info({
            "version": "6.0.0",
            "environment": "production"
        })
    
    def record_order(
        self,
        status: Literal["submitted", "filled", "rejected"],
        side: Literal["BUY", "SELL"],
        symbol: str,
        latency_ms: float | None = None,
        slippage_bps: float | None = None
    ) -> None:
        """Record order metrics."""
        METRICS["orders_total"].labels(
            status=status,
            side=side.lower(),
            symbol=symbol
        ).inc()
        
        if latency_ms is not None:
            METRICS["order_latency"].observe(latency_ms)
        
        if slippage_bps is not None:
            METRICS["fill_slippage"].observe(slippage_bps)
        
        self._health.record_order()
    
    def record_position(
        self,
        symbol: str,
        direction: Literal["long", "short", "flat"],
        size: float,
        unrealized_pnl: float
    ) -> None:
        """Record position metrics."""
        METRICS["position_size"].labels(
            symbol=symbol,
            direction=direction
        ).set(size)
        
        METRICS["unrealized_pnl"].labels(symbol=symbol).set(unrealized_pnl)
    
    def record_prediction(
        self,
        model: str,
        latency_ms: float,
        confidence: float,
        drift_score: float | None = None
    ) -> None:
        """Record ML metrics."""
        METRICS["prediction_latency"].observe(latency_ms)
        METRICS["prediction_confidence"].observe(confidence)
        
        if drift_score is not None:
            METRICS["model_drift"].labels(model=model).set(drift_score)
    
    def record_risk(
        self,
        var_95: float,
        drawdown_pct: float,
        risk_level: int
    ) -> None:
        """Record risk metrics."""
        METRICS["var_95"].set(var_95)
        METRICS["current_drawdown"].set(drawdown_pct)
        METRICS["risk_level"].set(risk_level)
    
    def get_prometheus_metrics(self) -> tuple[str, str]:
        """Get Prometheus-formatted metrics."""
        METRICS["uptime_seconds"].set(time.time() - self._health._start_time)
        
        return generate_latest(), CONTENT_TYPE_LATEST
    
    @property
    def health(self) -> HealthChecker:
        """Access health checker."""
        return self._health


# Global exporter
_metrics_exporter: MetricsExporter | None = None


def get_metrics_exporter() -> MetricsExporter:
    """Get or create global metrics exporter."""
    global _metrics_exporter
    if _metrics_exporter is None:
        _metrics_exporter = MetricsExporter()
    return _metrics_exporter
