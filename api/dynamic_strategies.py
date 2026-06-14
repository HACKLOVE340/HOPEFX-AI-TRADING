# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/dynamic_strategies.py
==========================
REST API endpoints for the Dynamic Strategy Registry.

Provides CRUD operations for dynamically loaded strategies, including
registration, activation, deactivation, and health monitoring.

Endpoints:
    POST   /api/strategies/dynamic/register     — Register a new strategy
    POST   /api/strategies/dynamic/activate     — Activate a validated strategy
    POST   /api/strategies/dynamic/deactivate   — Deactivate an active strategy
    GET    /api/strategies/dynamic/active        — List active strategies
    GET    /api/strategies/dynamic/versions      — List all versions
    GET    /api/strategies/dynamic/health        — Registry health metrics
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/strategies/dynamic",
    tags=["Dynamic Strategies"],
)


# ── Request/Response Models ───────────────────────────────────────────────────


class RegisterStrategyRequest(BaseModel):
    """Request body for registering a new dynamic strategy."""
    name: str = Field(..., min_length=1, max_length=100, description="Strategy name")
    source_code: str = Field(..., min_length=10, description="Python source code")
    symbol: str = Field(default="XAU_USD", description="Trading symbol")
    timeframe: str = Field(default="M15", description="Timeframe")


class ActivateStrategyRequest(BaseModel):
    """Request body for activating a strategy version."""
    version_id: str = Field(..., description="Version ID to activate")


class DeactivateStrategyRequest(BaseModel):
    """Request body for deactivating a strategy."""
    name: str = Field(..., description="Strategy name to deactivate")


class StrategyVersionResponse(BaseModel):
    """Response model for a strategy version."""
    version_id: str
    name: str
    source_hash: str
    symbol: str
    timeframe: str
    author_id: str
    state: str
    created_at: str
    activated_at: str | None = None
    validation_errors: list[str] = []
    performance_metrics: dict[str, float] = {}


# ── Auth dependency ───────────────────────────────────────────────────────────


def _get_current_user():
    """Get the current authenticated user."""
    try:
        from api.auth import get_current_user
        return Depends(get_current_user)
    except ImportError:
        return None


def _require_admin():
    """Require admin role."""
    try:
        from api.auth import require_role
        return Depends(require_role("admin"))
    except ImportError:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/register", response_model=dict)
async def register_strategy(request: RegisterStrategyRequest):
    """
    Register a new dynamic strategy.

    Validates the source code for safety (no dangerous imports/calls),
    compiles it in an isolated namespace, and stores the version.
    The strategy is NOT activated until explicitly requested.
    """
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()

    try:
        version_id = await registry.register_strategy(
            name=request.name,
            source_code=request.source_code,
            symbol=request.symbol,
            timeframe=request.timeframe,
            author_id="system",  # Will be replaced with actual user ID from auth
        )
        return {
            "status": "success",
            "version_id": version_id,
            "message": f"Strategy '{request.name}' registered successfully. "
                       f"Call /activate to make it live.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Strategy registration failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during registration") from exc


@router.post("/activate", response_model=dict)
async def activate_strategy(request: ActivateStrategyRequest):
    """
    Activate a validated strategy version.

    Atomically swaps the previous active version (if any) for this name.
    The strategy becomes immediately available for signal generation.
    """
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()

    try:
        await registry.activate_strategy(request.version_id)
        return {
            "status": "success",
            "message": f"Strategy version '{request.version_id}' activated.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Strategy activation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during activation") from exc


@router.post("/deactivate", response_model=dict)
async def deactivate_strategy(request: DeactivateStrategyRequest):
    """
    Deactivate an active strategy without retiring it.

    The strategy can be re-activated later.
    """
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()

    try:
        await registry.deactivate_strategy(request.name)
        return {
            "status": "success",
            "message": f"Strategy '{request.name}' deactivated.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Strategy deactivation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during deactivation") from exc


@router.get("/list", response_model=dict)
async def list_all_strategies():
    """List all registered strategies (active + inactive) for the frontend."""
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()
    all_versions = registry.get_all_versions()
    active = registry.get_active_strategies()
    strategies = []
    for v in all_versions:
        d = v.to_dict()
        d["is_active"] = v.name in active
        strategies.append(d)
    return {
        "count": len(strategies),
        "strategies": strategies,
    }


@router.post("/{name}/{action_type}", response_model=dict)
async def strategy_action(name: str, action_type: str):
    """
    Perform an action on a strategy by name.
    Supported actions: activate, deactivate, pause, resume.
    Used by the frontend StrategyBuilder page.
    """
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()

    if action_type == "activate":
        # Find latest version of this strategy and activate it
        versions = registry.get_all_versions(name=name)
        if not versions:
            raise HTTPException(status_code=404, detail=f"No versions found for '{name}'")
        latest = versions[-1]
        await registry.activate_strategy(latest.version_id)
        return {"status": "success", "message": f"Strategy '{name}' activated."}
    elif action_type in ("deactivate", "pause"):
        await registry.deactivate_strategy(name)
        return {"status": "success", "message": f"Strategy '{name}' deactivated."}
    elif action_type == "resume":
        versions = registry.get_all_versions(name=name)
        if not versions:
            raise HTTPException(status_code=404, detail=f"No versions found for '{name}'")
        latest = versions[-1]
        await registry.activate_strategy(latest.version_id)
        return {"status": "success", "message": f"Strategy '{name}' resumed."}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action_type}")


@router.get("/active", response_model=dict)
async def list_active_strategies():
    """List all currently active dynamic strategies."""
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()
    active = registry.get_active_strategies()

    return {
        "count": len(active),
        "strategies": [v.to_dict() for v in active.values()],
    }


@router.get("/versions", response_model=dict)
async def list_all_versions(name: str | None = None):
    """List all registered strategy versions, optionally filtered by name."""
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()
    versions = registry.get_all_versions(name=name)

    return {
        "count": len(versions),
        "versions": [v.to_dict() for v in versions],
    }


@router.get("/health", response_model=dict)
async def registry_health():
    """Return Dynamic Strategy Registry health metrics."""
    from strategies.dynamic_registry import get_dynamic_registry

    registry = get_dynamic_registry()
    return registry.health()
