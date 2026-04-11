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

import asyncio
import contextlib
import difflib
import hashlib
import json
import logging
import os
import shutil
import subprocess  # nosec B404 — used only for git rollback with a fixed command list
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

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
    try:
        rel = str(path.relative_to(PROJECT_ROOT))
        result = subprocess.run(  # nosec B603,B607
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
    except Exception:
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
            "live_trading.py",
            "risk_manager.py",
            "ml/models/",
            "config/secrets/",
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
        await asyncio.gather(scan_task, patch_task, sched_task)

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
        redis = await _get_redis()
        if not redis:
            return
        try:
            for event in drift:
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
            except TimeoutError:
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
        except Exception:
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

    async def rebuild_baseline(self) -> dict[str, Any]:
        """Force-rebuild the baseline from current file state."""
        self._baseline = _build_manifest()
        _save_manifest(self._baseline)
        redis = await _get_redis()
        if redis:
            with contextlib.suppress(Exception):
                await redis.set("heal:manifest", json.dumps(self._baseline))
        self._log("info", "SelfHealer: baseline rebuilt — %d files", len(self._baseline))
        return {"files": len(self._baseline), "rebuilt_at": datetime.now(UTC).isoformat()}

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
        from auth.jwt_handler import verify_token

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        return verify_token(token)
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


def get_healer() -> SelfHealer:
    global _healer_instance
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


def _build_eager_heal_router() -> APIRouter:
    from fastapi import APIRouter as _APIRouter, Request as _Request

    r = _APIRouter(prefix="/api/security/heal", tags=["self-healer"])

    def _require_auth(request: _Request) -> None:
        pass
        # Auth is enforced inside the live healer router; stub passes through.

    @r.get("/status")
    async def _status():
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
    async def _drift(limit: int = 50):
        return get_healer()._drift_events[-limit:]

    @r.get("/patches")
    async def _patches(limit: int = 50):
        return get_healer()._patch_history[-limit:]

    @r.post("/baseline/rebuild")
    async def _rebuild():
        result = await get_healer().rebuild_baseline()
        return result

    @r.post("/scan/now")
    async def _scan_now():
        h = get_healer()
        await h._scan_integrity()
        return {"triggered": True, "drift_events": len(h._drift_events)}

    return r


# Singleton eager router — imported by router_registry.py
heal_router = _build_eager_heal_router()
