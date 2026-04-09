# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Whitelabel Tenant Management API

Endpoints:
  GET    /api/whitelabel/tenants              — list all tenants
  POST   /api/whitelabel/tenants              — create new tenant
  GET    /api/whitelabel/tenants/{id}         — get tenant detail
  PATCH  /api/whitelabel/tenants/{id}         — update theme / domain
  POST   /api/whitelabel/tenants/{id}/activate
  POST   /api/whitelabel/tenants/{id}/suspend
  DELETE /api/whitelabel/tenants/{id}
  POST   /api/whitelabel/tenants/{id}/features/{feature}   — enable feature
  DELETE /api/whitelabel/tenants/{id}/features/{feature}   — disable feature
  POST   /api/whitelabel/tenants/{id}/api-key              — generate API key
  GET    /api/whitelabel/tenants/{id}/preview              — branded preview data
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from whitelabel import (
    FeatureFlag,
    TenantStatus,
    WhiteLabelManager,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whitelabel", tags=["Whitelabel"])

_manager = WhiteLabelManager()


# Seed a couple of demo tenants so the UI has data immediately
def _seed_demo():
    if _manager.list_tenants():
        return
    t1 = _manager.create_tenant(
        name="PropFirm Alpha",
        owner_email="admin@propfirmalpha.com",
        features=[
            FeatureFlag.TRADING,
            FeatureFlag.RISK_MANAGEMENT,
            FeatureFlag.ANALYTICS,
        ],
    )
    _manager.update_theme(
        t1.tenant_id,
        {
            "primary_color": "#f59e0b",
            "logo_url": "",
            "company_name": "PropFirm Alpha",
        },
    )
    t2 = _manager.create_tenant(
        name="FX Academy",
        owner_email="admin@fxacademy.io",
        trial_days=14,
        features=[FeatureFlag.TRADING, FeatureFlag.BACKTESTING],
    )
    _manager.update_theme(
        t2.tenant_id,
        {
            "primary_color": "#8b5cf6",
            "logo_url": "",
            "company_name": "FX Academy",
        },
    )


_seed_demo()

# In-memory API key store: tenant_id → hashed key (shown once at creation)
_api_keys: dict[str, str] = {}


# ── Models ────────────────────────────────────────────────────────────────────


class CreateTenantBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    owner_email: str
    trial_days: int = Field(0, ge=0, le=365)
    features: list[str] = []
    primary_color: str | None = None
    logo_url: str | None = None


class UpdateTenantBody(BaseModel):
    primary_color: str | None = None
    logo_url: str | None = None
    company_name: str | None = None
    custom_domain: str | None = None


def _tenant_to_dict(t: Any) -> dict:
    return {
        "tenant_id": t.tenant_id,
        "name": t.name,
        "owner_email": t.owner_email,
        "status": t.status.value if hasattr(t.status, "value") else str(t.status),
        "features": [f.value if hasattr(f, "value") else str(f) for f in t.features],
        "theme": {
            "primary_color": getattr(t.theme, "primary_color", "#3b82f6"),
            "logo_url": getattr(t.theme, "logo_url", ""),
            "company_name": getattr(t.theme, "company_name", t.name),
        },
        "custom_domain": getattr(t, "custom_domain", None),
        "created_at": t.created_at.isoformat() if getattr(t, "created_at", None) else None,
        "expires_at": t.expires_at.isoformat() if getattr(t, "expires_at", None) else None,
        "has_api_key": t.tenant_id in _api_keys,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/tenants")
async def list_tenants(
    status_filter: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    status_enum = None
    if status_filter:
        try:
            status_enum = TenantStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status_filter}",
            ) from None
    tenants = _manager.list_tenants(status=status_enum)
    return {"tenants": [_tenant_to_dict(t) for t in tenants], "total": len(tenants)}


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: CreateTenantBody,
    user: TokenPayload = Depends(get_current_user),
):
    features = []
    for f in body.features:
        with contextlib.suppress(ValueError):
            features.append(FeatureFlag(f))

    tenant = _manager.create_tenant(
        name=body.name,
        owner_email=body.owner_email,
        trial_days=body.trial_days,
        features=features,
    )
    if body.primary_color or body.logo_url:
        _manager.update_theme(
            tenant.tenant_id,
            {
                k: v
                for k, v in {
                    "primary_color": body.primary_color,
                    "logo_url": body.logo_url,
                    "company_name": body.name,
                }.items()
                if v is not None
            },
        )
    return _tenant_to_dict(_manager.get_tenant(tenant.tenant_id))


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    t = _manager.get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _tenant_to_dict(t)


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: UpdateTenantBody,
    user: TokenPayload = Depends(get_current_user),
):
    t = _manager.get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")

    theme_updates = {
        k: v
        for k, v in body.model_dump().items()
        if k in ("primary_color", "logo_url", "company_name") and v is not None
    }
    if theme_updates:
        _manager.update_theme(tenant_id, theme_updates)

    if body.custom_domain:
        _manager.set_custom_domain(tenant_id, body.custom_domain)

    return _tenant_to_dict(_manager.get_tenant(tenant_id))


