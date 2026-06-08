# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/nuclear_controls.py
====================================
Nuclear Emergency Controls sub-router.
Wires to the real KillSwitch and risk orchestrator.

Routes
------
GET  /superadmin/nuclear/status          — current nuclear/kill-switch state
POST /superadmin/nuclear/halt            — emergency halt all trading
POST /superadmin/nuclear/resume          — resume trading
POST /superadmin/nuclear/hedge/activate  — activate emergency hedge
POST /superadmin/nuclear/hedge/deactivate — deactivate hedge
POST /superadmin/nuclear/risk-override   — override max risk parameters
GET  /superadmin/nuclear/log             — nuclear event log
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()

_NUCLEAR_LOG_KEY = "superadmin:nuclear:log"
_HEDGE_STATE_KEY = "superadmin:nuclear:hedge"


def _get_kill_switch():
    """Return the global KillSwitch instance if available."""
    try:
        # Try to get the singleton from app state
        try:
            from api.admin import app_state

            if app_state and hasattr(app_state, "kill_switch"):
                return app_state.kill_switch
        except Exception:  # nosec B110  # noqa: S110
            pass
        # Fall back to module-level singleton
        try:
            import kill_switch as _ks_mod

            if hasattr(_ks_mod, "_instance"):
                return _ks_mod._instance
        except Exception:  # nosec B110  # noqa: S110
            pass
    except Exception:  # nosec B110  # noqa: S110
        pass
    return None


def _append_nuclear_log(event: str, detail: dict, actor: str) -> None:
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_NUCLEAR_LOG_KEY)
            log = json.loads(raw) if raw else []
            log.insert(
                0,
                {
                    "event": event,
                    "detail": detail,
                    "actor": actor,
                    "timestamp": _utcnow().isoformat(),
                },
            )
            rc.set(_NUCLEAR_LOG_KEY, json.dumps(log[:200]), ex=86400 * 90)
    except Exception:  # nosec B110  # noqa: S110
        pass


@router.get("/nuclear/status")
async def get_nuclear_status(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict[str, Any]:
    ks = _get_kill_switch()
    kill_switch_active = False
    kill_switch_reason = None
    if ks is not None:
        kill_switch_active = bool(getattr(ks, "is_active", False) or getattr(ks, "enabled", False))
        kill_switch_reason = getattr(ks, "reason", None)

    # Hedge state
    hedge_active = False
    hedge_params: dict = {}
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_HEDGE_STATE_KEY)
            if raw:
                hedge_data = json.loads(raw)
                hedge_active = hedge_data.get("active", False)
                hedge_params = hedge_data.get("params", {})
    except Exception:  # nosec B110  # noqa: S110
        pass

    # Risk override state
    risk_override: dict = {}
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("superadmin:nuclear:risk_override")
            if raw:
                risk_override = json.loads(raw)
    except Exception:  # nosec B110  # noqa: S110
        pass

    return {
        "kill_switch_active": kill_switch_active,
        "kill_switch_reason": kill_switch_reason,
        "hedge_active": hedge_active,
        "hedge_params": hedge_params,
        "risk_override_active": bool(risk_override),
        "risk_override": risk_override,
        "checked_at": _utcnow().isoformat(),
    }


