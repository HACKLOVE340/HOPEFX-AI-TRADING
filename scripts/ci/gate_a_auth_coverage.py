#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate A: auth coverage on all mutating HTTP routes.
#
# Exits 0 when every scanned POST/PUT/PATCH/DELETE endpoint is covered by auth.
# Exits 1 and lists offending routes when any are unprotected.
#
# Strategy:
#   1. Router-level exemption: if APIRouter is constructed with
#      `dependencies=[Depends(<auth>)]` every route it owns is protected.
#   2. Function-level: each mutating endpoint must have an auth-bearing
#      default value (Depends(require_role), Depends(get_current_user), or any
#      of the module-level alias patterns listed in AUTH_DEPENDS_MARKERS).
#   3. KNOWN_PUBLIC lists functions that are intentionally unauthenticated.
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_DIRS = [
    REPO_ROOT / "api",
    REPO_ROOT / "nocode",
    REPO_ROOT / "research",
]

MUTATING_HTTP_METHODS = {"post", "put", "patch", "delete"}

# String fragments that, when present in ast.unparse(default_value), indicate
# the parameter is an auth dependency.  This covers both direct calls
# (require_role, get_current_user) and module-level aliases used across
# api/superadmin/, api/whitelabel_admin.py, api/platform.py, etc.
AUTH_DEPENDS_MARKERS: frozenset[str] = frozenset(
    {
        # Direct auth functions
        "require_role",
        "get_current_user",
        "require_kyc",
        "get_optional_user",
        # Subscription-gated auth (monetization/subscription.py)
        "require_plan",
        "_require_plan",
        # Quota-gated auth (core/ai_quota.py). `ai_quota(...)` returns a
        # dependency whose own signature is
        # `_check(user: TokenPayload = Depends(get_current_user))`, so a route
        # using it is authenticated — this gate reads source, not the resolved
        # dependency graph, so it cannot see through the indirection itself.
        # That claim is asserted, not assumed:
        # tests/unit/test_gate_a_markers_really_authenticate.py fails if
        # ai_quota ever stops resolving get_current_user, so this entry cannot
        # quietly become a hole. Adding it here fixed seven false positives on
        # api/brain.py, api/chat.py and api/voice.py, which have been
        # authenticated since the commit that introduced the quota.
        "ai_quota",
        # Module-level aliases (api/superadmin/_shared.py, api/platform.py, etc.)
        "_require_superadmin",
        "_require_admin",
        "_require_admin_dep",
        "_require_trader",
        "_superadmin",
        "_get_current_user",
        # Generic auth sentinel names used in dynamic builders (api/server.py)
        "_require_auth",
        "_auth",
        # Dynamic builder alias for Depends() (api/signals.py uses _Depends)
        "_Depends",
        # HTTPBearer / OAuth2 security (api/gateway.py uses Depends(self.security))
        "self.security",
        "HTTPBearer",
        "OAuth2",
        "security",
    }
)

# Functions that are intentionally public — no token required.
# Keep this list minimal and justified.
KNOWN_PUBLIC: frozenset[str] = frozenset(
    {
        # ── Auth flow ── creates / invalidates tokens; can't require one
        "login",
        "register",
        "refresh_token",
        "logout",
        "request_password_reset",
        "reset_password",
        "verify_email",
        "confirm_email",
        "resend_verification",
        "change_password",
        # ── Health / liveness probes ── must be reachable without auth
        "health",
        "health_live",
        "health_ready",
        "liveness",
        "readiness",
        "ping",
        "live",
        "ready",
        # ── External webhooks ── token is the URL path secret, not a Bearer header
        "stripe_webhook",
        "paypal_webhook",
        "telegram_webhook",
        "sumsub_webhook",
        "onfido_webhook",
        "payment_webhook",
        "webhook",
        "handle_webhook",
        "receive_webhook",
        # TradingView alerts: authenticated via HMAC-SHA256 X-TV-Signature header
        # or body-level secret field — no Bearer token in the request.
        "tradingview_webhook",
        # ── Post-signup endpoint ── called right after register before the user
        # has a session token; grants the free-tier trial subscription
        "activate_free_tier",
        # ── Public pricing calculator ── shown on the marketing/pricing page
        # to unauthenticated visitors; returns no personal data
        "estimate_cost",
        # ── Explicitly internal / demo stubs ──
        "paper_trading_gate_record_fill",  # internal fill recorder, no user context
    }
)

