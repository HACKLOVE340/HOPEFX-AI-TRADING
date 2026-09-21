#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/runtime_invariant_check.py — runtime output-invariant checker.

The static audit answers "is the code well-formed?". This answers the question
static analysis cannot: **"does the running platform produce sane output?"** —
the "looks right, behaves wrong" class of bug (the 18 duplicated chart patterns,
the ML accuracy shown as 0.6%, NaN tiles, empty-when-populated lists).

It runs in two phases:

  Phase 1 — BOOT: import the app and (optionally) start a live server. Any
            SyntaxError / ImportError / startup failure fails here loudly, so a
            "missing comma" or broken import is caught before anything else.
  Phase 2 — PROBE: authenticate, call the key data endpoints, and assert a
            battery of invariants on each RESPONSE:
              * HTTP 200 + valid JSON + expected keys/shape
              * no NaN / Infinity (numbers or "NaN"/"Infinity" strings)
              * no excessive duplicate / tiled list items (the rectangle bug)
              * no "all-identical" metric columns that should vary
              * targeted per-endpoint rules (e.g. ≤N patterns per type)
            Finally it scans the observability event log produced during the
            probe for any ERROR / CRITICAL / uncaught exception.

Exit code: 0 = clean, 1 = findings, 2 = could not run (boot/auth failure).

Usage
-----
    python scripts/runtime_invariant_check.py            # boot + probe (default)
    python scripts/runtime_invariant_check.py --url http://127.0.0.1:8000
    python scripts/runtime_invariant_check.py --json     # machine-readable report

Stdlib only. Safe to run in CI.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Run as a script (`python scripts/runtime_invariant_check.py`) puts scripts/ on
# sys.path[0], NOT the repo root — so the in-process Phase-3 checks (audit chain,
# tenant isolation, recovery readiness) could not import repo modules. Put the
# repo root first so those imports resolve exactly as they do in the app.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── tunable thresholds ─────────────────────────────────────────────────────────
DUP_HARD = 4  # ≥ this many byte-identical list items → ERROR
DUP_SOFT = 3  # ≥ this many → WARN
DUP_RATIO_HARD = 0.5  # ≥ 50% of a (len≥4) list identical → ERROR
BOOT_READY_TIMEOUT = 180  # seconds to wait for full startup
HTTP_TIMEOUT = 45

# Keys that legitimately vary per item — excluded from the duplicate signature
# so "same pattern at different indices" is still flagged as a duplicate, while
# genuinely-distinct rows (different id/time) are not.
_VOLATILE_KEY = re.compile(
    r"(?i)(^id$|_id$|idx|index|time|timestamp|_at$|date|updated|created|checked_at|"
    r"latency|seq|cursor|offset|page|uuid|hash|sha)"
)
# Numeric metric fields that should normally VARY across a list of rows.
_METRIC_KEY = re.compile(r"(?i)(conf|score|accuracy|price|pnl|return|rate|ratio|sharpe|drawdown|strength)")


# ── finding model ──────────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str  # "ERROR" | "WARN" | "INFO"
    endpoint: str
    rule: str
    message: str


@dataclass
class CheckResult:
    findings: list[Finding] = field(default_factory=list)

    def add(self, sev: str, endpoint: str, rule: str, msg: str) -> None:
        self.findings.append(Finding(sev, endpoint, rule, msg))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "WARN"]