@router.post("/tenants/{tenant_id}/activate")
async def activate_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    if not _manager.activate_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"activated": True, "tenant_id": tenant_id}


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    if not _manager.suspend_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"suspended": True, "tenant_id": tenant_id}


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, user: TokenPayload = Depends(get_current_user)):
    if not _manager.delete_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="Tenant not found")
    _api_keys.pop(tenant_id, None)
    return {"deleted": True, "tenant_id": tenant_id}


@router.post("/tenants/{tenant_id}/features/{feature}")
async def enable_feature(
    tenant_id: str,
    feature: str,
    user: TokenPayload = Depends(get_current_user),
):
    try:
        flag = FeatureFlag(feature)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}") from None
    if not _manager.enable_feature(tenant_id, flag):
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"enabled": True, "feature": feature, "tenant_id": tenant_id}


@router.delete("/tenants/{tenant_id}/features/{feature}")
async def disable_feature(
    tenant_id: str,
    feature: str,
    user: TokenPayload = Depends(get_current_user),
):
    try:
        flag = FeatureFlag(feature)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}") from None
    if not _manager.disable_feature(tenant_id, flag):
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"disabled": True, "feature": feature, "tenant_id": tenant_id}


@router.post("/tenants/{tenant_id}/api-key")
async def generate_api_key(
    tenant_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Generate a new API key for a tenant. Shown once — stored as hash."""
    t = _manager.get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    raw_key = f"hfx_{secrets.token_urlsafe(32)}"
    _api_keys[tenant_id] = hashlib.sha256(raw_key.encode()).hexdigest()
    return {
        "api_key": raw_key,
        "tenant_id": tenant_id,
        "note": "Store this key securely — it will not be shown again.",
    }


@router.get("/tenants/{tenant_id}/preview")
async def preview_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Return branded theme data for dashboard preview."""
    t = _manager.get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "tenant_id": tenant_id,
        "company_name": getattr(t.theme, "company_name", t.name),
        "primary_color": getattr(t.theme, "primary_color", "#3b82f6"),
        "logo_url": getattr(t.theme, "logo_url", ""),
        "features": [f.value if hasattr(f, "value") else str(f) for f in t.features],
        "status": t.status.value if hasattr(t.status, "value") else str(t.status),
    }


@router.get("/features")
async def list_available_features(user: TokenPayload = Depends(get_current_user)):
    """Return all available feature flags."""
    return {"features": [f.value for f in FeatureFlag]}


# ── Internal helpers called by api/superadmin/infrastructure.py ──────────────


def _get_tenants() -> list[dict]:
    """Return all tenants as plain dicts (superadmin helper).

    Returns:
        List of tenant dicts from the WhiteLabelManager.
    """
    return [_tenant_to_dict(t) for t in _manager.list_tenants()]


def _get_tenant_by_id(tenant_id: str) -> dict | None:
    """Look up a single tenant by *tenant_id* (superadmin helper).

    Args:
        tenant_id: UUID string of the tenant to retrieve.

    Returns:
        Tenant dict, or ``None`` if not found.
    """
    tenant = _manager.get_tenant(tenant_id)
    return _tenant_to_dict(tenant) if tenant else None


def _create_tenant(tenant_data: dict) -> None:
    """Persist a tenant record that was already constructed externally.

    The superadmin endpoint builds the full tenant dict itself and calls this
    to propagate it into the WhiteLabelManager's store.

    Args:
        tenant_data: Fully-formed tenant dict (must include ``tenant_id``).
    """
    tid = tenant_data.get("tenant_id", "")
    if not tid:
        return
    # Only persist if not already tracked
    if _manager.get_tenant(tid) is None:
        try:
            _manager.create_tenant(
                name=tenant_data.get("name", ""),
                owner_email=tenant_data.get("domain", ""),
                features=[],
            )
        except Exception as exc:
            logger.debug("_create_tenant delegation error: %s", exc)
