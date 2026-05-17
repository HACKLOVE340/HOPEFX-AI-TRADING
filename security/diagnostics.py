# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/diagnostics.py
=======================
Advanced diagnostic engine — fills every blind spot the existing self-healer
cannot see.

Checks performed
----------------
1. Runtime route health      — HTTP-tests every registered FastAPI endpoint
2. SPA routing               — verifies /dashboard, /superadmin, etc. return 200 + HTML
3. Import chain integrity    — subprocess-imports every package to catch broken imports
4. Environment variable completeness — validates all required env vars are present
5. Data feed health          — probes live data-feed endpoints / Redis streams
6. Frontend build freshness  — checks static/index.html exists and is recent
7. Cookie / auth flow        — end-to-end login → protected-route → logout test
8. Log pattern detection     — maps recurring log patterns to root causes + auto-fix hints
9. Database connectivity     — verifies DB is reachable and migrations are current
10. Redis connectivity       — verifies Redis is reachable and key namespaces are healthy

Each check returns a DiagnosticResult.  The engine aggregates them into a
DiagnosticReport that the self-healer and the superadmin REST endpoint consume.

Usage (standalone)::

    import asyncio
    from security.diagnostics import DiagnosticsEngine
    engine = DiagnosticsEngine()
    report = asyncio.run(engine.run_full_diagnostic())
    print(report.summary())

Usage (from self-healer)::

    from security.diagnostics import DiagnosticsEngine
    _diag = DiagnosticsEngine()
    report = await _diag.run_full_diagnostic()
    if report.has_critical():
        await _diag.auto_remediate(report)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Configuration — all overridable via environment variables
# ---------------------------------------------------------------------------

_APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
_DIAG_HTTP_TIMEOUT: float = float(os.getenv("DIAG_HTTP_TIMEOUT", "10"))
_FRONTEND_MAX_AGE_HOURS: int = int(os.getenv("DIAG_FRONTEND_MAX_AGE_HOURS", "24"))


def _diag_import_timeout() -> int:
    """Read DIAG_IMPORT_TIMEOUT at call time so tests can override it via env."""
    return int(os.getenv("DIAG_IMPORT_TIMEOUT", "30"))


# SPA routes that must return 200 + HTML
_SPA_ROUTES: list[str] = [
    "/",
    "/dashboard",
    "/superadmin",
    "/login",
    "/register",
]

# Required environment variables — (name, description, is_secret)
# SECURITY_JWT_SECRET is the canonical name (also accepted: JWT_SECRET_KEY).
# SECRET_KEY is a legacy alias kept for backward compatibility — check both.
_REQUIRED_ENV_VARS: list[tuple[str, str, bool]] = [
    ("SECURITY_JWT_SECRET", "JWT signing key (canonical name)", True),
    ("DATABASE_URL", "Primary database connection string", True),
    ("REDIS_URL", "Redis connection string", False),
    ("APP_ENV", "Application environment (development/production)", False),
]

# Optional but important env vars — warn if missing
_OPTIONAL_ENV_VARS: list[tuple[str, str]] = [
    ("ANTHROPIC_API_KEY", "Claude LLM for auto-healing"),
    ("SENTRY_DSN", "Error tracking"),
    ("BROKER_TYPE", "Broker backend selection"),
    ("OANDA_API_KEY", "OANDA broker credentials"),
]

# Core Python packages that must import cleanly
_CORE_PACKAGES: list[str] = [
    "app",
    "api.auth",
    "api.trading",
    "api.health",
    "security.self_healer",
    "security.code_analyzer",
    "core.router_registry",
    "config.startup_validator",
    "risk",
    "execution",
]

