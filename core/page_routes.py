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

import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

_TEMPLATES = Path(__file__).parent.parent / "templates"

# Shape of a servable static asset path, e.g. "assets/index-a1b2c3.js",
# "favicon.svg", "images/logo.png".
#
# Every segment must begin with an alphanumeric. That single rule is what makes
# traversal unspellable: "." and ".." can never BE a segment, so there is no
# input that climbs out of the build directory for the confinement check to
# catch. Backslashes, NUL, and a leading "/" are excluded by the character
# class.
_ASSET_PATH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*(?:/[A-Za-z0-9][A-Za-z0-9_.\-]*)*")

# Length bound applied before matching, so a pathological URL never reaches the
# regex or the filesystem. Comfortably above any real Vite asset path.
_MAX_ASSET_PATH_LEN = 255


# ── Caching ───────────────────────────────────────────────────────────────────
#
# Vite emits content-hashed filenames — `app-analytics-DUbayt-I.js`. The hash
# changes whenever the contents change, so the file at a given URL is immutable
# by construction and can be cached for as long as the browser will keep it.
#
# Nothing was setting Cache-Control, so the browser fell back to revalidating
# on every navigation: roughly fifteen conditional requests, each a full round
# trip, before any page could paint. On a distant VPS that is most of the
# perceived load time even when every response is a 304.
#
# index.html is the opposite case and must never be cached — it is the document
# that names the current hashed bundles. Caching it pins the browser to a stale
# build after a deploy, and the assets it references may no longer exist.
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
_NO_CACHE = "no-cache, no-store, must-revalidate"

_INDEX_CACHE_HEADERS = {"Cache-Control": _NO_CACHE}

