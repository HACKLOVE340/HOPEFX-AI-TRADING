"""
HOPEFX Health Check System
Comprehensive health monitoring with dependency checks
"""

import asyncio
import time
import psutil
import os
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import json

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Individual health check result"""
    name: str
    status: HealthStatus
    response_time_ms: float
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'status': self.status.value,
            'response_time_ms': round(self.response_time_ms, 2),
            'message': self.message,
            'details': self.details,
            'last_check': self.last_check.isoformat()
        }


@dataclass
class SystemHealth:
    """Overall system health"""
    status: HealthStatus
    checks: List[HealthCheck]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "2.1.0"
    uptime_seconds: float = 0.0
    hostname: str = field(default_factory=lambda: os.uname().nodename)
    
    def to_dict(self) -> Dict:
        return {
            'status': self.status.value,
            'timestamp': self.timestamp.isoformat(),
            'version': self.version,
            'uptime_seconds': round(self.uptime_seconds, 2),
            'hostname': self.hostname,
            'checks': [c.to_dict() for c in self.checks]
        }


class HealthChecker:
    """
    Comprehensive health checking system
    
    Checks:
    - CPU and memory usage
    - Disk space
    - Database connectivity
    - Redis connectivity
    - Broker connectivity
    - Price feed latency
    - Brain state
    """
    
    def __init__(self, app=None):
        self.app = app
        self._checks: Dict[str, Callable] = {}
        self._last_results: Dict[str, HealthCheck] = {}
        self._start_time = time.time()
        self._running = False
        self._check_interval = 30  # seconds
        
        # Register default checks
        self._register_default_checks()
    
    def _register_default_checks(self):
        """Register default health checks"""
        self.register_check("system_resources", self._check_system_resources)
        self.register_check("database", self._check_database)
        self.register_check("cache", self._check_cache)
        self.register_check("broker", self._check_broker)
        self.register_check("price_feed", self._check_price_feed)
        self.register_check("brain", self._check_brain)
    
    def register_check(self, name: str, check_fn: Callable):
        """Register a health check"""
        self._checks[name] = check_fn
        logger.info(f"Registered health check: {name}")
    
    async def run_check(self, name: str) -> HealthCheck:
        """Run single health check"""
        if name not in self._checks:
            return HealthCheck(
                name=name,
                status=HealthStatus.UNKNOWN,
                response_time_ms=0,
                message="Check not registered"
            )
        
        start_time = time.time()
        
        try:
            result = await asyncio.wait_for(
                self._checks[name](),
                timeout=10.0
            )
            result.response_time_ms = (time.time() - start_time) * 1000
            self._last_results[name] = result
            return result
            
        except asyncio.TimeoutError:
            result = HealthCheck(
                name=name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                message="Health check timeout"
            )
            self._last_results[name] = result
            return result
            
        except Exception as e:
            result = HealthCheck(
                name=name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                message=f"Health check error: {str(e)}"
            )
            self._last_results[name] = result
            return result
    
    async def run_all_checks(self) -> SystemHealth:
        """Run all health checks"""
        checks = []
        
        # Run checks concurrently
        results = await asyncio.gather(
            *[self.run_check(name) for name in self._checks.keys()],
            return_exceptions=True
        )
        
        for result in results:
            if isinstance(result, Exception):
                checks.append(HealthCheck(
                    name="unknown",
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=0,
                    message=str(result)
                ))
            else:
                checks.append(result)
        
        # Determine overall status
        if any(c.status == HealthStatus.UNHEALTHY for c in checks):
            overall_status = HealthStatus.UNHEALTHY
        elif any(c.status == HealthStatus.DEGRADED for c in checks):
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY
        
        return SystemHealth(
            status=overall_status,
            checks=checks,
            uptime_seconds=time.time() - self._start_time
        )
    
    # Default health check implementations
    
    async def _check_system_resources(self) -> HealthCheck:
        """Check CPU, memory, and disk"""
        details = {}
        issues = []
        
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
        details['cpu_percent'] = cpu_percent
        if cpu_percent > 90:
            issues.append(f"High CPU usage: {cpu_percent}%")
        elif cpu_percent > 70:
            issues.append(f"Elevated CPU usage: {cpu_percent}%")
        
        # Memory usage
        memory = psutil.virtual_memory()
        details['memory_percent'] = memory.percent
        details['memory_available_mb'] = memory.available / 1024 / 1024
        if memory.percent > 90:
            issues.append(f"High memory usage: {memory.percent}%")
        elif memory.percent > 80:
            issues.append(f"Elevated memory usage: {memory.percent}%")
        
        # Disk usage
        disk = psutil.disk_usage('/')
        disk_percent = (disk.used / disk.total) * 100
        details['disk_percent'] = disk_percent
        details['disk_free_gb'] = disk.free / 1024 / 1024 / 1024
        if disk_percent > 90:
            issues.append(f"Low disk space: {disk_percent:.1f}% used")
        
        # Determine status
        if any("High" in i for i in issues):
            status = HealthStatus.UNHEALTHY
        elif issues:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.HEALTHY
        
        return HealthCheck(
            name="system_resources",
            status=status,
            response_time_ms=0,
            message="; ".join(issues) if issues else "System resources OK",
            details=details
        )
    
    async def _check_database(self) -> HealthCheck:
        """Check database connectivity"""
        if not self.app or not self.app.db_engine:
            return HealthCheck(
                name="database",
                status=HealthStatus.UNKNOWN,
                response_time_ms=0,
                message="Database not configured"
            )
        
        try:
            start = time.time()
            # Simple connectivity check
            from sqlalchemy import text
            with self.app.db_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            return HealthCheck(
                name="database",
                status=HealthStatus.HEALTHY,
                response_time_ms=(time.time() - start) * 1000,
                message="Database connection OK",
                details={'type': self.app.config.database.db_type}
            )
        except Exception as e:
            return HealthCheck(
                name="database",
                status=HealthStatus.UNHEALTHY,
                response_time_ms=0,
                message=f"Database error: {str(e)}"
            )
    
    async def _check_cache(self) -> HealthCheck:
        """Check Redis/cache connectivity"""
        if not self.app or not self.app.cache:
            return HealthCheck(
                name="cache",
                status=HealthStatus.UNKNOWN,
                response_time_ms=0,
                message="Cache not configured"
            )
        
        try:
            start = time.time()
            healthy = await self.app.cache.health_check_async()
            
            if healthy:
                return HealthCheck(
                    name="cache",
                    status=HealthStatus.HEALTHY,
                    response_time_ms=(time.time() - start) * 1000,
                    message="Cache connection OK",
                    details={'using_fallback': getattr(self.app.cache, '_using_fallback', False)}
                )
            else:
                return HealthCheck(
                    name="cache",
                    status=HealthStatus.DEGRADED,
                    response_time_ms=0,
                    message="Cache unhealthy, using fallback"
                )
        except Exception as e:
            return HealthCheck(
                name="cache",
                status=HealthStatus.UNHEALTHY,
                response_time_ms=0,
                message=f"Cache error: {str(e)}"
            )
    
    async def _check_broker(self) -> HealthCheck:
        """Check broker connectivity"""
        if not self.app or not self.app.broker:
            return HealthCheck(
                name="broker",
                status=HealthStatus.UNKNOWN,
                response_time_ms=0,
                message="Broker not configured"
            )
        
        try:
            start = time.time()
            
            if not self.app.broker.connected:
                return HealthCheck(
                    name="broker",
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=0,
                    message="Broker disconnected"
                )
            
            # Try to get account info
            account = await asyncio.wait_for(
                self.app.broker.get_account_info(),
                timeout=5.0
            )
            
            return HealthCheck(
                name="broker",
                status=HealthStatus.HEALTHY,
                response_time_ms=(time.time() - start) * 1000,
                message="Broker connection OK",
                details={
                    'equity': account.get('equity', 0),
                    'open_positions': account.get('open_positions', 0)
                }
            )
        except Exception as e:
            return HealthCheck(
                name="broker",
                status=HealthStatus.UNHEALTHY,
                response_time_ms=0,
                message=f"Broker error: {str(e)}"
            )
    
    async def _check_price_feed(self) -> HealthCheck:
        """Check price feed health"""
        if not self.app or not self.app.price_engine:
            return HealthCheck(
                name="price_feed",
                status=HealthStatus.UNKNOWN,
                response_time_ms=0,
                message="Price engine not configured"
            )
        
        try:
            engine = self.app.price_engine
            
            if not engine.active:
                return HealthCheck(
                    name="price_feed",
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=0,
                    message="Price engine inactive"
                )
            
            # Check data staleness
            stale_symbols = []
            current_time = time.time()
            
            for symbol in getattr(engine, 'symbols', []):
                tick = engine.get_last_price(symbol)
                if tick and (current_time - tick.timestamp) > 300:  # 5 min stale
                    stale_symbols.append(symbol)
            
            if stale_symbols:
                return HealthCheck(
                    name="price_feed",
                    status=HealthStatus.DEGRADED,
                    response_time_ms=0,
                    message=f"Stale data for {len(stale_symbols)} symbols",
                    details={'stale_symbols': stale_symbols[:5]}  # Limit to 5
                )
            
            return HealthCheck(
                name="price_feed",
                status=HealthStatus.HEALTHY,
                response_time_ms=0,
                message="Price feed OK",
                details={'symbols_tracked': len(getattr(engine, 'symbols', []))}
            )
            
        except Exception as e:
            return HealthCheck(
                name="price_feed",
                status=HealthStatus.UNHEALTHY,
                response_time_ms=0,
                message=f"Price feed error: {str(e)}"
            )
    
    async def _check_brain(self) -> HealthCheck:
        """Check brain health"""
        if not self.app or not self.app.brain:
            return HealthCheck(
                name="brain",
                status=HealthStatus.UNKNOWN,
                response_time_ms=0,
                message="Brain not configured"
            )
        
        try:
            health = self.app.brain.get_health()
            
            if not health['running']:
                return HealthCheck(
                    name="brain",
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=0,
                    message="Brain not running"
                )
            
            if health['circuit_breaker']['is_open']:
                return HealthCheck(
                    name="brain",
                    status=HealthStatus.DEGRADED,
                    response_time_ms=0,
                    message="Circuit breaker open",
                    details={'failure_count': health['circuit_breaker']['failure_count']}
                )
            
            return HealthCheck(
                name="brain",
                status=HealthStatus.HEALTHY,
                response_time_ms=health.get('avg_cycle_time_ms', 0),
                message="Brain operational",
                details={
                    'cycle_count': health['cycle_count'],
                    'state': health['state']
                }
            )
            
        except Exception as e:
            return HealthCheck(
                name="brain",
                status=HealthStatus.UNHEALTHY,
                response_time_ms=0,
                message=f"Brain error: {str(e)}"
            )
    
    async def start_monitoring(self, interval: Optional[int] = None):
        """Start background health monitoring"""
        if interval:
            self._check_interval = interval
        
        self._running = True
        
        while self._running:
            try:
                health = await self.run_all_checks()
                
                # Log if unhealthy
                if health.status != HealthStatus.HEALTHY:
                    logger.warning(f"Health check: {health.status.value}")
                    for check in health.checks:
                        if check.status != HealthStatus.HEALTHY:
                            logger.warning(
                                f"  {check.name}: {check.status.value} - {check.message}"
                            )
                
                # Wait for next check
                await asyncio.sleep(self._check_interval)
                
            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(5)
    
    def stop_monitoring(self):
        """Stop health monitoring"""
        self._running = False


# HTTP Server for health checks
async def start_health_server(host: str = "0.0.0.0", port: int = 8080, checker: Optional[HealthChecker] = None):
    """Start HTTP health check server"""
    if not AIOHTTP_AVAILABLE:
        logger.error("aiohttp required for health server")
        return
    
    async def health_handler(request):
        """Health check endpoint"""
        if checker:
            health = await checker.run_all_checks()
            status = 200 if health.status == HealthStatus.HEALTHY else 503
            return web.json_response(health.to_dict(), status=status)
        else:
            return web.json_response({
                'status': 'unknown',
                'message': 'Health checker not configured'
            }, status=503)
    
    async def ready_handler(request):
        """Readiness check"""
        if checker and checker.app:
            ready = (
                checker.app._components_initialized and
                checker.app.running
            )
            status = 200 if ready else 503
            return web.json_response({'ready': ready}, status=status)
        return web.json_response({'ready': False}, status=503)
    
    async def live_handler(request):
        """Liveness check"""
        return web.json_response({'alive': True})
    
    async def metrics_handler(request):
        """Prometheus-style metrics"""
        if not checker:
            return web.Response(text="", status=503)
        
        health = await checker.run_all_checks()
        
        # Format as Prometheus metrics
        metrics = []
        metrics.append(f"# HELP hopefx_health Overall health status")
        metrics.append(f"# TYPE hopefx_health gauge")
        status_value = 1 if health.status == HealthStatus.HEALTHY else 0
        metrics.append(f"hopefx_health{{status=\"{health.status.value}\"}} {status_value}")
        
        for check in health.checks:
            check_value = 1 if check.status == HealthStatus.HEALTHY else 0
            metrics.append(f"hopefx_check_health{{name=\"{check.name}\"}} {check_value}")
            metrics.append(f"hopefx_check_response_time{{name=\"{check.name}\"}} {check.response_time_ms}")
        
        return web.Response(text="\n".join(metrics), content_type="text/plain")
    
    app = web.Application()
    app.router.add_get('/health', health_handler)
    app.router.add_get('/ready', ready_handler)
    app.router.add_get('/live', live_handler)
    app.router.add_get('/metrics', metrics_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    logger.info(f"Health server started on http://{host}:{port}")
    logger.info(f"  - Health:  http://{host}:{port}/health")
    logger.info(f"  - Ready:   http://{host}:{port}/ready")
    logger.info(f"  - Live:    http://{host}:{port}/live")
    logger.info(f"  - Metrics: http://{host}:{port}/metrics")
    
    return runner


# Global instance
_health_checker: Optional[HealthChecker] = None

def get_health_checker(app=None) -> HealthChecker:
    """Get global health checker"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker(app)
    return _health_checker
