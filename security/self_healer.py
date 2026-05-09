# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/self_healer.py
=======================
Autonomous code integrity monitor and self-healing engine.

Responsibilities
----------------
* Baseline: on first run, SHA-256 hash every tracked Python/config file and
  store the manifest in Redis (``heal:manifest``) and on disk
  (``data/heal_manifest.json``).
* Drift detection: every HEAL_SCAN_INTERVAL seconds, re-hash all tracked
  files and compare against the baseline.  Any unexpected change is flagged
  as a potential tampering event and pushed to ``alerts:critical``.
* Auto-patch: drain ``fixes:queue`` (populated by HOPEFXBrain LLM loop),
  apply approved patches to disk, and record the result.
* Rollback: if a patch breaks imports, revert via ``git checkout -- <file>``.
* Quarantine: files that fail integrity checks are copied to
  ``data/quarantine/`` before any modification.
* API router: exposes ``/api/security/heal/*`` endpoints consumed by the
  Auto-Heal dashboard.

Integration
-----------
Start from connect_to_life.py or global_fortress.py::

    from security.self_healer import SelfHealer
    healer = SelfHealer()
    _t = asyncio.create_task(healer.run())
    _t.add_done_callback(lambda _: None)

The FastAPI sub-router is mounted automatically when ``mount_router`` is
called with the app instance.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import difflib
import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess  # nosec B404 — used only for git rollback with a fixed command list
import threading
import time
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── File-based logging (writes to logs/app.log) ───────────────────────────────

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "app.log"
_file_handler_installed = False


def _ensure_file_logging() -> None:
    """Install a rotating file handler on the root logger (idempotent)."""
    global _file_handler_installed
    if _file_handler_installed:
        return
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        _fh = logging.handlers.RotatingFileHandler(
            _LOG_FILE,
            maxBytes=20 * 1024 * 1024,  # 20 MB per file
            backupCount=10,
            encoding="utf-8",
        )
        _fh.setLevel(logging.DEBUG)
        _fh.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logging.getLogger().addHandler(_fh)
        _file_handler_installed = True
        logger.debug("SelfHealer: file logging active → %s", _LOG_FILE)
    except Exception as exc:
        logger.warning("SelfHealer: could not install file log handler: %s", exc)


# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "heal_manifest.json"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "quarantine"
HEAL_SCAN_INTERVAL: int = int(os.getenv("HEAL_SCAN_INTERVAL", "120"))  # seconds
HEAL_PATCH_INTERVAL: int = int(os.getenv("HEAL_PATCH_INTERVAL", "60"))  # seconds
MAX_PATCH_SIZE: int = int(os.getenv("HEAL_MAX_PATCH_BYTES", str(64 * 1024)))  # 64 KB

# Files/dirs to track for integrity (relative to PROJECT_ROOT)
TRACKED_GLOBS: list[str] = [
    "app.py",
    "connect_to_life.py",
    "hopefx_engine.py",
    "api/**/*.py",
    "auth/**/*.py",
    "security/**/*.py",
    "core/**/*.py",
    "risk/**/*.py",
    "execution/**/*.py",
    "ml/inference*.py",
    "ml/registry*.py",
    "config/**/*.py",
    "config/**/*.yaml",
]

# Paths that are expected to change at runtime (excluded from drift alerts)
RUNTIME_PATHS: set[str] = {
    "security/__pycache__",
    "data/",
    "logs/",
    ".git/",
}

# ── Patch signing (HMAC-SHA256) ───────────────────────────────────────────────
# Patches written to fixes:approved must be signed with this key so that a
# compromised Redis instance cannot inject arbitrary code.  Set
# HEAL_PATCH_SIGNING_KEY in the environment (min 32 bytes recommended).
# If unset, signing is skipped and a warning is emitted on every drain cycle.
_PATCH_SIGNING_KEY: bytes = os.getenv("HEAL_PATCH_SIGNING_KEY", "").encode()

# Dangerous AST node types / call patterns that must never appear in a patch.
# This is a defence-in-depth check on top of the compile() gate.
_DANGEROUS_CALLS: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "subprocess",
        "os.system",
        "os.popen",
        "open",  # file writes inside patches are suspicious
        "socket",
        "urllib",
        "requests",
        "httpx",
    }
)
_DANGEROUS_ATTRS: frozenset[str] = frozenset(
    {
        "system",
        "popen",
        "execve",
        "execvp",
        "spawn",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "run",
    }
)

# Baseline rebuild rate-limit: at most once per N seconds per process lifetime.
_BASELINE_REBUILD_INTERVAL: int = int(os.getenv("HEAL_BASELINE_REBUILD_INTERVAL", "300"))
_last_baseline_rebuild_ts: float = 0.0


# ── Redis helper ──────────────────────────────────────────────────────────────

_redis_client: Any | None = None


async def _get_redis() -> Any | None:
    global _redis_client
    if _redis_client is None:
        try:
            from cache.redis_client import get_redis as _gr

            _redis_client = await _gr()
        except Exception:
            try:
                import redis.asyncio as aioredis  # pylint: disable=no-name-in-module

                _redis_client = aioredis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                    decode_responses=True,
                )
            except Exception as exc:
                logger.warning("SelfHealer: Redis unavailable: %s", exc)
    return _redis_client


# ── Manifest helpers ──────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with Path(path).open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _collect_tracked_files() -> list[Path]:
    """Expand TRACKED_GLOBS into a deduplicated list of existing files."""
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in TRACKED_GLOBS:
        for p in PROJECT_ROOT.glob(pattern):
            if p.is_file() and p not in seen:
                # Skip runtime-mutated paths
                rel = str(p.relative_to(PROJECT_ROOT))
                if not any(rel.startswith(rt) for rt in RUNTIME_PATHS):
                    seen.add(p)
                    files.append(p)
    return sorted(files)


def _build_manifest() -> dict[str, str]:
    """Return {relative_path: sha256} for all tracked files."""
    manifest: dict[str, str] = {}
    for p in _collect_tracked_files():
        rel = str(p.relative_to(PROJECT_ROOT))
        manifest[rel] = _sha256(p)
    return manifest


def _load_manifest() -> dict[str, str]:
    if MANIFEST_PATH.exists():
        with contextlib.suppress(Exception):
            return json.loads(MANIFEST_PATH.read_text())
    return {}


