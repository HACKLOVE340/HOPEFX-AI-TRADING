# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/page_routes.py
===================
HTML page routes and static dashboard mounting.

Extracted from app.py to keep the application entry point under 300 lines.

Register with:
    from core.page_routes import register_page_routes
    register_page_routes(app)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

_TEMPLATES = Path(__file__).parent.parent / "templates"


def _serve_template(name: str, fallback_html: str) -> HTMLResponse:
    """Return the named template file, or *fallback_html* if missing."""
    path = _TEMPLATES / name
    if path.exists():
        return HTMLResponse(content=path.read_text(encoding="utf-8"))
    return HTMLResponse(content=fallback_html, status_code=200)


def register_page_routes(app: FastAPI) -> None:
    """Mount all HTML page routes and the React dashboard on *app*."""

    @app.get("/admin", response_class=HTMLResponse, tags=["Admin"], include_in_schema=False)
    async def admin_redirect():
        """Redirect /admin to the admin dashboard at /api/admin/."""
        return HTMLResponse(
            content='<html><head><meta http-equiv="refresh" content="0;url=/api/admin/"></head>'
            "<body>Redirecting to admin dashboard…</body></html>",
            status_code=200,
        )

    @app.get("/login", response_class=HTMLResponse, tags=["Auth"], include_in_schema=False)
    async def login_page():
        """Serve the login page."""
        return _serve_template(
            "login.html",
            '<html><body><p>Login template missing. <a href="/docs">Use /docs to authenticate.</a></p></body></html>',
        )

    @app.get("/register", response_class=HTMLResponse, tags=["Auth"], include_in_schema=False)
    async def register_page():
        """Redirect /register to the login page (registration is via API)."""
        return HTMLResponse(
            content='<html><head><meta http-equiv="refresh" content="0;url=/login"></head>'
            "<body>Redirecting to login…</body></html>",
            status_code=200,
        )

    @app.get(
        "/dashboard",
        response_class=HTMLResponse,
        tags=["Dashboard"],
        include_in_schema=False,
    )
    async def dashboard_redirect():
        """Redirect /dashboard to the paper-trading dashboard."""
        return HTMLResponse(
            content='<html><head><meta http-equiv="refresh" content="0;url=/paper-trading"></head>'
            "<body>Redirecting…</body></html>",
            status_code=200,
        )

    @app.get("/pricing", response_class=HTMLResponse, tags=["Monetization"])
    async def pricing_page():
        """Pricing tiers and subscription options."""
        return _serve_template(
            "pricing.html",
            """<html>
            <head><title>HOPEFX Pricing</title></head>
            <body style="background:#0a0f1c;color:#ffffff;font-family:sans-serif;padding:40px;text-align:center;">
                <h1>Pricing</h1>
                <p>Pricing page template not found. Please ensure templates/pricing.html exists.</p>
                <a href="/docs" style="color:#00d4aa;">Go to API Docs</a>
            </body></html>""",
        )

    @app.get("/paper-trading", response_class=HTMLResponse, tags=["Trading"])
    async def paper_trading_dashboard():
        """Paper trading simulation dashboard."""
        return _serve_template(
            "paper_trading.html",
            """<html>
            <head><title>Paper Trading</title></head>
            <body style="background:#131722;color:#d1d4dc;font-family:sans-serif;padding:40px;text-align:center;">
                <h1>Paper Trading Dashboard</h1>
                <p>Template not found. Please ensure templates/paper_trading.html exists.</p>
                <a href="/docs" style="color:#26a69a;">Go to API Docs</a>
            </body></html>""",
        )

    @app.get("/stream", response_class=HTMLResponse, tags=["Dashboard"])
    async def stream_dashboard():
        """Live streaming dashboard (prices, signals, news, alerts)."""
        return _serve_template(
            "stream_dashboard.html",
            """<html>
            <head><title>Live Stream</title></head>
            <body style="background:#131722;color:#d1d4dc;font-family:sans-serif;padding:40px;text-align:center;">
                <h1>Live Stream</h1>
                <p>Template not found. Please ensure templates/stream_dashboard.html exists.</p>
                <a href="/docs" style="color:#26a69a;">Go to API Docs</a>
            </body></html>""",
        )

    # React dashboard — mounted LAST so all /api/* routes take precedence.
    # Falls back gracefully when dist/ doesn't exist yet.
    _dashboard_dist = Path(__file__).parent.parent / "dashboard" / "dist"
    if _dashboard_dist.exists():

        @app.get("/", include_in_schema=False)
        async def _root_redirect():
            return RedirectResponse(url="/app/", status_code=302)

        app.mount(
            "/app",
            StaticFiles(directory=str(_dashboard_dist), html=True),
            name="dashboard",
        )
        app.mount(
            "/",
            StaticFiles(directory=str(_dashboard_dist), html=True),
            name="dashboard_root",
        )
        logger.info("React dashboard mounted at /app and / (dashboard/dist/)")
    else:
        logger.warning("dashboard/dist/ not found — run 'cd dashboard && npm run build' to build the UI")
