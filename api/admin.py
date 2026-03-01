"""
Admin Panel API Endpoints

REST API endpoints for admin dashboard and management.
"""

import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Dict, Any
import os
import time

from strategies import StrategyManager
from risk import RiskManager, RiskConfig

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
