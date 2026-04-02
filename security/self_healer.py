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
    asyncio.create_task(healer.run())

The FastAPI sub-router is mounted automatically when ``mount_router`` is
called with the app instance.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel

UTC = timezone.utc
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
                import redis.asyncio as aioredis
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
        with open(path, "rb") as f:
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
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            pass
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
        with open(path, "rb") as f:
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

    Usage::

        healer = SelfHealer()
        asyncio.create_task(healer.run())
        healer.mount_router(app)
    """

    def __init__(self) -> None:
        self._baseline: dict[str, str] = {}
        self._drift_events: list[dict[str, Any]] = []
        self._patch_history: list[dict[str, Any]] = []
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main loop: integrity scan + patch drain, running forever."""
        self._running = True
        await self._ensure_baseline()
        logger.info(
            "SelfHealer: started — tracking %d files, scan_interval=%ds",
            len(self._baseline),
            HEAL_SCAN_INTERVAL,
        )
        scan_task = asyncio.create_task(self._scan_loop())
        patch_task = asyncio.create_task(self._patch_loop())
        await asyncio.gather(scan_task, patch_task)

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
                await self._scan_integrity()
            except Exception as exc:
                logger.warning("SelfHealer: scan error: %s", exc)
            await asyncio.sleep(HEAL_SCAN_INTERVAL)

    async def _scan_integrity(self) -> None:
        """Compare current file hashes against baseline; flag drift."""
        current = _build_manifest()
        drift: list[dict[str, Any]] = []

        for rel_path, expected_hash in self._baseline.items():
            actual_hash = current.get(rel_path, "")
            if not actual_hash:
                drift.append({"path": rel_path, "type": "deleted", "ts": datetime.now(UTC).isoformat()})
            elif actual_hash != expected_hash:
                drift.append({
                    "path": rel_path,
                    "type": "modified",
                    "expected": expected_hash[:16],
                    "actual": actual_hash[:16],
                    "ts": datetime.now(UTC).isoformat(),
                })

        for rel_path in current:
            if rel_path not in self._baseline:
                drift.append({"path": rel_path, "type": "new_file", "ts": datetime.now(UTC).isoformat()})

        if drift:
            logger.warning("SelfHealer: %d drift event(s) detected", len(drift))
            self._drift_events.extend(drift)
            # Keep last 500 events in memory
            self._drift_events = self._drift_events[-500:]
            await self._push_drift_alerts(drift)

    async def _push_drift_alerts(self, drift: list[dict[str, Any]]) -> None:
        redis = await _get_redis()
        if not redis:
            return
        try:
            for event in drift:
                await redis.rpush(
                    "alerts:critical",
                    json.dumps({
                        "type": "file_integrity_drift",
                        "ip": "internal",
                        "ts": event["ts"],
                        "detail": event,
                    }),
                )
                # Trim to last 1000 alerts
                await redis.ltrim("alerts:critical", -1000, -1)
        except Exception as exc:
            logger.debug("SelfHealer: alert push failed: %s", exc)

    # ── Patch drain loop ──────────────────────────────────────────────────────

    async def _patch_loop(self) -> None:
        while self._running:
            try:
                await self._drain_approved_patches()
            except Exception as exc:
                logger.warning("SelfHealer: patch drain error: %s", exc)
            await asyncio.sleep(HEAL_PATCH_INTERVAL)

    async def _drain_approved_patches(self) -> None:
        """Apply all approved fixes from fixes:queue."""
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

            # Resolve endpoint path to a real file
            target = self._resolve_endpoint_to_file(endpoint)
            if target is None:
                logger.warning("SelfHealer: cannot resolve endpoint to file: %s", endpoint)
                continue

            original_code = ""
            if target.exists():
                original_code = target.read_text(encoding="utf-8", errors="replace")

            success, msg = _apply_patch(target, new_code)
            record: dict[str, Any] = {
                "endpoint": endpoint,
                "file": str(target.relative_to(PROJECT_ROOT)),
                "success": success,
                "message": msg,
                "diff": _unified_diff(original_code, new_code, target.name) if success else "",
                "applied_at": datetime.now(UTC).isoformat(),
            }
            self._patch_history.append(record)
            self._patch_history = self._patch_history[-200:]

            if success:
                applied.append(raw)
                # Update baseline hash for the patched file
                self._baseline[str(target.relative_to(PROJECT_ROOT))] = _sha256(target)
                _save_manifest(self._baseline)
                logger.info("SelfHealer: patch applied to %s", target)
            else:
                logger.warning("SelfHealer: patch rejected for %s: %s", endpoint, msg)

            # Push result to Redis
            try:
                await redis.rpush("heal:patch_history", json.dumps(record))
                await redis.ltrim("heal:patch_history", -200, -1)
            except Exception:
                pass

        # Remove applied entries from the queue
        for raw in applied:
            try:
                await redis.lrem("fixes:approved", 1, raw)
            except Exception:
                pass

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
            try:
                await redis.set("heal:manifest", json.dumps(self._baseline))
            except Exception:
                pass
        return {"files": len(self._baseline), "rebuilt_at": datetime.now(UTC).isoformat()}

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
        raise HTTPException(status_code=401, detail=str(exc)) from exc


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
    Start the SelfHealer background task and mount its router.
    Call from connect_to_life.py or app lifespan.
    """
    healer = get_healer()
    healer.mount_router(app)
    asyncio.create_task(healer.run(), name="self-healer")
    logger.info("SelfHealer: background task started")
