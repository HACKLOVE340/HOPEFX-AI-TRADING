
# 9. ADMIN ROUTER - System control and monitoring

admin_router = '''"""
HOPEFX Admin API Router
System administration endpoints
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, List
import logging
import time

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

app_state = None

def set_state(state):
    global app_state
    app_state = state

# Activity log
activity_log = []

def log_activity(message: str):
    """Log admin activity"""
    activity_log.append({
        "timestamp": time.time(),
        "message": message
    })
    if len(activity_log) > 1000:
        activity_log.pop(0)
    logger.info(f"ADMIN: {message}")

@router.get("/status")
async def admin_status():
    """Get full system status"""
    if not app_state:
        raise HTTPException(status_code=503, detail="App not initialized")
    
    return {
        "app_status": app_state.get_status(),
        "components": {
            "config": app_state.config is not None,
            "database": app_state.db_engine is not None,
            "cache": app_state.cache is not None,
            "broker": app_state.broker is not None,
            "price_engine": app_state.price_engine is not None,
            "brain": app_state.brain is not None,
            "risk_manager": app_state.risk_manager is not None,
            "strategy_manager": app_state.strategy_manager is not None
        },
        "uptime": time.time() - app_state.brain.state.timestamp if app_state.brain else 0
    }

@router.get("/logs")
async def get_logs(limit: int = 100):
    """Get recent activity logs"""
    return activity_log[-limit:]

@router.post("/pause")
async def pause_trading():
    """Pause all trading"""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=503, detail="Brain not available")
    
    app_state.brain.pause()
    log_activity("Trading paused by admin")
    return {"status": "paused"}

@router.post("/resume")
async def resume_trading():
    """Resume trading"""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=503, detail="Brain not available")
    
    app_state.brain.resume()
    log_activity("Trading resumed by admin")
    return {"status": "resumed"}

@router.get("/strategies")
async def get_strategies():
    """Get strategy status"""
    if not app_state or not app_state.strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not available")
    
    return {
        "strategies": app_state.strategy_manager.get_strategy_performance(),
        "allocations": app_state.strategy_manager.regime_allocations
    }

@router.post("/strategies/{strategy_name}/{action}")
async def control_strategy(strategy_name: str, action: str):
    """Enable or disable a strategy"""
    if not app_state or not app_state.strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not available")
    
    if action == "enable":
        app_state.strategy_manager.enable_strategy(strategy_name)
    elif action == "disable":
        app_state.strategy_manager.disable_strategy(strategy_name)
    else:
        raise HTTPException(status_code=400, detail="Action must be enable or disable")
    
    log_activity(f"Strategy {strategy_name} {action}d")
    return {"status": "success", "strategy": strategy_name, "action": action}

@router.get("/risk-report")
async def risk_report():
    """Get comprehensive risk report"""
    if not app_state or not app_state.risk_manager or not app_state.brain:
        raise HTTPException(status_code=503, detail="Risk components not available")
    
    return app_state.risk_manager.get_risk_report(app_state.brain.state)

@router.post("/risk-settings")
async def update_risk_settings(settings: Dict):
    """Update risk settings"""
    if not app_state or not app_state.risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not available")
    
    # Update config
    for key, value in settings.items():
        if hasattr(app_state.risk_manager.config, key):
            setattr(app_state.risk_manager.config, key, value)
    
    log_activity(f"Risk settings updated: {settings}")
    return {"status": "success", "settings": settings}

def apply_persisted_risk_settings():
    """Apply risk settings from database on startup"""
    # Placeholder for loading persisted settings
    pass
'''

with open(project_root / "api" / "admin.py", "w") as f:
    f.write(admin_router)

print("✓ Created api/admin.py")