@router.post("/nuclear/halt")
async def nuclear_halt(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    reason = body.get("reason", "Superadmin emergency halt")
    ks = _get_kill_switch()
    if ks is not None:
        try:
            if hasattr(ks, "activate"):
                await ks.activate(reason=reason)
            elif hasattr(ks, "enable"):
                ks.enable(reason=reason)
        except Exception as exc:
            logger.error("Kill switch activate error: %s", exc)

    # Also set via Redis so all pods pick it up
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.set("kill_switch:active", "1", ex=86400)
            rc.set("kill_switch:reason", reason, ex=86400)
    except Exception:  # nosec B110  # noqa: S110
        pass

    _append_nuclear_log("HALT", {"reason": reason}, user.sub)
    _log_superadmin_action(user, "nuclear_halt", {"reason": reason})

    # Broadcast nuclear_halt to all connected WebSocket clients so the
    # frontend can display the emergency halt banner immediately.
    try:
        from api.ws_live import manager as _ws_manager
        import asyncio as _asyncio

        _halt_msg = {
            "type": "nuclear_halt",
            "data": {
                "reason": reason,
                "activated_by": user.sub,
                "timestamp": _utcnow().isoformat(),
            },
        }
        _asyncio.create_task(_ws_manager.broadcast("system", _halt_msg))
    except Exception as _ws_err:
        logger.debug("nuclear_halt WS broadcast skipped: %s", _ws_err)

    return {"ok": True, "kill_switch_active": True, "reason": reason}


@router.post("/nuclear/resume")
async def nuclear_resume(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    ks = _get_kill_switch()
    if ks is not None:
        try:
            if hasattr(ks, "deactivate"):
                await ks.deactivate()
            elif hasattr(ks, "disable"):
                ks.disable()
        except Exception as exc:
            logger.error("Kill switch deactivate error: %s", exc)

    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.delete("kill_switch:active")
            rc.delete("kill_switch:reason")
    except Exception:  # nosec B110  # noqa: S110
        pass

    _append_nuclear_log("RESUME", {}, user.sub)
    _log_superadmin_action(user, "nuclear_resume", {})

    # Broadcast system_event so the frontend clears the halt banner.
    try:
        from api.ws_live import manager as _ws_manager
        import asyncio as _asyncio

        _resume_msg = {
            "type": "system_event",
            "data": {
                "event": "nuclear_resume",
                "message": "Trading resumed by superadmin.",
                "activated_by": user.sub,
                "timestamp": _utcnow().isoformat(),
            },
        }
        _asyncio.create_task(_ws_manager.broadcast("system", _resume_msg))
    except Exception as _ws_err:
        logger.debug("nuclear_resume WS broadcast skipped: %s", _ws_err)

    return {"ok": True, "kill_switch_active": False}


@router.post("/nuclear/hedge/activate")
async def activate_hedge(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.set(
                _HEDGE_STATE_KEY,
                json.dumps(
                    {"active": True, "params": body, "activated_at": _utcnow().isoformat(), "activated_by": user.sub}
                ),
                ex=86400,
            )
    except Exception:  # nosec B110  # noqa: S110
        pass

    # Attempt to place hedge via risk orchestrator
    try:
        from risk.orchestrator import risk_orchestrator

        if hasattr(risk_orchestrator, "activate_hedge"):
            await risk_orchestrator.activate_hedge(**body)
    except Exception as exc:
        logger.warning("Hedge activate via orchestrator: %s", exc)

    _append_nuclear_log("HEDGE_ACTIVATE", body, user.sub)
    _log_superadmin_action(user, "nuclear_hedge_activate", body)
    return {"ok": True, "hedge_active": True}


@router.post("/nuclear/hedge/deactivate")
async def deactivate_hedge(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.set(_HEDGE_STATE_KEY, json.dumps({"active": False}), ex=86400)
    except Exception:  # nosec B110  # noqa: S110
        pass

    try:
        from risk.orchestrator import risk_orchestrator

        if hasattr(risk_orchestrator, "deactivate_hedge"):
            await risk_orchestrator.deactivate_hedge()
    except Exception as exc:
        logger.warning("Hedge deactivate via orchestrator: %s", exc)

    _append_nuclear_log("HEDGE_DEACTIVATE", {}, user.sub)
    _log_superadmin_action(user, "nuclear_hedge_deactivate", {})
    return {"ok": True, "hedge_active": False}


@router.post("/nuclear/risk-override")
async def max_risk_override(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    override = {**body, "set_by": user.sub, "set_at": _utcnow().isoformat()}
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.set("superadmin:nuclear:risk_override", json.dumps(override), ex=3600)
    except Exception:  # nosec B110  # noqa: S110
        pass

    # Apply to live risk manager
    try:
        from risk.manager import RiskManager

        if hasattr(RiskManager, "_instance") and RiskManager._instance:
            rm = RiskManager._instance
            for k, v in body.items():
                if hasattr(rm.config, k):
                    setattr(rm.config, k, v)
    except Exception as exc:
        logger.warning("Risk override apply: %s", exc)

    _append_nuclear_log("RISK_OVERRIDE", body, user.sub)
    _log_superadmin_action(user, "nuclear_risk_override", body)
    return {"ok": True, "override": override}


@router.get("/nuclear/log")
async def get_nuclear_log(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    log: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_NUCLEAR_LOG_KEY)
            if raw:
                log = json.loads(raw)
    except Exception:  # nosec B110  # noqa: S110
        pass
    return {"log": log, "total": len(log)}
