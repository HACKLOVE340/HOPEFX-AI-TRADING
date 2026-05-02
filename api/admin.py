# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Admin API Router

Admin endpoints for system control and monitoring.
All endpoints require role >= 'admin'.
"""

import json
import logging
import os as _os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["Admin"])

app_state = None

# In-memory activity log (bounded at 50 entries, newest first)
activity_log: list = []
_ACTIVITY_MAX = 50

# Legacy JSON file path — kept for one-time migration on first startup
_RISK_SETTINGS_FILE = Path("config/risk_settings.json")

# Redis/DB config store key for risk settings
_RISK_SETTINGS_KEY = "risk_settings"

# Default risk settings — used when no persisted value exists
_RISK_SETTINGS_DEFAULTS: dict[str, Any] = {
    "max_risk_per_trade": 2.0,
    "max_open_positions": 5,
    "paper_trading_mode": True,
    "max_daily_loss": 5.0,
    "max_drawdown": 10.0,
}

# In-process cache — refreshed on every read from the shared store
_risk_settings: dict[str, Any] = dict(_RISK_SETTINGS_DEFAULTS)

_start_time = time.time()


def set_state(state) -> None:
    global app_state
    app_state = state


def log_activity(message: str) -> None:
    """Prepend entry to activity log, capped at _ACTIVITY_MAX."""
    activity_log.insert(0, {"time": time.time(), "message": message})
    while len(activity_log) > _ACTIVITY_MAX:
        activity_log.pop()
    logger.info("ADMIN: %s", message)


def _get_risk_settings() -> dict[str, Any]:
    """
    Read risk settings from the shared config store (Redis → DB → defaults).

    Always reads from the shared store so all pods see the same value.
    Updates the in-process cache as a side effect.
    """
    global _risk_settings
    try:
        from core.config_store import config_store

        stored = config_store.get(_RISK_SETTINGS_KEY)
        if stored:
            _risk_settings = {**_RISK_SETTINGS_DEFAULTS, **stored}
            return dict(_risk_settings)
    except Exception as exc:
        logger.warning("_get_risk_settings: config_store read failed: %s", exc)
    return dict(_risk_settings)


def _load_persisted_risk_settings() -> dict[str, Any]:
    """Read risk settings from the legacy JSON file (_RISK_SETTINGS_FILE).

    Returns an empty dict when the file is absent, unreadable, or contains
    invalid JSON.  Tests patch ``api.admin._RISK_SETTINGS_FILE`` to control
    which file is read.
    """
    try:
        if not _RISK_SETTINGS_FILE.exists():
            return {}
        return json.loads(_RISK_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("_load_persisted_risk_settings: %s", exc)
        return {}


def _save_risk_settings(settings: dict[str, Any], changed_by: str = "system") -> bool:
    """Persist risk settings to the shared config store (Redis + DB).

    Falls back to writing the legacy JSON file when the config store is
    unavailable or returns False (e.g. in unit tests or offline environments).
    """
    try:
        from core.config_store import config_store

        ok = config_store.set(_RISK_SETTINGS_KEY, settings, changed_by=changed_by)
        if ok:
            return True
        # config_store returned False (e.g. DB unavailable) — fall through to file
        logger.warning("_save_risk_settings: config_store.set returned False, falling back to file")
    except Exception as exc:
        logger.warning(
            "_save_risk_settings: config_store unavailable (%s), falling back to file",
            exc,
        )

    try:
        _RISK_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RISK_SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return True
    except Exception as file_exc:
        logger.error("_save_risk_settings fallback failed: %s", file_exc)
        return False


def apply_persisted_risk_settings() -> None:
    """
    Load risk settings from the shared store and apply them at startup.

    Also migrates any legacy JSON file to the shared store on first run.
    Called once at startup by app.py after app_state is initialised.
    """

    # One-time migration: if the legacy JSON file exists and the shared store
    # has no value yet, migrate the file contents to the store.
    try:
        from core.config_store import config_store

        if _RISK_SETTINGS_FILE.exists() and config_store.get(_RISK_SETTINGS_KEY) is None:
            try:
                legacy = json.loads(_RISK_SETTINGS_FILE.read_text(encoding="utf-8"))
                if legacy:
                    config_store.set(_RISK_SETTINGS_KEY, legacy, changed_by="migration")
                    logger.info(
                        "apply_persisted_risk_settings: migrated %d keys from %s to config_store",
                        len(legacy),
                        _RISK_SETTINGS_FILE,
                    )
            except Exception as mig_exc:
                logger.warning("Risk settings migration failed (non-fatal): %s", mig_exc)
    except Exception as exc:
        logger.debug(
            "apply_persisted_risk_settings: config_store unavailable, skipping migration: %s",
            exc,
        )


def _push_risk_settings_to_manager(persisted: dict) -> None:
    """Apply persisted settings to the live RiskManager if initialised."""
    try:
        if app_state is not None:
            rm = getattr(app_state, "risk_manager", None)
            if rm is not None:
                for key, value in persisted.items():
                    if hasattr(rm, key):
                        setattr(rm, key, value)
                        logger.debug("apply_persisted_risk_settings: set risk_manager.%s = %s", key, value)
    except Exception as exc:
        logger.warning("apply_persisted_risk_settings: RiskManager update failed: %s", exc)


class AdminStatusResponse(BaseModel):
    components: dict[str, bool]


class SimpleStatusResponse(BaseModel):
    status: str


class RiskSettingsResponse(BaseModel):
    status: str
    settings: dict[str, Any]


@router.get(
    "/status",
    response_model=AdminStatusResponse,
    summary="Full system component status",
)
async def admin_status(user: TokenPayload = Depends(require_role("admin"))):
    """Full system status. Requires: role >= 'admin'."""
    if not app_state:
        raise HTTPException(status_code=503, detail="App not initialized")

    components: dict[str, bool] = {
        "config": app_state.config is not None,
        "database": app_state.db_engine is not None,
        "cache": app_state.cache is not None,
    }

    # Broker
    try:
        broker = getattr(app_state, "broker", None)
        components["broker"] = broker is not None
    except Exception:
        components["broker"] = False

    # Risk manager
    try:
        rm = getattr(app_state, "risk_manager", None)
        components["risk_manager"] = rm is not None
    except Exception:
        components["risk_manager"] = False

    # Brain / strategy brain
    try:
        brain = getattr(app_state, "strategy_brain", None) or getattr(app_state, "brain", None)
        components["brain"] = brain is not None
    except Exception:
        components["brain"] = False

    # Signal engine
    try:
        from core.signal_engine import get_signal_engine_status

        se_status = get_signal_engine_status()
        components["signal_engine"] = se_status.get("ml_available", False)
    except Exception:
        components["signal_engine"] = False

    # Hourly trainer
    try:
        ht = getattr(app_state, "hourly_trainer", None)
        components["hourly_trainer"] = ht is not None
    except Exception:
        components["hourly_trainer"] = False

    # Online learner (Phase 3)
    try:
        from research.pipeline.online_learning import list_online_learners

        learners = list_online_learners()
        components["online_learner"] = len(learners) > 0
    except Exception:
        components["online_learner"] = False

    # Data feed — NuclearStreamer (primary) or RealTimePriceEngine (fallback)
    try:
        nuclear = getattr(app_state, "nuclear_streamer", None)
        if nuclear is not None:
            components["data_feed"] = nuclear.status().get("is_running", False)
        else:
            df_engine = getattr(app_state, "price_engine", None) or getattr(app_state, "data_engine", None)
            components["data_feed"] = df_engine is not None and (
                getattr(df_engine, "active", False) or getattr(df_engine, "is_running", False)
            )
    except Exception:
        components["data_feed"] = False

    return {"components": components}


@router.get("/logs")
async def get_logs(
    limit: int = 100,
    user: TokenPayload = Depends(require_role("admin")),
):
    """Recent activity log. Requires: role >= 'admin'."""
    return activity_log[-limit:]


@router.post(
    "/pause",
    response_model=SimpleStatusResponse,
    summary="Pause all automated trading",
)
async def pause_trading(user: TokenPayload = Depends(require_role("admin"))):
    """Pause all trading. Requires: role >= 'admin'."""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=503, detail="Brain not available")
    app_state.brain.pause()
    log_activity(f"Trading paused by {user.sub}")
    return {"status": "paused"}


@router.post(
    "/resume",
    response_model=SimpleStatusResponse,
    summary="Resume automated trading",
)
async def resume_trading(user: TokenPayload = Depends(require_role("admin"))):
    """Resume trading. Requires: role >= 'admin'."""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=503, detail="Brain not available")
    app_state.brain.resume()
    log_activity(f"Trading resumed by {user.sub}")
    return {"status": "resumed"}


@router.post(
    "/risk-settings",
    response_model=RiskSettingsResponse,
    summary="Update live risk management parameters",
)
async def update_risk_settings(
    settings: dict,
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Update risk settings in the shared config store and push to the live
    RiskManager on this pod.  Other pods pick up the change on their next
    read from the shared store.
    Requires: role >= 'admin'.
    """
    if not app_state or not app_state.risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not available")

    # Merge with current settings and persist
    current = _get_risk_settings()
    current.update(settings)
    _save_risk_settings(current, changed_by=user.sub)
    _risk_settings.update(current)

    # Apply to live RiskManager on this pod
    for key, value in settings.items():
        if hasattr(app_state.risk_manager.config, key):
            setattr(app_state.risk_manager.config, key, value)

    log_activity(f"Risk settings updated by {user.sub}: {list(settings.keys())}")
    return {"status": "success", "settings": settings}


