# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_auth_coverage.py
============================
Structural gate: every mutating route (POST/PUT/PATCH/DELETE) must carry
an auth dependency — either ``get_current_user`` or ``require_role`` — or
be explicitly whitelisted.

Why this matters
----------------
Two previous auth gaps (the /api/nocode and /api/research routes) were
reachable without a token because the routers were registered without a
top-level ``dependencies=[Depends(get_current_user)]`` and the individual
endpoint functions also lacked the dependency.  This test iterates every
registered FastAPI route at import time and fails the build if the same
class of omission recurs.

Whitelist policy
----------------
Only routes that are *intentionally* public (auth/register, auth/login,
password-reset initiation, health probes) belong in WHITELIST.  Adding a
route to the whitelist to silence this test without a documented reason is
a security regression.
"""

from __future__ import annotations

import os
import sys

# Must be set before any app module is imported so startup validators and
# feature-flag checks see the test environment.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("STARTUP_GATE", "false")
os.environ.setdefault("CSRF_PROTECTION", "false")

import pytest

# ---------------------------------------------------------------------------
# Lazy app import — skip the whole module if the app cannot be imported in
# this environment (e.g. missing optional C-extensions in a minimal CI image).
# ---------------------------------------------------------------------------
try:
    from app import app as _app
    from api.auth import get_current_user, require_role

    _import_error: Exception | None = None
except Exception as _exc:  # noqa: BLE001
    _import_error = _exc

if _import_error is not None:
    pytest.skip(
        f"test_auth_coverage: app import failed — {_import_error}",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# Whitelist — routes that are intentionally public for mutating methods.
# Each entry must have a comment explaining why it is public.
# ---------------------------------------------------------------------------
WHITELIST: frozenset[str] = frozenset(
    {
        # ── Authentication (unauthenticated by design) ──────────────────────
        "/api/auth/login",               # issues the token — cannot require one
        "/api/auth/register",            # new-user registration
        "/api/auth/refresh",             # token refresh (uses refresh token, not access)
        "/api/auth/logout",              # stateless logout — token may already be expired
        "/api/auth/verify-email",        # email verification link
        "/api/auth/2fa/setup",           # 2FA setup — some flows allow pre-auth setup
        "/api/auth/forgot-password",     # user has no token (forgot it)
        "/api/auth/reset-password",      # uses emailed reset token, not JWT
        "/api/auth/resend-verification", # user may not be logged in yet
        "/api/auth/activate-free-tier",  # called immediately after registration
        # ── Health / readiness probes (called by load-balancers, no auth) ───
        "/api/health",
        "/api/health/",
        "/api/health/live",
        "/api/health/ready",
        "/api/health/startup",
        # ── Kill switch (uses its own HOPEFX_KILL_SWITCH_TOKEN header) ───────
        "/api/kill-switch/activate",     # uses HOPEFX_KILL_SWITCH_TOKEN header
        "/api/kill-switch/deactivate",   # uses HOPEFX_KILL_SWITCH_TOKEN header
        # ── Webhook receivers (use HMAC/ECDSA signature verification) ────────
        "/api/webhooks/tradingview",         # TradingView HMAC-verified webhook
        "/api/v1/webhooks/tradingview",      # v1 alias — same HMAC verification
        "/api/billing/webhook/stripe",       # Stripe HMAC-verified webhook
        "/api/v1/billing/webhook/stripe",    # v1 alias
        "/api/monetization/webhook/stripe",  # Stripe HMAC-verified webhook
        "/api/v1/monetization/webhook/stripe",  # v1 alias
        "/api/payments/webhook",             # crypto payment provider webhook
        "/api/v1/payments/webhook",          # v1 alias
        "/kyc/webhooks/sumsub",              # Sumsub HMAC-verified webhook
        "/kyc/webhooks/onfido",              # Onfido HMAC-verified webhook
        "/api/email/webhook",                # SendGrid ECDSA-verified webhook
        # ── Public pricing calculator (landing page, no session needed) ──────
        "/api/pricing/estimate",
        "/api/v1/pricing/estimate",
        # ── Billing: free-tier activation (called right after registration) ──
        "/api/billing/auth/activate-free-tier",
        "/api/v1/billing/auth/activate-free-tier",
        # ── Mobile auth (own JWT stack, public by design) ─────────────────────
        "/mobile/api/v2/auth/register",
        "/mobile/api/v2/auth/login",
        "/mobile/api/v2/auth/refresh",
        # ── v1 auth aliases (same public flows as /api/auth/*) ───────────────
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/resend-verification",
        "/api/v1/auth/activate-free-tier",
        "/api/v1/auth/2fa/setup",
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_auth_deps(route) -> list:
    """
    Return the list of dependency *callables* attached to a route.

    FastAPI stores dependencies as ``fastapi.params.Depends`` objects on
    ``route.dependencies``.  We also inspect the endpoint function's own
    parameter defaults so that per-parameter ``Depends(get_current_user)``
    annotations are detected even when the router carries no top-level deps.
    """
    from fastapi.params import Depends as _Depends
    import inspect

    dep_callables: list = []

    # 1. Router-level / route-level dependencies (route.dependencies)
    for dep in getattr(route, "dependencies", []):
        if isinstance(dep, _Depends) and dep.dependency is not None:
            dep_callables.append(dep.dependency)

    # 2. Per-parameter Depends() in the endpoint signature
    try:
        sig = inspect.signature(route.endpoint)
        for param in sig.parameters.values():
            if isinstance(param.default, _Depends) and param.default.dependency is not None:
                dep_callables.append(param.default.dependency)
    except (ValueError, TypeError):
        pass

    return dep_callables


def _is_auth_dep(dep) -> bool:
    """
    Return True if *dep* is any recognised authentication/authorisation
    dependency used across the HOPEFX codebase.

    Recognised patterns
    -------------------
    * ``get_current_user`` / ``require_role`` from api.auth
    * ``require_role.<locals>._check`` — closure returned by require_role(...)
    * ``require_plan.<locals>._dependency`` — closure returned by require_plan(...)
    * ``_get_current_user_id`` from auth.router (session-based auth)
    * ``_heal_require_admin`` from security.self_healer
    * ``_av_require_admin`` from security.antivirus
    * ``require_kyc`` from api.auth
    * ``MobileAPIServer._verify_token`` from mobile.api_v2
    * ``_require_auth`` from api.tracing
    * ``create_kill_switch_router.<locals>._require_admin`` from kill_switch
    * Any callable from api.auth / auth.router whose name implies auth
    """
    if dep is get_current_user:
        return True
    if dep is require_role:
        return True

    qualname: str = getattr(dep, "__qualname__", "") or ""
    module: str = getattr(dep, "__module__", "") or ""
    name: str = getattr(dep, "__name__", "") or ""

    # Closures returned by factory functions
    _AUTH_QUALNAMES = {
        "require_role.<locals>._check",
        "require_plan.<locals>._dependency",
        "create_kill_switch_router.<locals>._require_admin",
    }
    if qualname in _AUTH_QUALNAMES:
        return True

    # Named auth helpers in known auth modules
    _AUTH_MODULES = {
        "api.auth",
        "auth.router",
        "security.self_healer",
        "security.antivirus",
        "mobile.api_v2",
        "kill_switch",
        "api.tracing",
    }
    _AUTH_KEYWORDS = {"user", "role", "auth", "admin", "require", "token", "verify", "kyc"}
    if module in _AUTH_MODULES and any(kw in name.lower() for kw in _AUTH_KEYWORDS):
        return True

    # Catch-all: any qualname that contains "require_role" or "require_plan"
    if "require_role" in qualname or "require_plan" in qualname:
        return True

    return False


# ---------------------------------------------------------------------------
# The gate test
# ---------------------------------------------------------------------------


def test_all_mutating_routes_require_auth() -> None:
    """
    Every POST/PUT/PATCH/DELETE route must have an auth dependency unless it
    is explicitly whitelisted.

    Failure means a mutating endpoint was registered without authentication.
    Fix: add ``Depends(get_current_user)`` or ``Depends(require_role(...))``
    to the endpoint or its router, then re-run this test.
    """
    from fastapi.routing import APIRoute

    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    violations: list[str] = []

    for route in _app.routes:
        if not isinstance(route, APIRoute):
            continue  # WebSocket, Mount, etc. — not in scope

        methods = route.methods or set()
        if not (methods & MUTATING_METHODS):
            continue  # GET / HEAD / OPTIONS — not in scope

        if route.path in WHITELIST:
            continue

        dep_callables = _collect_auth_deps(route)
        if not any(_is_auth_dep(d) for d in dep_callables):
            mutating = sorted(methods & MUTATING_METHODS)
            violations.append(
                f"  {' | '.join(mutating):30s}  {route.path}"
            )

    if violations:
        header = (
            f"\n{len(violations)} mutating route(s) have no auth dependency.\n"
            "Add Depends(get_current_user) or Depends(require_role(...)) to each,\n"
            "or add the path to WHITELIST with a justification comment.\n\n"
            "  METHODS                          PATH\n"
            "  " + "-" * 60
        )
        pytest.fail(header + "\n" + "\n".join(violations))


def test_whitelist_entries_are_registered() -> None:
    """
    Every path in WHITELIST must correspond to at least one registered route.

    Stale whitelist entries hide real gaps: if a route is renamed or removed
    the whitelist silently covers a path that no longer exists, masking future
    additions at the same path.
    """
    from fastapi.routing import APIRoute

    registered_paths = {route.path for route in _app.routes if isinstance(route, APIRoute)}

    stale = [p for p in WHITELIST if p not in registered_paths]

    if stale:
        pytest.fail(
            f"\n{len(stale)} WHITELIST path(s) are not registered in the app.\n"
            "Remove them from WHITELIST or re-register the route:\n"
            + "\n".join(f"  {p}" for p in sorted(stale))
        )


def test_auth_endpoints_are_whitelisted() -> None:
    """
    Sanity check: the core auth endpoints that must be public are present in
    both the whitelist and the registered routes.
    """
    from fastapi.routing import APIRoute

    MUST_BE_PUBLIC = {"/api/auth/login", "/api/auth/register"}

    registered_paths = {route.path for route in _app.routes if isinstance(route, APIRoute)}

    for path in MUST_BE_PUBLIC:
        assert path in WHITELIST, (
            f"{path} must be in WHITELIST — it is intentionally unauthenticated"
        )
        assert path in registered_paths, (
            f"{path} is in WHITELIST but not registered in the app"
        )