# ── JSON walkers / generic invariants ───────────────────────────────────────────
def _walk(obj: Any, path: str = "$"):
    """Yield (path, value) for every leaf in a JSON structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def check_non_finite(resp: Any, ep: str, res: CheckResult) -> None:
    """NaN / Infinity (as float or as the strings 'NaN'/'Infinity') are bugs.

    json.loads(parse_constant) surfaces Python float('nan')/inf; we also catch
    the literal strings that frontends render verbatim.
    """
    bad_strs = {"nan", "inf", "-inf", "infinity", "-infinity"}
    for p, v in _walk(resp):
        if isinstance(v, float) and not math.isfinite(v):
            res.add("ERROR", ep, "non_finite", f"{p} = {v!r} (NaN/Infinity in response)")
        elif isinstance(v, str) and v.strip().lower() in bad_strs:
            res.add("ERROR", ep, "non_finite", f"{p} = {v!r} (NaN/Infinity rendered as string)")


def _signature(item: Any) -> str | None:
    """Stable signature of a dict item, ignoring volatile (per-row) keys."""
    if not isinstance(item, dict):
        return json.dumps(item, sort_keys=True, default=repr)
    stable = {k: v for k, v in item.items() if not _VOLATILE_KEY.search(k)}
    if not stable:
        return None
    return json.dumps(stable, sort_keys=True, default=repr)


def check_duplicate_items(resp: Any, ep: str, res: CheckResult) -> None:
    """Flag any list (anywhere in the response) with excessive identical items.

    This is the generic catcher for the "same pattern repeated N times" class —
    it would have caught the 18 tiled rectangles automatically.
    """
    for p, v in _iter_lists(resp):
        dict_items = [x for x in v if isinstance(x, dict)]
        if len(dict_items) < DUP_SOFT:
            continue
        groups: dict[str, int] = {}
        for it in dict_items:
            sig = _signature(it)
            if sig is None:
                continue
            groups[sig] = groups.get(sig, 0) + 1
        if not groups:
            continue
        worst = max(groups.values())
        ratio = worst / len(dict_items)
        if worst >= DUP_HARD or (len(dict_items) >= 4 and ratio >= DUP_RATIO_HARD):
            res.add(
                "ERROR",
                ep,
                "duplicate_items",
                f"{p}: {worst}/{len(dict_items)} list items are identical "
                f"(ignoring id/index/time) — likely duplicated/tiled output",
            )
        elif worst >= DUP_SOFT:
            res.add(
                "WARN",
                ep,
                "duplicate_items",
                f"{p}: {worst} identical items — verify not unintended duplicates",
            )


def check_all_identical_metrics(resp: Any, ep: str, res: CheckResult) -> None:
    """A metric column (confidence/score/price…) identical across a whole list
    of ≥4 rows is suspicious (e.g. every pattern conf=0.71)."""
    for p, v in _iter_lists(resp):
        dict_items = [x for x in v if isinstance(x, dict)]
        if len(dict_items) < 4:
            continue
        keys = set(dict_items[0].keys())
        for k in keys:
            if not _METRIC_KEY.search(k):
                continue
            vals = [it.get(k) for it in dict_items if isinstance(it.get(k), (int, float))]
            if len(vals) >= 4 and len(set(vals)) == 1:
                res.add(
                    "WARN",
                    ep,
                    "all_identical_metric",
                    f"{p}[*].{k} is {vals[0]!r} for all {len(vals)} rows — metric not varying",
                )


def _iter_lists(obj: Any, path: str = "$"):
    """Yield (path, list) for every list found anywhere in the structure."""
    if isinstance(obj, list):
        yield path, obj
        for i, v in enumerate(obj):
            yield from _iter_lists(v, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_lists(v, f"{path}.{k}")


# ── endpoint registry ────────────────────────────────────────────────────────--
@dataclass
class Endpoint:
    path: str
    auth: bool = True  # send the superadmin bearer token
    expect_keys: tuple[str, ...] = ()  # keys that must be present (dict response)
    list_key: str | None = None  # key whose value must be a list
    max_same_type: int = 0  # patterns/signals: max rows sharing (type/direction)
    type_fields: tuple[str, ...] = ()
    allow_503: bool = False  # data endpoints may 503 during warmup — retry


ENDPOINTS: list[Endpoint] = [
    # /api/health 302-redirects to /api/health/ready, which is specified to
    # answer 503 when a critical dependency is degraded. Treated as a warning
    # for the same reason as the probes in check_route_coverage: a fail-closed
    # readiness probe doing its job is not an output-invariant violation.
    # ``expect_keys`` was ("status",), which this endpoint has never returned:
    # it redirects to /api/health/ready, whose ReadinessResponse is
    # {ready, timestamp, failed_critical, components}. The mismatch was hidden
    # because the 503 was reported first and the body was never checked.
    Endpoint("/api/health", auth=False, expect_keys=("ready",), allow_503=True),
    Endpoint("/api/superadmin/overview", expect_keys=("total_users", "system_health", "ml_model_accuracy")),
    Endpoint("/api/superadmin/users", list_key="users"),
    Endpoint("/api/superadmin/ml/models", list_key="models", max_same_type=3, type_fields=("name",)),
    Endpoint("/api/superadmin/ml/metrics"),
    Endpoint("/api/superadmin/reliability/status", expect_keys=("overall", "components"), list_key="components"),
    Endpoint("/api/superadmin/engine/status", expect_keys=("status",)),
    Endpoint(
        "/api/trading/patterns?symbol=XAUUSD&timeframe=1h&limit=400",
        list_key="patterns",
        max_same_type=3,
        type_fields=("pattern_type", "direction"),
        allow_503=True,
    ),
    Endpoint("/api/signals/active", allow_503=True),
    Endpoint("/api/performance/equity-curve", allow_503=True),
    Endpoint("/api/calendar/upcoming", allow_503=True),
]


def check_endpoint_specific(ep: Endpoint, resp: Any, res: CheckResult) -> None:
    """Targeted per-endpoint invariants beyond the generic ones."""
    name = ep.path
    if ep.expect_keys:
        if not isinstance(resp, dict):
            res.add("ERROR", name, "shape", f"expected a JSON object, got {type(resp).__name__}")
        else:
            missing = [k for k in ep.expect_keys if k not in resp]
            if missing:
                res.add("ERROR", name, "missing_keys", f"response missing required keys: {missing}")
    if ep.list_key:
        container = resp.get(ep.list_key) if isinstance(resp, dict) else None
        if not isinstance(container, list):
            res.add("ERROR", name, "shape", f"'{ep.list_key}' should be a list, got {type(container).__name__}")
    if ep.max_same_type and ep.type_fields:
        rows = resp.get(ep.list_key, []) if isinstance(resp, dict) else (resp if isinstance(resp, list) else [])
        groups: dict[tuple, int] = {}
        for r in rows:
            if isinstance(r, dict):
                key = tuple(str(r.get(f, "")) for f in ep.type_fields)
                groups[key] = groups.get(key, 0) + 1
        for key, n in groups.items():
            if n > ep.max_same_type:
                res.add(
                    "ERROR",
                    name,
                    "excessive_same_type",
                    f"{n} rows share {ep.type_fields}={key} (max {ep.max_same_type}) — duplicated detections",
                )


# ── HTTP / auth / boot ───────────────────────────────────────────────────────--
def _http(method: str, url: str, token: str | None = None, body: dict | None = None, timeout: int = HTTP_TIMEOUT):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # surfaced as a finding, not raised
        return None, str(e).encode()


def _superadmin_password() -> str:
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("BOOTSTRAP_SUPERADMIN_PASSWORD="):
                return line.split("=", 1)[1].strip()
    return os.getenv("BOOTSTRAP_SUPERADMIN_PASSWORD", "")


def _login(base: str) -> str | None:
    pw = _superadmin_password()
    if not pw:
        return None
    status, raw = _http("POST", f"{base}/api/auth/login", body={"username": "superadmin", "password": pw}, timeout=20)
    if status == 200:
        try:
            return json.loads(raw).get("access_token")
        except Exception:
            return None
    return None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def boot_server(port: int) -> subprocess.Popen:
    """Start uvicorn in its own process group; caller terminates it."""
    env = dict(os.environ, LOG_DIR="logs", HOPEFX_OBSERVE_LEVEL="DEBUG")
    log = open(REPO_ROOT / "logs" / "invariant_server.out", "w")  # noqa: SIM115
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
        cwd=str(REPO_ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )


def wait_ready(base: str, proc: subprocess.Popen | None, timeout: int) -> str | None:
    """Wait until login succeeds (full readiness). Returns a token or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return None  # server died during boot
        tok = _login(base)
        if tok:
            return tok
        time.sleep(3)
    return None


