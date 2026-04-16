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
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        """Return the favicon from dashboard/dist or a minimal 1×1 transparent ICO."""
        _ico_candidates = [
            Path(__file__).parent.parent / "dashboard" / "dist" / "favicon.ico",
            Path(__file__).parent.parent / "static" / "favicon.ico",
            Path(__file__).parent.parent / "assets" / "favicon.ico",
        ]
        for _p in _ico_candidates:
            if _p.exists():
                return Response(content=_p.read_bytes(), media_type="image/x-icon")
        # Minimal 1×1 transparent ICO (46 bytes) — avoids 404 noise in logs
        _ico_bytes = (
            b"\x00\x00\x01\x00\x01\x00\x01\x01\x00\x00\x01\x00\x18\x00"
            b"\x30\x00\x00\x00\x16\x00\x00\x00\x28\x00\x00\x00\x01\x00"
            b"\x00\x00\x02\x00\x00\x00\x01\x00\x18\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00"
        )
        return Response(content=_ico_bytes, media_type="image/x-icon")

    # NOTE: /login, /register, /dashboard, /admin, /superadmin are intentionally
    # NOT registered here. The React SPA (mounted below with html=True) serves
    # index.html for all unmatched paths, which lets React Router handle them.
    # Adding server-side routes for those paths would intercept the browser
    # request before React Router runs and break client-side navigation.

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

    # ── React SPA mounts — loaded LAST so all /api/* routes take precedence ──
    #
    # Priority order (first match wins):
    #   1. frontend/static/  — main React app (Vite outDir: ../static)
    #   2. dashboard/dist/   — legacy GodMode dashboard (fallback)
    #
    # Build commands:
    #   Main app:   cd frontend && npm run build   → outputs to ../static/
    #   GodMode:    cd dashboard && npm run build  → outputs to dashboard/dist/
    _root = Path(__file__).parent.parent
    _frontend_dist = _root / "static"  # frontend Vite build output
    _dashboard_dist = _root / "dashboard" / "dist"  # legacy dashboard build

    if _frontend_dist.exists() and (_frontend_dist / "index.html").exists():
        # Primary: serve the main React app at /
        app.mount(
            "/",
            StaticFiles(directory=str(_frontend_dist), html=True),
            name="frontend_spa",
        )
        logger.info("Main React app mounted at / (static/)")

        # Also expose legacy GodMode at /godmode/ if it exists
        if _dashboard_dist.exists() and (_dashboard_dist / "index.html").exists():
            app.mount(
                "/godmode",
                StaticFiles(directory=str(_dashboard_dist), html=True),
                name="godmode_dashboard",
            )
            logger.info("GodMode dashboard mounted at /godmode/ (dashboard/dist/)")

    elif _dashboard_dist.exists() and (_dashboard_dist / "index.html").exists():
        # Fallback: only legacy dashboard is built
        @app.get("/", include_in_schema=False)
        async def _root_redirect_godmode():
            return RedirectResponse(url="/godmode/", status_code=302)

        app.mount(
            "/godmode",
            StaticFiles(directory=str(_dashboard_dist), html=True),
            name="godmode_dashboard",
        )
        logger.info("GodMode dashboard mounted at /godmode/ (dashboard/dist/) — main app not built yet")
        logger.warning("Run 'cd frontend && npm run build' to build the main React app")

    else:
        logger.warning(
            "No React build found. Run:\n"
            "  cd frontend && npm run build   # main app → static/\n"
            "  cd dashboard && npm run build  # GodMode  → dashboard/dist/"
        )
