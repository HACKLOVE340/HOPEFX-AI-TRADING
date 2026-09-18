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

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload
from api.error_details import safe_error
from ._shared import require_superadmin_2fa, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()

_NUCLEAR_LOG_KEY = "superadmin:nuclear:log"
_HEDGE_STATE_KEY = "superadmin:nuclear:hedge"


#: Strong references to in-flight broadcast tasks.
#:
#: The event loop keeps only a WEAK reference to a task, so a bare
#: `asyncio.create_task(...)` whose result nobody holds may be garbage-collected
#: before it runs. For an emergency-halt banner that means the operator's
#: warning silently never appears. Tasks discard themselves on completion.
_BACKGROUND_TASKS: set = set()

#: How long to wait for the halt/resume banner before reporting it undelivered.
#: Short: an operator waiting on an emergency stop must not wait on a slow
#: WebSocket fan-out, but "we could not tell anyone" is worth knowing.
_BROADCAST_TIMEOUT_S = 2.0


async def _broadcast_or_report(channel: str, message: dict, *, what: str) -> str:
    """Send `message`, and say whether it arrived.

    Returns a leg status the caller puts in its response. Awaited rather than
    fired and forgotten: the caller is already async, and awaiting is the only
    way to report delivery truthfully.

    Failures log at ERROR, not DEBUG. These used to be
    `logger.debug("... broadcast skipped: %s", exc)` — and DEBUG is off in
    production, so a halt nobody was told about left no trace at all. A handler
    around a safety action logs louder, not quieter.
    """
    import asyncio as _asyncio

    try:
        from api.ws_live import get_live_manager

        coro = get_live_manager().broadcast(channel, message)
        task = _asyncio.ensure_future(coro)
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        await _asyncio.wait_for(_asyncio.shield(task), timeout=_BROADCAST_TIMEOUT_S)
        return "sent"
    except TimeoutError:
        # The task keeps running — it is still referenced — but we will not
        # hold the operator's response open waiting for it.
        logger.error("%s broadcast did not complete within %.1fs", what, _BROADCAST_TIMEOUT_S)
        return f"timeout after {_BROADCAST_TIMEOUT_S}s"
    except Exception as exc:
        logger.error("%s broadcast FAILED — no client was told: %s", what, exc, exc_info=True)
        return f"failed: {exc.__class__.__name__}"


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
        # Fall back to the module-level singleton. It is named `kill_switch`
        # (kill_switch.py) — this used to look for `_instance`, which exists
        # nowhere in that module, so together with the app_state branch above
        # (AppState defines no kill_switch attribute) this function returned
        # None on every call and the in-process kill switch was never touched.
        try:
            import kill_switch as _ks_mod

            return getattr(_ks_mod, "kill_switch", None)
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
    user: TokenPayload = Depends(require_superadmin_2fa),
) -> dict[str, Any]:
    ks = _get_kill_switch()
    kill_switch_active = False
    kill_switch_reason = None
    if ks is not None:
        # is_active is a method: bool(bound method) is always True, so this
        # reported every kill switch as active once resolution started working.
        _is_active = getattr(ks, "is_active", None)
        kill_switch_active = bool(_is_active()) if callable(_is_active) else bool(getattr(ks, "enabled", False))
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
    user: TokenPayload = Depends(require_superadmin_2fa),
) -> dict:
    # This handler used to end in an unconditional
    #
    #     return {"ok": True, "kill_switch_active": True, "reason": reason}
    #
    # reached by four paths that halted nothing: no kill switch resolved
    # (`if ks is not None` skipped everything), activation raised, the
    # cross-pod Redis write failed inside `except Exception: pass`, or there
    # was no Redis client at all. This is the control of last resort, and it
    # reported success for work that did not happen.
    #
    # Each leg now returns its own outcome and the response carries them, so an
    # operator can see WHICH parts of the fleet actually stopped.
    reason = body.get("reason", "Superadmin emergency halt")
    legs: dict[str, str] = {}
    warnings: list[str] = []

    # ── Leg 1: this pod ──────────────────────────────────────────────────────
    ks = _get_kill_switch()
    local_halted = False
    if ks is None:
        legs["local"] = "no_switch"
        warnings.append("No kill switch is available in this process — nothing was halted locally.")
        logger.error("nuclear_halt: no kill switch available; NOTHING was halted locally")
    else:
        try:
            # activate() is synchronous — awaiting its None return raises
            # TypeError, which the handler below logged as an activation error.
            if hasattr(ks, "activate"):
                ks.activate(reason)
            elif hasattr(ks, "enable"):
                ks.enable(reason=reason)
            else:
                raise AttributeError("kill switch exposes neither activate() nor enable()")
            local_halted = True
            legs["local"] = "activated"
        except Exception as exc:
            legs["local"] = f"failed: {exc.__class__.__name__}"
            warnings.append(f"Local kill switch did NOT activate: {safe_error(exc)}")
            logger.error("Kill switch activate error: %s", exc, exc_info=True)

    # ── Leg 2: every other pod ───────────────────────────────────────────────
    # This is the leg whose silent failure was most dangerous: the local halt
    # works, so nothing looks wrong, and the rest of the fleet keeps trading
    # until somebody notices a fill.
    propagated = False
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc is None:
            legs["propagation"] = "no_client"
            warnings.append("No Redis client — the halt did NOT propagate. Other pods are still trading.")
            logger.error("nuclear_halt: no Redis client; halt did NOT propagate to other pods")
        else:
            rc.set("kill_switch:active", "1", ex=86400)
            rc.set("kill_switch:reason", reason, ex=86400)
            propagated = True
            legs["propagation"] = "written"
    except Exception as exc:
        legs["propagation"] = f"failed: {exc.__class__.__name__}"
        warnings.append(
            f"The halt did NOT propagate to other pods ({safe_error(exc)}). "
            "Halt them directly before assuming trading has stopped."
        )
        logger.error("nuclear_halt: cross-pod propagation FAILED: %s", exc, exc_info=True)

    _append_nuclear_log("HALT", {"reason": reason, "legs": legs}, user.sub)
    _log_superadmin_action(user, "nuclear_halt", {"reason": reason, "legs": legs})

    # ── Leg 3: tell everyone watching ────────────────────────────────────────
    legs["broadcast"] = await _broadcast_or_report(
        "system",
        {
            "type": "nuclear_halt",
            "data": {
                "reason": reason,
                "activated_by": user.sub,
                "timestamp": _utcnow().isoformat(),
            },
        },
        what="nuclear_halt",
    )

    anything_halted = local_halted or propagated
    if not anything_halted:
        # The emergency control did not function at all. A 200 here would be
        # the worst possible answer.
        raise HTTPException(
            status_code=500,
            detail={
                "message": "EMERGENCY HALT FAILED — nothing was halted. Stop trading manually.",
                "legs": legs,
                "warnings": warnings,
            },
        )

    return {
        "ok": local_halted and propagated,
        "kill_switch_active": anything_halted,
        "reason": reason,
        "legs": legs,
        "warnings": warnings,
    }


