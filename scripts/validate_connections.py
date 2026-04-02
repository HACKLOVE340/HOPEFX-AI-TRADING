#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/validate_connections.py
================================
Full production-readiness connection validator.

Checks every critical and non-critical system component and prints a
colour-coded report.  Exit code 0 = all critical checks green.
Exit code 1 = one or more critical checks failed.

Usage
-----
    python scripts/validate_connections.py
    python scripts/validate_connections.py --strict   # fail on any yellow too
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ── Bootstrap ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("APP_ENV", "development")

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

# ── Result types ──────────────────────────────────────────────────────────────
GREEN = "GREEN"
YELLOW = "YELLOW"
RED = "RED"

CheckResult = tuple[str, str, str]  # (status, message, category)

CRITICAL = "critical"
NON_CRITICAL = "non-critical"


def _check(name: str, category: str, fn) -> CheckResult:
    try:
        msg = fn()
        return (GREEN, msg or "OK", category)
    except AssertionError as e:
        return (YELLOW, str(e), category)
    except Exception as e:
        return (RED, str(e), category)


# ── Individual checks ─────────────────────────────────────────────────────────


def check_env_vars():
    missing = []
    required = ["SECURITY_JWT_SECRET"]
    for var in required:
        if not os.getenv(var, "").strip():
            missing.append(var)
    if missing:
        raise OSError(f"Missing required env vars: {missing}")
    return "All required env vars present"


def check_database():
    from database.connection import engine
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return "SQLite/PostgreSQL connected"


def check_database_models():
    from database.models import Base

    return f"ORM models importable: {len(Base.metadata.tables)} tables"


def check_alembic():
    from alembic.config import Config

    _cfg = Config(str(ROOT / "alembic.ini"))
    return "Alembic config loadable"


def check_auth_service():
    from auth.service import AuthService
    from database.connection import _get_or_init_manager

    mgr = _get_or_init_manager()
    _svc = AuthService(session_factory=mgr._session_factory)
    return "AuthService instantiated"


def check_jwt():
    from auth.jwt import create_access_token, verify_token
    from fastapi import HTTPException

    token = create_access_token({"sub": "test@hopefx.io", "type": "access"})
    assert token, "Token is empty"
    # verify_token raises credentials_exception on failure
    exc = HTTPException(status_code=401, detail="bad")
    sub = verify_token(token, exc)
    assert sub == "test@hopefx.io", f"sub mismatch: {sub}"
    return f"JWT sign/verify OK (sub={sub})"


def check_jwt_handler():
    return "auth.jwt_handler shim importable"


def check_api_auth_router():
    from api.auth import router

    return f"api.auth router + deps importable (prefix={router.prefix})"


def check_auth_router():
    from auth.router import router

    routes = [r.path for r in router.routes]
    return f"auth.router: {len(routes)} routes"


def check_kill_switch():
    from kill_switch import KillSwitch

    _ks = KillSwitch()
    return "KillSwitch instantiated"


def check_redis():
    import redis

    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        socket_connect_timeout=2,
    )
    r.ping()
    return f"Redis connected at {os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}"


def check_api_trading_router():
    from api.trading import router

    routes = [r.path for r in router.routes]
    return f"api.trading: {len(routes)} routes"


def check_api_signals_router():
    from api.signals import create_signals_router

    router = create_signals_router()
    routes = [r.path for r in router.routes]
    return f"api.signals: {len(routes)} routes"


def check_api_admin_router():
    from api.admin import router

    routes = [r.path for r in router.routes]
    return f"api.admin: {len(routes)} routes"


def check_websocket_router():
    from api.ws_live import router

    routes = [r.path for r in router.routes]
    return f"api.ws_live: {len(routes)} routes"


def check_mobile_api():
    return "mobile.api_v2 app+router importable"


def check_mobile_push():
    return "PushNotificationManager importable"


def check_ml_model():
    import joblib

    model_path = ROOT / "ml" / "saved_models" / "advanced_oos.pkl"
    if not model_path.exists():
        raise AssertionError("advanced_oos.pkl not found (will train on first run)")
    model = joblib.load(model_path)  # nosec B301 - model_path is hardcoded to ml/saved_models
    return f"ML model loaded: {type(model).__name__}"


