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
        "unit": True, "api": True, "broker": True, "risk": True,
        "ml": True, "security": True, "performance": False, "e2e": False,
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
    """Push relevant config values into the live SelfHealer instance."""
    try:
        from security.self_healer import get_healer
        import security.self_healer as _sh

        healer = get_healer()
        _sh.HEAL_SCAN_INTERVAL = cfg.get("scan_interval_sec", 120)
        _sh.HEAL_PATCH_INTERVAL = cfg.get("patch_interval_sec", 60)
        _sh.MAX_PATCH_SIZE = cfg.get("max_patch_bytes", 65536)

        if hasattr(healer, "_enabled"):
            healer._enabled = cfg.get("enabled", True)
        if hasattr(healer, "_quarantine_enabled"):
            healer._quarantine_enabled = cfg.get("quarantine_enabled", True)
        if hasattr(healer, "_aggressiveness"):
            healer._aggressiveness = cfg.get("aggressiveness", "medium")
        if hasattr(healer, "_max_patch_size"):
            healer._max_patch_size = cfg.get("max_patch_bytes", 65536)
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
        failed  = sum(1 for p in h._patch_history if not p.get("success"))
        last_scan = h._drift_events[-1]["ts"] if h._drift_events else None
        return {
            "running":         h._running,
            "baseline_files":  len(h._baseline),
            "drift_events":    len(h._drift_events),
            "patches_applied": applied,
            "patches_failed":  failed,
            "last_scan":       last_scan,
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
    except Exception:
        pass

    return {
        "running": False, "baseline_files": 0,
        "drift_events": 0, "patches_applied": 0,
        "patches_failed": 0, "last_scan": None,
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
    _log_superadmin_action(user, "auto_healing_config_save",
                           f"aggressiveness={cfg['aggressiveness']} enabled={cfg['enabled']}")
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
            "total": 0, "files": 0, "by_category": {},
            "last_indexed": None, "last_run": None,
            "last_run_passed": None, "last_run_failed": None,
        }


@router.post("/auto-healing/tests/reindex")
async def reindex_tests(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Trigger a full codebase test scan in the background."""
    import asyncio

    _log_superadmin_action(user, "auto_healing_test_reindex")

    async def _run_scan() -> None:
        try:
            from security.test_scanner import get_test_index
            get_test_index(force_rescan=True)
            logger.info("auto_healing: test re-index complete")
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
    try:
        from security.self_healer import get_healer
        result = await get_healer().rebuild_baseline()
        return {"ok": True, **result}
    except Exception as exc:
        logger.warning("auto_healing baseline rebuild: %s", exc)
        # Fallback: rebuild via module-level helpers
        try:
            from security.self_healer import _build_manifest, _save_manifest
            manifest = _build_manifest()
            _save_manifest(manifest)
            return {
                "ok": True,
                "files": len(manifest),
                "rebuilt_at": _utcnow().isoformat(),
            }
        except Exception as exc2:
            logger.error("auto_healing baseline rebuild fallback: %s", exc2)
            return {"ok": False, "error": str(exc2), "rebuilt_at": _utcnow().isoformat()}
