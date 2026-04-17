# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/auto_healing.py
==============================
Superadmin REST endpoints for the Autonomous Healing Engine.

Routes
------
GET  /superadmin/auto-healing/status          — live healer status
GET  /superadmin/auto-healing/config          — load saved config
PUT  /superadmin/auto-healing/config          — save config
GET  /superadmin/auto-healing/tests/index     — test discovery index
POST /superadmin/auto-healing/tests/reindex   — trigger full re-scan
POST /superadmin/auto-healing/baseline/rebuild — rebuild integrity baseline
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import TokenPayload
from ._shared import _log_superadmin_action, _require_superadmin, _utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Config persistence ────────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "auto_healing_config.json"
_REDIS_CONFIG_KEY = "superadmin:auto_healing:config"

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "scan_interval_sec": 120,
    "patch_interval_sec": 60,
    "max_patch_bytes": 65536,
    "aggressiveness": "medium",
    "baseline_auto_rebuild": True,
    "quarantine_enabled": True,
    "quarantine_retention_days": 30,
    "tests_enabled": True,
    "test_categories": {
        "unit": True,
        "api": True,
        "broker": True,
        "risk": True,
        "ml": True,
        "security": True,
        "performance": False,
        "e2e": False,
    },
    "test_execution_strategy": ["after_patch", "on_drift"],
    "test_timeout_sec": 120,
    "global_test_timeout_sec": 600,
    "parallel_tests": True,
    "test_schedule_interval_min": 60,
    "require_approval_categories": ["nuclear", "e2e"],
    "protected_paths": "live_trading.py,risk_manager.py,ml/models/,config/secrets/",
    "auto_rollback_sensitivity": "medium",
    "max_healing_attempts": 3,
    "healing_cooldown_sec": 300,
    "log_level": "standard",
}


def _load_config() -> dict[str, Any]:
    # Redis first
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.get(_REDIS_CONFIG_KEY)
            if raw:
                return {**_DEFAULT_CONFIG, **json.loads(raw)}
    except Exception as exc:
        logger.debug("auto_healing: redis config read: %s", exc)

    # Disk fallback
    try:
        if _CONFIG_PATH.exists():
            return {**_DEFAULT_CONFIG, **json.loads(_CONFIG_PATH.read_text())}
    except Exception as exc:
        logger.debug("auto_healing: disk config read: %s", exc)

    return dict(_DEFAULT_CONFIG)


def _save_config(cfg: dict[str, Any]) -> None:
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        tmp.replace(_CONFIG_PATH)
    except Exception as exc:
        logger.warning("auto_healing: disk config save failed: %s", exc)

    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.set(_REDIS_CONFIG_KEY, json.dumps(cfg))
    except Exception as exc:
        logger.debug("auto_healing: redis config save: %s", exc)


def _apply_config_to_healer(cfg: dict[str, Any]) -> None:
    """Push config into the live SelfHealer singleton via apply_config()."""
    try:
        from security.self_healer import get_healer

        get_healer().apply_config(cfg)
    except Exception as exc:
        logger.debug("auto_healing: apply_config_to_healer: %s", exc)


# ── Pydantic models ───────────────────────────────────────────────────────────