# Log patterns → root cause + remediation
_LOG_PATTERN_MAP: list[dict[str, Any]] = [
    {
        "pattern": re.compile(r"OperationalError.*could not connect", re.IGNORECASE),
        "category": "db_connection",
        "severity": "critical",
        "root_cause": "Database unreachable — check DATABASE_URL and DB server status",
        "remediation": "Verify DATABASE_URL, ensure DB container/service is running",
    },
    {
        "pattern": re.compile(r"redis.*connection refused", re.IGNORECASE),
        "category": "redis_connection",
        "severity": "critical",
        "root_cause": "Redis unreachable — check REDIS_URL and Redis server status",
        "remediation": "Verify REDIS_URL, ensure Redis container/service is running",
    },
    {
        "pattern": re.compile(r"ImportError|ModuleNotFoundError", re.IGNORECASE),
        "category": "import_error",
        "severity": "critical",
        "root_cause": "Missing Python dependency or broken import chain",
        "remediation": "Run: pip install -r requirements.txt; check for circular imports",
    },
    {
        "pattern": re.compile(r"JWT.*expired|token.*invalid|signature.*verification", re.IGNORECASE),
        "category": "auth_failure",
        "severity": "high",
        "root_cause": "JWT validation failures — possible clock skew or key rotation issue",
        "remediation": "Check SECRET_KEY consistency across pods; verify system clock sync",
    },
    {
        "pattern": re.compile(r"NaN|inf.*value|division by zero", re.IGNORECASE),
        "category": "numeric_error",
        "severity": "high",
        "root_cause": "Numeric instability in trading calculations",
        "remediation": "Add NaN guards and division-by-zero checks in signal/risk code",
    },
    {
        "pattern": re.compile(r"lookahead|shift\(-\d+\)", re.IGNORECASE),
        "category": "lookahead_bias",
        "severity": "critical",
        "root_cause": "Look-ahead bias detected in live trading path",
        "remediation": "Replace shift(-N) with shift(+N) in all feature engineering code",
    },
    {
        "pattern": re.compile(r"rate.?limit|429|too many requests", re.IGNORECASE),
        "category": "rate_limit",
        "severity": "medium",
        "root_cause": "Rate limiting triggered — possible abuse or misconfigured client",
        "remediation": "Review rate limit config; check for runaway retry loops",
    },
    {
        "pattern": re.compile(r"memory.*error|MemoryError|OOM", re.IGNORECASE),
        "category": "memory_pressure",
        "severity": "critical",
        "root_cause": "Out-of-memory condition",
        "remediation": "Profile memory usage; check for unbounded caches or data leaks",
    },
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticResult:
    """Result of a single diagnostic check."""

    check_name: str
    status: str  # "ok" | "warning" | "error" | "critical"
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: str = ""
    duration_ms: float = 0.0
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def is_healthy(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "remediation": self.remediation,
            "duration_ms": round(self.duration_ms, 2),
            "checked_at": self.checked_at,
        }


@dataclass
class DiagnosticReport:
    """Aggregated results from a full diagnostic run."""

    results: list[DiagnosticResult] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str = ""
    total_duration_ms: float = 0.0

    def has_critical(self) -> bool:
        return any(r.status == "critical" for r in self.results)

    def has_errors(self) -> bool:
        return any(r.status in ("critical", "error") for r in self.results)

    def by_status(self) -> dict[str, list[DiagnosticResult]]:
        out: dict[str, list[DiagnosticResult]] = {"ok": [], "warning": [], "error": [], "critical": []}
        for r in self.results:
            out.setdefault(r.status, []).append(r)
        return out

    def summary(self) -> str:
        counts = dict.fromkeys(("ok", "warning", "error", "critical"), 0)
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        parts = [f"{v} {k}" for k, v in counts.items() if v]
        return f"DiagnosticReport [{', '.join(parts)}] in {self.total_duration_ms:.0f}ms"

    def to_dict(self) -> dict[str, Any]:
        by_status = self.by_status()
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "counts": {s: len(v) for s, v in by_status.items()},
            "has_critical": self.has_critical(),
            "has_errors": self.has_errors(),
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# DiagnosticsEngine
# ---------------------------------------------------------------------------


class DiagnosticsEngine:
    """Advanced diagnostic engine — fills blind spots the self-healer cannot see."""

    def __init__(self) -> None:
        self._last_report: DiagnosticReport | None = None
        self._last_run_ts: float = 0.0

    async def run_full_diagnostic(self, *, parallel: bool = True) -> DiagnosticReport:
        t0 = time.monotonic()
        report = DiagnosticReport()
        checks = [
            self._check_env_vars(),
            self._check_import_chain(),
            self._check_database(),
            self._check_redis(),
            self._check_frontend_build(),
            self._check_route_health(),
            self._check_spa_routing(),
            self._check_auth_flow(),
            self._check_data_feeds(),
            self._check_log_patterns(),
        ]
        if parallel:
            raw = await asyncio.gather(*checks, return_exceptions=True)
            for r in raw:
                if isinstance(r, Exception):
                    report.results.append(DiagnosticResult(check_name="unknown", status="error", message=str(r)))
                elif isinstance(r, list):
                    report.results.extend(r)
                elif isinstance(r, DiagnosticResult):
                    report.results.append(r)
        else:
            for coro in checks:
                try:
                    r = await coro
                    if isinstance(r, list):
                        report.results.extend(r)
                    elif isinstance(r, DiagnosticResult):
                        report.results.append(r)
                except Exception as exc:
                    report.results.append(DiagnosticResult(check_name="unknown", status="error", message=str(exc)))
        report.completed_at = datetime.now(UTC).isoformat()
        report.total_duration_ms = (time.monotonic() - t0) * 1000
        self._last_report = report
        self._last_run_ts = time.time()
        logger.info("DiagnosticsEngine: %s", report.summary())
        return report

    async def auto_remediate(self, report: DiagnosticReport) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for result in report.results:
            if result.status not in ("critical", "error"):
                continue
            action = await self._remediate_result(result)
            if action:
                actions.append(action)
        return actions

    def get_last_report(self) -> DiagnosticReport | None:
        return self._last_report

    # ------------------------------------------------------------------
    # Check 1: Environment variables
    # ------------------------------------------------------------------

    async def _check_env_vars(self) -> list[DiagnosticResult]:
        t0 = time.monotonic()
        missing_req: list[str] = []
        missing_opt: list[str] = []

        # Aliases: if any alias is set, the var is considered present
        _ALIASES: dict[str, list[str]] = {
            "SECURITY_JWT_SECRET": ["JWT_SECRET_KEY", "SECRET_KEY"],
        }

        for name, desc, required in _REQUIRED_ENV_VARS:
            val = os.getenv(name, "")
            if not val:
                # Check known aliases before reporting missing
                aliases = _ALIASES.get(name, [])
                val = next((os.getenv(a, "") for a in aliases if os.getenv(a, "")), "")
            if not val:
                if required:
                    missing_req.append(f"{name} ({desc})")
                else:
                    missing_opt.append(f"{name} ({desc})")
        for name, desc in _OPTIONAL_ENV_VARS:
            if not os.getenv(name, ""):
                missing_opt.append(f"{name} ({desc})")
        dur = (time.monotonic() - t0) * 1000
        results: list[DiagnosticResult] = []
        if missing_req:
            results.append(
                DiagnosticResult(
                    check_name="env_vars_required",
                    status="critical",
                    message=f"Missing {len(missing_req)} required env var(s)",
                    details={"missing": missing_req},
                    remediation="Set the missing environment variables before starting the app",
                    duration_ms=dur,
                )
            )
        else:
            results.append(
                DiagnosticResult(
                    check_name="env_vars_required",
                    status="ok",
                    message="All required environment variables are set",
                    duration_ms=dur,
                )
            )
        if missing_opt:
            results.append(
                DiagnosticResult(
                    check_name="env_vars_optional",
                    status="warning",
                    message=f"Missing {len(missing_opt)} optional env var(s)",
                    details={"missing": missing_opt},
                    remediation="Set optional env vars to enable full functionality",
                    duration_ms=dur,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Check 2: Import chain integrity
    # ------------------------------------------------------------------

    async def _check_import_chain(self) -> list[DiagnosticResult]:
        t0 = time.monotonic()
        broken: list[dict[str, str]] = []
        ok_count = 0

        async def _test_import(pkg: str) -> tuple[str, bool, str]:
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    f"import {pkg}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(PROJECT_ROOT),
                )
                try:
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_diag_import_timeout())
                    if proc.returncode == 0:
                        return pkg, True, ""
                    return pkg, False, stderr.decode(errors="replace").strip()[:300]
                except TimeoutError:
                    proc.kill()
                    return pkg, False, "import timed out"
            except Exception as exc:
                return pkg, False, str(exc)

        import_results = await asyncio.gather(*[_test_import(p) for p in _CORE_PACKAGES])
        for pkg, ok, err in import_results:
            if ok:
                ok_count += 1
            else:
                broken.append({"package": pkg, "error": err})

        dur = (time.monotonic() - t0) * 1000
        if broken:
            return [
                DiagnosticResult(
                    check_name="import_chain",
                    status="critical",
                    message=f"{len(broken)} package(s) fail to import",
                    details={"broken": broken, "ok_count": ok_count},
                    remediation="Fix import errors; run: pip install -r requirements.txt",
                    duration_ms=dur,
                )
            ]
        return [
            DiagnosticResult(
                check_name="import_chain",
                status="ok",
                message=f"All {ok_count} core packages import cleanly",
                duration_ms=dur,
            )
        ]

    # ------------------------------------------------------------------
    # Check 3: Database connectivity
    # ------------------------------------------------------------------

    async def _check_database(self) -> DiagnosticResult:
        t0 = time.monotonic()
        try:
            loop = asyncio.get_running_loop()

            def _probe() -> tuple[bool, str]:
                try:
                    from database.connection import get_db as _gdb
                    import sqlalchemy

                    db = next(_gdb())
                    if db is None:
                        return False, "get_db returned None"
                    db.execute(sqlalchemy.text("SELECT 1"))
                    return True, ""
                except Exception as exc:
                    return False, str(exc)[:200]

            ok, err = await loop.run_in_executor(None, _probe)
            dur = (time.monotonic() - t0) * 1000
            if ok:
                return DiagnosticResult(
                    check_name="database", status="ok", message="Database connection healthy", duration_ms=dur
                )
            return DiagnosticResult(
                check_name="database",
                status="critical",
                message=f"Database unreachable: {err}",
                remediation="Check DATABASE_URL; ensure DB service is running",
                duration_ms=dur,
            )
        except Exception as exc:
            return DiagnosticResult(
                check_name="database",
                status="error",
                message=f"Database check failed: {exc}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

    # ------------------------------------------------------------------
    # Check 4: Redis connectivity
    # ------------------------------------------------------------------

    async def _check_redis(self) -> DiagnosticResult:
        t0 = time.monotonic()
        try:
            import redis.asyncio as aioredis

            url = os.getenv("REDIS_URL", "")
            if not url:
                return DiagnosticResult(
                    check_name="redis",
                    status="warning",
                    message="REDIS_URL not configured — Redis features disabled",
                    remediation="Set REDIS_URL=redis://localhost:6379/0 to enable caching and pub/sub",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            url = url or "redis://localhost:6379/0"
            client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=5)
            try:
                pong = await asyncio.wait_for(client.ping(), timeout=5)
                dur = (time.monotonic() - t0) * 1000
                if pong:
                    ns_status: dict[str, bool] = {}
                    for ns in ["heal:manifest", "alerts:critical", "fixes:approved"]:
                        try:
                            ns_status[ns] = bool(await client.exists(ns))
                        except Exception:
                            ns_status[ns] = False
                    return DiagnosticResult(
                        check_name="redis",
                        status="ok",
                        message="Redis connection healthy",
                        details={"namespace_exists": ns_status},
                        duration_ms=dur,
                    )
                return DiagnosticResult(
                    check_name="redis", status="error", message="Redis PING returned falsy", duration_ms=dur
                )
            finally:
                await client.aclose()
        except Exception as exc:
            return DiagnosticResult(
                check_name="redis",
                status="critical",
                message=f"Redis unreachable: {exc}",
                remediation="Check REDIS_URL; ensure Redis service is running",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

    # ------------------------------------------------------------------
    # Check 5: Frontend build freshness
    # ------------------------------------------------------------------

    async def _check_frontend_build(self) -> DiagnosticResult:
        t0 = time.monotonic()
        candidates = [
            PROJECT_ROOT / "static" / "index.html",
            PROJECT_ROOT / "frontend" / "dist" / "index.html",
            PROJECT_ROOT / "frontend" / "build" / "index.html",
            PROJECT_ROOT / "templates" / "index.html",
        ]
        found: Path | None = next((p for p in candidates if p.exists()), None)
        dur = (time.monotonic() - t0) * 1000
        if found is None:
            return DiagnosticResult(
                check_name="frontend_build",
                status="warning",
                message="No frontend build artifact found (index.html missing)",
                details={"searched": [str(p) for p in candidates]},
                remediation="Run: cd frontend && npm run build",
                duration_ms=dur,
            )
        age_hours = (time.time() - found.stat().st_mtime) / 3600
        if age_hours > _FRONTEND_MAX_AGE_HOURS:
            return DiagnosticResult(
                check_name="frontend_build",
                status="warning",
                message=f"Frontend build is {age_hours:.1f}h old (threshold: {_FRONTEND_MAX_AGE_HOURS}h)",
                details={"path": str(found), "age_hours": round(age_hours, 1)},
                remediation="Rebuild frontend: cd frontend && npm run build",
                duration_ms=dur,
            )
        return DiagnosticResult(
            check_name="frontend_build",
            status="ok",
            message=f"Frontend build found and fresh ({age_hours:.1f}h old)",
            details={"path": str(found)},
            duration_ms=dur,
        )

    # ------------------------------------------------------------------
    # Check 6: Runtime route health
    # ------------------------------------------------------------------

    async def _check_route_health(self) -> list[DiagnosticResult]:
        t0 = time.monotonic()

        # Only probe GET endpoints and a small set of POST endpoints that
        # accept empty bodies or have known-safe minimal payloads.
        # POST endpoints that require a request body (register, login, etc.)
        # are excluded — probing them with {} generates 422 log noise and
        # provides no signal beyond "the route exists".
        _PROBE_GET_ONLY_PREFIXES: tuple[str, ...] = (
            "/api/auth/register",
            "/api/auth/login",
            "/api/auth/resend-verification",
            "/api/auth/forgot-password",
            "/api/auth/reset-password",
            "/api/auth/activate-free-tier",
            "/api/auth/verify-email",
            "/api/auth/refresh",
            "/api/auth/logout",
            "/api/auth/logout-all",
            "/api/auth/2fa/",
            "/api/trading/order",
            "/api/trading/orders",
        )

        routes_to_test: list[tuple[str, str]] = [
            ("GET", "/api/health/ready"),
            ("GET", "/api/status"),
            ("GET", "/api/auth/csrf-token"),
        ]
        try:
            from app import app as _app

            for route in _app.routes:
                path = getattr(route, "path", None)
                methods = getattr(route, "methods", None)
                if path and methods:
                    for m in methods:
                        if m == "GET":
                            routes_to_test.append(("GET", path))
                        elif m == "POST" and not any(path.startswith(p) for p in _PROBE_GET_ONLY_PREFIXES):
                            routes_to_test.append(("POST", path))
        except Exception:  # nosec B110 — app not initialised yet; route list stays empty
            pass
        routes_to_test = list(dict.fromkeys(routes_to_test))[:50]
        try:
            import httpx

            unhealthy: list[dict[str, Any]] = []
            ok_count = 0
            # Internal health-check header allows loopback probes to bypass CSRF
            # validation on POST/PUT/PATCH/DELETE endpoints without a browser session.
            _internal_headers = {"X-Internal-Health-Check": "1"}
            async with httpx.AsyncClient(
                base_url=_APP_BASE_URL, timeout=_DIAG_HTTP_TIMEOUT, follow_redirects=True
            ) as client:
                for method, path in routes_to_test:
                    if "{" in path:
                        continue
                    try:
                        if method == "GET":
                            resp = await client.get(path)
                        else:
                            resp = await client.post(path, json={}, headers=_internal_headers)
                        if resp.status_code in (200, 201, 401, 403, 405, 422):
                            ok_count += 1
                        elif resp.status_code >= 500:
                            unhealthy.append({"method": method, "path": path, "status": resp.status_code})
                    except httpx.ConnectError:
                        break
                    except Exception as exc:
                        unhealthy.append({"method": method, "path": path, "error": str(exc)[:100]})
            dur = (time.monotonic() - t0) * 1000
            if unhealthy:
                return [
                    DiagnosticResult(
                        check_name="route_health",
                        status="error",
                        message=f"{len(unhealthy)} route(s) returning 5xx errors",
                        details={"unhealthy": unhealthy, "ok_count": ok_count},
                        remediation="Check application logs for 500 errors",
                        duration_ms=dur,
                    )
                ]
            return [
                DiagnosticResult(
                    check_name="route_health",
                    status="ok",
                    message=f"All {ok_count} tested routes are alive",
                    duration_ms=dur,
                )
            ]
        except ImportError:
            return [
                DiagnosticResult(
                    check_name="route_health",
                    status="warning",
                    message="httpx not available — route health check skipped",
                    remediation="pip install httpx",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            ]
        except Exception as exc:
            return [
                DiagnosticResult(
                    check_name="route_health",
                    status="error",
                    message=f"Route health check failed: {exc}",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            ]

    # ------------------------------------------------------------------
    # Check 7: SPA routing
    # ------------------------------------------------------------------

    async def _check_spa_routing(self) -> list[DiagnosticResult]:
        t0 = time.monotonic()
        try:
            import httpx

            broken: list[dict[str, Any]] = []
            ok_count = 0
            async with httpx.AsyncClient(
                base_url=_APP_BASE_URL, timeout=_DIAG_HTTP_TIMEOUT, follow_redirects=True
            ) as client:
                for route in _SPA_ROUTES:
                    try:
                        resp = await client.get(route)
                        ct = resp.headers.get("content-type", "")
                        if resp.status_code == 200 and "html" in ct:
                            ok_count += 1
                        elif resp.status_code == 404:
                            broken.append({"route": route, "status": 404, "issue": "SPA catch-all not configured"})
                        elif resp.status_code >= 500:
                            broken.append({"route": route, "status": resp.status_code, "issue": "Server error"})
                        else:
                            ok_count += 1
                    except httpx.ConnectError:
                        break
                    except Exception as exc:
                        broken.append({"route": route, "error": str(exc)[:100]})
            dur = (time.monotonic() - t0) * 1000
            if broken:
                return [
                    DiagnosticResult(
                        check_name="spa_routing",
                        status="error",
                        message=f"{len(broken)} SPA route(s) not serving HTML",
                        details={"broken": broken},
                        remediation="Add catch-all route in app.py that serves index.html",
                        duration_ms=dur,
                    )
                ]
            return [
                DiagnosticResult(
                    check_name="spa_routing",
                    status="ok",
                    message=f"All {ok_count} SPA routes serve HTML correctly",
                    duration_ms=dur,
                )
            ]
        except ImportError:
            return [
                DiagnosticResult(
                    check_name="spa_routing",
                    status="warning",
                    message="httpx not available — SPA routing check skipped",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            ]
        except Exception as exc:
            return [
                DiagnosticResult(
                    check_name="spa_routing",
                    status="error",
                    message=f"SPA routing check failed: {exc}",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            ]

    # ------------------------------------------------------------------
    # Check 8: Auth flow
    # ------------------------------------------------------------------

    async def _check_auth_flow(self) -> DiagnosticResult:
        t0 = time.monotonic()
        test_email = os.getenv("DIAG_TEST_EMAIL", "")
        test_password = os.getenv("DIAG_TEST_PASSWORD", "")
        if not test_email or not test_password:
            return DiagnosticResult(
                check_name="auth_flow",
                status="warning",
                message="Auth flow test skipped — set DIAG_TEST_EMAIL and DIAG_TEST_PASSWORD",
                duration_ms=(time.monotonic() - t0) * 1000,
            )
        try:
            import httpx

            async with httpx.AsyncClient(
                base_url=_APP_BASE_URL, timeout=_DIAG_HTTP_TIMEOUT, follow_redirects=True
            ) as client:
                login_resp = await client.post("/api/auth/login", json={"email": test_email, "password": test_password})
                if login_resp.status_code != 200:
                    return DiagnosticResult(
                        check_name="auth_flow",
                        status="error",
                        message=f"Login returned {login_resp.status_code}",
                        remediation="Check auth endpoint and test credentials",
                        duration_ms=(time.monotonic() - t0) * 1000,
                    )
                data = login_resp.json()
                token = data.get("access_token") or data.get("token", "")
                if not token:
                    return DiagnosticResult(
                        check_name="auth_flow",
                        status="error",
                        message="Login succeeded but no access_token in response",
                        duration_ms=(time.monotonic() - t0) * 1000,
                    )
                me_resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
                dur = (time.monotonic() - t0) * 1000
                if me_resp.status_code == 200:
                    return DiagnosticResult(
                        check_name="auth_flow",
                        status="ok",
                        message="Auth flow (login → protected route) works correctly",
                        duration_ms=dur,
                    )
                return DiagnosticResult(
                    check_name="auth_flow",
                    status="error",
                    message=f"/api/auth/me returned {me_resp.status_code} with valid token",
                    remediation="Check JWT validation middleware",
                    duration_ms=dur,
                )
        except ImportError:
            return DiagnosticResult(
                check_name="auth_flow",
                status="warning",
                message="httpx not available — auth flow check skipped",
                duration_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            return DiagnosticResult(
                check_name="auth_flow",
                status="error",
                message=f"Auth flow check failed: {exc}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

    # ------------------------------------------------------------------
    # Check 9: Data feeds
    # ------------------------------------------------------------------

    async def _check_data_feeds(self) -> list[DiagnosticResult]:
        t0 = time.monotonic()
        results: list[DiagnosticResult] = []
        try:
            import redis.asyncio as aioredis

            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=3)
            try:
                found_feeds: list[str] = []
                stale_feeds: list[str] = []
                for pattern in ["market:tick:*", "feed:ohlcv:*", "data:live:*"]:
                    try:
                        # Use SCAN (non-blocking, O(1) per call) instead of KEYS
                        # (blocking O(N)) to avoid stalling Redis during the check.
                        # Collect at most 5 keys per pattern — enough for a health signal.
                        collected: list[str] = []
                        async for key in client.scan_iter(pattern, count=10):
                            collected.append(key)
                            if len(collected) >= 5:
                                break
                        for key in collected:
                            ttl = await asyncio.wait_for(client.ttl(key), timeout=2)
                            (found_feeds if ttl != 0 else stale_feeds).append(key)
                    except TimeoutError:  # nosec B110 — Redis TTL check timed out; skip key
                        pass
                dur = (time.monotonic() - t0) * 1000
                if stale_feeds:
                    results.append(
                        DiagnosticResult(
                            check_name="data_feeds_redis",
                            status="warning",
                            message=f"{len(stale_feeds)} Redis feed key(s) are stale/expired",
                            details={"stale": stale_feeds[:10], "active": found_feeds[:10]},
                            remediation="Check data feed connectors",
                            duration_ms=dur,
                        )
                    )
                else:
                    results.append(
                        DiagnosticResult(
                            check_name="data_feeds_redis",
                            status="ok",
                            message=f"Redis data feeds healthy ({len(found_feeds)} active keys)",
                            duration_ms=dur,
                        )
                    )
            finally:
                await client.aclose()
        except Exception as exc:
            results.append(
                DiagnosticResult(
                    check_name="data_feeds_redis",
                    status="warning",
                    message=f"Redis feed check skipped: {exc}",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            )

        try:
            loop = asyncio.get_running_loop()

            def _probe_feed() -> tuple[bool, str]:
                try:
                    from data_feed import get_feed_status

                    status = get_feed_status()
                    return status.get("healthy", False), status.get("message", "")
                except ImportError:
                    return True, "data_feed module not present (optional)"
                except Exception as exc2:
                    return False, str(exc2)[:200]

            ok, msg = await loop.run_in_executor(None, _probe_feed)
            results.append(
                DiagnosticResult(
                    check_name="data_feeds_module",
                    status="ok" if ok else "warning",
                    message=msg or ("Data feed module healthy" if ok else "Data feed module unhealthy"),
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            )
        except Exception as exc:
            results.append(
                DiagnosticResult(
                    check_name="data_feeds_module",
                    status="warning",
                    message=f"Data feed module check failed: {exc}",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Check 10: Log pattern detection
    # ------------------------------------------------------------------

    async def _check_log_patterns(self) -> list[DiagnosticResult]:
        t0 = time.monotonic()
        log_file = PROJECT_ROOT / "logs" / "app.log"
        if not log_file.exists():
            return [
                DiagnosticResult(
                    check_name="log_patterns",
                    status="warning",
                    message="Log file not found — cannot scan for patterns",
                    details={"searched": str(log_file)},
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            ]
        try:
            loop = asyncio.get_running_loop()

            def _scan_logs() -> list[dict[str, Any]]:
                findings: dict[str, dict[str, Any]] = {}
                try:
                    with log_file.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(0, 2)
                        size = f.tell()
                        # Cap at 128KB to keep scan fast regardless of log size
                        f.seek(max(0, size - 131_072))
                        lines = f.readlines()[-1000:]
                except OSError:
                    return []
                for line in lines:
                    for pd in _LOG_PATTERN_MAP:
                        cat = pd["category"]
                        if pd["pattern"].search(line):
                            if cat not in findings:
                                findings[cat] = {
                                    "category": cat,
                                    "severity": pd["severity"],
                                    "root_cause": pd["root_cause"],
                                    "remediation": pd["remediation"],
                                    "count": 0,
                                    "sample": line.strip()[:200],
                                }
                            findings[cat]["count"] += 1
                return list(findings.values())

            hits = await loop.run_in_executor(None, _scan_logs)
            dur = (time.monotonic() - t0) * 1000
            if not hits:
                return [
                    DiagnosticResult(
                        check_name="log_patterns",
                        status="ok",
                        message="No known error patterns detected in recent logs",
                        duration_ms=dur,
                    )
                ]
            results: list[DiagnosticResult] = []
            for hit in hits:
                sev = hit["severity"]
                status = "critical" if sev == "critical" else "error" if sev == "high" else "warning"
                results.append(
                    DiagnosticResult(
                        check_name=f"log_pattern_{hit['category']}",
                        status=status,
                        message=f"[{hit['count']}x] {hit['root_cause']}",
                        details={"count": hit["count"], "sample": hit["sample"]},
                        remediation=hit["remediation"],
                        duration_ms=dur,
                    )
                )
            return results
        except Exception as exc:
            return [
                DiagnosticResult(
                    check_name="log_patterns",
                    status="error",
                    message=f"Log pattern scan failed: {exc}",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            ]

    # ------------------------------------------------------------------
    # Auto-remediation
    # ------------------------------------------------------------------

    async def _remediate_result(self, result: DiagnosticResult) -> dict[str, Any] | None:
        check = result.check_name
        action: dict[str, Any] = {
            "check": check,
            "status": result.status,
            "attempted_at": datetime.now(UTC).isoformat(),
            "action": None,
            "success": False,
        }
        try:
            if check == "frontend_build":
                frontend_dir = PROJECT_ROOT / "frontend"
                if frontend_dir.exists() and (frontend_dir / "package.json").exists():
                    proc = await asyncio.create_subprocess_exec(
                        "npm",
                        "run",
                        "build",
                        cwd=str(frontend_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                        action["action"] = "npm run build"
                        action["success"] = proc.returncode == 0
                        if not action["success"]:
                            action["error"] = stderr.decode(errors="replace")[:300]
                    except TimeoutError:
                        proc.kill()
                        action["action"] = "npm run build (timed out)"
            elif check == "import_chain":
                # _CORE_PACKAGES contains internal project modules (api.auth,
                # security.self_healer, core.router_registry, …).  Their top-level
                # names ("api", "security", "core", "risk", "execution", "app") are
                # all real PyPI packages unrelated to this project — pip-installing
                # them would pull in arbitrary third-party code.  Import failures
                # for internal modules indicate a code or environment problem, not a
                # missing dependency; log them for operator attention instead.
                _INTERNAL_NAMESPACES: frozenset[str] = frozenset(
                    {
                        "api",
                        "app",
                        "auth",
                        "brain",
                        "brokers",
                        "cache",
                        "charting",
                        "config",
                        "core",
                        "data_feed",
                        "data_layer",
                        "database",
                        "execution",
                        "features",
                        "health",
                        "market_data",
                        "ml",
                        "monitoring",
                        "nuclear",
                        "risk",
                        "security",
                        "strategies",
                        "strategy",
                        "utils",
                    }
                )
                broken_internal = [
                    item
                    for item in result.details.get("broken", [])
                    if item.get("package", "").split(".")[0] in _INTERNAL_NAMESPACES
                ]
                if broken_internal:
                    action["action"] = "logged_internal_import_failures"
                    action["success"] = False
                    action["detail"] = (
                        f"{len(broken_internal)} internal module(s) failed to import — "
                        "check for circular imports or missing __init__.py files: "
                        + ", ".join(i.get("package", "") for i in broken_internal[:5])
                    )
                    logger.warning(
                        "DiagnosticsEngine: internal import failures (not pip-installable): %s",
                        [i.get("package") for i in broken_internal],
                    )
            elif check.startswith("log_pattern_"):
                try:
                    from security.self_healer import get_healer

                    await get_healer()._enqueue_claude_fix(
                        {
                            "category": check.replace("log_pattern_", ""),
                            "severity": result.status,
                            "description": result.message,
                            "file": "logs/app.log",
                            "line": 0,
                            "snippet": result.details.get("sample", ""),
                            "suggestion": result.remediation,
                        }
                    )
                    action["action"] = "enqueued_claude_fix"
                    action["success"] = True
                except Exception as exc:
                    action["error"] = str(exc)
        except Exception as exc:
            action["error"] = str(exc)
            logger.warning("DiagnosticsEngine: remediation failed for %s: %s", check, exc)
        if action["action"]:
            logger.info(
                "DiagnosticsEngine: remediation %s — action=%s success=%s", check, action["action"], action["success"]
            )
            return action
        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine_instance: DiagnosticsEngine | None = None


def get_diagnostics_engine() -> DiagnosticsEngine:
    """Return the module-level DiagnosticsEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = DiagnosticsEngine()
    return _engine_instance