# Files whose routes are covered by the dynamic auth builder pattern
# (api/server.py builds auth deps at runtime from JWT secrets).
SKIP_FILES: frozenset[str] = frozenset(
    {
        "server.py",  # auth injected via _register_trading_routes()
    }
)


def _guarded_router_names(tree: ast.Module) -> set[str]:
    """
    Return the names of routers constructed with a `dependencies=[...]`
    argument that references an auth marker.

    Scoped per router, not per file. This used to answer "does ANY router in
    this file carry auth?" and, on a yes, exempt every endpoint in the file
    without looking at one of them. A second, auth-free router in the same file
    then inherited that exemption — which is precisely the shape of
    `api/advanced_trading.py`:

        router        = APIRouter(dependencies=[Depends(get_current_user)])
        public_router = APIRouter()      # mounted, no auth

    A mutating route added to `public_router` was waved through by the guard on
    `router`. Returning the guarded names instead lets `check_file` exempt only
    the routes whose own router is guarded.
    """
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not (
            (isinstance(func, ast.Name) and func.id == "APIRouter")
            or (isinstance(func, ast.Attribute) and func.attr == "APIRouter")
        ):
            continue
        has_auth = any(
            kw.arg == "dependencies" and any(marker in ast.unparse(kw.value) for marker in AUTH_DEPENDS_MARKERS)
            for kw in call.keywords
        )
        if not has_auth:
            continue
        for target in node.targets:
            guarded.add(ast.unparse(target))
    return guarded


def _route_owner(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """
    Return the name of the router a route decorator hangs off — the `x` in
    `@x.post(...)` — or None when this is not a decorated route.
    """
    for dec in node.decorator_list:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(func, ast.Attribute) and func.attr in MUTATING_HTTP_METHODS:
            return ast.unparse(func.value)
    return None


def _has_auth_depends(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Return True if the function is protected by auth, either via:
      (a) a parameter default containing Depends(<auth_func>), or
      (b) a body-level call to an imperative auth helper (_require_admin, etc.)
          that raises on failure — used in files that predate the Depends pattern.
    """
    # (a) parameter default check
    all_defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
    for default in all_defaults:
        src = ast.unparse(default)
        if any(marker in src for marker in AUTH_DEPENDS_MARKERS):
            return True

    # (b) body-level imperative auth call
    body_src = " ".join(ast.unparse(stmt) for stmt in node.body[:10])  # first 10 stmts
    BODY_AUTH_MARKERS = {
        "_require_admin(",
        "_require_superadmin(",
        "_require_auth(",
        "_require_trader(",
        "require_role(",
        "get_current_user(",
    }
    return any(m in body_src for m in BODY_AUTH_MARKERS)


def _is_mutating_endpoint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr in MUTATING_HTTP_METHODS:
                return True
        elif isinstance(dec, ast.Attribute):
            if dec.attr in MUTATING_HTTP_METHODS:
                return True
    return False


def check_file(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    # Routers constructed with a top-level dependencies=[Depends(<auth>)]
    # protect every endpoint registered on *that* router — those need no
    # per-function check. Routers without it get checked function by function.
    guarded_routers = _guarded_router_names(tree)

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name in KNOWN_PUBLIC:
            continue
        if not _is_mutating_endpoint(node):
            continue
        if _route_owner(node) in guarded_routers:
            continue
        if not _has_auth_depends(node):
            rel = path.relative_to(REPO_ROOT)
            violations.append(f"  {rel}:{node.lineno}  {node.name}()")
    return violations


def main() -> int:
    all_violations: list[str] = []
    scanned = 0

    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for py_file in sorted(scan_dir.rglob("*.py")):
            if py_file.name in SKIP_FILES:
                continue
            if any(part.startswith("test_") for part in py_file.parts):
                continue
            violations = check_file(py_file)
            all_violations.extend(violations)
            scanned += 1

    if all_violations:
        print(f"Gate A FAILED — {len(all_violations)} mutating endpoint(s) missing auth:")
        for v in all_violations:
            print(v)
        print()
        print("Fix: add  user: TokenPayload = Depends(require_role('trader'))  to each.")
        return 1

    print(f"Gate A PASSED — {scanned} files scanned, all mutating endpoints have auth.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
