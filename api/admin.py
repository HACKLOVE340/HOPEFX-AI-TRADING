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
