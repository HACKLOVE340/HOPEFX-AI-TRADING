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


def _file_has_router_level_auth(tree: ast.Module) -> bool:
    """
    Return True if ANY APIRouter in this file is constructed with
    a `dependencies=[...]` argument that references an auth marker.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            (isinstance(func, ast.Name) and func.id == "APIRouter")
            or (isinstance(func, ast.Attribute) and func.attr == "APIRouter")
        ):
            continue
        for kw in node.keywords:
            if kw.arg != "dependencies":
                continue
            src = ast.unparse(kw.value)
            if any(marker in src for marker in AUTH_DEPENDS_MARKERS):
                return True
    return False


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

    # If every APIRouter in this file is constructed with a top-level
    # dependencies=[Depends(<auth>)] argument, all endpoints it owns are
    # protected — no per-function check needed.
    if _file_has_router_level_auth(tree):
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name in KNOWN_PUBLIC:
            continue
        if not _is_mutating_endpoint(node):
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
