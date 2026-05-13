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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

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
            "Accept",
            "Accept-Language",
            "Authorization",
            "Content-Language",
            "Content-Type",
            "X-Request-ID",
            "X-Webhook-Signature",
            # Required for CSRF double-submit cookie pattern — must be listed here
            # or the browser will block the preflight for all state-changing requests.
            "X-CSRF-Token",
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


# ── CSRF middleware ───────────────────────────────────────────────────────────

# Cookie and header names must match auth/router.py get_csrf_token()
_CSRF_COOKIE = "hopefx_csrf"
_CSRF_HEADER = "X-CSRF-Token"

# Paths exempt from CSRF validation (public endpoints, token issuance, webhooks)
_CSRF_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/auth/csrf-token",  # token issuance — no token yet
    "/api/auth/login",  # pre-auth — no session cookie yet
    "/api/auth/register",  # pre-auth
    "/api/auth/activate-free-tier",  # post-registration setup, called before session cookie exists
    "/api/billing/auth/activate-free-tier",  # billing router alias — same semantics
    "/api/auth/refresh",  # uses refresh token, not session
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/verify-email",
    "/api/auth/resend-verification",
    "/api/email/webhook",  # SendGrid webhook — uses HMAC signature
    "/api/billing/webhook/stripe",  # Stripe webhook — uses HMAC-SHA256 signature, no CSRF token
    "/api/monetization/webhook/stripe",  # Stripe webhook (monetization router alias)
    "/api/health",  # health checks
    "/ws",  # WebSocket — uses JWT auth
    "/metrics",  # Prometheus scrape
)

# Methods that mutate state and require CSRF validation
_CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# Disable CSRF in test/CI environments where no browser is involved.
# Evaluated at request time (not module import time) so that test modules
# can set CSRF_PROTECTION=false after the module is imported and have it
# take effect without reloading the module.
def _csrf_enabled() -> bool:
    return os.getenv("CSRF_PROTECTION", "true").lower() not in ("false", "0", "no")


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Double-submit cookie CSRF protection.

    On every state-changing request (POST/PUT/PATCH/DELETE) that is not
    exempt, validates that:
      1. The ``hopefx_csrf`` cookie is present.
      2. The ``X-CSRF-Token`` request header matches the cookie value.

    The token is issued by GET /api/auth/csrf-token and stored as a
    SameSite=Strict cookie.  JavaScript reads the cookie and echoes it
    back as a header — cross-origin requests cannot do this because
    SameSite=Strict prevents the cookie from being sent cross-origin.

    Set CSRF_PROTECTION=false to disable in dev/test environments.

    Internal health-check probes from loopback addresses that carry the
    ``X-Internal-Health-Check: 1`` header are exempt — they are not
    browser-initiated and cannot carry a CSRF cookie.
    """

    # Loopback addresses allowed to use the internal health-check bypass.
    _LOOPBACK_ADDRS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})
    _INTERNAL_HEADER = "X-Internal-Health-Check"

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not _csrf_enabled():
            return await call_next(request)

        if request.method not in _CSRF_PROTECTED_METHODS:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in _CSRF_EXEMPT_PREFIXES):
            return await call_next(request)

        # Internal health-check bypass: loopback-only, explicit opt-in header.
        # This allows the diagnostic runner and self-healer to probe CSRF-protected
        # endpoints without a browser session while keeping the protection intact
        # for all external requests.
        client_ip = request.client.host if request.client else ""
        if client_ip in self._LOOPBACK_ADDRS and request.headers.get(self._INTERNAL_HEADER) == "1":
            return await call_next(request)

        cookie_token = request.cookies.get(_CSRF_COOKIE, "")
        header_token = request.headers.get(_CSRF_HEADER, "")

        if not cookie_token or not header_token:
            # Log at DEBUG — missing tokens are expected from health probes,
            # API clients, and server-side callers that don't carry a browser
            # session.  Token *mismatch* (below) is the real attack signal.
            logger.debug(
                "CSRF validation failed — missing token: path=%s method=%s cookie_present=%s header_present=%s",
                path,
                request.method,
                bool(cookie_token),
                bool(header_token),
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing. Fetch a token from GET /api/auth/csrf-token."},
            )

        # Constant-time comparison to prevent timing attacks
        import hmac as _hmac

        if not _hmac.compare_digest(cookie_token, header_token):
            # Token mismatch IS a warning — it indicates a forged or replayed token.
            logger.warning(
                "CSRF validation failed — token mismatch: path=%s method=%s ip=%s",
                path,
                request.method,
                client_ip or "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token invalid."},
            )

        return await call_next(request)


def setup_csrf_middleware(app: FastAPI) -> None:
    """Add CSRF double-submit cookie middleware."""
    if _csrf_enabled():
        app.add_middleware(CSRFMiddleware)
        logger.info("CSRF middleware enabled (cookie=%s header=%s)", _CSRF_COOKIE, _CSRF_HEADER)
    else:
        logger.warning("CSRF protection DISABLED (CSRF_PROTECTION=false)")


# ── Startup health gate ───────────────────────────────────────────────────────
# Returns 503 for data-dependent API endpoints until app_state.initialized
# is True.  Health, auth, CSRF, docs, and static assets are always allowed
# through so the frontend can render and users can log in while the trading
# engine is still warming up.

# Paths that are always allowed regardless of startup state.
_STARTUP_GATE_ALWAYS_ALLOW: tuple[str, ...] = (
    "/api/health",
    "/api/auth",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/static",
    "/favicon.ico",
    "/ws",  # WebSocket — auth is checked inside the handler
    "/api/status",  # lightweight status page
    "/api/billing",  # billing/plans must be readable before startup completes
    "/api/notifications",
    "/api/kyc",
    "/api/profiles",
    "/api/settings",
    "/api/superadmin",  # admin ops must not be gated
)


class StartupGateMiddleware(BaseHTTPMiddleware):
    """Block data-dependent endpoints with 503 until startup completes.

    Reads app_state.initialized from app.state.app_state so it works
    without importing the module-level app_state directly (avoids circular
    imports and makes the gate testable with a plain Starlette app).

    The gate is disabled when STARTUP_GATE=false (useful in unit tests that
    don't run the full startup sequence).
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if os.getenv("STARTUP_GATE", "true").lower() in ("false", "0", "no"):
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in _STARTUP_GATE_ALWAYS_ALLOW):
            return await call_next(request)

        # Check app_state.initialized via app.state (set in startup_event)
        app_state = getattr(request.app.state, "app_state", None)
        initialized = getattr(app_state, "initialized", False) if app_state else False

        if not initialized:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Server is starting up. Please retry in a few seconds.",
                    "status": "starting",
                },
                headers={"Retry-After": "5"},
            )

        return await call_next(request)


def setup_startup_gate(app: FastAPI) -> None:
    """Add the startup health gate middleware."""
    app.add_middleware(StartupGateMiddleware)
    logger.info("StartupGateMiddleware registered — data endpoints return 503 until initialized")


def register_all(app: FastAPI) -> None:
    """Register all middleware on *app* in the correct order.

    Order matters — Starlette applies middleware in reverse registration order
    (last registered = outermost = first to process the request).
    We want:
      startup_gate → CSRF → metrics → security headers → CORS (outermost)
    """
    setup_startup_gate(app)  # innermost — gate before CSRF so 503 beats 403
    setup_csrf_middleware(app)
    setup_metrics_middleware(app)
    setup_security_headers(app)
    setup_cors(app)  # outermost — handles preflight first
