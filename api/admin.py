"""
HOPEFX Admin API Router

Admin endpoints for system control and monitoring.
All endpoints require role >= 'admin'.
"""

import logging
import time
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

app_state = None

# In-memory activity log (bounded)
activity_log = []


def set_state(state) -> None:
    global app_state
    app_state = state


def log_activity(message: str) -> None:
    activity_log.append({"timestamp": time.time(), "message": message})
    if len(activity_log) > 1000:
        activity_log.pop(0)
    logger.info("ADMIN: %s", message)


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

from typing import Optional
from pydantic import BaseModel


class KYCDecision(BaseModel):
    user_id: str
    action: str          # "approve" | "reject" | "request_more_info"
    notes: Optional[str] = None


@router.get("/kyc/pending")
async def list_pending_kyc(user: TokenPayload = Depends(require_role("admin"))):
    """List users with pending KYC submissions. Requires: role >= 'admin'."""
    try:
        from database.user_models import User
        from app import app_state as _state
        if not _state or not _state.db_session_factory:
            raise HTTPException(status_code=503, detail="Database not available")
        with _state.db_session_factory() as session:
            pending = session.query(User).filter(
                User.kyc_status.in_(["pending", "submitted", "under_review"])
            ).all()
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
        raise HTTPException(status_code=400, detail="action must be approve | reject | request_more_info")

    try:
        from database.user_models import User
        from app import app_state as _state
        from datetime import datetime, timezone
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
        except Exception:
            pass  # email failure is non-fatal

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
        from database.user_models import User
        from app import app_state as _state
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
