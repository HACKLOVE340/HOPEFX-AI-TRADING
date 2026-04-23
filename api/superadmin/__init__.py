# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX SuperAdmin API Router — thin orchestrator.

All sub-routers are mounted here.  External code that does::

    from api.superadmin import router

continues to work without changes.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from api.auth import TokenPayload

from ._shared import (
    _require_superadmin,
    _TEMPLATES_DIR,
    _iso as _iso,
    _get_config_store as _get_config_store,
    _log_superadmin_action as _log_superadmin_action,
    UpdateUserBody as UpdateUserBody,
    SetRoleBody as SetRoleBody,
    SetPlanBody as SetPlanBody,
    BanUserBody as BanUserBody,
    BulkUserBody as BulkUserBody,
    MaintenanceBody as MaintenanceBody,
    BroadcastBody as BroadcastBody,
    PlatformConfigBody as PlatformConfigBody,
    EngineConfigBody as EngineConfigBody,
    KillSwitchBody as KillSwitchBody,
    PauseBody as PauseBody,
    BlockIPBody as BlockIPBody,
    SetLogLevelBody as SetLogLevelBody,
    SetFeatureFlagBody as SetFeatureFlagBody,
    SetUserFlagOverrideBody as SetUserFlagOverrideBody,
    RefundBody as RefundBody,
    MLControlBody as MLControlBody,
    DeployModelBody as DeployModelBody,
    KYCDecisionBody as KYCDecisionBody,
    AMLAlertUpdateBody as AMLAlertUpdateBody,
    SanctionsClearBody as SanctionsClearBody,
    RegReportTriggerBody as RegReportTriggerBody,
    CircuitBreakerActionBody as CircuitBreakerActionBody,
)
from .platform import (
    _PLATFORM_CONFIG_DEFAULTS as _PLATFORM_CONFIG_DEFAULTS,
    _load_platform_config as _load_platform_config,
    _save_platform_config as _save_platform_config,
    _load_engine_config as _load_engine_config,
)
from .overview import router as _overview_router
from .users import router as _users_router
from .platform import router as _platform_router
from .ml_ai import router as _ml_ai_router
from .financial import router as _financial_router
from .security import router as _security_router
from .logs import router as _logs_router
from .feature_flags import router as _feature_flags_router
from .audit import router as _audit_router
from .infrastructure import router as _infrastructure_router
from .auto_healing import router as _auto_healing_router
from .diagnostics import router as _diagnostics_router
from .reliability import router as _reliability_router
from .health_engine_api import router as _health_engine_router

router = APIRouter(prefix="/api/superadmin", tags=["SuperAdmin"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def superadmin_dashboard(user: TokenPayload = Depends(_require_superadmin)) -> HTMLResponse:
    """SuperAdmin master control center UI. Requires: role = superadmin.

    Called by the React SPA (SuperAdminDashboard.tsx) via fetch() with an
    Authorization: Bearer header. Browser navigation to /superadmin is handled
    by the React Router — the SPA serves index.html for that path.
    """
    path = _TEMPLATES_DIR / "admin" / "superadmin.html"
    if path.exists():
        return HTMLResponse(content=path.read_text(encoding="utf-8"))
    # Fallback: redirect to the React SPA which renders SuperAdminDashboard
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/superadmin", status_code=302)  # type: ignore[return-value]


router.include_router(_overview_router)
router.include_router(_users_router)
router.include_router(_platform_router)
router.include_router(_ml_ai_router)
router.include_router(_financial_router)
router.include_router(_security_router)
router.include_router(_logs_router)
router.include_router(_feature_flags_router)
router.include_router(_audit_router)
router.include_router(_infrastructure_router)
router.include_router(_auto_healing_router)
router.include_router(_diagnostics_router)
router.include_router(_reliability_router)
router.include_router(_health_engine_router)
