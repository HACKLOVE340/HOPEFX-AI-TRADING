"""
Institutional Monitoring & Observability
Prometheus metrics, health checks, alerting
"""

from prometheus_client import Counter, Histogram, Gauge, Info, start_http_server
import psutil
import asyncio
from datetime import datetime
from typing import Dict, Callable, List

# ============================================================================
# METRICS REGISTRY
# ============================================================================

class MetricsCollector:
    """
    Centralized metrics for institutional monitoring.
    """
    
    def __init__(self):
        # System metrics
        self.system_info = Info('hopefx_system', 'System information')
        self.uptime = Gauge('hopefx_uptime_seconds', 'System uptime')
        self.memory_usage = Gauge('hopefx_memory_bytes', 'Memory usage')
        self.cpu_usage = Gauge('hopefx_cpu_percent', 'CPU usage')
        self.open_files = Gauge('hopefx_open_files', 'Open file descriptors')
        
        # Trading metrics
        self.orders_submitted = Counter('hopefx_orders_submitted_total', 'Orders submitted', ['symbol', 'side'])
        self.orders_filled = Counter('hopefx_orders_filled_total', 'Orders filled', ['symbol', 'status'])
        self.order_latency = Histogram('hopefx_order_latency_seconds', 'Order round-trip time')
        self.position_size = Gauge('hopefx_position_size', 'Current position size', ['symbol'])
        self.unrealized_pnl = Gauge('hopefx_unrealized_pnl', 'Unrealized P&L', ['symbol'])
        
        # Risk metrics
        self.daily_drawdown = Gauge('hopefx_daily_drawdown_percent', 'Current drawdown')
        self.margin_used = Gauge('hopefx_margin_used', 'Margin used', ['account'])
        self.risk_breaches = Counter('hopefx_risk_breaches_total', 'Risk limit breaches', ['type'])
        
        # Data metrics
        self.cache_hits = Counter('hopefx_cache_hits_total', 'Cache hits', ['tier'])
        self.cache_misses = Counter('hopefx_cache_misses_total', 'Cache misses', ['tier'])
        self.db_query_time = Histogram('hopefx_db_query_seconds', 'Database query time')
        
        # Event metrics
        self.events_processed = Counter('hopefx_events_processed_total', 'Events processed', ['type'])
        self.event_queue_depth = Gauge('hopefx_event_queue_depth', 'Event queue size')
        self.event_latency = Histogram('hopefx_event_latency_seconds', 'Event processing time')
        
        self._start_time = datetime.utcnow()
        self._alert_handlers: List[Callable] = []
    
    def start_server(self, port: int = 9090):
        """Start Prometheus metrics server."""
        start_http_server(port)
        self.system_info.info({'version': '4.0.0', 'environment': 'institutional'})
    
    async def start_collection(self):
        """Start background metrics collection."""
        while True:
            # System metrics
            self.uptime.set((datetime.utcnow() - self._start_time).total_seconds())
            self.memory_usage.set(psutil.Process().memory_info().rss)
            self.cpu_usage.set(psutil.cpu_percent())
            self.open_files.set(len(psutil.Process().open_files()))
            
            await asyncio.sleep(15)  # 15-second intervals
    
    def alert_on(self, condition: str, threshold: float, current: float, severity: str = "warning"):
        """Trigger alert if condition met."""
        if current > threshold:
            for handler in self._alert_handlers:
                handler({
                    'timestamp': datetime.utcnow().isoformat(),
                    'condition': condition,
                    'threshold': threshold,
                    'current': current,
                    'severity': severity
                })
    
    def register_alert_handler(self, handler: Callable[[Dict], None]):
        """Register alert callback."""
        self._alert_handlers.append(handler)

# Global instance
metrics = MetricsCollector()