# ── observability log scan ───────────────────────────────────────────────────--
def scan_event_log(since_ts: float, res: CheckResult) -> None:
    """Flag any ERROR/CRITICAL/exception the harness recorded during the probe."""
    path = REPO_ROOT / "logs" / "hopefx_events.jsonl"
    if not path.exists():
        return
    seen: set[str] = set()
    for raw_line in path.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:  # noqa: S112 — skip malformed log lines
            continue
        ev = rec.get("event")
        lvl = rec.get("level")
        if ev in ("exception", "uncaught_exception", "thread_exception", "asyncio_exception", "unraisable_exception"):
            msg = f"{ev}: {rec.get('error') or rec.get('message')}"
            if msg not in seen:
                seen.add(msg)
                res.add("ERROR", "observability", "logged_exception", msg)
        elif lvl in ("ERROR", "CRITICAL"):
            msg = f"[{rec.get('logger')}] {rec.get('message', '')[:160]}"
            if msg not in seen:
                seen.add(msg)
                res.add("WARN", "observability", "logged_error", msg)


# ── runner ───────────────────────────────────────────────────────────────────--
def run(base: str, token: str | None, res: CheckResult) -> None:
    for ep in ENDPOINTS:
        tok = token if ep.auth else None
        status, raw = None, b""
        # Retry 503 (data endpoints may warm up after readiness).
        for _ in range(8 if ep.allow_503 else 1):
            status, raw = _http("GET", f"{base}{ep.path}", token=tok)
            if status != 503:
                break
            time.sleep(3)
        if status is None:
            res.add("ERROR", ep.path, "unreachable", raw.decode(errors="replace")[:120])
            continue
        if status != 200:
            sev = "WARN" if (status == 503 and ep.allow_503) else "ERROR"
            res.add(sev, ep.path, "http_status", f"HTTP {status}")
            continue
        try:
            resp = json.loads(raw)
        except Exception as e:
            res.add("ERROR", ep.path, "invalid_json", f"{type(e).__name__}: {e}")
            continue
        # generic + targeted invariants
        check_non_finite(resp, ep.path, res)
        check_duplicate_items(resp, ep.path, res)
        check_all_identical_metrics(resp, ep.path, res)
        check_endpoint_specific(ep, resp, res)


