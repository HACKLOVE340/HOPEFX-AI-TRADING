# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/middleware.py
==================
FastAPI middleware registration: CORS, security headers, request-ID tracing,
cache-control, and Prometheus metrics.

Extracted from app.py to keep the application entry point under 300 lines.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from typing import ClassVar

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").lower() == "production"


def _build_csp(allowed_origins: list[str]) -> str:
    """Build a Content-Security-Policy header value.

    connect-src includes all configured ALLOWED_ORIGINS (both https:// and
    wss:// variants) so the browser permits XHR/fetch and WebSocket connections
    to the API without needing a wildcard.
    """
    # Derive wss:// equivalents from https:// origins for WebSocket connections
    connect_srcs = ["'self'"]
    for origin in allowed_origins:
        connect_srcs.append(origin)
        if origin.startswith("https://"):
            connect_srcs.append("wss://" + origin[len("https://") :])
        elif origin.startswith("http://"):
            connect_srcs.append("ws://" + origin[len("http://") :])

    connect_src = " ".join(connect_srcs)

    # In production avoid unsafe-inline for scripts; React is bundled so it
    # doesn't need it.  Keep unsafe-inline for styles (Tailwind inline styles).
    script_src = "'self'" if _is_production() else "'self' 'unsafe-inline'"

    return (
        f"default-src 'self'; "
        f"script-src {script_src}; "
        f"style-src 'self' 'unsafe-inline'; "
        # QR code images for 2FA setup (api.qrserver.com) + data URIs for charts
        f"img-src 'self' data: https://api.qrserver.com; "
        f"font-src 'self'; "
        f"connect-src {connect_src}; "
        f"frame-ancestors 'none'; "
        f"base-uri 'self'; "
        f"form-action 'self';"
    )


# ── CORS ──────────────────────────────────────────────────────────────────────


def setup_cors(app: FastAPI) -> None:
    """Add CORS middleware with restricted origins.

    In production set ALLOWED_ORIGINS to your frontend domain(s):
        ALLOWED_ORIGINS=https://app.hopefx.io,https://hopefx.io

    The default (localhost) is intentionally restrictive so the app starts
    safely without any .env file, but it will block browser requests from
    any non-localhost origin.
    """
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
    allowed_origins = [o.strip() for o in raw.split(",") if o.strip()]

    if _is_production():
        if "*" in allowed_origins:
            logger.critical(
                "STARTUP BLOCKED: ALLOWED_ORIGINS contains '*' with "
                "allow_credentials=True — exposes authenticated endpoints to any "
                "origin. Set explicit HTTPS origins, e.g.: "
                "ALLOWED_ORIGINS=https://app.yourdomain.com"
            )
            sys.exit(1)

        insecure = [o for o in allowed_origins if o.startswith("http://")]
        if insecure:
            logger.critical(
                "STARTUP BLOCKED: ALLOWED_ORIGINS contains insecure http:// "
                "origins in production: %s. Use https:// only.",
                insecure,
            )
            sys.exit(1)

        if all("localhost" in o or "127." in o for o in allowed_origins):
            logger.critical(
                "STARTUP BLOCKED: ALLOWED_ORIGINS is restricted to localhost in "
                "production. Set ALLOWED_ORIGINS to your frontend domain(s), e.g.: "
                "ALLOWED_ORIGINS=https://app.yourdomain.com"
            )
            sys.exit(1)

    logger.info("CORS allowed origins: %s", allowed_origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-Webhook-Signature",
        ],
        expose_headers=["X-Request-ID"],
    )

    # Store for use by CSP builder
    app.state.allowed_origins = allowed_origins


# ── Security headers ──────────────────────────────────────────────────────────


def setup_security_headers(app: FastAPI) -> None:
    """Add security response headers to every reply.

    Headers applied:
    - X-Content-Type-Options: prevent MIME sniffing
    - X-Frame-Options: clickjacking protection (also covered by CSP frame-ancestors)
    - X-XSS-Protection: legacy XSS filter (belt-and-suspenders)
    - Referrer-Policy: limit referrer leakage
    - Strict-Transport-Security: HSTS (only meaningful behind TLS)
    - Permissions-Policy: disable unused browser features
    - Content-Security-Policy: restrict resource loading
    - Cache-Control: prevent caching of API responses
    - X-Request-ID: echo the request ID for client-side correlation
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as _Req

    # Build CSP once at startup using the origins registered by setup_cors()
    _allowed_origins: list[str] = getattr(app.state, "allowed_origins", [])
    _csp = _build_csp(_allowed_origins)

    _STATIC_HEADERS: dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        "Content-Security-Policy": _csp,
    }
    # HSTS only makes sense over TLS — skip in dev to avoid breaking http://
    if _is_production():
        _STATIC_HEADERS["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

    class _SecurityHeaders(BaseHTTPMiddleware):
        _headers: ClassVar[dict[str, str]] = _STATIC_HEADERS

        async def dispatch(self, request: _Req, call_next):
            # Generate or propagate a request ID for distributed tracing
            req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

            response = await call_next(request)

            for header, value in self._headers.items():
                response.headers[header] = value

            # Echo request ID so clients can correlate logs
            response.headers["X-Request-ID"] = req_id

            # Prevent API responses from being cached by proxies / browsers.
            # Static assets served by StaticFiles already set their own headers.
            path = request.url.path
            if path.startswith("/api/") or path.startswith("/ws/"):
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
                response.headers["Pragma"] = "no-cache"

            return response

    app.add_middleware(_SecurityHeaders)
    logger.info("Security headers middleware registered (CSP: %d chars)", len(_csp))


# ── Prometheus metrics ────────────────────────────────────────────────────────


def setup_metrics_middleware(app: FastAPI) -> None:
    """Add Prometheus HTTP metrics middleware."""
    try:
        from starlette.middleware.base import BaseHTTPMiddleware

        from core.metrics import make_metrics_middleware

        app.add_middleware(BaseHTTPMiddleware, dispatch=make_metrics_middleware())
        logger.info("Prometheus metrics middleware registered")
    except Exception as exc:
        logger.warning("Metrics middleware not available: %s", exc)


# ── Entry point ───────────────────────────────────────────────────────────────


def register_all(app: FastAPI) -> None:
    """Register all middleware on *app* in the correct order.

    Order matters — Starlette applies middleware in reverse registration order
    (last registered = outermost = first to process the request).
    We want: metrics → security headers → CORS (outermost).
    """
    setup_metrics_middleware(app)  # innermost — runs after routing
    setup_security_headers(app)  # middle
    setup_cors(app)  # outermost — handles preflight first