def _save_manifest(manifest: dict[str, str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.replace(MANIFEST_PATH)


# ── Quarantine ────────────────────────────────────────────────────────────────


def _quarantine(path: Path) -> Path:
    """Copy a suspicious file to the quarantine directory before touching it."""
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    dest = QUARANTINE_DIR / f"{ts}_{path.name}"
    try:
        shutil.copy2(path, dest)
        logger.info("SelfHealer: quarantined %s → %s", path, dest)
        # Log into the singleton's quarantine_log for the dashboard
        if _healer_instance is not None:
            _healer_instance._quarantine_log.append(
                {
                    "original": str(path),
                    "quarantined_to": str(dest),
                    "ts": datetime.now(UTC).isoformat(),
                }
            )
            _healer_instance._quarantine_log = _healer_instance._quarantine_log[-200:]
    except OSError as exc:
        logger.warning("SelfHealer: quarantine copy failed: %s", exc)
    return dest


# ── Git rollback ──────────────────────────────────────────────────────────────


def _git_rollback(path: Path) -> bool:
    """Revert a single file to its last committed state via git checkout."""
    import re as _re

    try:
        rel = str(path.relative_to(PROJECT_ROOT))
        # Validate path is a safe relative file path before passing to subprocess
        if not _re.fullmatch(r"[A-Za-z0-9_./ \-]+", rel):
            logger.warning("SelfHealer: unsafe path rejected for git rollback: %r", rel)
            return False
        result = subprocess.run(  # nosec B603 B607
            ["git", "checkout", "--", rel],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            logger.info("SelfHealer: git rollback OK for %s", rel)
            return True
        logger.warning("SelfHealer: git rollback failed for %s: %s", rel, result.stderr)
    except Exception as exc:
        logger.warning("SelfHealer: git rollback exception for %s: %s", path, exc)
    return False


# ── Import smoke-test ─────────────────────────────────────────────────────────


# ── Patch signing helpers ─────────────────────────────────────────────────────


def _sign_patch(payload: str) -> str:
    """Return HMAC-SHA256 hex digest of *payload* using the signing key."""
    return hmac.new(_PATCH_SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()


def _verify_patch_signature(raw: str, sig: str) -> bool:
    """Return True if *sig* matches the HMAC of *raw*."""
    expected = _sign_patch(raw)
    return hmac.compare_digest(expected, sig)


def _patch_entry_is_trusted(raw: str, fix: dict[str, Any]) -> bool:
    """
    Return True if the patch entry passes the trust check.

    When HEAL_PATCH_SIGNING_KEY is set, the entry must carry a matching
    ``_sig`` field.  Without a key, all entries are accepted but a warning
    is logged so operators know signing is disabled.
    """
    if not _PATCH_SIGNING_KEY:
        logger.warning(
            "SelfHealer: HEAL_PATCH_SIGNING_KEY not set — patch queue trust "
            "verification disabled.  Set this env var to prevent Redis injection."
        )
        return True
    sig = fix.get("_sig", "")
    if not sig:
        logger.warning("SelfHealer: patch entry has no _sig field — rejecting")
        return False
    if not _verify_patch_signature(raw, sig):
        logger.error("SelfHealer: patch signature mismatch — possible Redis injection, rejecting")
        return False
    return True


# ── Deep patch validator ──────────────────────────────────────────────────────


def _patch_is_safe(new_code: str, target_path: Path) -> tuple[bool, str]:
    """
    Validate patch content beyond a simple compile() check.

    Checks:
    1. AST parses without error (catches more than compile() alone).
    2. No dangerous built-in calls (exec, eval, subprocess, socket, …).
    3. No path-traversal strings targeting sensitive files.
    4. Patch does not shrink the file by more than 50 % (guards against
       wholesale deletion of safety logic).

    Returns (ok, reason).
    """
    # 1. AST parse
    try:
        tree = ast.parse(new_code, filename=str(target_path))
    except SyntaxError as exc:
        return False, f"AST parse failed: {exc}"

    # 2. Dangerous call/attribute scan
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Direct calls: exec(...), eval(...)
            if isinstance(node.func, ast.Name) and node.func.id in _DANGEROUS_CALLS:
                return False, f"Dangerous call detected: {node.func.id}()"
            # Attribute calls: subprocess.Popen(...), os.system(...)
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in _DANGEROUS_ATTRS:
                    return False, f"Dangerous attribute call: .{node.func.attr}()"
                if isinstance(node.func.value, ast.Name) and node.func.value.id in _DANGEROUS_CALLS:
                    return False, f"Dangerous module call: {node.func.value.id}.{node.func.attr}()"

    # 3. Path-traversal / sensitive file references in string literals
    _sensitive_re = re.compile(r"(?i)(\.env|secrets?[/\\]|id_rsa|\.pem|\.key|/etc/passwd|/etc/shadow)")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _sensitive_re.search(node.value):
            return False, f"Sensitive path reference in patch: {node.value[:60]!r}"

    # 4. Wholesale-deletion guard — patch must not be < 50 % of original size
    if target_path.exists():
        original_size = target_path.stat().st_size
        if original_size > 200 and len(new_code.encode()) < original_size * 0.5:
            return False, (
                f"Patch shrinks file by more than 50 % "
                f"({len(new_code.encode())} bytes vs {original_size} original) — rejected"
            )

    return True, "ok"


def _import_ok(path: Path) -> bool:
    """Return True if the Python file compiles without syntax errors."""
    try:
        with Path(path).open("rb") as f:
            source = f.read()
        compile(source, str(path), "exec")
        return True
    except SyntaxError as exc:
        logger.warning("SelfHealer: syntax error in %s: %s", path, exc)
        return False
    except Exception:  # nosec B110 — any other read/compile error → treat as unsafe
        return False


# ── Patch applier ─────────────────────────────────────────────────────────────


def _apply_patch(target_path: Path, new_code: str) -> tuple[bool, str]:
    """
    Write new_code to target_path after:
    1. Quarantining the original.
    2. Verifying the new code compiles.
    3. Rolling back via git if compilation fails.

    Returns (success, message).
    """
    if len(new_code.encode()) > MAX_PATCH_SIZE:
        return False, f"Patch too large ({len(new_code.encode())} bytes > {MAX_PATCH_SIZE})"

    if not target_path.exists():
        return False, f"Target file not found: {target_path}"

    # Deep safety validation before touching disk
    safe, reason = _patch_is_safe(new_code, target_path)
    if not safe:
        logger.warning("SelfHealer: patch safety check failed for %s: %s", target_path, reason)
        return False, f"Safety check failed: {reason}"

    # Quarantine original
    _quarantine(target_path)

    # Write new code atomically
    tmp = target_path.with_suffix(".heal_tmp")
    try:
        tmp.write_text(new_code, encoding="utf-8")
    except OSError as exc:
        return False, f"Write failed: {exc}"

    # Compile check
    if not _import_ok(tmp):
        tmp.unlink(missing_ok=True)
        return False, "New code has syntax errors — patch rejected"

    # Atomic replace
    tmp.replace(target_path)

    # Post-apply compile check on the real path
    if not _import_ok(target_path):
        logger.warning("SelfHealer: post-apply compile failed, rolling back %s", target_path)
        _git_rollback(target_path)
        return False, "Post-apply compile failed — rolled back via git"

    return True, "Patch applied successfully"


# ── Diff generator ────────────────────────────────────────────────────────────


def _unified_diff(original: str, patched: str, filename: str) -> str:
    lines_a = original.splitlines(keepends=True)
    lines_b = patched.splitlines(keepends=True)
    diff = difflib.unified_diff(lines_a, lines_b, fromfile=f"a/{filename}", tofile=f"b/{filename}")
    return "".join(diff)


# ── SelfHealer ────────────────────────────────────────────────────────────────


class SelfHealer:
    """
    Autonomous code integrity monitor and patch applier.

    Runtime-configurable via the SuperAdmin Auto-Healing panel.
    All config attributes can be hot-patched by api/superadmin/auto_healing.py
    without restarting the process.

    Usage::

        healer = SelfHealer()
        _t = asyncio.create_task(healer.run())
        _t.add_done_callback(lambda _: None)
        healer.mount_router(app)
    """

    def __init__(self) -> None:
        self._baseline: dict[str, str] = {}
        self._drift_events: list[dict[str, Any]] = []
        self._patch_history: list[dict[str, Any]] = []
        self._quarantine_log: list[dict[str, Any]] = []
        self._running = False

        # ── Runtime-configurable settings (hot-patched by auto_healing.py) ──
        self._enabled: bool = True
        self._aggressiveness: str = "medium"  # low|medium|aggressive|nuclear
        self._quarantine_enabled: bool = True
        self._quarantine_retention_days: int = 30
        self._max_patch_size: int = MAX_PATCH_SIZE
        self._auto_rollback_sensitivity: str = "medium"  # low|medium|high
        self._max_healing_attempts: int = 3
        self._healing_cooldown_sec: int = 300
        self._log_level: str = "standard"  # minimal|standard|verbose|debug
        self._protected_paths: list[str] = [
            # Core live-trading execution files — must never be auto-patched
            "live_trading.py",
            "hopefx_engine.py",
            "execution/engine.py",
            "execution/order_gateway.py",
            "execution/trade_executor.py",
            "execution/paper_runner.py",
            "execution/broker_circuit_breaker.py",
            "execution/position_tracker.py",
            "execution/fill_processor.py",
            # Risk and kill-switch — safety-critical
            "risk_manager.py",
            "risk/manager.py",
            "risk/pre_trade_gate.py",
            "risk/gatekeeper.py",
            "risk/circuit_breakers.py",
            "risk/position_sizer.py",
            "kill_switch.py",
            # Resilience — circuit breakers protect live order flow
            "resilience/service_circuit_breakers.py",
            "core/live_trading_gate.py",
            # Auth — credential and session security
            "auth/jwt.py",
            "auth/service.py",
            "auth/dependencies.py",
            # ML model artifacts and config secrets
            "ml/models/",
            "config/secrets/",
            # Broker connectors — live order routing
            "brokers/paper_trading.py",
            "brokers/oanda_broker.py",
            "brokers/mt5_broker.py",
            "brokers/ibkr_connector.py",
            "brokers/base_broker.py",
            # Data feed — price integrity
            "data_feed/engine.py",
            "data_feed/mt5_backup.py",
        ]
        self._tests_enabled: bool = True
        self._test_categories: dict[str, bool] = {
            "unit": True,
            "api": True,
            "broker": True,
            "risk": True,
            "ml": True,
            "security": True,
            "performance": False,
            "e2e": False,
        }
        self._test_execution_strategy: list[str] = ["after_patch", "on_drift"]
        self._test_timeout_sec: int = 120
        self._global_test_timeout_sec: int = 600
        self._parallel_tests: bool = True
        self._require_approval_categories: list[str] = ["nuclear", "e2e"]
        self._baseline_auto_rebuild: bool = True

        # ── Internal state ────────────────────────────────────────────────────
        self._incident_attempts: dict[str, int] = {}  # file → attempt count
        self._last_heal_ts: dict[str, float] = {}  # file → epoch of last heal
        self._last_test_run_ts: float = 0.0
        self._last_test_result: dict[str, Any] = {}

        # ── Deep code analysis state ──────────────────────────────────────────
        self._code_issues: list[dict[str, Any]] = []  # last scan results
        self._last_code_scan_ts: float = 0.0
        self._code_scan_interval: int = int(os.getenv("HEAL_CODE_SCAN_INTERVAL", "300"))  # 5 min
        self._log_scan_interval: int = int(os.getenv("HEAL_LOG_SCAN_INTERVAL", "60"))  # 1 min
        self._last_log_scan_ts: float = 0.0
        self._log_issues: list[dict[str, Any]] = []  # recent log errors
        self._claude_fix_queue: list[dict[str, Any]] = []  # pending Claude fixes

        # ── Advanced diagnostics engine state ─────────────────────────────────
        self._diag_interval: int = int(os.getenv("HEAL_DIAG_INTERVAL", "300"))  # 5 min
        self._last_diag_ts: float = 0.0
        self._last_diag_report: dict[str, Any] = {}
        self._diag_remediation_log: list[dict[str, Any]] = []

        # Ensure all log output goes to logs/app.log
        _ensure_file_logging()

    def _log(self, level: str, msg: str, *args: Any) -> None:
        """Respect _log_level: minimal suppresses INFO, debug emits everything."""
        lvl_order = {"minimal": 0, "standard": 1, "verbose": 2, "debug": 3}
        msg_order = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
        threshold = lvl_order.get(self._log_level, 1)
        msg_lvl = msg_order.get(level, 1)
        if msg_lvl == 0 and threshold < 3:
            return
        if msg_lvl == 1 and threshold == 0:
            return
        getattr(logger, level)(msg, *args)

    def _is_protected(self, rel_path: str) -> bool:
        """Return True if rel_path matches any protected path prefix/pattern."""
        norm = rel_path.replace("\\", "/")
        for raw_p in self._protected_paths:
            p = raw_p.strip()
            if not p:
                continue
            if norm == p or norm.startswith(p.rstrip("/") + "/") or norm.endswith(p):
                return True
        return False

    def _cooldown_ok(self, file_key: str) -> bool:
        """Return True if enough time has passed since the last heal on this file."""
        last = self._last_heal_ts.get(file_key, 0.0)
        import time

        return (time.time() - last) >= self._healing_cooldown_sec

    def _attempts_ok(self, file_key: str) -> bool:
        """Return True if we haven't exceeded max healing attempts for this file."""
        return self._incident_attempts.get(file_key, 0) < self._max_healing_attempts

    def _record_heal_attempt(self, file_key: str) -> None:
        import time

        self._incident_attempts[file_key] = self._incident_attempts.get(file_key, 0) + 1
        self._last_heal_ts[file_key] = time.time()

    def apply_config(self, cfg: dict[str, Any]) -> None:
        """Hot-apply a config dict from the SuperAdmin panel."""
        self._enabled = bool(cfg.get("enabled", self._enabled))
        self._aggressiveness = str(cfg.get("aggressiveness", self._aggressiveness))
        self._quarantine_enabled = bool(cfg.get("quarantine_enabled", self._quarantine_enabled))
        self._quarantine_retention_days = int(cfg.get("quarantine_retention_days", self._quarantine_retention_days))
        self._max_patch_size = int(cfg.get("max_patch_bytes", self._max_patch_size))
        self._auto_rollback_sensitivity = str(cfg.get("auto_rollback_sensitivity", self._auto_rollback_sensitivity))
        self._max_healing_attempts = int(cfg.get("max_healing_attempts", self._max_healing_attempts))
        self._healing_cooldown_sec = int(cfg.get("healing_cooldown_sec", self._healing_cooldown_sec))
        self._log_level = str(cfg.get("log_level", self._log_level))
        self._tests_enabled = bool(cfg.get("tests_enabled", self._tests_enabled))
        self._test_categories = dict(cfg.get("test_categories", self._test_categories))
        self._test_execution_strategy = list(cfg.get("test_execution_strategy", self._test_execution_strategy))
        self._test_timeout_sec = int(cfg.get("test_timeout_sec", self._test_timeout_sec))
        self._global_test_timeout_sec = int(cfg.get("global_test_timeout_sec", self._global_test_timeout_sec))
        self._parallel_tests = bool(cfg.get("parallel_tests", self._parallel_tests))
        self._require_approval_categories = list(
            cfg.get("require_approval_categories", self._require_approval_categories)
        )
        self._baseline_auto_rebuild = bool(cfg.get("baseline_auto_rebuild", self._baseline_auto_rebuild))
        raw_paths = cfg.get("protected_paths", "")
        if isinstance(raw_paths, str):
            self._protected_paths = [p.strip() for p in raw_paths.split(",") if p.strip()]
        elif isinstance(raw_paths, list):
            self._protected_paths = list(raw_paths)
        # Propagate to module-level constants used by helpers
        global HEAL_SCAN_INTERVAL, HEAL_PATCH_INTERVAL, MAX_PATCH_SIZE
        HEAL_SCAN_INTERVAL = int(cfg.get("scan_interval_sec", HEAL_SCAN_INTERVAL))
        HEAL_PATCH_INTERVAL = int(cfg.get("patch_interval_sec", HEAL_PATCH_INTERVAL))
        MAX_PATCH_SIZE = self._max_patch_size
        self._log(
            "info", "SelfHealer: config applied — aggressiveness=%s enabled=%s", self._aggressiveness, self._enabled
        )

    def get_full_status(self) -> dict[str, Any]:
        """Return a rich status dict for the SuperAdmin panel."""
        import time

        applied = sum(1 for p in self._patch_history if p.get("success"))
        failed = sum(1 for p in self._patch_history if not p.get("success"))
        last_scan = self._drift_events[-1]["ts"] if self._drift_events else None
        cooldowns = {
            k: max(0, int(self._healing_cooldown_sec - (time.time() - v)))
            for k, v in self._last_heal_ts.items()
            if (time.time() - v) < self._healing_cooldown_sec
        }
        code_critical = sum(1 for i in self._code_issues if i.get("severity") == "critical")
        code_high = sum(1 for i in self._code_issues if i.get("severity") == "high")
        log_errors = sum(1 for i in self._log_issues if i.get("level") in ("ERROR", "CRITICAL"))

        return {
            "running": self._running,
            "enabled": self._enabled,
            "aggressiveness": self._aggressiveness,
            "baseline_files": len(self._baseline),
            "drift_events": len(self._drift_events),
            "drift_events_recent": self._drift_events[-20:],
            "patches_applied": applied,
            "patches_failed": failed,
            "patch_history_recent": self._patch_history[-20:],
            "quarantine_log_recent": self._quarantine_log[-20:],
            "last_scan": last_scan,
            "last_test_run": self._last_test_result.get("ts"),
            "last_test_passed": self._last_test_result.get("passed"),
            "last_test_failed": self._last_test_result.get("failed"),
            "active_cooldowns": cooldowns,
            "incident_attempts": dict(self._incident_attempts),
            "protected_paths": self._protected_paths,
            "tests_enabled": self._tests_enabled,
            "test_execution_strategy": self._test_execution_strategy,
            # Deep analysis
            "code_issues_total": len(self._code_issues),
            "code_issues_critical": code_critical,
            "code_issues_high": code_high,
            "last_code_scan": datetime.fromtimestamp(self._last_code_scan_ts, UTC).isoformat()
            if self._last_code_scan_ts
            else None,
            "log_issues_total": len(self._log_issues),
            "log_errors_recent": log_errors,
            "last_log_scan": datetime.fromtimestamp(self._last_log_scan_ts, UTC).isoformat()
            if self._last_log_scan_ts
            else None,
            "claude_fix_queue_depth": len(self._claude_fix_queue),
            "log_file": str(_LOG_FILE),
            # Advanced diagnostics
            "last_diag_ts": datetime.fromtimestamp(self._last_diag_ts, UTC).isoformat() if self._last_diag_ts else None,
            "diag_has_critical": self._last_diag_report.get("has_critical", False),
            "diag_has_errors": self._last_diag_report.get("has_errors", False),
            "diag_counts": self._last_diag_report.get("counts", {}),
            "diag_remediation_actions": len(self._diag_remediation_log),
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main loop: integrity scan + patch drain, running forever."""
        self._running = True
        # Load saved config from disk/Redis before starting loops
        await self._load_saved_config()
        await self._ensure_baseline()
        self._log(
            "info",
            "SelfHealer: started — tracking %d files, scan=%ds patch=%ds aggressiveness=%s",
            len(self._baseline),
            HEAL_SCAN_INTERVAL,
            HEAL_PATCH_INTERVAL,
            self._aggressiveness,
        )
        scan_task = asyncio.create_task(self._scan_loop(), name="heal-scan")
        patch_task = asyncio.create_task(self._patch_loop(), name="heal-patch")
        sched_task = asyncio.create_task(self._scheduled_test_loop(), name="heal-test-sched")
        code_task = asyncio.create_task(self._code_analysis_loop(), name="heal-code-analysis")
        log_task = asyncio.create_task(self._log_analysis_loop(), name="heal-log-analysis")
        claude_task = asyncio.create_task(self._claude_fix_loop(), name="heal-claude-fix")
        diag_task = asyncio.create_task(self._diagnostics_loop(), name="heal-diagnostics")
        await asyncio.gather(scan_task, patch_task, sched_task, code_task, log_task, claude_task, diag_task)

    async def _load_saved_config(self) -> None:
        """Pull config saved by the SuperAdmin panel and apply it."""
        try:
            import json as _json

            cfg_path = PROJECT_ROOT / "data" / "auto_healing_config.json"
            if cfg_path.exists():
                cfg = _json.loads(cfg_path.read_text())
                self.apply_config(cfg)
                return
        except Exception as exc:
            logger.debug("SelfHealer: disk config load: %s", exc)
        try:
            redis = await _get_redis()
            if redis:
                raw = await redis.get("superadmin:auto_healing:config")
                if raw:
                    import json as _json

                    self.apply_config(_json.loads(raw))
        except Exception as exc:
            logger.debug("SelfHealer: redis config load: %s", exc)

    async def _ensure_baseline(self) -> None:
        """Load or build the file integrity baseline."""
        stored = _load_manifest()
        if stored:
            self._baseline = stored
            logger.info("SelfHealer: loaded baseline (%d files)", len(stored))
        else:
            self._baseline = _build_manifest()
            _save_manifest(self._baseline)
            logger.info("SelfHealer: built new baseline (%d files)", len(self._baseline))

        # Also persist to Redis for cross-pod access
        redis = await _get_redis()
        if redis:
            try:
                await redis.set("heal:manifest", json.dumps(self._baseline))
            except Exception as exc:
                logger.debug("SelfHealer: Redis manifest write failed: %s", exc)

    # ── Integrity scan loop ───────────────────────────────────────────────────

    async def _scan_loop(self) -> None:
        while self._running:
            try:
                if self._enabled:
                    await self._scan_integrity()
                else:
                    self._log("debug", "SelfHealer: scan skipped — disabled")
            except Exception as exc:
                logger.warning("SelfHealer: scan error: %s", exc)
            await asyncio.sleep(HEAL_SCAN_INTERVAL)

    async def _scan_integrity(self) -> None:
        """Compare current file hashes against baseline; flag drift."""
        current = _build_manifest()
        drift: list[dict[str, Any]] = []
        ts_now = datetime.now(UTC).isoformat()

        for rel_path, expected_hash in self._baseline.items():
            actual_hash = current.get(rel_path, "")
            if not actual_hash:
                drift.append(
                    {"path": rel_path, "type": "deleted", "ts": ts_now, "protected": self._is_protected(rel_path)}
                )
            elif actual_hash != expected_hash:
                drift.append(
                    {
                        "path": rel_path,
                        "type": "modified",
                        "ts": ts_now,
                        "expected": expected_hash[:16],
                        "actual": actual_hash[:16],
                        "protected": self._is_protected(rel_path),
                    }
                )

        for rel_path in current:
            if rel_path not in self._baseline:
                drift.append(
                    {"path": rel_path, "type": "new_file", "ts": ts_now, "protected": self._is_protected(rel_path)}
                )

        if drift:
            self._log("warning", "SelfHealer: %d drift event(s) detected", len(drift))
            self._drift_events.extend(drift)
            self._drift_events = self._drift_events[-500:]
            await self._push_drift_alerts(drift)
            # Persist drift log to Redis for the dashboard
            await self._persist_drift_to_redis()
            # Trigger tests if strategy includes on_drift
            if self._tests_enabled and "on_drift" in self._test_execution_strategy:
                asyncio.create_task(self._run_tests(trigger="on_drift"))

    async def _push_drift_alerts(self, drift: list[dict[str, Any]]) -> None:
        """Push drift events to alerts:critical.

        Only genuinely suspicious events are escalated to the critical alert
        queue to avoid flooding it with expected changes during development or
        deployment:
          - Any drift on a *protected* path → always critical
          - ``deleted`` or ``new_file`` on any tracked path → critical
          - ``modified`` on a non-protected path → dashboard log only
        """
        redis = await _get_redis()
        if not redis:
            return
        try:
            critical_events = [
                e for e in drift
                if e.get("protected")
                or e.get("type") in ("deleted", "new_file")
            ]
            for event in critical_events:
                await redis.rpush(
                    "alerts:critical",
                    json.dumps(
                        {
                            "type": "file_integrity_drift",
                            "ip": "internal",
                            "ts": event["ts"],
                            "detail": event,
                        }
                    ),
                )
            if critical_events:
                await redis.ltrim("alerts:critical", -1000, -1)
        except Exception as exc:
            logger.debug("SelfHealer: alert push failed: %s", exc)

    async def _persist_drift_to_redis(self) -> None:
        """Write the in-memory drift log to Redis so the dashboard can read it."""
        redis = await _get_redis()
        if not redis:
            return
        with contextlib.suppress(Exception):
            await redis.set(
                "heal:drift_events",
                json.dumps(self._drift_events[-200:]),
                ex=86400,
            )

    # ── Patch drain loop ──────────────────────────────────────────────────────

    async def _patch_loop(self) -> None:
        while self._running:
            try:
                if self._enabled and self._aggressiveness != "low":
                    await self._drain_approved_patches()
                else:
                    self._log("debug", "SelfHealer: patch loop skipped — disabled or low aggressiveness")
            except Exception as exc:
                logger.warning("SelfHealer: patch drain error: %s", exc)
            await asyncio.sleep(HEAL_PATCH_INTERVAL)

    async def _drain_approved_patches(self) -> None:
        """Apply all approved fixes from fixes:approved queue with full safety gates."""
        redis = await _get_redis()
        if not redis:
            return

        try:
            raw_entries = await redis.lrange("fixes:approved", 0, -1)
        except Exception as exc:
            logger.debug("SelfHealer: Redis lrange failed: %s", exc)
            return

        if not raw_entries:
            return

        applied: list[str] = []
        for raw in raw_entries:
            try:
                fix: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # ── Trust gate: verify HMAC signature ────────────────────────
            if not _patch_entry_is_trusted(raw, fix):
                self._log("error", "SelfHealer: untrusted patch entry rejected — possible Redis injection")
                with contextlib.suppress(Exception):
                    await redis.lrem("fixes:approved", 1, raw)
                continue

            endpoint = fix.get("endpoint", "")
            new_code = fix.get("fix", "")
            if not endpoint or not new_code:
                continue

            target = self._resolve_endpoint_to_file(endpoint)
            if target is None:
                self._log("warning", "SelfHealer: cannot resolve endpoint to file: %s", endpoint)
                continue

            rel_path = str(target.relative_to(PROJECT_ROOT))

            # ── Safety gate: protected paths ──────────────────────────────
            if self._is_protected(rel_path):
                self._log("warning", "SelfHealer: BLOCKED patch on protected path %s", rel_path)
                record = self._make_patch_record(
                    endpoint,
                    rel_path,
                    False,
                    f"Blocked — protected path: {rel_path}",
                    "",
                )
                self._store_patch_record(record)
                with contextlib.suppress(Exception):
                    await redis.rpush("heal:patch_history", json.dumps(record))
                    await redis.ltrim("heal:patch_history", -200, -1)
                continue

            # ── Safety gate: cooldown ─────────────────────────────────────
            if not self._cooldown_ok(rel_path):
                self._log("info", "SelfHealer: cooldown active for %s, skipping", rel_path)
                continue

            # ── Safety gate: max attempts ─────────────────────────────────
            if not self._attempts_ok(rel_path):
                self._log(
                    "warning", "SelfHealer: max attempts (%d) reached for %s", self._max_healing_attempts, rel_path
                )
                continue

            # ── Safety gate: approval required ───────────────────────────
            fix_category = fix.get("category", "")
            if fix_category in self._require_approval_categories and self._aggressiveness != "nuclear":
                self._log("info", "SelfHealer: patch for %s requires approval (category=%s)", rel_path, fix_category)
                with contextlib.suppress(Exception):
                    await redis.rpush(
                        "heal:pending_approval",
                        json.dumps(
                            {
                                **fix,
                                "queued_at": datetime.now(UTC).isoformat(),
                            }
                        ),
                    )
                    await redis.ltrim("heal:pending_approval", -100, -1)
                continue

            # ── Run pre-patch tests ───────────────────────────────────────
            if self._tests_enabled and "before_patch" in self._test_execution_strategy:
                pre_ok = await self._run_tests(trigger="before_patch")
                if not pre_ok and self._auto_rollback_sensitivity in ("medium", "high"):
                    self._log("warning", "SelfHealer: pre-patch tests failed for %s — skipping patch", rel_path)
                    continue

            original_code = ""
            if target.exists():
                original_code = target.read_text(encoding="utf-8", errors="replace")

            success, msg = _apply_patch(target, new_code)
            diff = _unified_diff(original_code, new_code, target.name) if success else ""
            record = self._make_patch_record(endpoint, rel_path, success, msg, diff)
            self._store_patch_record(record)
            self._record_heal_attempt(rel_path)

            if success:
                applied.append(raw)
                self._baseline[rel_path] = _sha256(target)
                _save_manifest(self._baseline)
                self._log("info", "SelfHealer: patch applied to %s", target)

                # ── Run post-patch tests ──────────────────────────────────
                if self._tests_enabled and "after_patch" in self._test_execution_strategy:
                    post_ok = await self._run_tests(trigger="after_patch")
                    if not post_ok and self._auto_rollback_sensitivity != "low":
                        self._log("warning", "SelfHealer: post-patch tests failed — rolling back %s", rel_path)
                        _git_rollback(target)
                        self._baseline[rel_path] = _sha256(target)
                        _save_manifest(self._baseline)
                        record["message"] += " | ROLLED BACK: post-patch tests failed"
                        record["success"] = False

                # Auto-rebuild baseline if configured
                if self._baseline_auto_rebuild:
                    self._baseline[rel_path] = _sha256(target)
            else:
                self._log("warning", "SelfHealer: patch rejected for %s: %s", endpoint, msg)

            with contextlib.suppress(Exception):
                await redis.rpush("heal:patch_history", json.dumps(record))
                await redis.ltrim("heal:patch_history", -200, -1)

        for raw in applied:
            with contextlib.suppress(Exception):
                await redis.lrem("fixes:approved", 1, raw)

    def _make_patch_record(
        self,
        endpoint: str,
        rel_path: str,
        success: bool,
        msg: str,
        diff: str,
    ) -> dict[str, Any]:
        return {
            "endpoint": endpoint,
            "file": rel_path,
            "success": success,
            "message": msg,
            "diff": diff,
            "applied_at": datetime.now(UTC).isoformat(),
        }

    def _store_patch_record(self, record: dict[str, Any]) -> None:
        self._patch_history.append(record)
        self._patch_history = self._patch_history[-200:]

    # ── Test runner ───────────────────────────────────────────────────────────

    async def _scheduled_test_loop(self) -> None:
        """Run tests on schedule if 'on_schedule' is in the execution strategy."""
        while self._running:
            await asyncio.sleep(60)  # check every minute
            if not self._enabled or not self._tests_enabled:
                continue
            if "on_schedule" not in self._test_execution_strategy:
                continue
            import time

            interval_sec = getattr(self, "_test_schedule_interval_min", 60) * 60
            if (time.time() - self._last_test_run_ts) >= interval_sec:
                asyncio.create_task(self._run_tests(trigger="on_schedule"))

    # ── Deep code analysis loop ───────────────────────────────────────────────

    async def _code_analysis_loop(self) -> None:
        """Periodically scan the entire codebase for code quality issues."""
        while self._running:
            await asyncio.sleep(self._code_scan_interval)
            if not self._enabled:
                continue
            try:
                await self._run_code_analysis()
            except Exception as exc:
                logger.warning("SelfHealer: code analysis error: %s", exc)

    async def _run_code_analysis(self) -> list[dict[str, Any]]:
        """
        Run deep static analysis on the codebase using code_analyzer.

        Detects: look-ahead bias, unfinished code, NaN leaks, division-by-zero,
        broken routers, missing error handling, TODO/FIXME, hardcoded secrets,
        synthetic data in production paths.

        Results are stored in self._code_issues and pushed to Redis.
        Critical issues are enqueued for Claude-powered fixes.
        """
        loop = asyncio.get_running_loop()
        try:
            from security.code_analyzer import scan_codebase, summarize_issues
        except ImportError:
            logger.warning("SelfHealer: code_analyzer not available — skipping deep scan")
            return []

        self._log("info", "SelfHealer: starting deep code analysis scan")
        try:
            issues = await loop.run_in_executor(
                None,
                lambda: scan_codebase(include_tests=False, max_files=2000),
            )
        except Exception as exc:
            logger.warning("SelfHealer: code scan failed: %s", exc)
            return []

        self._code_issues = [i.to_dict() for i in issues]
        self._last_code_scan_ts = time.time()

        summary = summarize_issues(issues)
        self._log(
            "info" if summary["total"] == 0 else "warning",
            "SelfHealer: code analysis complete — %d issues (%d critical, %d high)",
            summary["total"],
            summary["by_severity"].get("critical", 0),
            summary["by_severity"].get("high", 0),
        )

        # Persist to Redis for dashboard
        redis = await _get_redis()
        if redis:
            with contextlib.suppress(Exception):
                await redis.set(
                    "heal:code_issues",
                    json.dumps({"summary": summary, "issues": self._code_issues[:200]}),
                    ex=3600,
                )

        # Enqueue critical issues for Claude-powered fixes
        critical = [i for i in issues if i.severity == "critical"]
        for issue in critical[:10]:  # cap at 10 per scan to avoid flooding
            await self._enqueue_claude_fix(issue.to_dict())

        return self._code_issues

    # ── Log file analysis loop ────────────────────────────────────────────────

    async def _log_analysis_loop(self) -> None:
        """Periodically read logs/app.log and extract runtime errors."""
        while self._running:
            await asyncio.sleep(self._log_scan_interval)
            if not self._enabled:
                continue
            try:
                await self._run_log_analysis()
            except Exception as exc:
                logger.debug("SelfHealer: log analysis error: %s", exc)

    async def _run_log_analysis(self) -> list[dict[str, Any]]:
        """
        Parse logs/app.log for recent ERROR/CRITICAL/WARNING entries.

        Detected runtime issues are stored in self._log_issues and pushed
        to Redis. Repeated errors trigger Claude-powered fix requests.
        """
        loop = asyncio.get_running_loop()
        try:
            from security.code_analyzer import analyze_log_file
        except ImportError:
            return []

        try:
            log_issues = await loop.run_in_executor(
                None,
                lambda: analyze_log_file(since_minutes=10),
            )
        except Exception as exc:
            logger.debug("SelfHealer: log file read failed: %s", exc)
            return []

        if not log_issues:
            return []

        self._log_issues = [i.to_dict() for i in log_issues]
        self._last_log_scan_ts = time.time()

        errors = [i for i in log_issues if i.level in ("ERROR", "CRITICAL")]
        if errors:
            self._log(
                "warning",
                "SelfHealer: log analysis found %d ERROR/CRITICAL entries in last 10 min",
                len(errors),
            )

        # Push to Redis for dashboard
        redis = await _get_redis()
        if redis:
            with contextlib.suppress(Exception):
                await redis.set(
                    "heal:log_issues",
                    json.dumps(self._log_issues[-100:]),
                    ex=600,
                )
            # Also push to alerts:critical for severe entries
            for issue in errors[:5]:
                with contextlib.suppress(Exception):
                    await redis.rpush(
                        "alerts:critical",
                        json.dumps(
                            {
                                "type": "runtime_error",
                                "ts": issue.to_dict()["timestamp"],
                                "detail": issue.to_dict(),
                            }
                        ),
                    )
                    await redis.ltrim("alerts:critical", -1000, -1)

        # Enqueue repeated errors for Claude analysis
        error_messages = [i.message for i in errors]
        seen_msgs: dict[str, int] = {}
        for msg in error_messages:
            # Normalise: strip timestamps/IDs for dedup
            key = msg[:100]
            seen_msgs[key] = seen_msgs.get(key, 0) + 1

        for msg, count in seen_msgs.items():
            if count >= 2:  # repeated error → worth fixing
                await self._enqueue_claude_fix(
                    {
                        "category": "runtime_error",
                        "severity": "critical",
                        "description": f"Repeated runtime error ({count}x in 10 min): {msg}",
                        "file": "logs/app.log",
                        "line": 0,
                        "snippet": msg,
                        "suggestion": "Investigate the root cause and add proper error handling",
                    }
                )

        return self._log_issues

    # ── Claude-powered fix loop ───────────────────────────────────────────────

    async def _enqueue_claude_fix(self, issue: dict[str, Any]) -> None:
        """Add an issue to the Claude fix queue (deduplicates by file+line+category)."""
        key = f"{issue.get('file', '')}:{issue.get('line', 0)}:{issue.get('category', '')}"
        # Avoid duplicate entries
        existing_keys = {
            f"{e.get('file', '')}:{e.get('line', 0)}:{e.get('category', '')}": True for e in self._claude_fix_queue
        }
        if key not in existing_keys:
            self._claude_fix_queue.append({**issue, "queued_at": datetime.now(UTC).isoformat()})
            self._claude_fix_queue = self._claude_fix_queue[-50:]  # cap queue

    async def _claude_fix_loop(self) -> None:
        """Drain the Claude fix queue and generate production-ready patches."""
        while self._running:
            await asyncio.sleep(30)  # check every 30 seconds
            if not self._enabled or not self._claude_fix_queue:
                continue
            if self._aggressiveness not in ("aggressive", "nuclear"):
                # Only auto-apply Claude fixes in aggressive/nuclear mode
                continue
            try:
                await self._process_claude_fix_queue()
            except Exception as exc:
                logger.warning("SelfHealer: Claude fix loop error: %s", exc)

    async def _process_claude_fix_queue(self) -> None:
        """
        Process pending issues with Claude (Anthropic API).

        For each issue:
        1. Read the affected file
        2. Send file + issue description to Claude
        3. Parse the fix from Claude's response
        4. Apply via _apply_patch() with full safety gates
        5. Record result in patch history
        """
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            self._log("debug", "SelfHealer: ANTHROPIC_API_KEY not set — Claude fixes disabled")
            self._claude_fix_queue.clear()
            return

        loop = asyncio.get_running_loop()

        while self._claude_fix_queue:
            issue = self._claude_fix_queue.pop(0)
            file_rel = issue.get("file", "")
            if not file_rel or file_rel == "logs/app.log":
                continue

            target = PROJECT_ROOT / file_rel
            if not target.exists():
                continue

            # Read the file
            try:
                source = target.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("SelfHealer: cannot read %s for Claude fix: %s", file_rel, exc)
                continue

            # Safety gate: protected paths
            if self._is_protected(file_rel):
                self._log("warning", "SelfHealer: Claude fix blocked on protected path %s", file_rel)
                continue

            # Safety gate: cooldown
            if not self._cooldown_ok(file_rel):
                continue

            self._log("info", "SelfHealer: requesting Claude fix for %s (issue: %s)", file_rel, issue.get("category"))

            try:
                fixed_code = await loop.run_in_executor(
                    None,
                    lambda: self._call_claude_for_fix(source, issue, api_key),
                )
            except Exception as exc:
                logger.warning("SelfHealer: Claude API call failed for %s: %s", file_rel, exc)
                continue

            if not fixed_code or fixed_code == source:
                self._log("info", "SelfHealer: Claude returned no changes for %s", file_rel)
                continue

            # Apply the fix with full safety gates
            success, msg = _apply_patch(target, fixed_code)
            diff = _unified_diff(source, fixed_code, target.name) if success else ""
            record = self._make_patch_record(
                f"claude:{issue.get('category', 'unknown')}",
                file_rel,
                success,
                f"Claude fix: {msg}",
                diff,
            )
            self._store_patch_record(record)
            self._record_heal_attempt(file_rel)

            if success:
                self._baseline[file_rel] = _sha256(target)
                _save_manifest(self._baseline)
                self._log("info", "SelfHealer: Claude fix applied to %s", file_rel)

                # Run post-patch tests
                if self._tests_enabled and "after_patch" in self._test_execution_strategy:
                    post_ok = await self._run_tests(trigger="claude_fix")
                    if not post_ok and self._auto_rollback_sensitivity != "low":
                        self._log("warning", "SelfHealer: post-Claude-fix tests failed — rolling back %s", file_rel)
                        _git_rollback(target)
                        self._baseline[file_rel] = _sha256(target)
                        _save_manifest(self._baseline)
            else:
                self._log("warning", "SelfHealer: Claude fix rejected for %s: %s", file_rel, msg)

            # Persist to Redis
            redis = await _get_redis()
            if redis:
                with contextlib.suppress(Exception):
                    await redis.rpush("heal:patch_history", json.dumps(record))
                    await redis.ltrim("heal:patch_history", -200, -1)

            # Rate limit: one fix per 5 seconds
            await asyncio.sleep(5)

    @staticmethod
    def _call_claude_for_fix(source: str, issue: dict[str, Any], api_key: str) -> str:
        """
        Call the Anthropic Claude API to generate a production-ready fix.

        Returns the complete fixed file content, or empty string on failure.
        This is a synchronous function run in an executor.
        """
        try:
            import anthropic
        except ImportError:
            logger.warning("SelfHealer: anthropic package not installed — pip install anthropic")
            return ""

        category = issue.get("category", "unknown")
        description = issue.get("description", "")
        line = issue.get("line", 0)
        snippet = issue.get("snippet", "")
        suggestion = issue.get("suggestion", "")
        file_path = issue.get("file", "unknown")

        # Truncate source to fit context window (keep first 250 + last 150 lines around issue)
        lines = source.splitlines()
        if len(lines) > 400:
            # Keep lines around the issue for context
            issue_line = max(0, line - 1)
            start = max(0, issue_line - 50)
            end = min(len(lines), issue_line + 100)
            context_lines = (
                lines[:50]
                + (["# ... (truncated) ..."] if start > 50 else [])
                + lines[start:end]
                + (["# ... (truncated) ..."] if end < len(lines) - 50 else [])
                + lines[-50:]
            )
            source_for_prompt = "\n".join(context_lines)
        else:
            source_for_prompt = source

        # Category-specific guidance for Claude
        _category_guidance: dict[str, str] = {
            "lookahead_bias": (
                "CRITICAL: Look-ahead bias corrupts backtests and live trading by using future data. "
                "Replace shift(-N) with shift(+N) to use past data. Never use negative shifts in "
                "feature engineering, signal generation, or any ML pipeline."
            ),
            "nan_leak": (
                "NaN values propagate silently through calculations, producing incorrect signals. "
                "Add .dropna() before aggregations, or use .fillna(0) / np.nan_to_num() to handle "
                "NaN explicitly. Ensure the fix does not introduce data leakage."
            ),
            "division_by_zero": (
                "Division by zero crashes the process. Add a guard: use max(denominator, epsilon) "
                "where epsilon is a small positive float (e.g. 1e-8), or check denominator != 0 "
                "before dividing. Use np.where() for vectorised operations."
            ),
            "unfinished_code": (
                "Implement the function fully. No pass, no ..., no TODO, no raise NotImplementedError. "
                "The implementation must be production-ready and handle all edge cases."
            ),
            "hardcoded_secret": (
                "Move the credential to an environment variable. Use os.getenv('VAR_NAME') or "
                "python-dotenv. Never commit secrets to source control."
            ),
            "synthetic_data": (
                "Replace mock/synthetic/dummy data with a real data source. "
                "If the real source is unavailable, raise a clear RuntimeError rather than "
                "silently returning fake data that could corrupt trading decisions."
            ),
            "broken_router": (
                "Register the router in core/router_registry.py using _include_router_deduped(). "
                "Ensure the import is correct and the router prefix does not conflict."
            ),
            "swallowed_exception": (
                "Log the exception with logger.exception() or logger.error() and either re-raise "
                "or return a safe default. Never silently discard exceptions in trading code."
            ),
        }
        extra_guidance = _category_guidance.get(category, "")

        prompt = f"""FILE: {file_path}
ISSUE CATEGORY: {category}
SEVERITY: {issue.get("severity", "unknown")}
LINE: {line}
DESCRIPTION: {description}
OFFENDING CODE: {snippet}
SUGGESTED FIX: {suggestion}
{f"ADDITIONAL GUIDANCE: {extra_guidance}" if extra_guidance else ""}

Complete file content:

```python
{source_for_prompt}
```

Rules:
1. Fix ONLY the specific issue described above — do not refactor unrelated code
2. No mocks, no stubs, no TODO comments, no pass-only bodies, no synthetic data
3. All error paths must log with logger.exception() or logger.error()
4. Return ONLY the complete fixed Python file — no explanation, no markdown fences
5. The returned code must be syntactically valid Python and importable

Return the complete fixed file:"""

        try:
            # Prefer the env-configured model; fall back to claude-opus-4-5
            model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=16384,
                system=(
                    "You are an expert Python engineer specialising in production-grade "
                    "financial trading systems. You write clean, robust, fully-implemented "
                    "code with no stubs, no TODO comments, no mock data, and no pass-only "
                    "function bodies. Every fix you produce must be immediately deployable."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            fixed = response.content[0].text.strip()
            # Strip markdown code fences if Claude wrapped the response
            for fence in ("```python\n", "```py\n", "```\n"):
                if fixed.startswith(fence):
                    fixed = fixed[len(fence) :]
                    break
            if fixed.endswith("```"):
                fixed = fixed[:-3]
            return fixed.strip()
        except Exception as exc:
            logger.warning("SelfHealer: Claude API error: %s — trying llm_wrapper fallback", exc)
            # Fallback: try the shared llm_wrapper (may use OpenAI if configured).
            # Use asyncio.run() rather than manually creating a loop — it handles
            # loop creation, running, and cleanup atomically and is safe to call
            # from a thread-pool executor thread (which has no running loop).
            try:
                import asyncio as _asyncio
                from security.llm_wrapper import call_llm as _call_llm

                fixed = _asyncio.run(_call_llm(prompt))
                for fence in ("```python\n", "```py\n", "```\n"):
                    if fixed.startswith(fence):
                        fixed = fixed[len(fence) :]
                        break
                if fixed.endswith("```"):
                    fixed = fixed[:-3]
                return fixed.strip()
            except Exception as fallback_exc:
                logger.warning("SelfHealer: llm_wrapper fallback also failed: %s", fallback_exc)
                return ""

    # ── Advanced diagnostics loop ─────────────────────────────────────────────

    async def _diagnostics_loop(self) -> None:
        """
        Periodically run the full DiagnosticsEngine check suite.

        Runs every HEAL_DIAG_INTERVAL seconds (default 300s / 5 min).
        Critical findings are auto-remediated and pushed to Redis for the
        superadmin dashboard.
        """
        import os as _os
        # Skip diagnostics in development — they make blocking HTTP calls to
        # localhost which starve the single-worker event loop.
        if _os.getenv("APP_ENV", "development").lower() in ("development", "dev", "test"):
            logger.info("SelfHealer: diagnostics loop disabled in %s mode", _os.getenv("APP_ENV", "development"))
            return
        # Stagger startup so it doesn't compete with the initial baseline build
        await asyncio.sleep(30)
        while self._running:
            try:
                if self._enabled:
                    await self._run_diagnostics()
                else:
                    self._log("debug", "SelfHealer: diagnostics loop skipped — disabled")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("SelfHealer: diagnostics loop error: %s", exc)
            await asyncio.sleep(self._diag_interval)

    async def _run_diagnostics(self) -> dict[str, Any]:
        """
        Execute the full DiagnosticsEngine suite and act on findings.

        Actions taken:
        - Critical env-var issues → logged as CRITICAL alerts
        - Import chain failures → enqueued for Claude fix
        - Log pattern hits → enqueued for Claude fix
        - All results → persisted to Redis for the dashboard
        - Auto-remediation attempted for actionable findings
        """
        try:
            from security.diagnostics import get_diagnostics_engine
        except ImportError:
            logger.warning("SelfHealer: diagnostics module not available — skipping")
            return {}

        self._log("info", "SelfHealer: running advanced diagnostics suite")
        engine = get_diagnostics_engine()

        try:
            report = await engine.run_full_diagnostic(parallel=True)
        except Exception as exc:
            logger.warning("SelfHealer: diagnostics run failed: %s", exc)
            return {}

        self._last_diag_ts = time.time()
        self._last_diag_report = report.to_dict()

        # Persist to Redis for the dashboard
        redis = await _get_redis()
        if redis:
            with contextlib.suppress(Exception):
                await redis.set(
                    "heal:diagnostics:last_report",
                    json.dumps(self._last_diag_report),
                    ex=3600,
                )

        # Act on critical/error findings
        critical_results = [r for r in report.results if r.status in ("critical", "error")]
        for result in critical_results:
            # Push to alerts:critical
            if redis:
                with contextlib.suppress(Exception):
                    await redis.rpush(
                        "alerts:critical",
                        json.dumps(
                            {
                                "type": "diagnostic_failure",
                                "check": result.check_name,
                                "ts": result.checked_at,
                                "detail": result.to_dict(),
                            }
                        ),
                    )
                    await redis.ltrim("alerts:critical", -1000, -1)

            # Enqueue import chain failures for Claude fix
            if result.check_name == "import_chain":
                for broken in result.details.get("broken", [])[:5]:
                    await self._enqueue_claude_fix(
                        {
                            "category": "import_error",
                            "severity": "critical",
                            "description": f"Import chain broken: {broken.get('package')} — {broken.get('error', '')}",
                            "file": broken.get("package", "").replace(".", "/") + ".py",
                            "line": 0,
                            "snippet": broken.get("error", "")[:200],
                            "suggestion": "Fix the import error; run pip install -r requirements.txt",
                        }
                    )

            # Enqueue log pattern hits for Claude fix
            if result.check_name.startswith("log_pattern_"):
                await self._enqueue_claude_fix(
                    {
                        "category": result.check_name.replace("log_pattern_", ""),
                        "severity": result.status,
                        "description": result.message,
                        "file": "logs/app.log",
                        "line": 0,
                        "snippet": result.details.get("sample", "")[:200],
                        "suggestion": result.remediation,
                    }
                )

        # Auto-remediate if aggressiveness allows
        if self._aggressiveness in ("aggressive", "nuclear") and report.has_errors():
            try:
                actions = await engine.auto_remediate(report)
                if actions:
                    self._diag_remediation_log.extend(actions)
                    self._diag_remediation_log = self._diag_remediation_log[-100:]
                    self._log(
                        "info",
                        "SelfHealer: diagnostics auto-remediation — %d action(s) taken",
                        len(actions),
                    )
                    if redis:
                        with contextlib.suppress(Exception):
                            await redis.set(
                                "heal:diagnostics:remediation_log",
                                json.dumps(self._diag_remediation_log[-50:]),
                                ex=86400,
                            )
            except Exception as exc:
                logger.warning("SelfHealer: diagnostics auto-remediation error: %s", exc)

        self._log(
            "info" if not report.has_errors() else "warning",
            "SelfHealer: diagnostics complete — %s",
            report.summary(),
        )
        return self._last_diag_report

    async def run_diagnostics_now(self) -> dict[str, Any]:
        """Trigger an immediate full diagnostics run and return the report."""
        return await self._run_diagnostics()

    def get_last_diagnostic_report(self) -> dict[str, Any]:
        """Return the most recent diagnostics report."""
        return dict(self._last_diag_report)

    def get_diagnostics_remediation_log(self) -> list[dict[str, Any]]:
        """Return the diagnostics auto-remediation action log."""
        return list(self._diag_remediation_log)

    # ── Public API for deep analysis ──────────────────────────────────────────

    async def run_code_analysis_now(self) -> dict[str, Any]:
        """Trigger an immediate deep code analysis scan and return results."""
        issues = await self._run_code_analysis()
        return {
            "total": len(issues),
            "issues": issues[:100],
            "scanned_at": datetime.now(UTC).isoformat(),
        }

    async def run_log_analysis_now(self) -> dict[str, Any]:
        """Trigger an immediate log file analysis and return results."""
        log_issues = await self._run_log_analysis()
        return {
            "total": len(log_issues),
            "issues": log_issues[:100],
            "scanned_at": datetime.now(UTC).isoformat(),
        }

    def get_code_issues(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent code analysis results."""
        return self._code_issues[:limit]

    def get_log_issues(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent log analysis results."""
        return self._log_issues[:limit]

    def get_claude_queue(self) -> list[dict[str, Any]]:
        """Return the current Claude fix queue."""
        return list(self._claude_fix_queue)

    def get_issues_by_category(self, category: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return code issues filtered by category (e.g. 'nan_leak', 'broken_router')."""
        return [i for i in self._code_issues if i.get("category") == category][:limit]

    def get_broken_routers(self) -> list[dict[str, Any]]:
        """Return all detected broken (unregistered) routers."""
        return self.get_issues_by_category("broken_router")

    def get_nan_leaks(self) -> list[dict[str, Any]]:
        """Return all detected NaN leak risks."""
        return self.get_issues_by_category("nan_leak")

    def get_lookahead_issues(self) -> list[dict[str, Any]]:
        """Return all detected look-ahead bias issues."""
        return self.get_issues_by_category("lookahead_bias")

    async def force_claude_fix(self, file_path: str, category: str, description: str) -> dict[str, Any]:
        """
        Manually enqueue a specific file for Claude-powered fix.

        Useful for triggering fixes from the admin dashboard or API.
        Returns the enqueued issue dict.
        """
        issue = {
            "file": file_path,
            "category": category,
            "severity": "high",
            "description": description,
            "line": 0,
            "snippet": "",
            "suggestion": "Apply a production-ready fix for the described issue.",
        }
        await self._enqueue_claude_fix(issue)
        return issue

    # ── Plugin availability (probed once per process) ─────────────────────────

    @staticmethod
    def _pytest_available() -> bool:
        """Return True if pytest is importable in this Python environment."""
        try:
            import importlib

            return importlib.util.find_spec("pytest") is not None
        except Exception:
            return False

    @staticmethod
    def _xdist_available() -> bool:
        """Return True if pytest-xdist is installed (provides -n flag)."""
        try:
            import importlib

            return importlib.util.find_spec("xdist") is not None
        except Exception:
            return False

    @staticmethod
    def _timeout_plugin_available() -> bool:
        """Return True if pytest-timeout is installed (provides --timeout flag)."""
        try:
            import importlib

            return importlib.util.find_spec("pytest_timeout") is not None
        except Exception:
            return False

    def _build_pytest_cmd(self, test_paths: list[str]) -> list[str]:
        """
        Build a pytest command that only uses flags for installed plugins.
        Falls back gracefully when pytest-xdist or pytest-timeout are absent.
        """
        cmd = ["python", "-m", "pytest", "--tb=no", "-q", "--no-header"]

        # --timeout only if pytest-timeout is installed
        if self._timeout_plugin_available():
            cmd.append(f"--timeout={self._test_timeout_sec}")
        else:
            self._log("debug", "SelfHealer: pytest-timeout not installed — per-suite timeout disabled")

        # -n auto only if pytest-xdist is installed AND parallel is requested
        if self._parallel_tests:
            if self._xdist_available():
                cmd += ["-n", "auto"]
            else:
                self._log("debug", "SelfHealer: pytest-xdist not installed — running tests sequentially")

        cmd += test_paths
        return cmd

    async def _run_tests(self, trigger: str = "manual") -> bool:
        """
        Run enabled test categories via pytest subprocess.

        Probes for pytest, pytest-timeout, and pytest-xdist at call time so
        the healer degrades gracefully when any plugin is absent rather than
        crashing or silently skipping the run.

        Returns True if all tests pass (or no tests ran), False on failure.
        """
        import time

        self._last_test_run_ts = time.time()

        # Hard requirement: pytest itself must be present
        if not self._pytest_available():
            self._log("warning", "SelfHealer: pytest not installed — install pytest>=7.4 to enable test gates")
            self._record_test_result(0, 0, "skipped_no_pytest")
            return True  # don't block healing when pytest is absent

        self._log("info", "SelfHealer: running tests (trigger=%s)", trigger)

        # Collect test paths for enabled categories from the index
        try:
            from security.test_scanner import get_test_index

            index = get_test_index(force_rescan=False)
            file_list: list[dict[str, Any]] = index.get("file_list", [])
        except Exception as exc:
            logger.debug("SelfHealer: test_scanner unavailable: %s", exc)
            file_list = []

        test_paths: list[str] = [
            entry["path"]
            for entry in file_list
            if self._test_categories.get(entry.get("category", "unit"), False)
            and Path(PROJECT_ROOT / entry["path"]).exists()
        ][:200]  # hard cap — never run more than 200 files per gate

        if not test_paths:
            self._log("info", "SelfHealer: no test paths for enabled categories — skipping")
            return True

        cmd = self._build_pytest_cmd(test_paths)
        self._log("debug", "SelfHealer: pytest cmd: %s", " ".join(cmd[:8]) + " …")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(PROJECT_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=float(self._global_test_timeout_sec),
                )
            except (TimeoutError, asyncio.TimeoutError):
                with contextlib.suppress(Exception):
                    proc.kill()
                self._log(
                    "warning",
                    "SelfHealer: test run timed out after %ds (global_test_timeout_sec)",
                    self._global_test_timeout_sec,
                )
                self._record_test_result(0, 0, "timeout")
                return False

            output = (stdout + stderr).decode(errors="replace")
            passed, failed = self._parse_pytest_output(output)
            success = proc.returncode == 0
            self._record_test_result(passed, failed, "ok" if success else "failed")
            self._log(
                "info" if success else "warning",
                "SelfHealer: tests done trigger=%s passed=%d failed=%d rc=%d",
                trigger,
                passed,
                failed,
                proc.returncode,
            )
            return success

        except FileNotFoundError:
            # python -m pytest failed — python itself not on PATH (shouldn't happen)
            self._log("warning", "SelfHealer: python not found on PATH — skipping test run")
            return True
        except Exception as exc:
            logger.warning("SelfHealer: test run error: %s", exc)
            return False

    @staticmethod
    def _parse_pytest_output(output: str) -> tuple[int, int]:
        """Extract passed/failed counts from pytest -q summary line."""
        import re

        passed = failed = 0
        m = re.search(r"(\d+) passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", output)
        if m:
            failed = int(m.group(1))
        return passed, failed

    def _record_test_result(self, passed: int, failed: int, status: str) -> None:
        self._last_test_result = {
            "ts": datetime.now(UTC).isoformat(),
            "passed": passed,
            "failed": failed,
            "status": status,
        }
        try:
            from security.test_scanner import record_test_run

            record_test_run(passed, failed, status)
        except Exception:  # nosec B110 — test_scanner is optional telemetry; failure is non-fatal
            pass

    # ── Endpoint → file resolver ──────────────────────────────────────────────

    def _resolve_endpoint_to_file(self, endpoint: str) -> Path | None:
        """
        Map an API endpoint path (e.g. '/api/trading/signal') to a Python file.
        Tries common patterns: api/<module>.py, api/<module>/router.py, etc.
        """
        # Strip leading slash and split
        parts = endpoint.strip("/").split("/")
        if not parts:
            return None

        candidates: list[Path] = []
        if len(parts) >= 2:
            # api/trading.py or api/trading/router.py
            candidates += [
                PROJECT_ROOT / parts[0] / f"{parts[1]}.py",
                PROJECT_ROOT / parts[0] / parts[1] / "router.py",
                PROJECT_ROOT / parts[0] / parts[1] / "__init__.py",
            ]
        # Direct module path
        candidates.append(PROJECT_ROOT / "/".join(parts[:-1]) / f"{parts[-1]}.py")

        for c in candidates:
            if c.exists():
                return c
        return None

    # ── Baseline management ───────────────────────────────────────────────────

    async def rebuild_baseline(self, actor: str = "system") -> dict[str, Any]:
        """
        Force-rebuild the integrity baseline from current file state.

        Rate-limited to once per HEAL_BASELINE_REBUILD_INTERVAL seconds to
        prevent an attacker with a compromised superadmin token from repeatedly
        rebuilding the baseline after injecting malicious files.  Every rebuild
        is written to the audit log in Redis.
        """
        global _last_baseline_rebuild_ts
        now = time.time()
        elapsed = now - _last_baseline_rebuild_ts
        if elapsed < _BASELINE_REBUILD_INTERVAL:
            wait = int(_BASELINE_REBUILD_INTERVAL - elapsed)
            self._log(
                "warning",
                "SelfHealer: baseline rebuild rate-limited — next allowed in %ds (actor=%s)",
                wait,
                actor,
            )
            return {
                "ok": False,
                "error": f"Rate-limited: retry in {wait}s",
                "rebuilt_at": datetime.now(UTC).isoformat(),
            }

        self._baseline = _build_manifest()
        _save_manifest(self._baseline)
        _last_baseline_rebuild_ts = now
        rebuilt_at = datetime.now(UTC).isoformat()

        redis = await _get_redis()
        if redis:
            with contextlib.suppress(Exception):
                await redis.set("heal:manifest", json.dumps(self._baseline))
            # Audit trail — every rebuild is recorded with actor and timestamp
            with contextlib.suppress(Exception):
                audit_entry = json.dumps(
                    {
                        "event": "baseline_rebuild",
                        "actor": actor,
                        "files": len(self._baseline),
                        "ts": rebuilt_at,
                    }
                )
                await redis.rpush("heal:audit_log", audit_entry)
                await redis.ltrim("heal:audit_log", -500, -1)

        self._log(
            "info",
            "SelfHealer: baseline rebuilt by %s — %d files tracked",
            actor,
            len(self._baseline),
        )
        return {"ok": True, "files": len(self._baseline), "rebuilt_at": rebuilt_at}

    async def run_tests_now(self, trigger: str = "manual") -> dict[str, Any]:
        """Trigger a test run immediately and return the result."""
        success = await self._run_tests(trigger=trigger)
        return {**self._last_test_result, "success": success}

    def get_quarantine_log(self) -> list[dict[str, Any]]:
        return list(self._quarantine_log)

    # ── FastAPI router ────────────────────────────────────────────────────────

    def mount_router(self, app: FastAPI) -> None:
        router = self._build_router()
        app.include_router(router)
        logger.info("SelfHealer: router mounted at /api/security/heal")

    def _build_router(self) -> APIRouter:
        router = APIRouter(prefix="/api/security/heal", tags=["self-healer"])
        healer = self

        class RebuildResponse(BaseModel):
            files: int
            rebuilt_at: str

        class DriftEvent(BaseModel):
            path: str
            type: str
            ts: str
            expected: str | None = None
            actual: str | None = None

        class PatchRecord(BaseModel):
            endpoint: str
            file: str
            success: bool
            message: str
            diff: str
            applied_at: str

        class StatusResponse(BaseModel):
            running: bool
            baseline_files: int
            drift_events: int
            patches_applied: int
            patches_failed: int
            last_scan: str | None

        @router.get("/status", response_model=StatusResponse)
        async def get_status(request: Request):
            _require_auth(request)
            applied = sum(1 for p in healer._patch_history if p["success"])
            failed = sum(1 for p in healer._patch_history if not p["success"])
            last_scan = healer._drift_events[-1]["ts"] if healer._drift_events else None
            return StatusResponse(
                running=healer._running,
                baseline_files=len(healer._baseline),
                drift_events=len(healer._drift_events),
                patches_applied=applied,
                patches_failed=failed,
                last_scan=last_scan,
            )

        @router.get("/drift", response_model=list[DriftEvent])
        async def get_drift(request: Request, limit: int = 50):
            _require_auth(request)
            return [DriftEvent(**e) for e in healer._drift_events[-limit:]]

        @router.get("/patches", response_model=list[PatchRecord])
        async def get_patches(request: Request, limit: int = 50):
            _require_auth(request)
            return [PatchRecord(**p) for p in healer._patch_history[-limit:]]

        @router.post("/baseline/rebuild", response_model=RebuildResponse)
        async def rebuild_baseline(request: Request):
            _require_admin(request)
            result = await healer.rebuild_baseline()
            return RebuildResponse(**result)

        @router.post("/scan/now")
        async def trigger_scan(request: Request):
            _require_admin(request)
            await healer._scan_integrity()
            return {"triggered": True, "drift_events": len(healer._drift_events)}

        @router.get("/manifest")
        async def get_manifest(request: Request):
            _require_admin(request)
            return {"files": len(healer._baseline), "manifest": healer._baseline}

        return router


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _require_auth(request: Request) -> dict[str, Any]:
    try:
        from auth.jwt import decode_access_token

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        # decode_access_token(token) returns the full payload dict and raises
        # jwt.InvalidTokenError on any failure — no second argument needed.
        return decode_access_token(token)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Self-healer auth token decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


def _require_admin(request: Request) -> dict[str, Any]:
    payload = _require_auth(request)
    role = payload.get("role", "")
    if role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return payload


# ── Module-level singleton ────────────────────────────────────────────────────

_healer_instance: SelfHealer | None = None
_healer_lock = threading.Lock()


def get_healer() -> SelfHealer:
    global _healer_instance  # pylint: disable=global-statement
    if _healer_instance is None:
        with _healer_lock:
            if _healer_instance is None:
                _healer_instance = SelfHealer()
    return _healer_instance


async def start_healer(app: FastAPI) -> None:
    """
    Start the SelfHealer background task.
    The heal_router registered by router_registry.py already covers
    /api/security/heal/* via get_healer() delegation — no re-mount needed.
    """
    healer = get_healer()
    _t = asyncio.create_task(healer.run(), name="self-healer")
    _t.add_done_callback(lambda _: None)
    logger.info("SelfHealer: background task started")


# ── Module-level eager router ─────────────────────────────────────────────────
# Registered by router_registry.py at import time. Delegates to get_healer()
# at request time so the live instance is used once start_healer() runs.


def _heal_require_auth(request: Request) -> None:
    """Verify Bearer JWT — used as a Depends() on heal router read endpoints."""
    try:
        from auth.jwt import decode_access_token as _decode

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        _decode(token)
    except HTTPException:
        raise
    except ImportError:  # nosec B110
        logger.warning("SelfHealer router: auth.jwt unavailable, auth skipped")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Authentication failed") from exc


def _heal_require_admin(request: Request) -> None:
    """Verify Bearer JWT and require admin/superadmin — used as Depends() on mutating endpoints."""
    try:
        from auth.jwt import decode_access_token as _decode

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        payload = _decode(token)
        role = (payload or {}).get("role", "")
        if role not in ("admin", "superadmin"):
            raise HTTPException(status_code=403, detail="Admin role required")
    except HTTPException:
        raise
    except ImportError:  # nosec B110
        logger.warning("SelfHealer router: auth.jwt unavailable, admin check skipped")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Authentication failed") from exc


def _build_eager_heal_router() -> APIRouter:
    r = APIRouter(prefix="/api/security/heal", tags=["self-healer"])

    @r.get("/status")
    async def _status(_: None = Depends(_heal_require_auth)):
        h = get_healer()
        applied = sum(1 for p in h._patch_history if p["success"])
        failed = sum(1 for p in h._patch_history if not p["success"])
        last_scan = h._drift_events[-1]["ts"] if h._drift_events else None
        return {
            "running": h._running,
            "baseline_files": len(h._baseline),
            "drift_events": len(h._drift_events),
            "patches_applied": applied,
            "patches_failed": failed,
            "last_scan": last_scan,
        }

    @r.get("/drift")
    async def _drift(limit: int = 50, _: None = Depends(_heal_require_auth)):
        return get_healer()._drift_events[-limit:]

    @r.get("/patches")
    async def _patches(limit: int = 50, _: None = Depends(_heal_require_auth)):
        return get_healer()._patch_history[-limit:]

    @r.post("/baseline/rebuild")
    async def _rebuild(_: None = Depends(_heal_require_admin)):
        return await get_healer().rebuild_baseline()

    @r.post("/scan/now")
    async def _scan_now(_: None = Depends(_heal_require_admin)):
        h = get_healer()
        await h._scan_integrity()
        return {"triggered": True, "drift_events": len(h._drift_events)}

    @r.post("/code-analysis/now", summary="Trigger immediate deep code analysis scan")
    async def _code_analysis_now(_: None = Depends(_heal_require_admin)):
        return await get_healer().run_code_analysis_now()

    @r.get("/code-analysis/issues", summary="Get latest code analysis issues")
    async def _code_issues(limit: int = 100, _: None = Depends(_heal_require_auth)):
        h = get_healer()
        issues = h.get_code_issues(limit=limit)
        return {
            "total": len(h._code_issues),
            "returned": len(issues),
            "issues": issues,
            "last_scan": datetime.fromtimestamp(h._last_code_scan_ts, UTC).isoformat()
            if h._last_code_scan_ts
            else None,
        }

    @r.post("/log-analysis/now", summary="Trigger immediate log file analysis")
    async def _log_analysis_now(_: None = Depends(_heal_require_admin)):
        return await get_healer().run_log_analysis_now()

    @r.get("/log-analysis/issues", summary="Get latest log analysis issues")
    async def _log_issues(limit: int = 100, _: None = Depends(_heal_require_auth)):
        h = get_healer()
        issues = h.get_log_issues(limit=limit)
        return {
            "total": len(h._log_issues),
            "returned": len(issues),
            "issues": issues,
            "log_file": str(_LOG_FILE),
            "last_scan": datetime.fromtimestamp(h._last_log_scan_ts, UTC).isoformat()
            if h._last_log_scan_ts
            else None,
        }

    @r.get("/claude-queue", summary="Get pending Claude fix queue")
    async def _claude_queue(_: None = Depends(_heal_require_auth)):
        h = get_healer()
        return {"depth": len(h._claude_fix_queue), "items": h.get_claude_queue()}

    @r.delete("/claude-queue", summary="Clear the Claude fix queue")
    async def _clear_claude_queue(_: None = Depends(_heal_require_admin)):
        h = get_healer()
        count = len(h._claude_fix_queue)
        h._claude_fix_queue.clear()
        return {"cleared": count}

    @r.post("/diagnostics/now", summary="Trigger immediate full diagnostics run")
    async def _diagnostics_now(_: None = Depends(_heal_require_admin)):
        return await get_healer().run_diagnostics_now()

    @r.get("/diagnostics/report", summary="Get the last diagnostics report")
    async def _diagnostics_report(_: None = Depends(_heal_require_auth)):
        h = get_healer()
        report = h.get_last_diagnostic_report()
        if not report:
            return {"message": "No diagnostics report available yet — trigger one via POST /diagnostics/now"}
        return report

    @r.get("/diagnostics/remediation-log", summary="Get diagnostics auto-remediation log")
    async def _diagnostics_remediation_log(_: None = Depends(_heal_require_auth)):
        h = get_healer()
        return {"entries": h.get_diagnostics_remediation_log(), "total": len(h._diag_remediation_log)}

    @r.get("/full-status", summary="Complete healer + diagnostics status")
    async def _full_status(_: None = Depends(_heal_require_auth)):
        h = get_healer()
        status = h.get_full_status()
        status["last_diagnostic_report"] = h.get_last_diagnostic_report()
        status["last_diag_ts"] = datetime.fromtimestamp(h._last_diag_ts, UTC).isoformat() if h._last_diag_ts else None
        return status

    return r


# Singleton eager router — imported by router_registry.py
heal_router = _build_eager_heal_router()