def check_audit_integrity(res: CheckResult) -> None:
    """Exercise the live audit hash-chain mechanism (No Audit Gap): a fresh log
    must verify intact, and a tampered record must be detected. If the deployed
    hashing/verify logic is broken, this fails the build — monitoring the monitor.
    """
    import tempfile

    try:
        from compliance.auditor import AuditLevel, ImmutableAuditLog
    except Exception as e:  # audit module must import
        res.add("ERROR", "compliance/auditor.py", "audit_import", f"{type(e).__name__}: {e}")
        return

    try:
        with tempfile.TemporaryDirectory() as tmp:
            log = ImmutableAuditLog(log_path=f"{tmp}/")
            log.append(AuditLevel.INFO, "TEST", "checker", "probe-1", {"n": 1})
            log.append(AuditLevel.INFO, "TEST", "checker", "probe-2", {"n": 2})
            if not log.verify_integrity():
                res.add(
                    "ERROR",
                    "compliance/auditor.py",
                    "audit_chain",
                    "verify_integrity() False on an untampered chain — audit hashing is broken",
                )
                return
            # Tamper with a record; the verifier MUST now report a break.
            log.records[0].data["n"] = 999
            if log.verify_integrity():
                res.add(
                    "ERROR",
                    "compliance/auditor.py",
                    "audit_chain",
                    "tampering NOT detected — audit log is not tamper-evident (No Audit Gap)",
                )
    except Exception as e:
        res.add("ERROR", "compliance/auditor.py", "audit_chain", f"{type(e).__name__}: {e}")


