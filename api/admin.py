"""
Admin Panel API Endpoints

REST API endpoints for admin dashboard and management.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Dict, Any
import os

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
    return {
        "version": "1.0.0",
        "environment": os.getenv("APP_ENV", "development"),
        "uptime": "0h 0m",  # Would calculate actual uptime
        "status": "running",
    }