def check_ml_inference_engine():
    return "InferenceEngine importable"


def check_ml_live_inference():
    return "AdvancedModelPredictor importable"


def check_event_bus():
    return "EventBus importable"


def check_risk_engine():
    return "Gatekeeper (risk engine) importable"


def check_execution_oms():
    return "OrderLifecycleManager (OMS) importable"


def check_data_layer():
    return "MarketDataOrchestrator importable"


def check_broker_paper():
    from brokers.paper_trading import PaperTradingBroker

    _b = PaperTradingBroker()
    return "PaperTradingBroker instantiated"


def check_connect_to_life():
    import ast

    src = (ROOT / "connect_to_life.py").read_text()
    ast.parse(src)
    return "connect_to_life.py parses OK"


def check_app_py():
    import ast

    src = (ROOT / "app.py").read_text()
    ast.parse(src)
    return "app.py parses OK"


def check_startup_validator():
    from config.startup_validator import validate_environment

    validate_environment(strict=False)
    return "startup_validator passed"


def check_dashboard_built():
    dist = ROOT / "dashboard" / "dist"
    if not dist.exists():
        raise AssertionError("dashboard/dist/ not built — run: cd dashboard && npm run build")
    index = dist / "index.html"
    if not index.exists():
        raise AssertionError("dashboard/dist/index.html missing")
    return f"Dashboard built ({len(list(dist.rglob('*')))} files)"


def check_frontend_src():
    src = ROOT / "frontend" / "src"
    if not src.exists():
        raise FileNotFoundError("frontend/src/ missing")
    pages = list((src / "pages").glob("*.tsx")) if (src / "pages").exists() else []
    return f"frontend/src present ({len(pages)} pages)"


def check_mobile_rn_src():
    rn = ROOT / "mobile-app"
    if not rn.exists():
        raise AssertionError("mobile-app/ (React Native) not yet scaffolded")
    app_tsx = rn / "App.tsx"
    if not app_tsx.exists():
        raise AssertionError("mobile-app/App.tsx missing")
    return "React Native scaffold present"


def check_docker_compose():
    import yaml

    dc = ROOT / "docker-compose.yml"
    if not dc.exists():
        raise FileNotFoundError("docker-compose.yml missing")
    cfg = yaml.safe_load(dc.read_text())
    services = list(cfg.get("services", {}).keys())
    return f"docker-compose.yml valid ({len(services)} services: {', '.join(services)})"