class HealingConfigBody(BaseModel):
    enabled: bool = True
    scan_interval_sec: int = Field(120, ge=30)
    patch_interval_sec: int = Field(60, ge=30)
    max_patch_bytes: int = Field(65536, ge=1024)
    aggressiveness: str = "medium"
    baseline_auto_rebuild: bool = True
    quarantine_enabled: bool = True
    quarantine_retention_days: int = Field(30, ge=1, le=365)
    tests_enabled: bool = True
    test_categories: dict[str, bool] = Field(default_factory=dict)
    test_execution_strategy: list[str] = Field(default_factory=list)
    test_timeout_sec: int = Field(120, ge=10)
    global_test_timeout_sec: int = Field(600, ge=60)
    parallel_tests: bool = True
    test_schedule_interval_min: int = Field(60, ge=5)
    require_approval_categories: list[str] = Field(default_factory=list)
    protected_paths: str = ""
    auto_rollback_sensitivity: str = "medium"
    max_healing_attempts: int = Field(3, ge=1, le=10)
    healing_cooldown_sec: int = Field(300, ge=30)
    log_level: str = "standard"


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/auto-healing/status")
async def get_auto_healing_status(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Live healer status — delegates to SelfHealer singleton."""
    try:
        from security.self_healer import get_healer

        h = get_healer()
        applied = sum(1 for p in h._patch_history if p.get("success"))
        failed = sum(1 for p in h._patch_history if not p.get("success"))
        last_scan = h._drift_events[-1]["ts"] if h._drift_events else None
        return {
            "running": h._running,
            "baseline_files": len(h._baseline),
            "drift_events": len(h._drift_events),
            "patches_applied": applied,
            "patches_failed": failed,
            "last_scan": last_scan,
        }
    except Exception as exc:
        logger.debug("auto_healing status: %s", exc)

    # Redis fallback
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.get("security:self_healer:status")
            if raw:
                return json.loads(raw)
    except Exception:  # nosec B110 — Redis is optional; return safe default below
        pass

    return {
        "running": False,
        "baseline_files": 0,
        "drift_events": 0,
        "patches_applied": 0,
        "patches_failed": 0,
        "last_scan": None,
    }


@router.get("/auto-healing/config")
async def get_healing_config(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return the current healing engine configuration."""
    return _load_config()


@router.put("/auto-healing/config")
async def save_healing_config(
    body: HealingConfigBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Persist healing config and apply to the live healer."""
    cfg = body.model_dump()
    _save_config(cfg)
    _apply_config_to_healer(cfg)
    _log_superadmin_action(
        user, "auto_healing_config_save", f"aggressiveness={cfg['aggressiveness']} enabled={cfg['enabled']}"
    )
    return {"ok": True, "saved_at": _utcnow().isoformat()}


@router.get("/auto-healing/tests/index")
async def get_test_index(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return the cached test discovery index (no re-scan)."""
    try:
        from security.test_scanner import get_test_index

        return get_test_index(force_rescan=False)
    except Exception as exc:
        logger.warning("auto_healing test_index: %s", exc)
        return {
            "total": 0,
            "files": 0,
            "by_category": {},
            "last_indexed": None,
            "last_run": None,
            "last_run_passed": None,
            "last_run_failed": None,
        }


@router.post("/auto-healing/tests/reindex")
async def reindex_tests(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Trigger a full codebase test scan using async_reindex (non-blocking)."""
    import asyncio

    _log_superadmin_action(user, "auto_healing_test_reindex")

    async def _run_scan() -> None:
        try:
            from security.test_scanner import async_reindex

            result = await async_reindex()
            logger.info(
                "auto_healing: test re-index complete — %d tests in %d files",
                result.get("total", 0),
                result.get("files", 0),
            )
        except Exception as exc:
            logger.warning("auto_healing: test re-index failed: %s", exc)

    asyncio.create_task(_run_scan())
    return {"ok": True, "status": "scan_started", "triggered_at": _utcnow().isoformat()}


@router.post("/auto-healing/baseline/rebuild")
async def rebuild_baseline(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Rebuild the SelfHealer integrity baseline from current file state."""
    _log_superadmin_action(user, "auto_healing_baseline_rebuild")
    actor = getattr(user, "sub", None) or getattr(user, "email", "superadmin")
    try:
        from security.self_healer import get_healer

        result = await get_healer().rebuild_baseline(actor=actor)
        return result
    except Exception as exc:
        logger.warning("auto_healing baseline rebuild: %s", exc)
        try:
            from security.self_healer import _build_manifest, _save_manifest

            manifest = _build_manifest()
            _save_manifest(manifest)
            return {"ok": True, "files": len(manifest), "rebuilt_at": _utcnow().isoformat()}
        except Exception as exc2:
            logger.error("auto_healing baseline rebuild fallback: %s", exc2)
            return {"ok": False, "error": str(exc2), "rebuilt_at": _utcnow().isoformat()}


@router.get("/auto-healing/drift")
async def get_drift_history(
    limit: int = 100,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return recent drift events from the live healer."""
    try:
        from security.self_healer import get_healer

        events = get_healer()._drift_events[-limit:]
        return {"events": events, "total": len(get_healer()._drift_events)}
    except Exception:  # nosec B110 — healer may not be running; fall through to Redis
        pass
    # Redis fallback
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.get("heal:drift_events")
            if raw:
                events = json.loads(raw)[-limit:]
                return {"events": events, "total": len(events)}
    except Exception as exc:
        logger.debug("auto_healing drift: %s", exc)
    return {"events": [], "total": 0}


@router.get("/auto-healing/patches")
async def get_patch_history(
    limit: int = 50,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return recent patch history from the live healer."""
    try:
        from security.self_healer import get_healer

        patches = get_healer()._patch_history[-limit:]
        return {"patches": patches, "total": len(get_healer()._patch_history)}
    except Exception:  # nosec B110 — healer may not be running; fall through to Redis
        pass
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("heal:patch_history", -limit, -1)
            patches = [json.loads(r) for r in raw]
            return {"patches": patches, "total": len(patches)}
    except Exception as exc:
        logger.debug("auto_healing patches: %s", exc)
    return {"patches": [], "total": 0}


@router.get("/auto-healing/quarantine")
async def get_quarantine_log(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return the quarantine log."""
    try:
        from security.self_healer import get_healer

        return {"entries": get_healer().get_quarantine_log()}
    except Exception as exc:
        logger.debug("auto_healing quarantine: %s", exc)
    return {"entries": []}


@router.post("/auto-healing/tests/run")
async def run_tests_now(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Trigger an immediate test run for all enabled categories.

    Delegates to the live SelfHealer when available (uses its configured
    categories, timeouts, and parallel flag).  Falls back to
    run_category_tests() in a thread-pool executor so the event loop is
    never blocked by the synchronous subprocess call.
    """
    import asyncio

    _log_superadmin_action(user, "auto_healing_test_run_manual")

    # Prefer the live healer — it already knows which categories are enabled
    try:
        from security.self_healer import get_healer

        result = await get_healer().run_tests_now(trigger="manual")
        return {"ok": True, **result}
    except Exception as exc:
        logger.debug("auto_healing run_tests_now via healer failed: %s — falling back", exc)

    # Fallback: load config, run via test_scanner in executor
    try:
        cfg = _load_config()
        enabled_cats = [cat for cat, on in cfg.get("test_categories", {}).items() if on]
        if not enabled_cats:
            return {
                "ok": True,
                "passed": 0,
                "failed": 0,
                "output": "No test categories enabled in config.",
                "ts": _utcnow().isoformat(),
            }

        from security.test_scanner import run_category_tests

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_category_tests(
                categories=enabled_cats,
                timeout_sec=cfg.get("global_test_timeout_sec", 600),
                parallel=cfg.get("parallel_tests", True),
                per_suite_timeout=cfg.get("test_timeout_sec", 120),
            ),
        )
        return {
            "ok": True,
            "ts": _utcnow().isoformat(),
            **result,
        }
    except Exception as exc:
        logger.warning("auto_healing run_tests_now fallback: %s", exc)
        return {"ok": False, "error": str(exc), "ts": _utcnow().isoformat()}


@router.get("/auto-healing/pending-approval")
async def get_pending_approval(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return patches waiting for manual approval."""
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("heal:pending_approval", 0, -1)
            return {"patches": [json.loads(r) for r in raw]}
    except Exception as exc:
        logger.debug("auto_healing pending_approval: %s", exc)
    return {"patches": []}


@router.get("/auto-healing/audit-log")
async def get_audit_log(
    limit: int = 100,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return the healer audit log (baseline rebuilds, manual actions)."""
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("heal:audit_log", -limit, -1)
            return {"entries": [json.loads(r) for r in raw]}
    except Exception as exc:
        logger.debug("auto_healing audit_log: %s", exc)
    return {"entries": []}


@router.post("/auto-healing/approve/{patch_index}")
async def approve_patch(
    patch_index: int,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Move a pending patch to fixes:approved queue."""
    _log_superadmin_action(user, "auto_healing_patch_approve", f"index={patch_index}")
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            entries = rc.lrange("heal:pending_approval", 0, -1)
            if patch_index < 0 or patch_index >= len(entries):
                return {"ok": False, "error": "Invalid patch index"}
            entry = entries[patch_index]
            rc.lrem("heal:pending_approval", 1, entry)
            rc.rpush("fixes:approved", entry)
            return {"ok": True, "approved_at": _utcnow().isoformat()}
    except Exception as exc:
        logger.warning("auto_healing approve_patch: %s", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "Redis unavailable"}
