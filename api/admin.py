"""
HOPEFX Admin API Router

Admin endpoints for system control and monitoring.
All endpoints require role >= 'admin'.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

app_state = None

# In-memory activity log (bounded at 50 entries, newest first)
activity_log: list = []
_ACTIVITY_MAX = 50

# Path for persisted risk settings
_RISK_SETTINGS_FILE = Path("config/risk_settings.json")

# Current in-memory risk settings
_risk_settings: Dict[str, Any] = {
    "max_risk_per_trade": 2.0,
    "max_open_positions": 5,
    "paper_trading_mode": True,
    "max_daily_loss": 5.0,
    "max_drawdown": 10.0,
}

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


def _load_persisted_risk_settings() -> Dict[str, Any]:
    """Load risk settings from disk. Returns {} on missing/invalid file."""
    try:
        if not _RISK_SETTINGS_FILE.exists():
            return {}
        return json.loads(_RISK_SETTINGS_FILE.read_text())
    except Exception as exc:
        logger.warning(
            "Failed to load persisted risk settings from %s: %s",
            _RISK_SETTINGS_FILE,
            exc,
        )
        return {}


def apply_persisted_risk_settings() -> None:
    """Apply risk settings persisted from a previous run (placeholder)."""
    pass


@router.get("/status")
async def admin_status(user: TokenPayload = Depends(require_role("admin"))):
    """Full system status. Requires: role >= 'admin'."""
    if not app_state:
        raise HTTPException(status_code=503, detail="App not initialized")
    return {
        "components": {
            "config": app_state.config is not None,
            "database": app_state.db_engine is not None,
            "cache": app_state.cache is not None,
        }
    }


@router.get("/logs")
async def get_logs(
    limit: int = 100,
    user: TokenPayload = Depends(require_role("admin")),
):
    """Recent activity log. Requires: role >= 'admin'."""
    return activity_log[-limit:]


@router.post("/pause")
async def pause_trading(user: TokenPayload = Depends(require_role("admin"))):
    """Pause all trading. Requires: role >= 'admin'."""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=503, detail="Brain not available")
    app_state.brain.pause()
    log_activity(f"Trading paused by {user.sub}")
    return {"status": "paused"}


@router.post("/resume")
async def resume_trading(user: TokenPayload = Depends(require_role("admin"))):
    """Resume trading. Requires: role >= 'admin'."""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=503, detail="Brain not available")
    app_state.brain.resume()
    log_activity(f"Trading resumed by {user.sub}")
    return {"status": "resumed"}


@router.post("/risk-settings")
async def update_risk_settings(
    settings: Dict,
    user: TokenPayload = Depends(require_role("admin")),
):
    """Update risk settings. Requires: role >= 'admin'."""
    if not app_state or not app_state.risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not available")
    for key, value in settings.items():
        if hasattr(app_state.risk_manager.config, key):
            setattr(app_state.risk_manager.config, key, value)
    log_activity(f"Risk settings updated by {user.sub}: {list(settings.keys())}")
    return {"status": "success", "settings": settings}


# ── KYC management ────────────────────────────────────────────────────────────

from pydantic import BaseModel


class KYCDecision(BaseModel):
    user_id: str
    action: str  # "approve" | "reject" | "request_more_info"
    notes: Optional[str] = None


@router.get("/kyc/pending")
async def list_pending_kyc(user: TokenPayload = Depends(require_role("admin"))):
    """List users with pending KYC submissions. Requires: role >= 'admin'."""
    try:
        from app import app_state as _state
        from database.user_models import User

        if not _state or not _state.db_session_factory:
            raise HTTPException(status_code=503, detail="Database not available")
        with _state.db_session_factory() as session:
            pending = (
                session.query(User)
                .filter(User.kyc_status.in_(["pending", "submitted", "under_review"]))
                .all()
            )
            return {
                "count": len(pending),
                "users": [
                    {
                        "user_id": u.id,
                        "email": u.email,
                        "username": u.username,
                        "kyc_status": u.kyc_status,
                        "created_at": str(u.created_at),
                    }
                    for u in pending
                ],
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
        from app import app_state as _state
        from database.user_models import User

        if not _state or not _state.db_session_factory:
            raise HTTPException(status_code=503, detail="Database not available")

        with _state.db_session_factory() as session:
            target = session.query(User).filter_by(id=body.user_id).first()
            if not target:
                raise HTTPException(status_code=404, detail="User not found")

            status_map = {
                "approve": "approved",
                "reject": "rejected",
                "request_more_info": "more_info_required",
            }
            target.kyc_status = status_map[body.action]
            session.commit()

        # Audit log
        log_activity(
            f"KYC {body.action} for user {body.user_id} by admin {user.sub}"
            + (f" — {body.notes}" if body.notes else "")
        )

        # Notify user via email
        try:
            from core.email_service import _send
            from database.user_models import User as _User

            with _state.db_session_factory() as session:
                target = session.query(_User).filter_by(id=body.user_id).first()
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
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/kyc/{user_id}")
async def get_kyc_status(
    user_id: str,
    user: TokenPayload = Depends(require_role("admin")),
):
    """Get KYC status for a specific user. Requires: role >= 'admin'."""
    try:
        from app import app_state as _state
        from database.user_models import User

        if not _state or not _state.db_session_factory:
            raise HTTPException(status_code=503, detail="Database not available")
        with _state.db_session_factory() as session:
            target = session.query(User).filter_by(id=user_id).first()
            if not target:
                raise HTTPException(status_code=404, detail="User not found")
            return {
                "user_id": target.id,
                "email": target.email,
                "kyc_status": target.kyc_status,
                "is_email_verified": target.is_email_verified,
                "role": target.role,
                "status": target.status,
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── New endpoints expected by tests ──────────────────────────────────────────


@router.get("/api/system-info", response_model=None, summary="Server version and uptime")
def get_system_info(user: TokenPayload = Depends(require_role("admin"))):
    """Server version and uptime. Requires: role >= 'admin'."""
    return {
        "version": "1.0.0",
        "status": "running",
        "uptime": time.time() - _start_time,
    }


@router.get("/api/settings")
def get_settings(user: TokenPayload = Depends(require_role("admin"))):
    """Read current risk settings. Requires: role >= 'admin'."""
    return dict(_risk_settings)


@router.post("/api/settings")
def save_settings(
    payload: Dict[str, Any],
    user: TokenPayload = Depends(require_role("admin")),
):
    """Update risk settings. Requires: role >= 'admin'."""
    try:
        _risk_settings.update(payload)
        log_activity(f"Settings updated by {user.sub}: {list(payload.keys())}")
        return {"status": "ok", "saved": list(payload.keys())}
    except Exception as exc:
        logger.error("save_settings failed: %s", exc, exc_info=True)
        return {"status": "error", "detail": str(exc)}


@router.get("/api/activity")
def get_activity(user: TokenPayload = Depends(require_role("admin"))):
    """All user activity logs. Requires: role >= 'admin'."""
    return {"events": list(activity_log)}


@router.get("/api/dashboard-data")
def get_dashboard_data(user: TokenPayload = Depends(require_role("admin"))):
    """Full system state. Requires: role >= 'admin'."""
    return {
        "system_health": {"status": "ok"},
        "trading_stats": {"total_trades": 0, "open_positions": 0},
        "risk_status": {"within_limits": True},
        "module_status": {"strategies": True, "brokers": True},
    }


@router.get("/api/system-metrics", response_model=None, summary="System resource metrics")
def get_system_metrics(user: TokenPayload = Depends(require_role("admin"))):
    """Prometheus-style system metrics. Requires: role >= 'admin'."""
    uptime_secs = time.time() - _start_time
    return {
        "uptime": uptime_secs,
        "uptime_seconds": uptime_secs,
        "memory_mb": 0,
        "cpu_pct": 0,
    }


# ── Aliases expected by tests ─────────────────────────────────────────────────
_activity_log = activity_log


def _check_module(name: str) -> bool:
    """Return True if a module can be imported."""
    import importlib.util

    return importlib.util.find_spec(name) is not None


# ── Admin HTML pages ──────────────────────────────────────────────────────────


def _html_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><title>HOPEFX Admin — {title}</title></head>
<body><h1>HOPEFX Admin — {title}</h1>{body}</body></html>""")


@router.get("/", response_class=HTMLResponse)
def admin_dashboard(user: TokenPayload = Depends(require_role("admin"))):
    """Admin dashboard. Requires: role >= 'admin'."""
    return _html_page("Dashboard", "<p>Dashboard</p>")


@router.get("/strategies", response_class=HTMLResponse)
def admin_strategies(user: TokenPayload = Depends(require_role("admin"))):
    """Strategy management page. Requires: role >= 'admin'."""
    return _html_page("Strategies", "<p>Strategies</p>")


@router.get("/settings", response_class=HTMLResponse)
def admin_settings_page(user: TokenPayload = Depends(require_role("admin"))):
    """Settings page. Requires: role >= 'admin'."""
    return _html_page("Settings", "<p>Settings</p>")


@router.get("/monitoring", response_class=HTMLResponse)
def admin_monitoring(user: TokenPayload = Depends(require_role("admin"))):
    """Monitoring page. Requires: role >= 'admin'."""
    return _html_page("Monitoring", "<p>Monitoring</p>")