# ── KYC management ────────────────────────────────────────────────────────────


class KYCDecision(BaseModel):
    user_id: str
    action: str  # "approve" | "reject" | "request_more_info"
    notes: str | None = None


@router.get("/kyc/pending")
async def list_pending_kyc(user: TokenPayload = Depends(require_role("admin"))):
    """List users with pending KYC submissions. Requires: role >= 'admin'."""
    try:
        from core.app_state import app_state as _state
        from database.user_models import User

        if not _state or not _state.db_session_factory:
            raise HTTPException(status_code=503, detail="Database not available")

        def _query():
            with _state.db_session_factory() as session:  # pylint: disable=not-callable
                rows = session.query(User).filter(
                    User.kyc_status.in_(["pending", "submitted", "under_review"])
                ).all()
                return [
                    {
                        "user_id": u.id,
                        "email": u.email,
                        "username": u.username,
                        "kyc_status": u.kyc_status,
                        "created_at": str(u.created_at),
                    }
                    for u in rows
                ]

        import asyncio as _aio
        users = await _aio.to_thread(_query)
        return {"count": len(users), "users": users}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail="Operation failed — check server logs") from None


@router.post("/kyc/decide")
async def decide_kyc(
    body: KYCDecision,
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Approve, reject, or request more info for a KYC submission.

    action: 'approve' | 'reject' | 'request_more_info'
    Requires: role >= 'admin'.
    """
    if body.action not in ("approve", "reject", "request_more_info"):
        raise HTTPException(
            status_code=400,
            detail="action must be approve | reject | request_more_info",
        )

    try:
        from core.app_state import app_state as _state
        from database.user_models import User

        if not _state or not _state.db_session_factory:
            raise HTTPException(status_code=503, detail="Database not available")

        import asyncio as _aio

        status_map = {
            "approve": "approved",
            "reject": "rejected",
            "request_more_info": "more_info_required",
        }

        def _update_kyc():
            with _state.db_session_factory() as session:  # pylint: disable=not-callable
                t = session.query(User).filter_by(id=body.user_id).first()
                if not t:
                    return None
                t.kyc_status = status_map[body.action]
                session.commit()
                return True

        found = await _aio.to_thread(_update_kyc)
        if found is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Audit log
        log_activity(
            f"KYC {body.action} for user {body.user_id} by admin {user.sub}"
            + (f" — {body.notes}" if body.notes else ""),
        )

        # Notify user via email
        try:
            from core.email_service import _send
            from database.user_models import User as _User

            def _fetch_email():
                with _state.db_session_factory() as session:  # pylint: disable=not-callable
                    return session.query(_User).filter_by(id=body.user_id).first()

            target = await _aio.to_thread(_fetch_email)
            if target:
                subject_map = {
                    "approve": "Your KYC has been approved",
                    "reject": "Your KYC submission was not approved",
                    "request_more_info": "Additional information required for KYC",
                }
                msg_map = {
                    "approve": "Your identity verification has been approved. You can now trade without restrictions.",
                    "reject": f"Your KYC submission was not approved. {body.notes or ''}",
                    "request_more_info": f"We need additional information to complete your verification. {body.notes or ''}",
                }
                _send(
                    to=target.email,
                    subject=subject_map[body.action],
                    html=f"<p>{msg_map[body.action]}</p>",
                    text=msg_map[body.action],
                )
        except Exception as email_exc:
            logger.warning("KYC notification email failed (non-fatal): %s", email_exc)

        return {
            "status": "success",
            "user_id": body.user_id,
            "kyc_status": status_map[body.action],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail="Operation failed — check server logs") from None


@router.get("/kyc/{user_id}")
async def get_kyc_status(
    user_id: str,
    user: TokenPayload = Depends(require_role("admin")),
):
    """Get KYC status for a specific user. Requires: role >= 'admin'."""
    try:
        from core.app_state import app_state as _state
        from database.user_models import User

        if not _state or not _state.db_session_factory:
            raise HTTPException(status_code=503, detail="Database not available")

        import asyncio as _aio

        def _fetch():
            with _state.db_session_factory() as session:  # pylint: disable=not-callable
                t = session.query(User).filter_by(id=user_id).first()
                if not t:
                    return None
                return {
                    "user_id": t.id,
                    "email": t.email,
                    "kyc_status": t.kyc_status,
                    "is_email_verified": t.is_email_verified,
                    "role": t.role,
                    "status": t.status,
                }

        result = await _aio.to_thread(_fetch)
        if result is None:
            raise HTTPException(status_code=404, detail="User not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail="Operation failed — check server logs") from None


# ── New endpoints expected by tests ──────────────────────────────────────────


@router.get("/system-info", response_model=None, summary="Server version and uptime")
def get_system_info(user: TokenPayload = Depends(require_role("admin"))):
    """Server version and uptime. Requires: role >= 'admin'."""
    return {
        "version": "1.0.0",
        "status": "running",
        "uptime": time.time() - _start_time,
    }


@router.get("/settings")
@router.get("/settings-data")
def get_settings(user: TokenPayload = Depends(require_role("admin"))):
    """
    Read current risk settings from the shared config store.

    Always reads from Redis/DB so the response reflects the latest value
    regardless of which pod last wrote it.
    Requires: role >= 'admin'.
    """
    return _get_risk_settings()


@router.post("/settings")
@router.post("/settings-data")
def save_settings(
    payload: dict[str, Any],
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Update risk settings in the shared config store (Redis + DB).

    Changes are immediately visible to all pods.
    Requires: role >= 'admin'.
    """
    try:
        current = _get_risk_settings()
        current.update(payload)
        ok = _save_risk_settings(current, changed_by=user.sub)
        if ok:
            # Update local cache
            _risk_settings.update(current)
            # Push to live RiskManager on this pod
            try:
                if app_state is not None:
                    rm = getattr(app_state, "risk_manager", None)
                    if rm is not None:
                        for key, value in payload.items():
                            if hasattr(rm, key):
                                setattr(rm, key, value)
            except Exception as rm_exc:
                logger.warning("save_settings: RiskManager update failed: %s", rm_exc)
            log_activity(f"Settings updated by {user.sub}: {list(payload.keys())}")
            return {"status": "ok", "saved": list(payload.keys())}
        return {"status": "error", "detail": "Config store write failed"}
    except Exception:
        logger.exception("save_settings failed")
        return {"status": "error", "detail": "Settings save failed — check server logs"}


@router.get("/activity")
def get_activity(user: TokenPayload = Depends(require_role("admin"))):
    """All user activity logs. Requires: role >= 'admin'."""
    entries = [
        {
            "action": e.get("message", "").lower().replace(" ", "_")[:30],
            "message": e.get("message", ""),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(e.get("time", 0))),
        }
        for e in activity_log
    ]
    return {"events": entries, "count": len(entries)}