@router.post("/nuclear/resume")
async def nuclear_resume(
    user: TokenPayload = Depends(require_superadmin_2fa),
) -> dict:
    # Held to the same standard as the halt, and worth as much in the other
    # direction: a resume that clears this pod but not Redis leaves the rest of
    # the fleet halted while the operator believes trading is back, and they
    # find out from a fill that never arrives.
    legs: dict[str, str] = {}
    warnings: list[str] = []

    ks = _get_kill_switch()
    local_cleared = False
    if ks is None:
        legs["local"] = "no_switch"
        warnings.append("No kill switch in this process — nothing was cleared locally.")
        logger.error("nuclear_resume: no kill switch available; nothing cleared locally")
    else:
        try:
            # deactivate() is synchronous — see the note in nuclear_halt.
            if hasattr(ks, "deactivate"):
                ks.deactivate()
            elif hasattr(ks, "disable"):
                ks.disable()
            else:
                raise AttributeError("kill switch exposes neither deactivate() nor disable()")
            local_cleared = True
            legs["local"] = "cleared"
        except Exception as exc:
            legs["local"] = f"failed: {exc.__class__.__name__}"
            warnings.append(f"Local kill switch did NOT clear: {safe_error(exc)}")
            logger.error("Kill switch deactivate error: %s", exc, exc_info=True)

    propagated = False
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc is None:
            legs["propagation"] = "no_client"
            warnings.append("No Redis client — other pods remain halted.")
            logger.error("nuclear_resume: no Redis client; other pods remain halted")
        else:
            rc.delete("kill_switch:active")
            rc.delete("kill_switch:reason")
            propagated = True
            legs["propagation"] = "cleared"
    except Exception as exc:
        legs["propagation"] = f"failed: {exc.__class__.__name__}"
        warnings.append(f"The resume did NOT propagate ({safe_error(exc)}). Other pods remain halted.")
        logger.error("nuclear_resume: cross-pod propagation FAILED: %s", exc, exc_info=True)

    _append_nuclear_log("RESUME", {"legs": legs}, user.sub)
    _log_superadmin_action(user, "nuclear_resume", {"legs": legs})

    legs["broadcast"] = await _broadcast_or_report(
        "system",
        {
            "type": "system_event",
            "data": {
                "event": "nuclear_resume",
                "message": "Trading resumed by superadmin.",
                "activated_by": user.sub,
                "timestamp": _utcnow().isoformat(),
            },
        },
        what="nuclear_resume",
    )

    return {
        "ok": local_cleared and propagated,
        "kill_switch_active": not (local_cleared and propagated),
        "legs": legs,
        "warnings": warnings,
    }


@router.post("/nuclear/hedge/activate")
async def activate_hedge(
    body: dict,
    user: TokenPayload = Depends(require_superadmin_2fa),
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
    user: TokenPayload = Depends(require_superadmin_2fa),
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
    user: TokenPayload = Depends(require_superadmin_2fa),
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
    user: TokenPayload = Depends(require_superadmin_2fa),
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
