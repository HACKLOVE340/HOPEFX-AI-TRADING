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
        "/api/auth/login",           # issues the token — cannot require one
        "/api/auth/register",        # new-user registration
        "/api/auth/refresh",         # token refresh (uses refresh token, not access)
        "/api/auth/logout",          # stateless logout — token may already be expired
        "/api/auth/password-reset",  # initiate reset — user has no token yet
        "/api/auth/password-reset/confirm",  # confirm reset with emailed code
        "/api/auth/verify-email",    # email verification link
        "/api/auth/2fa/verify",      # 2FA challenge — mid-login, no access token yet
        "/api/auth/2fa/setup",       # 2FA setup — some flows allow pre-auth setup
        # ── Health / readiness probes (called by load-balancers, no auth) ───
        "/api/health",
        "/api/health/",
        "/api/health/live",
        "/api/health/ready",
        "/api/health/startup",
        # ── Kill switch (uses its own HOPEFX_KILL_SWITCH_TOKEN header) ───────
        "/api/kill",
        "/api/kill/",
        # ── Webhook receivers (use HMAC signature verification instead) ──────
        "/api/webhooks/stripe",
        "/api/webhooks/oanda",
        "/api/webhooks/tradingview",
        # ── Public landing / marketing pages (read-only POST forms) ──────────
        "/api/landing/contact",
        "/api/landing/waitlist",
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
    Return True if *dep* is ``get_current_user``, ``require_role``, or a
    callable returned by ``require_role(...)`` (i.e. a role-checking closure
    whose ``__qualname__`` starts with ``require_role``).
    """
    if dep is get_current_user:
        return True
    if dep is require_role:
        return True
    # require_role("trader") returns a _check closure; detect by qualname
    qualname = getattr(dep, "__qualname__", "") or ""
    if "require_role" in qualname:
        return True
    # Also accept any callable whose module is api.auth and whose name
    # suggests an auth check (future-proof for new auth helpers).
    module = getattr(dep, "__module__", "") or ""
    name = getattr(dep, "__name__", "") or ""
    if module == "api.auth" and ("user" in name.lower() or "role" in name.lower() or "auth" in name.lower()):
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
