"""
Admin Panel API Endpoints

REST API endpoints for admin dashboard and management.
"""

import time
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Dict, Any, Optional
import os

# Track server start time for uptime calculation
_start_time = time.time()

# Cache for module availability checks (avoid re-importing on every dashboard poll)
_module_cache: Dict[str, str] = {}
_module_cache_time: float = 0.0
_MODULE_CACHE_TTL = 60.0  # seconds

# Create router
router = APIRouter(prefix="/admin", tags=["Admin"])

# Setup templates
template_dir = Path(__file__).parent.parent / "templates"
template_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(template_dir))


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """
    Admin dashboard main page.
    """
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "title": "Admin Dashboard"}
    )


@router.get("/strategies", response_class=HTMLResponse)
async def strategies_page(request: Request):
    """
    Strategy management page.
    """
    return templates.TemplateResponse(
        "admin/strategies.html",
        {"request": request, "title": "Strategy Management"}
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """
    Settings and configuration page.
    """
    return templates.TemplateResponse(
        "admin/settings.html",
        {"request": request, "title": "Settings"}
    )


@router.get("/monitoring", response_class=HTMLResponse)
async def monitoring_page(request: Request):
    """
    Real-time monitoring page.
    """
    return templates.TemplateResponse(
        "admin/monitoring.html",
        {"request": request, "title": "System Monitoring"}
    )


@router.get("/api/system-info")
async def get_system_info():
    """
    Get system information for dashboard.
    """
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return {
        "version": "2.0.0",
        "environment": os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")),
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": uptime_seconds,
        "status": "running",
    }


@router.get("/api/dashboard-data")
async def get_dashboard_data():
    """
    Get aggregated dashboard data from all available modules.
    """
    data: Dict[str, Any] = {
        "system": {},
        "trading": {},
        "risk": {},
        "modules": {},
    }

    # System info
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    data["system"] = {
        "version": "2.0.0",
        "environment": os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")),
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": uptime_seconds,
        "status": "running",
    }

    # Trading performance
    try:
        from api.trading import strategy_manager
        data["trading"] = strategy_manager.get_performance_summary()
    except Exception as e:
        data["trading"] = {"error": str(e), "total_strategies": 0, "active_strategies": 0}

    # Risk metrics
    try:
        from api.trading import risk_manager
        data["risk"] = risk_manager.get_risk_metrics()
    except Exception as e:
        data["risk"] = {"error": str(e)}

    # Module availability (cached to avoid repeated imports on every poll)
    global _module_cache, _module_cache_time
    now = time.time()
    if not _module_cache or (now - _module_cache_time) > _MODULE_CACHE_TTL:
        modules = [
            ("config", "config"),
            ("database", "database"),
            ("cache", "cache"),
            ("strategies", "strategies"),
            ("risk", "risk"),
            ("brokers", "brokers"),
            ("ml", "ml"),
            ("news", "news"),
            ("analytics", "analytics"),
            ("monetization", "monetization"),
            ("notifications", "notifications"),
            ("websocket", "api.websocket_server"),
            ("charting", "charting"),
            ("backtesting", "backtesting"),
        ]
        module_status: Dict[str, str] = {}
        for name, module_path in modules:
            try:
                __import__(module_path)
                module_status[name] = "available"
            except Exception:
                module_status[name] = "unavailable"
        _module_cache = module_status
        _module_cache_time = now
    data["modules"] = _module_cache

    return data


@router.get("/api/settings")
async def get_settings():
    """
    Get current risk management settings.
    """
    try:
        from api.trading import risk_manager
        metrics = risk_manager.get_risk_metrics()
        config = risk_manager.config if hasattr(risk_manager, "config") else {}
        return {
            "max_risk_per_trade": getattr(config, "max_risk_per_trade", 2.0),
            "max_open_positions": getattr(config, "max_open_positions", 5),
            "max_daily_loss": getattr(config, "max_daily_loss_percent", 5.0),
            "max_drawdown": getattr(config, "max_drawdown_percent", 20.0),
            "paper_trading_mode": getattr(config, "paper_trading_mode", True),
            "notifications_enabled": True,
            "auto_trading_enabled": False,
        }
    except Exception as e:
        return {
            "max_risk_per_trade": 2.0,
            "max_open_positions": 5,
            "max_daily_loss": 5.0,
            "max_drawdown": 20.0,
            "paper_trading_mode": True,
            "notifications_enabled": True,
            "auto_trading_enabled": False,
            "error": str(e),
        }


@router.post("/api/settings")
async def save_settings(request: Request):
    """
    Save risk management settings.
    """
    try:
        body = await request.json()
        save_error: Optional[str] = None
        try:
            from api.trading import risk_manager
            config = risk_manager.config if hasattr(risk_manager, "config") else None
            if config is not None:
                if "max_risk_per_trade" in body:
                    config.max_risk_per_trade = float(body["max_risk_per_trade"])
                if "max_open_positions" in body:
                    config.max_open_positions = int(body["max_open_positions"])
                if "max_daily_loss" in body:
                    config.max_daily_loss_percent = float(body["max_daily_loss"])
                if "max_drawdown" in body:
                    config.max_drawdown_percent = float(body["max_drawdown"])
        except Exception as e:
            save_error = str(e)
        if save_error:
            return {"status": "error", "message": f"Settings partially saved: {save_error}"}
        return {"status": "ok", "message": "Settings saved successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/system-metrics")
async def get_system_metrics():
    """
    Get real-time system metrics including CPU, memory, and uptime.
    """
    metrics: Dict[str, Any] = {}

    # CPU and memory via psutil if available
    try:
        import psutil
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        metrics["memory_used_mb"] = round(mem.used / (1024 * 1024), 1)
        metrics["memory_total_mb"] = round(mem.total / (1024 * 1024), 1)
        metrics["memory_percent"] = mem.percent
    except Exception:
        metrics["cpu_percent"] = None
        metrics["memory_used_mb"] = None
        metrics["memory_total_mb"] = None
        metrics["memory_percent"] = None

    # Uptime
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    metrics["uptime"] = f"{hours}h {minutes}m {seconds}s"
    metrics["uptime_seconds"] = uptime_seconds

    # Cache status
    try:
        from cache import MarketDataCache
        metrics["cache_status"] = "available"
    except Exception:
        metrics["cache_status"] = "unavailable"

    # Database status
    try:
        from database.models import Base
        metrics["database_status"] = "available"
    except Exception:
        metrics["database_status"] = "unavailable"

    # Active connections placeholder
    metrics["active_connections"] = 0

    return metrics
