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

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
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

    @app.get("/docs/", include_in_schema=False)
    async def docs_trailing_slash():
        """Redirect /docs/ → /docs so the Swagger UI loads correctly."""
        return RedirectResponse(url="/docs", status_code=301)

    @app.get("/redoc/", include_in_schema=False)
    async def redoc_trailing_slash():
        """Redirect /redoc/ → /redoc so the ReDoc UI loads correctly."""
        return RedirectResponse(url="/redoc", status_code=301)

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
    # SuperAdminDashboard.tsx is the React component for /superadmin — it calls
    # /api/superadmin/* endpoints directly with the Bearer token in the header.

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
        _index_html = _frontend_dist / "index.html"

        # ── SPA catch-all: serve index.html for every React Router path ──────
        #
        # Starlette's StaticFiles(html=True) only serves index.html for the
        # exact root path ("/") and for paths that match real files on disk.
        # SPA routes like /dashboard, /trade, /superadmin have no corresponding
        # file, so StaticFiles returns 404. Fix: register explicit GET routes
        # for every known SPA path BEFORE the StaticFiles mount, all returning
        # index.html. React Router then handles the path client-side.
        #
        # The wildcard catch-all below handles any path not matched by an
        # earlier /api/* or static-asset route.

        _SPA_ROUTES = [
            "/dashboard", "/trade", "/trading", "/portfolio", "/profile",
            "/settings", "/admin", "/superadmin", "/onboarding",
            "/login", "/register", "/forgot-password", "/reset-password",
            "/2fa-setup", "/wallet", "/watchlist", "/leaderboard",
            "/copy-trading", "/social", "/marketplace", "/affiliate",
            "/performance", "/risk-calculator", "/economic-calendar",
            "/price-alerts", "/trade-journal", "/custom-indicators",
            "/ai-strategy", "/backtest", "/walk-forward", "/prop-firm",
            "/nuclear", "/whitelabel", "/audit-log", "/status",
            "/privacy", "/terms", "/security-dashboard", "/tca",
            "/correlation", "/geopolitical", "/sub-accounts",
            "/ab-testing", "/auto-heal", "/crypto-checkout",
        ]

        async def _spa_index(_req: Request) -> FileResponse:
            return FileResponse(str(_index_html))

        for _spa_path in _SPA_ROUTES:
            app.add_api_route(
                _spa_path,
                _spa_index,
                methods=["GET"],
                include_in_schema=False,
            )

        # Catch-all for any other SPA sub-path not listed above.
        # Must NOT intercept API routes, WebSocket paths, or static assets.
        @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
        async def _spa_catchall(full_path: str, request: Request) -> Response:
            # Paths that belong to real server-side handlers — pass through
            # by returning 404 here so Starlette tries the next matching route.
            # Note: StaticFiles mount is registered AFTER this route, so assets
            # under /assets/ are served by the StaticFiles handler, not here.
            _passthrough_prefixes = (
                "api/", "ws/", "godmode/", "godmode",
                "docs", "redoc",
                "health", "health/",
                "metrics",
                "kyc", "kyc/",
                "decision", "decision/",
                "replay", "replay/",
                "mobile", "mobile/",
                "favicon.ico",
            )
            if any(full_path == p or full_path.startswith(p + "/") or full_path.startswith(p)
                   for p in _passthrough_prefixes):
                return Response(status_code=404)
            # Serve real static assets (JS/CSS/images) from the build output
            _asset = _frontend_dist / full_path
            if _asset.exists() and _asset.is_file():
                return FileResponse(str(_asset))
            # Everything else is a React Router path → serve index.html
            return FileResponse(str(_index_html))

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
        # No built frontend found — serve a helpful placeholder at / that
        # explains how to build the frontend. The API still works fully.
        @app.get("/", include_in_schema=False)
        async def _root_no_frontend():
            return HTMLResponse(
                content="""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>HOPEFX — Build Required</title>
  <style>
    body{background:#0f172a;color:#f1f5f9;font-family:system-ui,sans-serif;
         display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
    .card{background:#1e293b;border:1px solid #334155;border-radius:12px;
          padding:40px;max-width:520px;text-align:center}
    h1{color:#3b82f6;margin-bottom:8px}
    code{background:#0f172a;padding:4px 8px;border-radius:4px;font-size:0.9em;color:#94a3b8}
    pre{background:#0f172a;padding:16px;border-radius:8px;text-align:left;
        overflow-x:auto;color:#94a3b8;font-size:0.85em}
    a{color:#3b82f6;text-decoration:none}
    a:hover{text-decoration:underline}
    .badge{display:inline-block;background:#1d4ed8;color:#fff;padding:4px 12px;
           border-radius:20px;font-size:0.8em;margin-top:8px}
  </style>
</head>
<body>
  <div class="card">
    <h1>HOPEFX AI Trading</h1>
    <span class="badge">Frontend Build Required</span>
    <p style="color:#94a3b8;margin-top:16px">
      The React frontend has not been built yet.<br>
      Run the following command to build it:
    </p>
    <pre>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>
    <p style="color:#94a3b8">Or use the quick-start script:</p>
    <pre>./start.sh</pre>
    <p style="margin-top:24px">
      <a href="/docs">API Documentation →</a>
      &nbsp;&nbsp;
      <a href="/health">Health Check →</a>
    </p>
  </div>
</body>
</html>""",
                status_code=200,
            )

        logger.warning(
            "No React build found — serving placeholder at /. Build the frontend with: cd frontend && npm run build"
        )