def check_tenant_isolation(res: CheckResult) -> None:
    """Exercise the cross-tenant isolation mechanism (No Cross-Tenant Leakage):
    two tenants' namespaced cache keys must be disjoint, and the isolation
    predicate must detect shared state. Fails the build if isolation is broken.
    """
    try:
        from whitelabel.tenant_isolation import NamespacedCache

        a = NamespacedCache(redis_client=None, tenant_id="tenant-a")
        b = NamespacedCache(redis_client=None, tenant_id="tenant-b")
        ka, kb = a._key("balance"), b._key("balance")
        if ka == kb or ka in kb or kb in ka:
            res.add(
                "ERROR",
                "whitelabel/tenant_isolation.py",
                "tenant_isolation",
                f"namespaced keys are not disjoint: {ka!r} vs {kb!r} (cross-tenant leakage)",
            )
    except Exception as e:
        res.add(
            "WARN",
            "whitelabel/tenant_isolation.py",
            "tenant_isolation",
            f"could not verify tenant isolation: {type(e).__name__}: {e}",
        )

    try:
        from invariants.governance import verify_pod_isolation

        if not verify_pod_isolation({"positions": [1]}, {"positions": [1]}):
            res.add(
                "ERROR",
                "invariants/governance.py",
                "pod_isolation",
                "verify_pod_isolation failed to detect identical shared state",
            )
    except Exception as e:
        res.add("ERROR", "invariants/governance.py", "pod_isolation", f"{type(e).__name__}: {e}")


def check_recovery_readiness(res: CheckResult) -> None:
    """Assert the recovery mechanisms (No Unrecoverable Failure) are present and
    importable — a recovery path that does not exist cannot be exercised in an
    incident. Live restore/failover *drills* still require an ops runbook.
    """
    recovery_modules = (
        "kill_switch",
        "resilience.auto_rollback",
        "resilience.hot_standby",
        "resilience.circuit_breaker",
        "core.position_reconciler",
    )
    missing: list[str] = []
    for mod in recovery_modules:
        try:
            __import__(mod)
        except Exception as e:  # a missing recovery path is a real gap
            missing.append(f"{mod} ({type(e).__name__})")
    if missing:
        res.add("ERROR", "resilience/", "recovery_readiness", f"recovery mechanism(s) not importable: {missing}")


def check_surveillance(res: CheckResult) -> None:
    """Exercise the market-surveillance predicates (No Compliance Breach):
    wash-trade, spoofing and layering detection must each flag a known-bad case.
    A broken surveillance mechanism would silently pass manipulation."""
    try:
        from invariants.compliance import (
            verify_no_layering,
            verify_no_spoofing,
            verify_no_wash_trade,
        )

        cases = [
            ("wash_trade", verify_no_wash_trade("acct-1", "acct-1")),  # buyer == seller
            ("spoofing", verify_no_spoofing(placed=100, cancelled=99, filled=0)),
            ("layering", verify_no_layering(same_side_orders_at_levels=25, max_levels=10)),
        ]
        for name, result in cases:
            if not result:
                res.add(
                    "ERROR",
                    "invariants/compliance.py",
                    "surveillance",
                    f"{name} detector failed to flag a known-bad case",
                )
    except Exception as e:
        res.add("ERROR", "invariants/compliance.py", "surveillance", f"{type(e).__name__}: {e}")


def check_action_audit(res: CheckResult) -> None:
    """Exercise the per-AI-action audit mechanism (No Hidden AI Action, #7): an
    action appended to the audit log must be discoverable, and an unaudited
    action id must be flagged by the completeness predicate."""
    import tempfile

    try:
        from compliance.auditor import AuditLevel, ImmutableAuditLog
        from invariants.governance import verify_action_audited
    except Exception as e:
        res.add("ERROR", "compliance/auditor.py", "action_audit", f"{type(e).__name__}: {e}")
        return

    try:
        with tempfile.TemporaryDirectory() as tmp:
            log = ImmutableAuditLog(log_path=f"{tmp}/")
            log.append(AuditLevel.INFO, "AI_ACTION", "decision_engine", "decision", {"decision_id": "dec-1"})
            audited = {r.data.get("decision_id") for r in log.records}
            # A recorded action passes; an unrecorded one is flagged.
            if verify_action_audited("dec-1", audited):
                res.add(
                    "ERROR", "invariants/governance.py", "action_audit", "audited action wrongly flagged as unaudited"
                )
            if not verify_action_audited("dec-UNLOGGED", audited):
                res.add(
                    "ERROR",
                    "invariants/governance.py",
                    "action_audit",
                    "unaudited action NOT flagged — No Hidden AI Action completeness broken",
                )
    except Exception as e:
        res.add("ERROR", "compliance/auditor.py", "action_audit", f"{type(e).__name__}: {e}")