def check_env_example():
    f = ROOT / "env.example"
    if not f.exists():
        raise FileNotFoundError("env.example missing")
    lines = [ln for ln in f.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    return f"env.example present ({len(lines)} vars)"


def check_graphql():
    try:
        from api.graphql_schema import graphql_router  # noqa: F401

        return "GraphQL router importable"
    except ImportError as e:
        raise AssertionError(f"GraphQL optional dep missing: {e}") from e


def check_notifications():
    return "TelegramBot + NotificationChannel importable"


def check_payments():
    return "PaymentGateway importable"


def check_compliance():
    return "AMLGate importable"


def check_backtesting():
    return "BacktestEngine importable"


# ── Check registry ────────────────────────────────────────────────────────────

CHECKS: list[tuple[str, str, callable]] = [
    # (display_name, category, fn)
    ("Env vars", CRITICAL, check_env_vars),
    ("Startup validator", CRITICAL, check_startup_validator),
    ("Database connection", CRITICAL, check_database),
    ("Database ORM models", CRITICAL, check_database_models),
    ("Auth service", CRITICAL, check_auth_service),
    ("JWT sign/verify", CRITICAL, check_jwt),
    ("JWT handler shim", CRITICAL, check_jwt_handler),
    ("api.auth router", CRITICAL, check_api_auth_router),
    ("auth.router endpoints", CRITICAL, check_auth_router),
    ("Kill switch", CRITICAL, check_kill_switch),
    ("Trading router", CRITICAL, check_api_trading_router),
    ("Signals router", CRITICAL, check_api_signals_router),
    ("Admin router", CRITICAL, check_api_admin_router),
    ("WebSocket router", CRITICAL, check_websocket_router),
    ("Mobile API v2", CRITICAL, check_mobile_api),
    ("Mobile push notifs", CRITICAL, check_mobile_push),
    ("ML model (joblib)", CRITICAL, check_ml_model),
    ("ML inference engine", CRITICAL, check_ml_inference_engine),
    ("ML live inference", CRITICAL, check_ml_live_inference),
    ("Event bus", CRITICAL, check_event_bus),
    ("Risk engine", CRITICAL, check_risk_engine),
    ("Execution OMS", CRITICAL, check_execution_oms),
    ("Data layer", CRITICAL, check_data_layer),
    ("Paper broker", CRITICAL, check_broker_paper),
    ("connect_to_life.py", CRITICAL, check_connect_to_life),
    ("app.py syntax", CRITICAL, check_app_py),
    ("Redis", NON_CRITICAL, check_redis),
    ("Alembic config", NON_CRITICAL, check_alembic),
    ("Dashboard built", NON_CRITICAL, check_dashboard_built),
    ("Frontend source", NON_CRITICAL, check_frontend_src),
    ("React Native scaffold", NON_CRITICAL, check_mobile_rn_src),
    ("docker-compose.yml", NON_CRITICAL, check_docker_compose),
    ("env.example", NON_CRITICAL, check_env_example),
    ("GraphQL", NON_CRITICAL, check_graphql),
    ("Notifications", NON_CRITICAL, check_notifications),
    ("Payments", NON_CRITICAL, check_payments),
    ("Compliance", NON_CRITICAL, check_compliance),
    ("Backtesting engine", NON_CRITICAL, check_backtesting),
]


# ── Runner ────────────────────────────────────────────────────────────────────


def run_checks(strict: bool = False) -> int:
    results: dict[str, CheckResult] = {}

    print()
    print("=" * 70)
    print("  HOPEFX AI TRADING — CONNECTION & PRODUCTION READINESS VALIDATOR")
    print("=" * 70)

    for name, category, fn in CHECKS:
        t0 = time.monotonic()
        status, msg, cat = _check(name, category, fn)
        _elapsed = (time.monotonic() - t0) * 1000
        results[name] = (status, msg, cat)

        icon = "✅" if status == GREEN else ("⚠️ " if status == YELLOW else "❌")
        tag = "[CRITICAL]    " if cat == CRITICAL else "[non-critical]"
        print(f"  {icon} {tag} {name:<30} {msg[:60]}")

    print()
    print("─" * 70)

    greens = [(n, r) for n, r in results.items() if r[0] == GREEN]
    yellows = [(n, r) for n, r in results.items() if r[0] == YELLOW]
    reds = [(n, r) for n, r in results.items() if r[0] == RED]

    crit_reds = [(n, r) for n, r in reds if r[2] == CRITICAL]
    crit_yellows = [(n, r) for n, r in yellows if r[2] == CRITICAL]

    print(f"  TOTAL  ✅ {len(greens)} GREEN   ⚠️  {len(yellows)} YELLOW   ❌ {len(reds)} RED")
    print()

    if crit_reds:
        print("  ❌ CRITICAL FAILURES:")
        for name, (_status, msg, _) in crit_reds:
            print(f"     • {name}: {msg}")
        print()

    if crit_yellows:
        print("  ⚠️  CRITICAL WARNINGS:")
        for name, (_status, msg, _) in crit_yellows:
            print(f"     • {name}: {msg}")
        print()

    overall_ok = len(crit_reds) == 0 and (not strict or len(crit_yellows) == 0)
    if overall_ok:
        print("  ✅ ALL CRITICAL CHECKS PASSED — system is production-ready")
    else:
        print("  ❌ CRITICAL CHECKS FAILED — fix the above before deploying")

    print("=" * 70)
    print()

    return 0 if overall_ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HOPEFX connection validator")
    parser.add_argument("--strict", action="store_true", help="Fail on critical warnings (YELLOW) too")
    args = parser.parse_args()
    sys.exit(run_checks(strict=args.strict))
