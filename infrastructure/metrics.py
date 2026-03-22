"""
HOPEFX Metrics Collection System
Prometheus-compatible metrics with custom collectors
"""

import time
import threading
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum
import json

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class MetricType(Enum):
    COUNTER = "counter"      # Monotonically increasing
    GAUGE = "gauge"          # Can go up or down
    HISTOGRAM = "histogram"  # Distribution of values
    SUMMARY = "summary"      # Similar to histogram but configurable quantiles


@dataclass
class MetricValue:
    """Single metric value"""
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)


class MetricCollector:
    """Base class for metric collectors"""
    
    def __init__(self, name: str, metric_type: MetricType, description: str, 
                 labels: Optional[List[str]] = None):
        self.name = name
        self.metric_type = metric_type
        self.description = description
        self.labels = labels or []
        self._values: Dict[str, List[MetricValue]] = defaultdict(list)
        self._lock = threading.Lock()
    
    def observe(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a value"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        
        with self._lock:
            self._values[label_key].append(MetricValue(
                value=value,
                timestamp=time.time(),
                labels=labels or {}
            ))
            
            # Keep only last 1000 values per label set
            if len(self._values[label_key]) > 1000:
                self._values[label_key] = self._values[label_key][-1000:]
    
    def get_values(self, labels: Optional[Dict[str, str]] = None) -> List[MetricValue]:
        """Get values for specific labels"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        with self._lock:
            return list(self._values.get(label_key, []))
    
    def get_all_values(self) -> Dict[str, List[MetricValue]]:
        """Get all values"""
        with self._lock:
            return {k: list(v) for k, v in self._values.items()}
    
    def clear(self):
        """Clear all values"""
        with self._lock:
            self._values.clear()


class Counter(MetricCollector):
    """Counter metric (monotonically increasing)"""
    
    def __init__(self, name: str, description: str, labels: Optional[List[str]] = None):
        super().__init__(name, MetricType.COUNTER, description, labels)
        self._totals: Dict[str, float] = defaultdict(float)
    
    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment counter"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        
        with self._lock:
            self._totals[label_key] += amount
            self.observe(self._totals[label_key], labels)
    
    def get_value(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current counter value"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        with self._lock:
            return self._totals.get(label_key, 0.0)


class Gauge(MetricCollector):
    """Gauge metric (can go up or down)"""
    
    def __init__(self, name: str, description: str, labels: Optional[List[str]] = None):
        super().__init__(name, MetricType.GAUGE, description, labels)
        self._current: Dict[str, float] = {}
    
    def set(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Set gauge value"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        
        with self._lock:
            self._current[label_key] = value
            self.observe(value, labels)
    
    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment gauge"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        
        with self._lock:
            current = self._current.get(label_key, 0.0)
            new_value = current + amount
            self._current[label_key] = new_value
            self.observe(new_value, labels)
    
    def dec(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Decrement gauge"""
        self.inc(-amount, labels)
    
    def get_value(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current gauge value"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        with self._lock:
            return self._current.get(label_key, 0.0)


class Histogram(MetricCollector):
    """Histogram metric (value distribution)"""
    
    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
    
    def __init__(self, name: str, description: str, 
                 labels: Optional[List[str]] = None,
                 buckets: Optional[List[float]] = None):
        super().__init__(name, MetricType.HISTOGRAM, description, labels)
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._bucket_counts: Dict[str, List[int]] = defaultdict(lambda: [0] * len(self.buckets))
        self._sums: Dict[str, float] = defaultdict(float)
        self._counts: Dict[str, int] = defaultdict(int)
    
    def observe(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Observe a value"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        
        with self._lock:
            # Update buckets
            for i, bucket in enumerate(self.buckets):
                if value <= bucket:
                    self._bucket_counts[label_key][i] += 1
            
            # Update sum and count
            self._sums[label_key] += value
            self._counts[label_key] += 1
            
            super().observe(value, labels)
    
    def get_bucket_counts(self, labels: Optional[Dict[str, str]] = None) -> List[int]:
        """Get bucket counts"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        with self._lock:
            return list(self._bucket_counts.get(label_key, [0] * len(self.buckets)))
    
    def get_sum(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get sum of all observations"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        with self._lock:
            return self._sums.get(label_key, 0.0)
    
    def get_count(self, labels: Optional[Dict[str, str]] = None) -> int:
        """Get total count"""
        label_key = json.dumps(labels or {}, sort_keys=True)
        with self._lock:
            return self._counts.get(label_key, 0)


class MetricsRegistry:
    """
    Central metrics registry for HOPEFX
    
    Collects:
    - Trading metrics (P&L, win rate, etc.)
    - System metrics (CPU, memory, etc.)
    - Performance metrics (latency, throughput)
    - Business metrics (orders, positions)
    """
    
    _instance: Optional['MetricsRegistry'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            self._collectors: Dict[str, MetricCollector] = {}
            self._custom_collectors: List[Callable] = []
            self._start_time = time.time()
            
            self._initialize_default_metrics()
            self._initialized = True
    
    def _initialize_default_metrics(self):
        """Initialize default HOPEFX metrics"""
        
        # Trading metrics
        self.create_counter("trades_total", "Total number of trades", ["symbol", "side", "outcome"])
        self.create_gauge("positions_open", "Number of open positions", ["symbol"])
        self.create_gauge("account_equity", "Current account equity")
        self.create_gauge("account_balance", "Current account balance")
        self.create_histogram("trade_pnl", "Trade P&L distribution", ["symbol"], 
                          buckets=[-1000, -500, -100, 0, 100, 500, 1000])
        
        # Performance metrics
        self.create_histogram("order_latency_ms", "Order execution latency", 
                          buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000])
        self.create_histogram("brain_cycle_time_ms", "Brain cycle execution time",
                          buckets=[10, 50, 100, 250, 500, 1000, 2500])
        self.create_counter("brain_cycles_total", "Total brain cycles")
        
        # System metrics
        self.create_gauge("system_cpu_percent", "CPU usage percent")
        self.create_gauge("system_memory_percent", "Memory usage percent")
        self.create_gauge("system_disk_free_gb", "Free disk space in GB")
        
        # Cache metrics
        self.create_counter("cache_hits_total", "Cache hits", ["cache_type"])
        self.create_counter("cache_misses_total", "Cache misses", ["cache_type"])
        self.create_gauge("cache_size", "Current cache size", ["cache_type"])
        
        # Error metrics
        self.create_counter("errors_total", "Total errors", ["component", "type"])
        self.create_counter("circuit_breaker_opens_total", "Circuit breaker opens")
        
        # Business metrics
        self.create_counter("signals_generated_total", "Trading signals generated", ["strategy"])
        self.create_counter("orders_submitted_total", "Orders submitted", ["symbol", "type"])
        self.create_counter("orders_filled_total", "Orders filled", ["symbol", "type"])
        self.create_counter("orders_rejected_total", "Orders rejected", ["symbol", "reason"])
    
    def create_counter(self, name: str, description: str, labels: Optional[List[str]] = None) -> Counter:
        """Create and register a counter"""
        counter = Counter(name, description, labels)
        self._collectors[name] = counter
        return counter
    
    def create_gauge(self, name: str, description: str, labels: Optional[List[str]] = None) -> Gauge:
        """Create and register a gauge"""
        gauge = Gauge(name, description, labels)
        self._collectors[name] = gauge
        return gauge
    
    def create_histogram(self, name: str, description: str, 
                        labels: Optional[List[str]] = None,
                        buckets: Optional[List[float]] = None) -> Histogram:
        """Create and register a histogram"""
        histogram = Histogram(name, description, labels, buckets)
        self._collectors[name] = histogram
        return histogram
    
    def get_collector(self, name: str) -> Optional[MetricCollector]:
        """Get a registered collector"""
        return self._collectors.get(name)
    
    def record_trade(self, symbol: str, side: str, pnl: float, 
                     commission: float = 0, duration_seconds: float = 0):
        """Record trade metrics"""
        outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven"
        
        self.get_collector("trades_total").inc(1, {"symbol": symbol, "side": side, "outcome": outcome})
        self.get_collector("trade_pnl").observe(pnl, {"symbol": symbol})
        
        # Update equity (approximate)
        equity_collector = self.get_collector("account_equity")
        if equity_collector:
            current = equity_collector.get_value()
            equity_collector.set(current + pnl - commission)
    
    def record_order_latency(self, latency_ms: float, order_type: str = "market"):
        """Record order latency"""
        self.get_collector("order_latency_ms").observe(latency_ms)
    
    def record_brain_cycle(self, duration_ms: float):
        """Record brain cycle metrics"""
        self.get_collector("brain_cycles_total").inc()
        self.get_collector("brain_cycle_time_ms").observe(duration_ms)
    
    def record_error(self, component: str, error_type: str):
        """Record error"""
        self.get_collector("errors_total").inc(1, {"component": component, "type": error_type})
    
    def record_cache_hit(self, cache_type: str = "redis"):
        """Record cache hit"""
        self.get_collector("cache_hits_total").inc(1, {"cache_type": cache_type})
    
    def record_cache_miss(self, cache_type: str = "redis"):
        """Record cache miss"""
        self.get_collector("cache_misses_total").inc(1, {"cache_type": cache_type})
    
    def update_system_metrics(self):
        """Update system resource metrics"""
        if not PSUTIL_AVAILABLE:
            return
        
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            self.get_collector("system_cpu_percent").set(cpu)
            self.get_collector("system_memory_percent").set(memory.percent)
            self.get_collector("system_disk_free_gb").set(disk.free / 1024 / 1024 / 1024)
        except Exception as e:
            logger.error(f"Error updating system metrics: {e}")
    
    def register_custom_collector(self, collector_fn: Callable):
        """Register a custom metrics collector function"""
        self._custom_collectors.append(collector_fn)
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics as dictionary"""
        metrics = {
            'timestamp': time.time(),
            'uptime_seconds': time.time() - self._start_time,
            'collectors': {}
        }
        
        for name, collector in self._collectors.items():
            metrics['collectors'][name] = {
                'type': collector.metric_type.value,
                'description': collector.description,
                'values': collector.get_all_values()
            }
        
        # Run custom collectors
        for collector_fn in self._custom_collectors:
            try:
                custom_metrics = collector_fn()
                metrics['collectors'].update(custom_metrics)
            except Exception as e:
                logger.error(f"Custom collector error: {e}")
        
        return metrics
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format"""
        lines = []
        
        for name, collector in self._collectors.items():
            lines.append(f"# HELP {name} {collector.description}")
            lines.append(f"# TYPE {name} {collector.metric_type.value}")
            
            if isinstance(collector, Counter):
                for label_key, values in collector.get_all_values().items():
                    if values:
                        labels = values[-1].labels
                        label_str = ",".join([f'{k}="{v}"' for k, v in labels.items()])
                        value = collector.get_value(labels)
                        lines.append(f"{name}{{{label_str}}} {value}")
            
            elif isinstance(collector, Gauge):
                for label_key, values in collector.get_all_values().items():
                    if values:
                        labels = values[-1].labels
                        label_str = ",".join([f'{k}="{v}"' for k, v in labels.items()])
                        value = collector.get_value(labels)
                        lines.append(f"{name}{{{label_str}}} {value}")
            
            elif isinstance(collector, Histogram):
                for label_key in collector.get_all_values().keys():
                    labels = json.loads(label_key) if label_key else {}
                    label_str = ",".join([f'{k}="{v}"' for k, v in labels.items()])
                    
                    # Export buckets
                    bucket_counts = collector.get_bucket_counts(labels)
                    for i, bucket in enumerate(collector.buckets):
                        bucket_labels = labels.copy()
                        bucket_labels['le'] = str(bucket)
                        bucket_str = ",".join([f'{k}="{v}"' for k, v in bucket_labels.items()])
                        lines.append(f"{name}_bucket{{{bucket_str}}} {bucket_counts[i]}")
                    
                    # Sum and count
                    lines.append(f"{name}_sum{{{label_str}}} {collector.get_sum(labels)}")
                    lines.append(f"{name}_count{{{label_str}}} {collector.get_count(labels)}")
            
            lines.append("")  # Empty line between metrics
        
        return "\n".join(lines)
    
    def start_collection(self, interval: float = 15.0):
        """Start background metric collection"""
        import asyncio
        
        async def collect():
            while True:
                self.update_system_metrics()
                await asyncio.sleep(interval)
        
        asyncio.create_task(collect())
    
    def clear(self):
        """Clear all metrics (use with caution)"""
        for collector in self._collectors.values():
            collector.clear()


# Global instance
_metrics_registry: Optional[MetricsRegistry] = None

def get_metrics_registry() -> MetricsRegistry:
    """Get global metrics registry"""
    global _metrics_registry
    if _metrics_registry is None:
        _metrics_registry = MetricsRegistry()
    return _metrics_registry


# Convenience functions
def record_trade(symbol: str, side: str, pnl: float, commission: float = 0):
    """Record trade"""
    get_metrics_registry().record_trade(symbol, side, pnl, commission)

def record_order_latency(latency_ms: float):
    """Record order latency"""
    get_metrics_registry().record_order_latency(latency_ms)

def record_error(component: str, error_type: str):
    """Record error"""
    get_metrics_registry().record_error(component, error_type)

def update_gauge(name: str, value: float, labels: Optional[Dict] = None):
    """Update gauge value"""
    collector = get_metrics_registry().get_collector(name)
    if isinstance(collector, Gauge):
        collector.set(value, labels)
