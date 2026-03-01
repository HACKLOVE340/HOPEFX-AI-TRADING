"""
Admin Panel API Endpoints

REST API endpoints for admin dashboard and management.
"""

import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Dict, Any, List, Optional
import os
import time

from strategies import StrategyManager
from risk import RiskManager, RiskConfig

logger = logging.getLogger(__name__)

# Track server start time for uptime calculation
_start_time = time.time()

# Cache for module availability checks (avoid re-importing on every dashboard poll)
_module_cache: Dict[str, str] = {}
_module_cache_time: float = 0.0
_MODULE_CACHE_TTL = 60.0  # seconds

# Bounded in-memory activity log (most-recent first)
_activity_log: deque = deque(maxlen=50)

# Persisted risk settings file
_RISK_SETTINGS_FILE = Path(__file__).parent.parent / "config" / "risk_settings.json"

# Singleton DashboardService (lazily initialised)
_dashboard_service = None


def log_activity(message: str) -> None:
    """Append a timestamped entry to the in-memory activity log."""
    _activity_log.appendleft({
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "message": message,
    })


def _load_persisted_risk_settings() -> Dict[str, Any]:
    """Load risk settings from the config JSON file, or return empty dict."""
    try:
        if _RISK_SETTINGS_FILE.exists():
            with open(_RISK_SETTINGS_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load persisted risk settings: {e}")
    return {}


def apply_persisted_risk_settings() -> None:
    """Apply settings saved in risk_settings.json to the live risk_manager."""
    saved = _load_persisted_risk_settings()
    if not saved:
        return
    try:
        from api.trading import risk_manager
        config = risk_manager.config
        if "max_risk_per_trade" in saved:
            config.max_risk_per_trade = float(saved["max_risk_per_trade"])
        if "max_open_positions" in saved:
            config.max_open_positions = int(saved["max_open_positions"])
        if "max_daily_loss" in saved:
            config.max_daily_loss = float(saved["max_daily_loss"])
        if "max_drawdown" in saved:
            config.max_drawdown = float(saved["max_drawdown"])
        logger.info("Applied persisted risk settings from config/risk_settings.json")
    except Exception as e:
        logger.warning(f"Could not apply persisted risk settings: {e}")


def _get_dashboard_service():
    """Return (or lazily create) the singleton DashboardService."""
    global _dashboard_service
    if _dashboard_service is None:
        from dashboard import DashboardService
        _dashboard_service = DashboardService()
    return _dashboard_service


# Create router
router = APIRouter(prefix="/admin", tags=["Admin"])

# Setup templates
template_dir = Path(__file__).parent.parent / "templates"
template_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(template_dir))

# Shared instances for dashboard data
_strategy_manager = StrategyManager()
_risk_manager = RiskManager(RiskConfig(), initial_balance=10000.0)
_start_time = time.time()
_logger = logging.getLogger(__name__)


def _check_module(module_name: str) -> bool:
    """Check if a module is importable."""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


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
    elapsed = int(time.time() - _start_time)
    hours, rem = divmod(elapsed, 3600)
    minutes = rem // 60
    return {
        "version": "1.0.0",
        "environment": os.getenv("APP_ENV", "development"),
        "uptime": f"{hours}h {minutes}m",
        "status": "running",
    }


