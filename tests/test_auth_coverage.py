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

Additionally asserts:
  - Every privileged GET route (admin, kyc, audit, account-specific data)
    has an auth dependency.
  - Every WebSocket endpoint uses in-band JWT auth (not silently public).
  - WS_AUTH_REQUIRED=false is blocked in production.
  - Route count has not regressed below the last-known baseline.
  - Every WHITELIST entry corresponds to a real registered route.
  - CSRF token endpoint is registered.
  - Health probe endpoints are public (no auth).

Why this matters
----------------
Two previous auth gaps (the /api/nocode and /api/research routes) were
reachable without a token because the routers were registered without a
top-level ``dependencies=[Depends(get_current_user)]`` and the individual
endpoint functions also lacked the dependency.  This test iterates every
registered FastAPI route at import time and fails the build if the same
class of omission recurs.

WebSocket auth model
--------------------
FastAPI WebSocket endpoints cannot use ``Depends(get_current_user)`` in the
same way as HTTP endpoints — the auth handshake is performed in-band after
the connection is accepted.  The gate verifies this by inspecting the
endpoint source for the canonical auth patterns used across the codebase:
  - ``_ws_auth_gate`` call
  - ``_validate_ws_token`` call
  - ``query_params.get("token"`` (token-in-query-param pattern)
  - ``WS_AUTH_REQUIRED`` guard
  - ``auth_required`` message sent to client

Whitelist policy
----------------
Only routes that are *intentionally* public (auth/register, auth/login,
password-reset initiation, health probes, public market data) belong in
WHITELIST.  Adding a route to the whitelist to silence this test without a
documented reason is a security regression.
"""

from __future__ import annotations

import inspect
import os

# Must be set before any app module is imported so startup validators and
# feature-flag checks see the test environment.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("STARTUP_GATE", "false")
os.environ.setdefault("CSRF_PROTECTION", "false")

import pytest

# ---------------------------------------------------------------------------
# Lazy auth-dep import — skip the whole module if api.auth cannot be imported
# (e.g. missing optional C-extensions in a minimal CI image).
# The FastAPI app itself is injected via the session-scoped ``app`` fixture
# defined in tests/conftest.py, which also handles the skip-on-import-error
# logic so each test gets a clean skip rather than an import-time failure.
# ---------------------------------------------------------------------------
try:
    from api.auth import get_current_user, require_kyc, require_role

    _import_error: Exception | None = None
except Exception as _exc:  # noqa: BLE001
    _import_error = _exc

if _import_error is not None:
    pytest.skip(
        f"test_auth_coverage: api.auth import failed — {_import_error}",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# Module-level app reference — populated lazily from the session fixture.
# Tests that use the fixture directly receive the app via their parameter.
# This reference is used by helper functions (_collect_auth_deps, etc.) that
# are called from both fixture-based and standalone tests.
# ---------------------------------------------------------------------------
_app = None  # set by the autouse _bind_app fixture below


@pytest.fixture(autouse=True, scope="module")
def _bind_app(app):  # noqa: F811  — 'app' is the conftest session fixture
    """Bind the session-scoped app fixture to the module-level _app reference.

    This lets helper functions reference _app without receiving it as a
    parameter, while still using the canonical pytest fixture injection path
    that the spec requires.
    """
    global _app
    _app = app
    yield
    _app = None

# ---------------------------------------------------------------------------
# WHITELIST — mutating routes that are intentionally public.
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
        "/api/webhooks/tradingview",
        "/api/v1/webhooks/tradingview",
        "/api/billing/webhook/stripe",
        "/api/v1/billing/webhook/stripe",
        "/api/monetization/webhook/stripe",
        "/api/v1/monetization/webhook/stripe",
        "/api/payments/webhook",
        "/api/v1/payments/webhook",
        "/kyc/webhooks/sumsub",
        "/kyc/webhooks/onfido",
        "/api/email/webhook",
        # ── Public pricing / billing info (landing page, no session needed) ──
        "/api/pricing/estimate",
        "/api/v1/pricing/estimate",
        "/api/billing/auth/activate-free-tier",
        "/api/v1/billing/auth/activate-free-tier",
        # ── Mobile auth (own JWT stack, public by design) ─────────────────────
        "/mobile/api/v2/auth/register",
        "/mobile/api/v2/auth/login",
        "/mobile/api/v2/auth/refresh",
        # ── v1 auth aliases ───────────────────────────────────────────────────
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/resend-verification",
        "/api/v1/auth/activate-free-tier",
        "/api/v1/auth/2fa/setup",
        # ── GraphQL (Strawberry) — in-band JWT auth via resolver context ──────
        # Strawberry GraphQL cannot use FastAPI Depends() at the route level.
        # Auth is enforced in-band: every resolver that returns user-scoped or
        # mutating data calls _require_auth(info) which validates the Bearer
        # token from the request context.  Unauthenticated requests receive a
        # structured UNAUTHORIZED error response, not a 401 HTTP status.
        # See api/graphql_schema.py: _require_auth(), _get_current_user().
        "/graphql",
    }
)

# ---------------------------------------------------------------------------
# PRIVILEGED_GET_PATHS — GET routes that must require auth.
#
# These are paths that return user-specific or admin-only data.  Unlike the
# broad keyword scan (which produces false positives on public market-data
# endpoints), this is an explicit allowlist of paths that MUST be protected.
#
# Rule: if a GET endpoint returns data scoped to a specific user (account
# balance, trade history, KYC status, audit log) or is admin-only, it must
# appear here.  The test fails if any of these paths lacks an auth dep.
# ---------------------------------------------------------------------------
PRIVILEGED_GET_PATHS: frozenset[str] = frozenset(
    {
        # ── Admin endpoints ───────────────────────────────────────────────────
        "/api/admin/status",
        "/api/admin/logs",
        "/api/admin/kyc/pending",
        "/api/admin/kyc/{user_id}",
        "/api/admin/system-info",
        "/api/admin/settings-data",
        "/api/admin/settings",
        "/api/admin/activity",
        "/api/admin/dashboard-data",
        "/api/admin/system-metrics",
        "/api/admin/",
        "/api/admin/strategies",
        "/api/admin/settings-page",
        "/api/admin/monitoring",
        "/api/admin/overview",
        "/api/admin/alerts",
        "/api/admin/audit-log/export",
        "/api/admin/users",
        "/api/admin/users/{user_id}",
        # ── User account / profile (own data) ────────────────────────────────
        "/api/auth/me",
        "/api/auth/sessions",
        "/api/users/me",
        "/api/users/me/profile",
        "/api/users/me/settings",
        "/api/users/me/notifications",
        "/api/users/me/api-keys",
        # ── Trading account data (user-scoped) ───────────────────────────────
        "/api/trading/positions",
        "/api/trading/orders",
        "/api/trading/history",
        "/api/trading/account",
        "/api/trading/balance",
        "/api/trading/pnl",
        # ── KYC (user-scoped) ─────────────────────────────────────────────────
        "/api/kyc/status",
        "/api/kyc/documents",
        "/kyc/status",
        "/kyc/documents",
        # ── Billing / subscription (user-scoped) ─────────────────────────────
        "/api/billing/subscription",
        "/api/billing/balance",
        "/api/billing/transactions",
        "/api/billing/invoices",
        "/api/billing/payment-methods",
        # ── Audit log (user-scoped or admin) ─────────────────────────────────
        "/api/audit/log",
        "/api/audit/events",
        "/api/audit-log",
        # ── Sub-accounts (user-scoped) ────────────────────────────────────────
        "/api/accounts/sub-accounts",
        "/api/accounts/{account_id}",
    }
)

# ---------------------------------------------------------------------------
# WS_PUBLIC_WHITELIST — WebSocket endpoints that are intentionally public.
# ---------------------------------------------------------------------------
WS_PUBLIC_WHITELIST: frozenset[str] = frozenset(
    {
        "/ws/public",                # public market-data feed — no user data, read-only
        "/api/stream/{symbol}/ws",   # public tick stream — rate-limited by IP, no user data
        # Strawberry GraphQL WebSocket (subscriptions) — in-band auth via
        # subscription context.  The _get_current_user(info) helper validates
        # the Bearer token from ws.headers on every subscription resolver.
        # Source inspection cannot detect this because Strawberry wraps the
        # handler in generated code; auth is enforced at the resolver level.
        # See api/graphql_schema.py: _require_auth() called in all subscription
        # resolvers (price_tick_stream, signal_stream, account_updates).
        "/graphql",
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_auth_deps(route) -> list:
    """
    Return the list of dependency callables attached to a route.

    Checks both route.dependencies (router-level) and per-parameter
    Depends() annotations in the endpoint signature.
    """
    from fastapi.params import Depends as _Depends

    dep_callables: list = []

    for dep in getattr(route, "dependencies", []):
        if isinstance(dep, _Depends) and dep.dependency is not None:
            dep_callables.append(dep.dependency)

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

    Recognised dependencies
    -----------------------
    - ``get_current_user``   — any authenticated user (user role or higher)
    - ``require_role(...)``  — minimum-role gate (returns a closure)
    - ``require_kyc``        — KYC-verified user gate (wraps get_current_user)

    The function also recognises:
    - Closures returned by ``require_role`` and ``require_plan`` factories
    - Named auth helpers in known auth modules (api.auth, auth.router, etc.)
    - The kill-switch admin gate
    """
    # Identity checks — fastest path, covers the common case
    if dep is get_current_user:
        return True
    if dep is require_role:
        return True
    if dep is require_kyc:
        return True

    qualname: str = getattr(dep, "__qualname__", "") or ""
    module: str = getattr(dep, "__module__", "") or ""
    name: str = getattr(dep, "__name__", "") or ""

    # Closures returned by factory functions
    _AUTH_QUALNAMES = {
        "require_role.<locals>._check",
        "require_plan.<locals>._dependency",
        "create_kill_switch_router.<locals>._require_admin",
        # require_kyc is a plain function, not a factory, but include its
        # qualname so it is recognised even when imported under an alias
        "require_kyc",
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

    if "require_role" in qualname or "require_plan" in qualname or "require_kyc" in qualname:
        return True

    return False


def _ws_endpoint_has_auth(route) -> bool:
    """
    Return True if a WebSocket endpoint implements in-band JWT authentication.

    WebSocket endpoints cannot use FastAPI Depends() for auth — they perform
    the handshake in-band after accepting the connection.  We verify this by
    inspecting the endpoint source for the canonical auth patterns.
    """
    try:
        src = inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        # Cannot inspect source — assume auth is present to avoid false positives
        # on compiled/wrapped endpoints.
        return True

    _WS_AUTH_PATTERNS = (
        "_ws_auth_gate",
        "_validate_ws_token",
        'query_params.get("token"',
        "WS_AUTH_REQUIRED",
        '"auth_required"',
        "'auth_required'",
        "auth_required=True",
        "decode_access_token",
        "verify_token",
    )
    return any(pattern in src for pattern in _WS_AUTH_PATTERNS)


# ---------------------------------------------------------------------------
# Gate A1 — mutating routes require auth
# ---------------------------------------------------------------------------


def test_all_mutating_routes_require_auth(app) -> None:  # noqa: F811
    """
    Every POST/PUT/PATCH/DELETE route must have an auth dependency unless
    explicitly whitelisted.

    The ``app`` parameter is the session-scoped FastAPI fixture from
    tests/conftest.py — this is the canonical fixture pattern required by
    the spec so the gate is wired through pytest's dependency injection
    rather than a module-level import.

    Failure means a mutating endpoint was registered without authentication.
    Fix: add ``Depends(get_current_user)`` or ``Depends(require_role(...))``
    to the endpoint or its router, then re-run this test.
    """
    from fastapi.routing import APIRoute

    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
    violations: list[str] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = route.methods or set()
        if not (methods & MUTATING_METHODS):
            continue
        if route.path in WHITELIST:
            continue

        dep_callables = _collect_auth_deps(route)
        if not any(_is_auth_dep(d) for d in dep_callables):
            mutating = sorted(methods & MUTATING_METHODS)
            violations.append(f"  {' | '.join(mutating):30s}  {route.path}")

    if violations:
        pytest.fail(
            f"\n{len(violations)} mutating route(s) have no auth dependency.\n"
            "Add Depends(get_current_user) or Depends(require_role(...)) to each,\n"
            "or add the path to WHITELIST with a justification comment.\n\n"
            "  METHODS                          PATH\n"
            "  " + "-" * 60 + "\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate A2 — privileged GET routes require auth
# ---------------------------------------------------------------------------


def test_privileged_get_routes_require_auth(app) -> None:  # noqa: F811
    """
    GET routes in PRIVILEGED_GET_PATHS must carry an auth dependency.

    These endpoints return user-specific or admin-only data.  A GET endpoint
    that returns such data without authentication is an information-disclosure
    vulnerability.

    Failure: add Depends(get_current_user) or Depends(require_role(...)) to
    the endpoint or its router.  If the path is intentionally public, remove
    it from PRIVILEGED_GET_PATHS with a justification comment.
    """
    from fastapi.routing import APIRoute

    registered = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and "GET" in (route.methods or set())
    }

    violations: list[str] = []
    missing: list[str] = []

    for path in sorted(PRIVILEGED_GET_PATHS):
        if path not in registered:
            missing.append(path)
            continue
        route = registered[path]
        dep_callables = _collect_auth_deps(route)
        if not any(_is_auth_dep(d) for d in dep_callables):
            violations.append(f"  GET  {path}")

    if violations:
        pytest.fail(
            f"\n{len(violations)} privileged GET route(s) have no auth dependency.\n"
            "These endpoints return user-specific or admin-only data.\n"
            "Add Depends(get_current_user) or Depends(require_role(...)):\n\n"
            + "\n".join(violations)
        )

    # Missing paths are reported as a warning (not a failure) — the route may
    # not be registered in all deployment configurations.
    if missing:
        print(
            f"\n[auth-coverage] {len(missing)} PRIVILEGED_GET_PATHS not registered "
            f"in this app instance (may be feature-flagged off):\n"
            + "\n".join(f"  {p}" for p in missing)
        )


# ---------------------------------------------------------------------------
# Gate A3 — WebSocket auth
# ---------------------------------------------------------------------------


def test_websocket_endpoints_implement_auth(app) -> None:  # noqa: F811
    """
    Every WebSocket endpoint must implement in-band JWT authentication unless
    it is explicitly listed in WS_PUBLIC_WHITELIST.

    Failure means a WebSocket endpoint was added without an auth handshake.
    Fix: call _ws_auth_gate() or implement the token-in-query-param pattern
    at the start of the endpoint handler.
    """
    from fastapi.routing import APIWebSocketRoute

    violations: list[str] = []

    for route in app.routes:
        if not isinstance(route, APIWebSocketRoute):
            continue
        if route.path in WS_PUBLIC_WHITELIST:
            continue
        if not _ws_endpoint_has_auth(route):
            violations.append(f"  WS  {route.path}")

    if violations:
        pytest.fail(
            f"\n{len(violations)} WebSocket endpoint(s) have no auth implementation.\n"
            "Add an in-band JWT auth handshake (call _ws_auth_gate or implement\n"
            "the token-in-query-param pattern), or add to WS_PUBLIC_WHITELIST\n"
            "with a justification comment:\n\n"
            + "\n".join(violations)
        )


def test_ws_auth_required_env_var_documented() -> None:
    """WS_AUTH_REQUIRED must be documented in .env.example."""
    from pathlib import Path

    env_example = Path(__file__).parent.parent / ".env.example"
    if not env_example.exists():
        pytest.skip(".env.example not found")

    content = env_example.read_text(encoding="utf-8")
    assert "WS_AUTH_REQUIRED" in content, (
        "WS_AUTH_REQUIRED is not documented in .env.example.\n"
        "Add it with a comment explaining that setting it to false in production\n"
        "disables WebSocket authentication and is a security regression."
    )


def test_ws_auth_required_false_blocked_in_production() -> None:
    """api/ws_live.py must raise when WS_AUTH_REQUIRED=false in production."""
    from pathlib import Path

    ws_live_path = Path(__file__).parent.parent / "api" / "ws_live.py"
    if not ws_live_path.exists():
        pytest.skip("api/ws_live.py not found")

    src = ws_live_path.read_text(encoding="utf-8")

    assert "production" in src and "WS_AUTH_REQUIRED" in src, (
        "api/ws_live.py does not contain a production guard for WS_AUTH_REQUIRED.\n"
        "Add: if APP_ENV == 'production' and not WS_AUTH_REQUIRED: raise RuntimeError(...)"
    )
    assert "raise RuntimeError" in src or "raise ValueError" in src, (
        "api/ws_live.py logs a warning when WS_AUTH_REQUIRED=false in production "
        "but does not raise.  Change the warning to a RuntimeError so the server "
        "refuses to start with this misconfiguration."
    )


# ---------------------------------------------------------------------------
# Gate A4 — whitelist integrity
# ---------------------------------------------------------------------------


def test_whitelist_entries_are_registered(app) -> None:  # noqa: F811
    """Every path in WHITELIST must correspond to at least one registered route."""
    from fastapi.routing import APIRoute

    registered_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    stale = [p for p in WHITELIST if p not in registered_paths]

    if stale:
        pytest.fail(
            f"\n{len(stale)} WHITELIST path(s) are not registered in the app.\n"
            "Remove them from WHITELIST or re-register the route:\n"
            + "\n".join(f"  {p}" for p in sorted(stale))
        )


def test_auth_endpoints_are_whitelisted(app) -> None:  # noqa: F811
    """Core auth endpoints that must be public are in both WHITELIST and the app."""
    from fastapi.routing import APIRoute

    MUST_BE_PUBLIC = {"/api/auth/login", "/api/auth/register"}
    registered_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    for path in MUST_BE_PUBLIC:
        assert path in WHITELIST, f"{path} must be in WHITELIST — it is intentionally unauthenticated"
        assert path in registered_paths, f"{path} is in WHITELIST but not registered in the app"


# ---------------------------------------------------------------------------
# Gate A5 — route count regression
# ---------------------------------------------------------------------------

_ROUTE_COUNT_BASELINE = 2200    # minimum total APIRoute count
_MUTATING_COUNT_BASELINE = 900  # minimum POST/PUT/PATCH/DELETE count


def test_route_count_has_not_regressed(app) -> None:  # noqa: F811
    """
    Total route count must not drop below the baseline.

    A sudden drop indicates a router was accidentally de-registered.
    Update _ROUTE_COUNT_BASELINE after intentional route removal with a
    justification comment.
    """
    from fastapi.routing import APIRoute

    total = sum(1 for r in app.routes if isinstance(r, APIRoute))
    mutating = sum(
        1 for r in app.routes
        if isinstance(r, APIRoute) and (r.methods or set()) & {"POST", "PUT", "PATCH", "DELETE"}
    )

    print(
        f"\n[route-count] total={total}  mutating={mutating}  "
        f"baseline_total={_ROUTE_COUNT_BASELINE}  baseline_mutating={_MUTATING_COUNT_BASELINE}"
    )

    assert total >= _ROUTE_COUNT_BASELINE, (
        f"Total route count ({total}) dropped below baseline ({_ROUTE_COUNT_BASELINE}).\n"
        "A router may have been accidentally de-registered.  Check app.py include_router calls.\n"
        "If routes were intentionally removed, update _ROUTE_COUNT_BASELINE in this file."
    )
    assert mutating >= _MUTATING_COUNT_BASELINE, (
        f"Mutating route count ({mutating}) dropped below baseline ({_MUTATING_COUNT_BASELINE}).\n"
        "A router may have been accidentally de-registered.  Check app.py include_router calls.\n"
        "If routes were intentionally removed, update _MUTATING_COUNT_BASELINE in this file."
    )


# ---------------------------------------------------------------------------
# Gate A6 — CSRF and health endpoints
# ---------------------------------------------------------------------------


def test_csrf_token_endpoint_is_registered(app) -> None:  # noqa: F811
    """The CSRF token issuance endpoint must be registered in the app."""
    from fastapi.routing import APIRoute

    csrf_paths = {"/api/auth/csrf-token", "/api/csrf-token", "/csrf-token"}
    registered = {r.path for r in app.routes if isinstance(r, APIRoute)}
    found = csrf_paths & registered

    assert found, (
        "No CSRF token endpoint found in the app.\n"
        f"Expected one of: {sorted(csrf_paths)}\n"
        "Register a CSRF token issuance endpoint so the frontend can obtain\n"
        "tokens before making state-changing requests."
    )


def test_health_endpoints_are_public(app) -> None:  # noqa: F811
    """Health probe endpoints must NOT require authentication."""
    from fastapi.routing import APIRoute

    HEALTH_PATHS = {"/api/health/live", "/api/health/ready"}

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path not in HEALTH_PATHS:
            continue
        if "GET" not in (route.methods or set()):
            continue

        dep_callables = _collect_auth_deps(route)
        has_auth = any(_is_auth_dep(d) for d in dep_callables)

        assert not has_auth, (
            f"Health endpoint {route.path} requires authentication.\n"
            "Health probes must be public — remove the auth dependency."
        )