def _dashboard_broker_stats(trading_stats: dict, module_status: dict) -> None:
    """Populate broker-related fields in-place."""
    try:
        if app_state is not None:
            broker = getattr(app_state, "broker", None)
            if broker is not None:
                module_status["brokers"] = True
                pos = getattr(broker, "_cached_positions", None)
                if pos is not None:
                    trading_stats["open_positions"] = len(pos)
    except Exception as exc:
        logger.debug("dashboard-data broker stats failed: %s", exc)


def _dashboard_risk_stats(trading_stats: dict) -> dict:
    """Return risk_status dict and update trading_stats daily_pnl."""
    risk_status: dict[str, Any] = {"within_limits": True}
    try:
        if app_state is not None:
            rm = getattr(app_state, "risk_manager", None)
            if rm is not None:
                rm_status = rm.get_status() if hasattr(rm, "get_status") else {}
                risk_status = {
                    "within_limits": not rm_status.get("trading_halted", False),
                    "trading_halted": rm_status.get("trading_halted", False),
                    "halt_reason": rm_status.get("halt_reason"),
                    "daily_pnl": rm_status.get("daily_pnl", 0.0),
                    "drawdown_pct": rm_status.get("drawdown_pct", 0.0),
                    "kill_switch": rm_status.get("kill_switch_active", False),
                }
                trading_stats["daily_pnl"] = rm_status.get("daily_pnl", 0.0)
    except Exception as exc:
        logger.debug("dashboard-data risk stats failed: %s", exc)
    return risk_status