@router.get("/api/dashboard-data")
async def get_dashboard_data():
    """
    Aggregated dashboard data from all modules.

    Returns:
        Dictionary with system health, trading stats, risk status,
        module status, and recent activity.
    """
    # System health
    elapsed = int(time.time() - _start_time)
    hours, rem = divmod(elapsed, 3600)
    minutes = rem // 60
    system_health: Dict[str, Any] = {
        "version": "1.0.0",
        "environment": os.getenv("APP_ENV", "development"),
        "uptime": f"{hours}h {minutes}m",
        "status": "running",
        "api_version": "v1",
    }

    # Trading stats
    try:
        perf = _strategy_manager.get_performance_summary()
        trading_stats: Dict[str, Any] = {
            "total_strategies": perf.get("total_strategies", 0),
            "active_strategies": perf.get("active_strategies", 0),
            "total_pnl": round(perf.get("total_pnl", 0.0), 2),
            "win_rate": round(perf.get("win_rate", 0.0), 2),
            "total_signals": perf.get("total_signals", 0),
            "open_positions": perf.get("open_positions", 0),
            "active_orders": perf.get("active_orders", 0),
        }
    except Exception:
        _logger.warning("Failed to fetch trading stats", exc_info=True)
        trading_stats = {
            "total_strategies": 0,
            "active_strategies": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "total_signals": 0,
            "open_positions": 0,
            "active_orders": 0,
        }

    # Risk status
    try:
        risk = _risk_manager.get_risk_metrics()
        max_dd = risk.get("max_drawdown", 20.0)
        curr_dd = risk.get("current_drawdown", 0.0)
        risk_utilization = round((curr_dd / max_dd * 100) if max_dd > 0 else 0.0, 1)
        risk_status: Dict[str, Any] = {
            "current_drawdown": curr_dd,
            "max_drawdown_limit": max_dd,
            "risk_utilization": risk_utilization,
            "open_positions": risk.get("open_positions", 0),
            "max_positions": risk.get("max_positions", 10),
            "daily_loss_pct": risk.get("daily_loss_pct", 0.0),
            "max_daily_loss": risk.get("max_daily_loss", 5.0),
            "current_balance": risk.get("current_balance", 0.0),
        }
    except Exception:
        _logger.warning("Failed to fetch risk metrics", exc_info=True)
        risk_status = {
            "current_drawdown": 0.0,
            "max_drawdown_limit": 20.0,
            "risk_utilization": 0.0,
            "open_positions": 0,
            "max_positions": 10,
            "daily_loss_pct": 0.0,
            "max_daily_loss": 5.0,
            "current_balance": 0.0,
        }

    # Module status — check key modules
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
        ("payments", "payments"),
        ("social", "social"),
        ("notifications", "notifications"),
        ("charting", "charting"),
        ("backtesting", "backtesting"),
        ("dashboard", "dashboard"),
    ]
    module_status = {name: _check_module(mod) for name, mod in modules}

    # Market data status
    market_data: Dict[str, Any] = {
        "status": "operational",
        "cached_symbols": 0,
        "last_update": "N/A",
        "data_feed": "paper",
    }
    try:
        from cache import MarketDataCache
        cache_instance = MarketDataCache()
        stats = cache_instance.get_stats()
        market_data["cached_symbols"] = stats.get("total_symbols", 0)
        market_data["last_update"] = stats.get("last_update", "N/A")
    except Exception:
        _logger.warning("Failed to fetch market data cache stats", exc_info=True)

    # Recent activity (last events from strategy manager)
    recent_activity = []
    try:
        strategies = _strategy_manager.list_strategies()
        for s in strategies[:5]:
            recent_activity.append({
                "type": "strategy",
                "message": f"Strategy '{s.get('name', '')}' is {s.get('status', 'unknown')}",
                "timestamp": s.get("last_signal_time", "N/A"),
            })
    except Exception:
        _logger.warning("Failed to fetch recent activity", exc_info=True)

    return {
        "system_health": system_health,
        "trading_stats": trading_stats,
        "risk_status": risk_status,
        "module_status": module_status,
        "market_data": market_data,
        "recent_activity": recent_activity,
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

    Returns in-memory values from risk_manager, merged with any values
    persisted to disk so that restarted instances reflect saved settings.
    """
    # Start with persisted-to-disk defaults
    saved = _load_persisted_risk_settings()
    defaults = {
        "max_risk_per_trade": saved.get("max_risk_per_trade", 2.0),
        "max_open_positions": saved.get("max_open_positions", 5),
        "max_daily_loss": saved.get("max_daily_loss", 5.0),
        "max_drawdown": saved.get("max_drawdown", 20.0),
        "paper_trading_mode": saved.get("paper_trading_mode", True),
        "notifications_enabled": saved.get("notifications_enabled", True),
        "auto_trading_enabled": saved.get("auto_trading_enabled", False),
    }
    try:
        from api.trading import risk_manager
        config = risk_manager.config if hasattr(risk_manager, "config") else None
        if config is not None:
            defaults["max_risk_per_trade"] = getattr(config, "max_risk_per_trade", defaults["max_risk_per_trade"])
            defaults["max_open_positions"] = getattr(config, "max_open_positions", defaults["max_open_positions"])
            defaults["max_daily_loss"] = getattr(config, "max_daily_loss", defaults["max_daily_loss"])
            defaults["max_drawdown"] = getattr(config, "max_drawdown", defaults["max_drawdown"])
    except Exception as e:
        defaults["error"] = str(e)
    return defaults


@router.post("/api/settings")
async def save_settings(request: Request):
    """
    Save risk management settings — updates the live risk_manager in memory
    and persists the values to config/risk_settings.json so they survive restarts.
    """
    try:
        body = await request.json()
        save_error: Optional[str] = None

        # Apply to live risk_manager
        try:
            from api.trading import risk_manager
            config = risk_manager.config if hasattr(risk_manager, "config") else None
            if config is not None:
                if "max_risk_per_trade" in body:
                    config.max_risk_per_trade = float(body["max_risk_per_trade"])
                if "max_open_positions" in body:
                    config.max_open_positions = int(body["max_open_positions"])
                if "max_daily_loss" in body:
                    config.max_daily_loss = float(body["max_daily_loss"])
                if "max_drawdown" in body:
                    config.max_drawdown = float(body["max_drawdown"])
        except Exception as e:
            save_error = str(e)

        # Persist to disk (merge with existing file so unrelated fields are preserved)
        try:
            persisted = _load_persisted_risk_settings()
            for key in ("max_risk_per_trade", "max_open_positions", "max_daily_loss",
                        "max_drawdown", "paper_trading_mode", "notifications_enabled",
                        "auto_trading_enabled"):
                if key in body:
                    persisted[key] = body[key]
            _RISK_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_RISK_SETTINGS_FILE, "w") as f:
                json.dump(persisted, f, indent=2)
            log_activity("Risk settings updated and saved to disk")
        except Exception as e:
            logger.warning(f"Could not persist risk settings: {e}")
            log_activity("Risk settings updated (in-memory only — disk write failed)")

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


@router.get("/api/widgets")
async def get_widgets():
    """
    Get the active dashboard layout and per-widget data from DashboardService.
    """
    try:
        svc = _get_dashboard_service()
        layout = svc.get_active_layout()
        if not layout:
            return {"layout_id": None, "layout_name": None, "widgets": []}

        widgets: List[Dict[str, Any]] = []
        for w in layout.widgets:
            data = svc.get_widget_data(w.widget_type)
            widgets.append({
                "widget_id": w.widget_id,
                "widget_type": w.widget_type.value,
                "title": w.title,
                "position": w.position,
                "refresh_interval": w.refresh_interval,
                "enabled": w.enabled,
                "data": data,
            })

        return {
            "layout_id": layout.layout_id,
            "layout_name": layout.name,
            "widgets": widgets,
        }
    except Exception as e:
        logger.error(f"Failed to get widgets: {e}")
        return {"layout_id": None, "layout_name": None, "widgets": [], "error": str(e)}


@router.get("/api/activity")
async def get_activity():
    """
    Return the most-recent activity log entries (newest first, max 50).
    """
    return {"events": list(_activity_log)}
