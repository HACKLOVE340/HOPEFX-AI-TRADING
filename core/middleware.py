# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/middleware.py
==================
FastAPI middleware registration: CORS, security headers, Prometheus metrics.

Extracted from app.py to keep the application entry point under 300 lines.
"""

from __future__ import annotations

import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


def setup_cors(app: FastAPI) -> None:
    """
    Add CORS middleware with restricted origins.

    In production set ALLOWED_ORIGINS to your frontend domain(s):
        ALLOWED_ORIGINS=https://app.hopefx.io,https://hopefx.io

    The default (localhost:3000) is intentionally restrictive so the app
    starts safely without any .env file, but it will block browser requests
    from any non-localhost origin.
    """
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
    allowed_origins = [o.strip() for o in raw.split(",") if o.strip()]

    app_env = os.getenv("APP_ENV", "development")
    if app_env == "production":
        if "*" in allowed_origins:
            logger.critical(
                "STARTUP BLOCKED: ALLOWED_ORIGINS contains '*' with "
                "allow_credentials=True. This is a CORS misconfiguration that "
                "exposes authenticated endpoints to any origin. Set explicit "
                "HTTPS origins, e.g.: ALLOWED_ORIGINS=https://app.yourdomain.com"
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
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


def setup_security_headers(app: FastAPI) -> None:
    """Add security response headers to every reply."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as _Req

    class _SecurityHeaders(BaseHTTPMiddleware):
        _HEADERS = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self' wss:;"
            ),
        }

        async def dispatch(self, request: _Req, call_next):
            response = await call_next(request)
            for header, value in self._HEADERS.items():
                response.headers[header] = value
            return response

    app.add_middleware(_SecurityHeaders)


def setup_metrics_middleware(app: FastAPI) -> None:
    """Add Prometheus HTTP metrics middleware."""
    try:
        from starlette.middleware.base import BaseHTTPMiddleware

        from core.metrics import make_metrics_middleware

        app.add_middleware(BaseHTTPMiddleware, dispatch=make_metrics_middleware())
        logger.info("Prometheus metrics middleware registered")
    except Exception as exc:
        logger.warning("Metrics middleware not available: %s", exc)


def register_all(app: FastAPI) -> None:
    """Register all middleware on *app* in the correct order."""
    setup_cors(app)
    setup_security_headers(app)
    setup_metrics_middleware(app)
