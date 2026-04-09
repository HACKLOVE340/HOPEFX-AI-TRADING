# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin platform config and trading engine sub-router."""

import logging
import sys
import time

from fastapi import APIRouter, Depends

from api.auth import TokenPayload

from ._shared import (
    BroadcastBody,
    EngineConfigBody,
    KillSwitchBody,
    MaintenanceBody,
    PauseBody,
    PlatformConfigBody,
    _get_config_store as _shared_get_config_store,
    _log_superadmin_action,
    _require_superadmin,
    _utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_config_store():
    """Return config store, honouring any test-level patch on api.superadmin._get_config_store."""
    parent = sys.modules.get("api.superadmin")
    if parent is not None:
        fn = getattr(parent, "_get_config_store", None)
        if fn is not None and fn is not _get_config_store:
            return fn()
    return _shared_get_config_store()

# ── Platform config ───────────────────────────────────────────────────────────

_PLATFORM_CONFIG_KEY = "superadmin_platform_config"

_PLATFORM_CONFIG_DEFAULTS: dict = {
    "platform_name": "HOPEFX AI Trading",
    "support_email": "support@hopefx.ai",
    "max_users": 10000,
    "allow_registrations": True,
    "require_email_verification": True,
    "default_new_user_plan": "free",
    "default_new_user_role": "trader",
    "session_timeout_minutes": 60,
    "max_api_keys_per_user": 5,
    "rate_limit_per_minute": 60,
    "maintenance_mode": False,
    "maintenance_message": "We're performing scheduled maintenance. Back shortly.",
    "announcement_enabled": False,
    "announcement_text": "",
    "announcement_type": "info",
    "force_2fa_for_admins": False,
    "ip_whitelist_enabled": False,
    "ip_whitelist": "",
}


def _load_platform_config() -> dict:
    cs = _get_config_store()
    if cs:
        stored = cs.get(_PLATFORM_CONFIG_KEY)
        if stored:
            import json

            try:
                return {**_PLATFORM_CONFIG_DEFAULTS, **json.loads(stored)}
            except Exception:
                logger.debug("Suppressed exception (no detail) in %s", __name__)
    return dict(_PLATFORM_CONFIG_DEFAULTS)


def _save_platform_config(cfg: dict) -> None:
    cs = _get_config_store()
    if cs:
        import json

        cs.set(_PLATFORM_CONFIG_KEY, json.dumps(cfg))


@router.get("/platform/config")
async def get_platform_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return _load_platform_config()


@router.patch("/platform/config")
async def update_platform_config(body: PlatformConfigBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_platform_config()
    updates = body.model_dump(exclude_none=True)
    cfg.update(updates)
    _save_platform_config(cfg)
    _log_superadmin_action(user, "update_platform_config", str(list(updates.keys())))
    return {"ok": True}


@router.post("/platform/maintenance")
async def set_maintenance_mode(body: MaintenanceBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_platform_config()
    cfg["maintenance_mode"] = body.enabled
    if body.message:
        cfg["maintenance_message"] = body.message
    _save_platform_config(cfg)
    cs = _get_config_store()
    if cs:
        cs.set("maintenance_mode", "1" if body.enabled else "0")
    _log_superadmin_action(user, "maintenance_mode", str(body.enabled))
    return {"ok": True, "maintenance_mode": body.enabled}


@router.post("/platform/broadcast")
async def broadcast_message(body: BroadcastBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "broadcast", f"[{body.type}] {body.title}")
    try:
        from cache.redis_client import get_redis_client
        import json

        rc = get_redis_client()
        if rc:
            msg = {"title": body.title, "body": body.body, "type": body.type, "ts": _utcnow().isoformat()}
            rc.lpush("platform:broadcasts", json.dumps(msg))
            rc.ltrim("platform:broadcasts", 0, 49)
    except Exception as exc:
        logger.debug("broadcast redis: %s", exc)
    return {"ok": True}


# ── Trading engine ────────────────────────────────────────────────────────────

_ENGINE_CONFIG_KEY = "superadmin_engine_config"

_ENGINE_CONFIG_DEFAULTS: dict = {
    "paper_trading_mode": True,
    "live_trading_enabled": False,
    "max_open_positions": 5,
    "max_risk_per_trade": 2.0,
    "max_daily_loss_pct": 5.0,
    "max_drawdown_pct": 10.0,
    "default_lot_size": 0.01,
    "slippage_tolerance": 2.0,
    "default_leverage": 50,
    "auto_trade_enabled": False,
    "signal_confidence_threshold": 0.65,
    "kill_switch_active": False,
    "engine_status": "running",
    "broker_type": "paper",
    "execution_mode": "market",
}


def _load_engine_config() -> dict:
    cs = _get_config_store()
    if cs:
        stored = cs.get(_ENGINE_CONFIG_KEY)
        if stored:
            import json

            try:
                return {**_ENGINE_CONFIG_DEFAULTS, **json.loads(stored)}
            except Exception:
                logger.debug("Suppressed exception (no detail) in %s", __name__)
    # Also pull from legacy risk settings
    try:
        from api.admin import _get_risk_settings

        rs = _get_risk_settings()
        merged = dict(_ENGINE_CONFIG_DEFAULTS)
        merged["max_open_positions"] = rs.get("max_open_positions", merged["max_open_positions"])
        merged["max_risk_per_trade"] = rs.get("max_risk_per_trade", merged["max_risk_per_trade"])
        merged["max_daily_loss_pct"] = rs.get("max_daily_loss", merged["max_daily_loss_pct"])
        merged["max_drawdown_pct"] = rs.get("max_drawdown", merged["max_drawdown_pct"])
        merged["paper_trading_mode"] = rs.get("paper_trading_mode", merged["paper_trading_mode"])
        return merged
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return dict(_ENGINE_CONFIG_DEFAULTS)


def _save_engine_config(cfg: dict) -> None:
    cs = _get_config_store()
    if cs:
        import json

        cs.set(_ENGINE_CONFIG_KEY, json.dumps(cfg))


@router.get("/engine/status")
async def get_engine_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    return {"status": cfg.get("engine_status", "unknown"), "kill_switch_active": cfg.get("kill_switch_active", False)}


@router.get("/engine/config")
async def get_engine_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return _load_engine_config()


@router.patch("/engine/config")
async def update_engine_config(body: EngineConfigBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    updates = body.model_dump(exclude_none=True)
    cfg.update(updates)
    _save_engine_config(cfg)
    try:
        from api.admin import apply_persisted_risk_settings

        apply_persisted_risk_settings()
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    _log_superadmin_action(user, "update_engine_config", str(list(updates.keys())))
    return {"ok": True}


@router.post("/engine/kill-switch")
async def toggle_kill_switch(body: KillSwitchBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["kill_switch_active"] = body.enabled
    cfg["engine_status"] = "stopped" if body.enabled else "running"
    _save_engine_config(cfg)
    cs = _get_config_store()
    if cs:
        cs.set("kill_switch_active", "1" if body.enabled else "0")
    try:
        from kill_switch import KillSwitch

        ks = KillSwitch()
        if body.enabled:
            ks.activate("Superadmin kill switch")
        else:
            ks.deactivate()
    except Exception as exc:
        logger.debug("kill_switch module: %s", exc)
    _log_superadmin_action(user, "kill_switch", str(body.enabled))
    return {"ok": True, "kill_switch_active": body.enabled}


@router.post("/engine/pause")
async def pause_trading(body: PauseBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["engine_status"] = "paused"
    _save_engine_config(cfg)
    _log_superadmin_action(user, "pause_trading", body.reason)
    return {"ok": True, "engine_status": "paused"}


@router.post("/engine/resume")
async def resume_trading(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["engine_status"] = "running"
    _save_engine_config(cfg)
    _log_superadmin_action(user, "resume_trading")
    return {"ok": True, "engine_status": "running"}


@router.get("/engine/metrics")
async def get_engine_metrics(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    metrics: dict = {
        "trades_today": 0,
        "open_positions": 0,
        "pnl_today": 0.0,
        "win_rate_today": 0.0,
        "avg_execution_ms": 0,
        "rejected_orders": 0,
        "kill_switch_triggers": 0,
        "uptime_hours": 0.0,
    }
    try:
        from api.admin import app_state, _start_time

        metrics["uptime_hours"] = round((time.time() - _start_time) / 3600, 2)
        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            metrics["open_positions"] = len(getattr(eng, "positions", {}))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return metrics