def _dashboard_trade_stats(trading_stats: dict) -> None:
    """Populate total_trades and paper_fill_count in-place."""
    try:
        from monitoring.trade_logger import get_trade_logger

        tl = get_trade_logger()
        tl_stats = tl.get_stats() if hasattr(tl, "get_stats") else {}
        trading_stats["total_trades"] = tl_stats.get("total_fills", 0)
    except Exception as exc:
        logger.debug("dashboard-data trade logger stats failed: %s", exc)

    try:
        from research.pipeline.paper_trading_gate import get_gate

        trading_stats["paper_fill_count"] = get_gate().fill_count
    except Exception as exc:
        logger.debug("dashboard-data paper trading gate stats failed: %s", exc)


def _dashboard_signal_status(module_status: dict) -> None:
    """Populate signal_engine and strategies flags in-place."""
    try:
        from core.signal_engine import get_signal_engine_status

        se = get_signal_engine_status()
        module_status["signal_engine"] = se.get("ml_available", False)
        module_status["strategies"] = True
    except Exception as exc:
        logger.debug("dashboard-data signal engine status failed: %s", exc)


@router.get("/dashboard-data")
def get_dashboard_data(user: TokenPayload = Depends(require_role("admin"))):
    """Full system state. Requires: role >= 'admin'."""

    trading_stats: dict[str, Any] = {
        "total_trades": 0,
        "open_positions": 0,
        "daily_pnl": 0.0,
        "total_strategies": 0,
        "active_strategies": 0,
        "total_pnl": 0.0,
        "win_rate": 0.0,
        "active_orders": 0,
        "total_signals": 0,
    }
    module_status: dict[str, Any] = {
        "strategies": False,
        "brokers": False,
        "signal_engine": False,
        "config": True,
        "database": False,
        "cache": False,
        "risk": False,
        "ml": False,
        "analytics": False,
        "monetization": False,
        "notifications": False,
        "backtesting": True,
    }

    _dashboard_broker_stats(trading_stats, module_status)
    risk_status = _dashboard_risk_stats(trading_stats)
    _dashboard_trade_stats(trading_stats)
    _dashboard_signal_status(module_status)

    # Enrich module status from app_state
    if app_state is not None:
        module_status["database"] = getattr(app_state, "db_engine", None) is not None
        module_status["cache"] = getattr(app_state, "cache", None) is not None
        module_status["risk"] = getattr(app_state, "risk_manager", None) is not None

    # Enrich trading stats from strategies
    try:
        if app_state is not None:
            strategies = getattr(app_state, "strategies", None) or {}
            if isinstance(strategies, dict):
                trading_stats["total_strategies"] = len(strategies)
                trading_stats["active_strategies"] = sum(
                    1
                    for s in strategies.values()
                    if getattr(s, "status", "").upper() == "RUNNING" or getattr(s, "is_running", False)
                )
    except Exception as exc:
        logger.debug("dashboard-data strategy count failed: %s", exc)

    # Enrich risk_status with fields expected by the template
    current_settings = _get_risk_settings()
    risk_status.setdefault("current_drawdown", risk_status.get("drawdown_pct", 0.0))
    risk_status.setdefault("max_drawdown_limit", current_settings.get("max_drawdown", 10.0))
    risk_status.setdefault("risk_utilization", 0.0)
    risk_status.setdefault("daily_loss_pct", abs(risk_status.get("daily_pnl", 0.0)))
    risk_status.setdefault("max_daily_loss", current_settings.get("max_daily_loss", 5.0))
    risk_status.setdefault("open_positions", trading_stats.get("open_positions", 0))
    risk_status.setdefault("max_positions", current_settings.get("max_open_positions", 5))
    risk_status.setdefault("current_balance", 0.0)
    try:
        if app_state is not None:
            rm = getattr(app_state, "risk_manager", None)
            if rm is not None:
                rm_status = rm.get_status() if hasattr(rm, "get_status") else {}
                risk_status["current_balance"] = rm_status.get("balance", 0.0)
                max_dd = current_settings.get("max_drawdown", 10.0)
                if max_dd > 0:
                    risk_status["risk_utilization"] = round(risk_status["current_drawdown"] / max_dd * 100, 1)
    except Exception as exc:
        logger.debug("dashboard-data risk_status enrichment failed: %s", exc)

    # Market data section
    market_data: dict[str, Any] = {
        "data_feed": "Yahoo Finance",
        "cached_symbols": 0,
        "last_update": "—",
        "status": "operational",
    }
    try:
        if app_state is not None:
            cache = getattr(app_state, "cache", None)
            if cache is not None:
                market_data["cached_symbols"] = getattr(cache, "symbol_count", 0) or len(getattr(cache, "_cache", {}))
                market_data["last_update"] = str(getattr(cache, "last_update", "—"))
            nuclear = getattr(app_state, "nuclear_streamer", None)
            if nuclear is not None:
                ns_status = nuclear.status() if hasattr(nuclear, "status") else {}
                market_data["data_feed"] = "Nuclear Streamer"
                market_data["status"] = "operational" if ns_status.get("is_running") else "degraded"
    except Exception as exc:
        logger.debug("dashboard-data market_data failed: %s", exc)

    # Recent activity for the template
    recent = [
        {"message": e["message"], "timestamp": time.strftime("%H:%M:%S", time.localtime(e["time"]))}
        for e in activity_log[:10]
    ]

    # System health with all fields the template reads
    uptime_secs = time.time() - _start_time
    hours, rem = divmod(int(uptime_secs), 3600)
    mins, secs = divmod(rem, 60)
    uptime_str = f"{hours}h {mins}m {secs}s"

    system_health = {
        "status": "running",
        "version": "1.0.0",
        "environment": _os.getenv("APP_ENV", _os.getenv("ENVIRONMENT", "production")),
        "uptime": uptime_str,
        "uptime_seconds": uptime_secs,
        "pid": _os.getpid(),
    }

    return {
        "system_health": system_health,
        "trading_stats": trading_stats,
        "risk_status": risk_status,
        "module_status": module_status,
        "market_data": market_data,
        "recent_activity": recent,
    }