# Vite's content hash: `<name>-<hash>.<ext>`, where the hash is 8 characters of
# the base64url alphabet. Only files carrying one are safe to treat as immutable.
#
# Deliberately not a regex. The obvious pattern for this —
# `.+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$` — is quadratic, because `.+` and the
# character class can both match '-' and have to be split between them: on a
# non-matching input of "-a" repeated, 4 k chars took 10 ms, 8 k took 39 ms,
# 16 k took 163 ms. `_CachingStaticFiles` calls this with the raw request path
# and no length bound, so that was reachable from a URL.
#
# The scan below is a single pass with no backtracking.
_HASH_LEN = 8
_HASH_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _has_content_hash(name: str) -> bool:
    """True when *name* ends in Vite's `-<8-char hash>.<ext>` form."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not ext or not ext.isalnum():
        return False
    # Room for at least one name character, the separator, and the hash.
    if len(stem) < _HASH_LEN + 2:
        return False
    if stem[-(_HASH_LEN + 1)] != "-":
        return False
    return all(c in _HASH_ALPHABET for c in stem[-_HASH_LEN:])


def _asset_cache_headers(rel_path: str) -> dict[str, str]:
    """Immutable for content-hashed files, revalidate for everything else."""
    name = rel_path.rsplit("/", 1)[-1]
    if name == "index.html":
        return {"Cache-Control": _NO_CACHE}
    if _has_content_hash(name):
        return {"Cache-Control": _IMMUTABLE_CACHE}
    # No hash in the name (favicon.ico, manifest.json, robots.txt): the URL is
    # stable across deploys, so it has to be revalidated to pick up changes.
    return {"Cache-Control": "public, max-age=0, must-revalidate"}


class _CachingStaticFiles(StaticFiles):
    """StaticFiles that applies the same cache policy as the catch-all above.

    The mount serves most asset requests in practice; without this the policy
    would only apply on the catch-all's fallback path, which is not where the
    hot requests go.
    """

    def file_response(self, full_path, stat_result, scope, status_code=200):  # type: ignore[override]
        response = super().file_response(full_path, stat_result, scope, status_code=status_code)
        rel = scope.get("path", "").lstrip("/")
        for header, value in _asset_cache_headers(rel).items():
            response.headers[header] = value
        return response


@lru_cache(maxsize=512)
def _slashed_paths(route_count: int, app_id: int) -> frozenset[str]:
    """Every registered path, flattened. Cached per (route count, app identity).

    A plain ``for route in app.routes`` walk does not see API routes: with this
    FastAPI version, ``app.routes`` holds opaque ``_IncludedRouter`` wrappers
    for each included router rather than flat ``APIRoute`` instances. The v1
    alias registration in core/router_registry.py hit the same thing and
    silently created zero aliases until it switched to ``iter_api_routes``.
    """
    from core.router_registry import iter_api_routes

    app = _APP_BY_ID.get(app_id)
    if app is None:
        return frozenset()
    return frozenset(r.path for r in iter_api_routes(app.routes))


_APP_BY_ID: dict[int, FastAPI] = {}


def _slashed_route_exists(app: FastAPI, path: str) -> bool:
    """True when *path* (which ends in '/') is a real registered route."""
    _APP_BY_ID[id(app)] = app
    try:
        return path in _slashed_paths(len(app.routes), id(app))
    except Exception:  # nosec B110 — a redirect aid must never break a request
        return False


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
        # Resolved once here so the catch-all below can confine every asset
        # lookup to this directory without re-resolving on each request.
        _frontend_dist_resolved = _frontend_dist.resolve()

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
            # ── Public / auth ──────────────────────────────────────────────
            "/",
            "/login",
            "/register",
            "/forgot-password",
            "/reset-password",
            "/onboarding",
            "/pricing",
            "/terms",
            "/risk-disclosure",
            "/privacy",
            "/status",
            # ── Core trading ───────────────────────────────────────────────
            "/dashboard",
            "/home",
            "/trade",
            "/trading",
            "/terminal",
            "/portfolio",
            "/performance",
            "/watchlist",
            "/alerts",
            "/calendar",
            # ── Analysis & research ────────────────────────────────────────
            "/nuclear",
            "/geopolitical",
            "/correlation",
            "/tca",
            "/ai-strategy",
            "/indicators",
            "/walk-forward",
            "/ab-testing",
            "/replay",
            "/research",
            "/backtest",
            # ── Tools ──────────────────────────────────────────────────────
            "/journal",
            "/prop-firm",
            "/copy-trading",
            "/risk-calc",
            "/risk-calculator",
            # ── Community / social ─────────────────────────────────────────
            "/leaderboard",
            "/feed",
            "/social",
            "/marketplace",
            "/affiliate",
            "/teams",
            # ── Account ────────────────────────────────────────────────────
            "/profile",
            "/wallet",
            "/sub-accounts",
            "/elite",
            "/checkout",
            "/crypto-checkout",
            "/settings",
            "/2fa-setup",
            # ── Admin ──────────────────────────────────────────────────────
            "/admin",
            "/audit",
            "/audit-log",
            "/security",
            "/security-dashboard",
            "/auto-heal",
            "/whitelabel",
            # ── Super admin ────────────────────────────────────────────────
            "/superadmin",
            "/system-reliability",
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
                "api/",
                "ws/",
                "godmode/",
                "godmode",
                "docs",
                "redoc",
                "health",
                "health/",
                "metrics",
                "kyc",
                "kyc/",
                "decision",
                "decision/",
                "replay",
                "replay/",
                "mobile",
                "mobile/",
                "favicon.ico",
            )
            if any(
                full_path == p or full_path.startswith(p + "/") or full_path.startswith(p)
                for p in _passthrough_prefixes
            ):
                # Restore the trailing-slash redirect this route otherwise eats.
                #
                # The comment here used to say returning 404 "passes through so
                # Starlette tries the next matching route". It does not: this
                # route has already matched, and returning a response ends the
                # request. Starlette's automatic redirect for a path whose only
                # registered form carries a trailing slash runs *after* no route
                # matched, so a catch-all that matches everything disables it.
                #
                # Concretely: /api/notifications 404s while
                # /api/notifications/ returns 200. api/notifications.py declares
                # the route at both "" and "/" specifically to avoid this, and
                # that mitigation does not survive router inclusion — both
                # declarations end up registered as /api/notifications/, so the
                # bare form has no route at all. The same holds for /api/admin,
                # /api/alerts, /api/dom and /api/superadmin.
                #
                # Redirecting here fixes every such endpoint, including ones
                # added later, instead of patching one router at a time.
                if request.method == "GET" and _slashed_route_exists(request.app, "/" + full_path + "/"):
                    _qs = request.url.query
                    return RedirectResponse(
                        url="/" + full_path + "/" + (f"?{_qs}" if _qs else ""),
                        status_code=307,
                    )
                # Say what was not found.
                #
                # This returned a bodiless 404, and the frontend's
                # `extractApiError` has an explicit branch for exactly that:
                #     // For 404 with no body, return the fallback rather than
                #     // the raw Axios message
                # so every missing endpoint surfaced as whatever generic string
                # the calling page happened to pass — "Could not load
                # notifications", "Could not load your subscription", "Failed to
                # load balance." Three panels, three different messages, one
                # cause, and nothing on screen or in the network tab that named
                # it. A whole endpoint family can go missing — a feature flag
                # off, a router that failed to import, a prefix renamed — and it
                # is indistinguishable from a server error or a bad session.
                return JSONResponse(
                    status_code=404,
                    content={
                        "detail": f"No route for {request.method} /{full_path}",
                        "path": f"/{full_path}",
                        "method": request.method,
                    },
                )
            # Serve real static assets (JS/CSS/images) from the build output.
            #
            # `full_path` is the raw catch-all segment. `Path / "x"` applies no
            # traversal check of its own, and the passthrough list above only
            # screens known route prefixes, so nothing here stopped a segment
            # climbing out of the build directory.
            #
            # Two independent guards, in the order the rest of the codebase uses
            # (security/antivirus.py, api/backtesting.py, ml/online_learner.py):
            #
            #   1. Allowlist. Every segment must begin with an alphanumeric, so
            #      "." and ".." cannot BE a segment — traversal is unspellable
            #      rather than merely detected. No backslashes, no NUL, no
            #      leading "/". The path is then rebuilt from the match output,
            #      so the tainted string never reaches path construction.
            #   2. Confinement. Resolve and prove the result is still inside the
            #      build output, in case the allowlist is ever loosened.
            #
            # A path failing either check is not an asset, so it falls through
            # to index.html like any other unknown route — the response does not
            # distinguish "escaped" from "not found".
            _is_asset = False
            _asset: Path | None = None
            _m = _ASSET_PATH_RE.fullmatch(full_path) if len(full_path) <= _MAX_ASSET_PATH_LEN else None
            if _m is not None:
                _safe_rel: str = _m.group(0)  # untainted — output of a pattern match
                try:
                    _asset = Path(os.path.join(str(_frontend_dist_resolved), _safe_rel)).resolve()
                    _asset.relative_to(_frontend_dist_resolved)
                    _is_asset = _asset.is_file()
                except (ValueError, OSError):
                    _is_asset = False
            if _is_asset and _asset is not None:
                return FileResponse(str(_asset), headers=_asset_cache_headers(_safe_rel))
            # Everything else is a React Router path → serve index.html
            return FileResponse(str(_index_html), headers=_INDEX_CACHE_HEADERS)

        app.mount(
            "/",
            _CachingStaticFiles(directory=str(_frontend_dist), html=True),
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