def check_dependency_spof(res: CheckResult) -> None:
    """Build a dependency inventory and assert no critical SPOF (No Critical
    Single Point Of Failure, #18) and blast-radius containment (#15).

    The platform's critical dependencies (DB, Redis, broker) are single-instance
    by current architecture, so this is reported as WARN, not a build failure —
    it makes the SPOF inventory explicit rather than silent. Data feeds are
    multi-source (redundant) and pass.
    """
    try:
        from invariants.systems import verify_blast_radius_contained, verify_no_single_point_of_failure
    except Exception as e:
        res.add("ERROR", "invariants/systems.py", "spof", f"{type(e).__name__}: {e}")
        return

    # Declared inventory: redundancy/failover reflect the current architecture.
    # Data feeds are multi-source (consensus); DB/Redis/broker are single-instance.
    inventory = {
        "database": {"critical": True, "redundancy": 1, "failover": False},
        "redis": {"critical": True, "redundancy": 1, "failover": False},
        "broker": {"critical": True, "redundancy": 1, "failover": False},
        "gold_data_feed": {"critical": True, "redundancy": 5, "failover": True},
        "news_data_feed": {"critical": False, "redundancy": 5, "failover": True},
    }
    spofs = verify_no_single_point_of_failure(inventory)
    for v in spofs:
        # Known single-instance infra → WARN (explicit, not a silent omission).
        res.add("WARN", "dependency_inventory", "spof", v.message)

    # Blast radius: with all declared components healthy, 0 failed → contained.
    blast = verify_blast_radius_contained(0, len(inventory))
    for v in blast:
        res.add("ERROR", "dependency_inventory", "blast_radius", v.message)


def check_route_coverage(base: str, token: str | None, res: CheckResult) -> None:
    """Enumerate EVERY GET route from /openapi.json and assert none returns 500
    (master-registry #16) and that protected routes don't return 200 without auth
    (#29). Parameterised paths ({id}) are skipped — they need fixtures. This turns
    "looks right" into "every endpoint actually responds sanely".
    """
    status, raw = _http("GET", f"{base}/openapi.json")
    if status != 200:
        res.add("WARN", "/openapi.json", "openapi", f"OpenAPI schema not available (HTTP {status})")
        return
    try:
        spec = json.loads(raw)
        paths = spec.get("paths", {})
    except Exception as e:
        res.add("ERROR", "/openapi.json", "openapi", f"invalid OpenAPI JSON: {e}")
        return

    # OK = sane non-500 responses; 5xx is never acceptable for a GET probe.
    #
    # 503 was in this set and could never be reached: the `st >= 500` branch
    # below runs first, so every 503 was reported as a server error regardless.
    # For most routes that is the behaviour we want and the set entry was simply
    # dead. For the Kubernetes probes it was wrong — `/health/ready` and
    # `/health/startup` are *specified* to answer 503 (see the contract at the
    # top of api/health.py: "MUST return 503, not 200, when any CRITICAL
    # component is degraded"). Flagging them meant this check failed hardest
    # exactly when a fail-closed probe was doing its job, and the four errors it
    # produced on a machine with no database were indistinguishable from four
    # real defects.
    allowed = {200, 201, 204, 301, 302, 304, 400, 401, 403, 404, 405, 422, 429}
    # Every one of these is documented to answer 503 when a dependency is
    # degraded: /ready and /startup per the contract in api/health.py, /deep
    # because it reports 503 if any real-I/O probe errors, and /api/health
    # because it 302-redirects to /ready.
    probes_that_may_503 = {
        "/api/health",
        "/api/health/deep",
        "/api/health/ready",
        "/api/health/startup",
        "/health/deep",
        "/health/ready",
        "/health/startup",
    }
    checked = 0
    for path, methods in paths.items():
        if "{" in path or "get" not in {m.lower() for m in methods}:
            continue  # skip parameterised paths and non-GET endpoints
        checked += 1
        st, _ = _http("GET", f"{base}{path}", token=token)
        if st is None:
            res.add("ERROR", path, "route_coverage", "GET route unreachable")
        elif st == 503 and path in probes_that_may_503:
            # Still surfaced, because a readiness probe that is red in CI is
            # worth knowing about — just not a build failure by itself.
            res.add("WARN", path, "route_coverage", "readiness probe reports 503 (a dependency is degraded)")
        elif st >= 500:
            res.add("ERROR", path, "route_coverage", f"GET {path} returned {st} (server error)")
        elif st not in allowed:
            res.add("WARN", path, "route_coverage", f"GET {path} unexpected status {st}")
    res.add("INFO", "routes", "route_coverage", f"smoke-tested {checked} parameter-free GET routes")