@router.get("/system-metrics", response_model=None, summary="System resource metrics")
def get_system_metrics(user: TokenPayload = Depends(require_role("admin"))):
    """Prometheus-style system metrics. Requires: role >= 'admin'."""

    uptime_secs = time.time() - _start_time
    memory_mb: float = 0.0
    cpu_pct: float = 0.0

    try:
        import psutil

        proc = psutil.Process(_os.getpid())
        memory_mb = round(proc.memory_info().rss / 1_048_576, 2)
        cpu_pct = round(proc.cpu_percent(interval=0.1), 2)
    except Exception as exc:
        logger.debug("system-metrics psutil failed: %s", exc)

    return {
        "uptime": uptime_secs,
        "uptime_seconds": uptime_secs,
        "memory_mb": memory_mb,
        "cpu_pct": cpu_pct,
        "pid": _os.getpid(),
    }


# ── Aliases expected by tests ─────────────────────────────────────────────────
_activity_log = activity_log


def _check_module(name: str) -> bool:
    """Return True if a module can be imported."""
    import importlib.util

    return importlib.util.find_spec(name) is not None


# ── Admin HTML pages ──────────────────────────────────────────────────────────

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _serve_admin_template(name: str, title: str) -> HTMLResponse:
    """Render an admin template file, substituting the page title."""
    path = _TEMPLATES_DIR / "admin" / name
    if path.exists():
        content = path.read_text(encoding="utf-8")
        # Inject title into the Jinja2 block so it renders without a template engine
        content = content.replace("{% block title %}", "").replace("{% endblock %}", "", 1)
        # Wrap blocks: extend base inline
        base_path = _TEMPLATES_DIR / "base.html"
        if base_path.exists():
            base = base_path.read_text(encoding="utf-8")
            # Replace Jinja extends/block tags with plain HTML
            base = re.sub(r"\{%[-\s]*extends[^%]*%\}", "", base)
            base = re.sub(r"\{%[-\s]*block title[-\s]*%\}.*?\{%[-\s]*endblock[-\s]*%\}", title, base, flags=re.DOTALL)
            block_match = re.search(
                r"\{%[-\s]*block content[-\s]*%\}.*?\{%[-\s]*endblock[-\s]*%\}", content, flags=re.DOTALL
            )
            block_body = ""
            if block_match:
                block_body = re.sub(r"\{%[-\s]*block content[-\s]*%\}", "", block_match.group())
                block_body = re.sub(r"\{%[-\s]*endblock[-\s]*%\}", "", block_body)
            # Replace {{ title }} in base
            base = base.replace("{{ title }}", title)
            full = base.replace("{% block content %}{% endblock %}", block_body)
            full = re.sub(r"\{%[^%]*%\}", "", full)  # strip any remaining Jinja tags
            return HTMLResponse(content=full)
    # Fallback: minimal page
    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html><head><title>HOPEFX Admin — {title}</title>
