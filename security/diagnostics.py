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
import importlib
import json
import logging
import os
import re
import subprocess  # nosec B404 — used only with fixed command lists
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
_DIAG_IMPORT_TIMEOUT: int = int(os.getenv("DIAG_IMPORT_TIMEOUT", "30"))
_FRONTEND_MAX_AGE_HOURS: int = int(os.getenv("DIAG_FRONTEND_MAX_AGE_HOURS", "24"))

# SPA routes that must return 200 + HTML
_SPA_ROUTES: list[str] = [
    "/",
    "/dashboard",
    "/superadmin",
    "/login",
    "/register",
]

# Required environment variables — (name, description, is_secret)
_REQUIRED_ENV_VARS: list[tuple[str, str, bool]] = [
    ("SECRET_KEY", "JWT signing key", True),
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
        counts = {s: 0 for s in ("ok", "warning", "error", "critical")}
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