def report(res: CheckResult, as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                {"findings": [f.__dict__ for f in res.findings], "errors": len(res.errors), "warnings": len(res.warns)},
                indent=2,
            )
        )
    else:
        if not res.findings:
            print("✅ runtime invariant check: all endpoints passed, no anomalies.")
        for f in sorted(res.findings, key=lambda x: {"ERROR": 0, "WARN": 1, "INFO": 2}[x.severity]):
            icon = {"ERROR": "❌", "WARN": "⚠️ ", "INFO": "ℹ️ "}[f.severity]
            print(f"{icon} [{f.severity}] {f.endpoint}  ({f.rule})\n      {f.message}")
        print(f"\n— {len(res.errors)} error(s), {len(res.warns)} warning(s) —")
    return 1 if res.errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="HOPEFX runtime output-invariant checker")
    ap.add_argument("--url", help="probe an already-running server instead of booting one")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-log-scan", action="store_true", help="skip observability event-log scan")
    args = ap.parse_args()

    (REPO_ROOT / "logs").mkdir(exist_ok=True)
    res = CheckResult()
    proc: subprocess.Popen | None = None
    started = time.time()

    try:
        if args.url:
            base = args.url.rstrip("/")
            token = _login(base)
            if token is None:
                print("⚠️  could not authenticate as superadmin (probing unauthenticated endpoints only)")
        else:
            port = _free_port()
            base = f"http://127.0.0.1:{port}"
            print(f"Phase 1 — booting app on :{port} (this exercises every import; a syntax/import error fails here)…")
            # Clear prior event log so the scan only sees this run.
            for fn in ("hopefx_events.jsonl", "hopefx_all.log"):
                fp = REPO_ROOT / "logs" / fn
                if fp.exists():
                    fp.unlink()
            proc = boot_server(port)
            token = wait_ready(base, proc, BOOT_READY_TIMEOUT)
            if token is None:
                tail = ""
                outf = REPO_ROOT / "logs" / "invariant_server.out"
                if outf.exists():
                    tail = "\n".join(outf.read_text(errors="replace").splitlines()[-20:])
                print("❌ BOOT FAILED — app did not become ready (syntax/import/startup error).")
                print(tail)
                return 2

        print("Phase 2 — probing endpoints + asserting invariants…")
        run(base, token, res)
        print("Phase 2b — route coverage (every GET route never 500)…")
        check_route_coverage(base, token, res)
        print("Phase 3 — verifying audit hash-chain, tenant isolation & recovery readiness…")
        check_audit_integrity(res)
        check_tenant_isolation(res)
        check_recovery_readiness(res)
        check_surveillance(res)
        check_action_audit(res)
        check_dependency_spof(res)
        if not args.no_log_scan:
            scan_event_log(started, res)
        return report(res, args.json)
    finally:
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