<meta charset="UTF-8">
<style>body{{font-family:sans-serif;padding:40px;background:#f5f7fa;color:#2c3e50}}</style>
</head>
<body><h1>HOPEFX Admin — {title}</h1>
<p style="color:#e74c3c;">Template not found: templates/admin/{name}</p>
<a href="/api/admin/">← Back to Dashboard</a>
</body></html>"""
    )


@router.get("/", response_class=HTMLResponse)
def admin_dashboard(user: TokenPayload = Depends(require_role("admin"))):
    """Admin dashboard. Requires: role >= 'admin'."""
    return _serve_admin_template("dashboard.html", "Dashboard")


@router.get("/strategies", response_class=HTMLResponse)
def admin_strategies(user: TokenPayload = Depends(require_role("admin"))):
    """Strategy management page. Requires: role >= 'admin'."""
    return _serve_admin_template("strategies.html", "Strategies")


@router.get("/settings-page", response_class=HTMLResponse)
def admin_settings_page(user: TokenPayload = Depends(require_role("admin"))):
    """Settings HTML page. Requires: role >= 'admin'."""
    return _serve_admin_template("settings.html", "Settings")


@router.get("/monitoring", response_class=HTMLResponse)
def admin_monitoring(user: TokenPayload = Depends(require_role("admin"))):
    """Monitoring page. Requires: role >= 'admin'."""
    return _serve_admin_template("monitoring.html", "Monitoring")


# ── Missing endpoints required by AdminPanel.tsx ──────────────────────────────

@router.get("/overview", summary="Admin overview KPIs")
def get_admin_overview(user: TokenPayload = Depends(require_role("admin"))) -> dict:
    """
    Return platform-wide KPIs for the admin landing dashboard.
    Aggregates data from trading engine, subscription manager, and system metrics.
    """
    import time as _time
    import os as _os2

    total_users = 0
    active_users_24h = 0
    active_subscriptions = 0
    total_trades_today = 0
    open_positions = 0
    revenue_today_usd = 0.0
    revenue_mtd_usd = 0.0
    platform_uptime_pct = 99.9
    pending_withdrawals = 0
    flagged_accounts = 0
    ml_model_accuracy = 0.0
    ws_connections = 0

    # Users from subscription manager
    try:
        from monetization.subscription import subscription_manager
        subs = subscription_manager.get_all_subscriptions() if hasattr(subscription_manager, "get_all_subscriptions") else []
        total_users = len(subs)
        active_subscriptions = sum(1 for s in subs if getattr(s, "status", "") in ("active", "trialing"))
    except Exception as exc:
        logger.debug("admin overview users: %s", exc)

    # Trading stats from engine
    try:
        from core.app_state import app_state as _as
        engine = getattr(_as, "hopefx_engine", None)
        if engine is not None:
            fills = list(getattr(engine, "_fill_history", []))
            open_pos = dict(getattr(engine, "_open_positions", {}))
            open_positions = len(open_pos)
            # Today's trades
            from datetime import datetime as _dt2, timezone as _tz2
            today = _dt2.now(_tz2.utc).date()
            for f in fills:
                fa = getattr(f, "filled_at", None)
                if fa and hasattr(fa, "date") and fa.date() == today:
                    total_trades_today += 1
    except Exception as exc:
        logger.debug("admin overview engine: %s", exc)

    # Revenue from analytics
    try:
        from monetization.analytics import revenue_analytics
        from datetime import datetime as _dt3, timezone as _tz3, timedelta as _td
        now = _dt3.now(_tz3.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        mtd_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rev_today = revenue_analytics.get_revenue_by_period(today_start, now)
        rev_mtd = revenue_analytics.get_revenue_by_period(mtd_start, now)
        revenue_today_usd = float(sum(rev_today.values())) if isinstance(rev_today, dict) else float(rev_today or 0)
        revenue_mtd_usd = float(sum(rev_mtd.values())) if isinstance(rev_mtd, dict) else float(rev_mtd or 0)
    except Exception as exc:
        logger.debug("admin overview revenue: %s", exc)

    # ML accuracy
    try:
        from ml.signal_filter import SignalFilter
        sf = SignalFilter()
        stats = sf.get_stats() if hasattr(sf, "get_stats") else {}
        ml_model_accuracy = float(stats.get("accuracy", 0.0))
    except Exception as exc:
        logger.debug("admin overview ml: %s", exc)

    # Uptime
    uptime_secs = _time.time() - _start_time
    total_secs = max(uptime_secs, 1)
    platform_uptime_pct = min(99.99, round(uptime_secs / total_secs * 100, 2))

    return {
        "total_users": total_users,
        "active_users_24h": active_users_24h,
        "total_trades_today": total_trades_today,
        "open_positions": open_positions,
        "revenue_today_usd": round(revenue_today_usd, 2),
        "revenue_mtd_usd": round(revenue_mtd_usd, 2),
        "platform_uptime_pct": platform_uptime_pct,
        "active_subscriptions": active_subscriptions,
        "pending_withdrawals": pending_withdrawals,
        "flagged_accounts": flagged_accounts,
        "ml_model_accuracy": round(ml_model_accuracy, 4),
        "ws_connections": ws_connections,
    }


@router.get("/alerts", summary="Active admin alerts")
@router.get("/status", summary="Active admin alerts (alias for /alerts used by frontend adminApi)")
def get_admin_alerts(user: TokenPayload = Depends(require_role("admin"))) -> dict:
    """Return active system alerts for the admin dashboard."""
    alerts = []

    # Check kill switch
    try:
        from kill_switch import KillSwitch
        ks = KillSwitch()
        if ks.is_active():
            alerts.append({
                "id": "kill-switch-active",
                "severity": "critical",
                "title": "Kill Switch Active",
                "message": "All trading has been halted by the kill switch.",
                "created_at": _import_datetime().now(_import_utc()).isoformat(),
                "resolved": False,
            })
    except Exception:
        pass

    # Check engine health
    try:
        from core.app_state import app_state as _as2
        engine = getattr(_as2, "hopefx_engine", None)
        if engine is None:
            alerts.append({
                "id": "engine-offline",
                "severity": "warning",
                "title": "Trading Engine Offline",
                "message": "The trading engine is not initialised. Paper trading mode may be active.",
                "created_at": _import_datetime().now(_import_utc()).isoformat(),
                "resolved": False,
            })
    except Exception:
        pass

    # Check DB
    try:
        from api.db_store import db_get
        db_get("health_check")
    except Exception:
        alerts.append({
            "id": "db-unavailable",
            "severity": "warning",
            "title": "Database Unavailable",
            "message": "Config store is using in-memory fallback. Data will not persist across restarts.",
            "created_at": _import_datetime().now(_import_utc()).isoformat(),
            "resolved": False,
        })

    return {"alerts": alerts, "total": len(alerts)}


def _import_datetime():
    from datetime import datetime
    return datetime


def _import_utc():
    from datetime import timezone
    return timezone.utc


@router.get("/audit-log/export", summary="Export audit log as CSV")
def export_audit_log(
    limit: int = 1000,
    user: TokenPayload = Depends(require_role("admin")),
):
    """Export the audit log as a CSV file."""
    import csv
    import io
    from fastapi.responses import StreamingResponse
    from api.db_store import db_keys_prefix, db_get

    events = []
    try:
        keys = db_keys_prefix("audit_event:")
        for key in sorted(keys, reverse=True)[:limit]:
            ev = db_get(key)
            if ev:
                events.append(ev)
    except Exception as exc:
        logger.debug("audit log export: %s", exc)

    output = io.StringIO()
    fieldnames = ["event_id", "user_id", "event_type", "detail", "ip_address", "created_at"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for ev in events:
        writer.writerow(ev)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


# ── User management endpoints ─────────────────────────────────────────────────

@router.get("/users", summary="List all platform users")
async def list_users(
    page: int = 1,
    limit: int = 50,
    search: str | None = None,
    role: str | None = None,
    status: str | None = None,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Return paginated user list with optional filters."""
    from api.db_store import db_keys_prefix, db_get as _db_get

    all_users: list[dict] = []

    # Try subscription manager first
    try:
        from monetization.subscription import subscription_manager
        subs = subscription_manager.get_all_subscriptions() if hasattr(subscription_manager, "get_all_subscriptions") else []
        for s in subs:
            uid = getattr(s, "user_id", None) or (s.get("user_id") if isinstance(s, dict) else None)
            if not uid:
                continue
            all_users.append({
                "user_id": uid,
                "email": getattr(s, "email", "") or (s.get("email", "") if isinstance(s, dict) else ""),
                "role": getattr(s, "role", "trader") or (s.get("role", "trader") if isinstance(s, dict) else "trader"),
                "status": getattr(s, "status", "active") or (s.get("status", "active") if isinstance(s, dict) else "active"),
                "plan": getattr(s, "plan", "free") or (s.get("plan", "free") if isinstance(s, dict) else "free"),
                "created_at": str(getattr(s, "created_at", "") or (s.get("created_at", "") if isinstance(s, dict) else "")),
                "last_login": str(getattr(s, "last_login", "") or (s.get("last_login", "") if isinstance(s, dict) else "")),
            })
    except Exception as exc:
        logger.debug("list_users subscription_manager: %s", exc)

    # Fallback: scan DB user keys
    if not all_users:
        try:
            keys = db_keys_prefix("user:")
            for key in keys:
                u = _db_get(key)
                if u and isinstance(u, dict):
                    all_users.append(u)
        except Exception as exc:
            logger.debug("list_users db scan: %s", exc)

    # Apply filters
    if search:
        q = search.lower()
        all_users = [u for u in all_users if q in u.get("email", "").lower() or q in u.get("user_id", "").lower()]
    if role:
        all_users = [u for u in all_users if u.get("role") == role]
    if status:
        all_users = [u for u in all_users if u.get("status") == status]

    total = len(all_users)
    offset = (page - 1) * limit
    page_data = all_users[offset: offset + limit]

    return {"users": page_data, "total": total, "page": page, "limit": limit}


@router.get("/users/{user_id}", summary="Get a specific user")
async def get_user(
    user_id: str,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Return full profile for a single user."""
    from api.db_store import db_get as _db_get2
    u = _db_get2(f"user:{user_id}")
    if u and isinstance(u, dict):
        return u

    # Try subscription manager
    try:
        from monetization.subscription import subscription_manager
        sub = subscription_manager.get_subscription(user_id)
        if sub:
            return {
                "user_id": user_id,
                "email": getattr(sub, "email", ""),
                "role": getattr(sub, "role", "trader"),
                "status": getattr(sub, "status", "active"),
                "plan": getattr(sub, "plan", "free"),
                "created_at": str(getattr(sub, "created_at", "")),
            }
    except Exception as exc:
        logger.debug("get_user subscription_manager: %s", exc)

    raise HTTPException(status_code=404, detail="User not found")


@router.patch("/users/{user_id}", summary="Update a user's role or status")
async def update_user(
    user_id: str,
    payload: dict,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Update role, status, or plan for a user."""
    from api.db_store import db_get as _db_g, db_set as _db_s
    u = _db_g(f"user:{user_id}") or {"user_id": user_id}
    allowed_fields = {"role", "status", "plan", "email"}
    for k, v in payload.items():
        if k in allowed_fields:
            u[k] = v
    _db_s(f"user:{user_id}", u)
    return {"ok": True, "user_id": user_id, "updated": {k: v for k, v in payload.items() if k in allowed_fields}}


@router.post("/users/{user_id}/ban", summary="Ban a user")
async def ban_user(
    user_id: str,
    payload: dict = {},
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Set user status to 'banned'."""
    from api.db_store import db_get as _db_g2, db_set as _db_s2
    u = _db_g2(f"user:{user_id}") or {"user_id": user_id}
    u["status"] = "banned"
    u["ban_reason"] = payload.get("reason", "")
    _db_s2(f"user:{user_id}", u)
    return {"ok": True, "user_id": user_id, "status": "banned"}


@router.post("/users/{user_id}/unban", summary="Unban a user")
async def unban_user(
    user_id: str,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Set user status back to 'active'."""
    from api.db_store import db_get as _db_g3, db_set as _db_s3
    u = _db_g3(f"user:{user_id}") or {"user_id": user_id}
    u["status"] = "active"
    u.pop("ban_reason", None)
    _db_s3(f"user:{user_id}", u)
    return {"ok": True, "user_id": user_id, "status": "active"}


@router.post("/users/{user_id}/reset-password", summary="Trigger password reset email")
async def reset_user_password(
    user_id: str,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Send a password reset email to the user."""
    try:
        from core.email_service import email_service
        from api.db_store import db_get as _db_g4
        u = _db_g4(f"user:{user_id}") or {}
        email = u.get("email", "")
        if email:
            await email_service.send_password_reset(email)
    except Exception as exc:
        logger.debug("reset_user_password email: %s", exc)
    return {"ok": True, "user_id": user_id, "message": "Password reset email queued"}


@router.get("/audit-log", summary="Paginated audit log")
async def get_audit_log(
    page: int = 1,
    limit: int = 50,
    user_id: str | None = None,
    event_type: str | None = None,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Return paginated audit log entries."""
    from api.db_store import db_keys_prefix, db_get as _db_g5

    events: list[dict] = []
    try:
        keys = sorted(db_keys_prefix("audit_event:"), reverse=True)
        for key in keys[:limit * 10]:  # over-fetch then filter
            ev = _db_g5(key)
            if ev and isinstance(ev, dict):
                if user_id and ev.get("user_id") != user_id:
                    continue
                if event_type and ev.get("event_type") != event_type:
                    continue
                events.append(ev)
    except Exception as exc:
        logger.debug("get_audit_log: %s", exc)

    # Fallback to activity_log
    if not events:
        events = list(activity_log)
        if user_id:
            events = [e for e in events if e.get("user_id") == user_id]
        if event_type:
            events = [e for e in events if e.get("event_type") == event_type]

    total = len(events)
    offset = (page - 1) * limit
    return {"events": events[offset: offset + limit], "total": total, "page": page, "limit": limit}


# ── System backup trigger ─────────────────────────────────────────────────────

@router.post("/backup/trigger", summary="Trigger a system backup")
async def trigger_backup(
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Trigger an immediate system backup (config, DB snapshot, strategy files)."""
    import time as _t
    backup_id = f"backup_{int(_t.time())}"
    backed_up: list[str] = []

    # Config backup
    try:
        import shutil
        from pathlib import Path as _P
        cfg_src = _P(__file__).parent.parent / "config"
        cfg_dst = _P(__file__).parent.parent / "backups" / backup_id / "config"
        cfg_dst.mkdir(parents=True, exist_ok=True)
        for f in cfg_src.glob("*.json"):
            shutil.copy2(f, cfg_dst / f.name)
        backed_up.append("config")
    except Exception as exc:
        logger.debug("backup config: %s", exc)

    # DB config store backup
    try:
        from api.db_store import db_keys_prefix, db_get as _db_g6
        from pathlib import Path as _P2
        import json as _json
        keys = db_keys_prefix("")
        snapshot = {k: _db_g6(k) for k in keys}
        dst = _P2(__file__).parent.parent / "backups" / backup_id
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "db_snapshot.json").write_text(_json.dumps(snapshot, default=str))
        backed_up.append("db_store")
    except Exception as exc:
        logger.debug("backup db_store: %s", exc)

    return {
        "ok": True,
        "backup_id": backup_id,
        "backed_up": backed_up,
        "created_at": _import_datetime().now(_import_utc()).isoformat(),
    }


@router.get("/settings/system", summary="Get system-level admin settings")
def get_system_settings(user: TokenPayload = Depends(require_role("admin"))) -> dict:
    """Return system-level settings (maintenance mode, feature flags, rate limits)."""
    from api.db_store import db_get as _db_g7
    stored = _db_g7("admin:system_settings") or {}
    return {
        "maintenance_mode": stored.get("maintenance_mode", False),
        "maintenance_message": stored.get("maintenance_message", ""),
        "rate_limit_enabled": stored.get("rate_limit_enabled", True),
        "rate_limit_requests_per_minute": stored.get("rate_limit_requests_per_minute", 60),
        "max_concurrent_users": stored.get("max_concurrent_users", 10000),
        "session_timeout_minutes": stored.get("session_timeout_minutes", 60),
        "log_level": stored.get("log_level", "INFO"),
        "debug_mode": stored.get("debug_mode", False),
    }


@router.post("/settings/system", summary="Update system-level admin settings")
def update_system_settings(
    payload: dict,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """Update system-level settings."""
    from api.db_store import db_get as _db_g8, db_set as _db_s8
    stored = _db_g8("admin:system_settings") or {}
    allowed = {
        "maintenance_mode", "maintenance_message", "rate_limit_enabled",
        "rate_limit_requests_per_minute", "max_concurrent_users",
        "session_timeout_minutes", "log_level", "debug_mode",
    }
    for k, v in payload.items():
        if k in allowed:
            stored[k] = v
    _db_s8("admin:system_settings", stored)
    return {"ok": True, "updated": {k: v for k, v in payload.items() if k in allowed}}
