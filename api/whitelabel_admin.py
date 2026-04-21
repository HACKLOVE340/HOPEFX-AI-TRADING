# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Whitelabel Tenant Management API

All tenant records are persisted to the ``whitelabel_tenants`` database table
(migration i1j2k3l4m5n6).  The in-memory WhiteLabelManager is kept only for
feature-flag enum validation.

Endpoints:
  GET    /api/whitelabel/tenants
  POST   /api/whitelabel/tenants
  GET    /api/whitelabel/tenants/{id}
  PATCH  /api/whitelabel/tenants/{id}
  POST   /api/whitelabel/tenants/{id}/activate
  POST   /api/whitelabel/tenants/{id}/suspend
  DELETE /api/whitelabel/tenants/{id}
  POST   /api/whitelabel/tenants/{id}/features/{feature}
  DELETE /api/whitelabel/tenants/{id}/features/{feature}
  POST   /api/whitelabel/tenants/{id}/api-key
  GET    /api/whitelabel/tenants/{id}/preview
  GET    /api/whitelabel/features
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from whitelabel import FeatureFlag

UTC = timezone.utc
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whitelabel", tags=["Whitelabel"])


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_session():
    try:
        from database.connection import SessionLocal
        return SessionLocal()
    except Exception:
        return None


def _get_model():
    try:
        from database.models import WhitelabelTenant
        return WhitelabelTenant
    except Exception:
        return None


# ── Pydantic models ───────────────────────────────────────────────────────────

class CreateTenantBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    owner_email: str
    plan: str = Field("starter")
    trial_days: int = Field(30, ge=0, le=365)
    features: list[str] = []
    primary_color: str | None = None
    logo_url: str | None = None
    custom_domain: str | None = None


class UpdateTenantBody(BaseModel):
    primary_color: str | None = None
    logo_url: str | None = None
    company_name: str | None = None
    custom_domain: str | None = None
    plan: str | None = None


# ── Serialisation ─────────────────────────────────────────────────────────────

def _row_to_dict(row: Any) -> dict:
    if hasattr(row, "to_dict"):
        d = row.to_dict()
        d["has_api_key"] = bool(getattr(row, "api_key_hash", None))
        return d
    features: list = []
    try:
        features = json.loads(getattr(row, "features_json", "[]") or "[]")
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    return {
        "tenant_id": row.id,
        "name": row.name,
        "owner_email": row.owner_email,
        "status": row.status,
        "tier": getattr(row, "tier", "starter"),
        "features": features,
        "theme": {
            "primary_color": row.primary_color or "#3b82f6",
            "logo_url": row.logo_url or "",
            "company_name": row.company_name or row.name,
        },
        "custom_domain": row.custom_domain,
        "revenue_usd": float(row.revenue_usd or 0.0),
        "user_count": int(row.user_count or 0),
        "has_api_key": bool(getattr(row, "api_key_hash", None)),
        "trial_ends_at": row.trial_ends_at.isoformat() if row.trial_ends_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/tenants")
async def list_tenants(
    status_filter: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        return {"tenants": [], "total": 0}
    try:
        q = db.query(Model)
        if status_filter:
            q = q.filter(Model.status == status_filter)
        rows = q.order_by(Model.created_at.desc()).all()
        result = [_row_to_dict(r) for r in rows]
        return {"tenants": result, "total": len(result)}
    finally:
        db.close()


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: CreateTenantBody,
    user: TokenPayload = Depends(get_current_user),
):
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        valid_features: list[str] = []
        for f in body.features:
            try:
                valid_features.append(FeatureFlag(f).value)
            except ValueError:
                logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

        now = datetime.now(UTC)
        trial_ends = (now + timedelta(days=body.trial_days)) if body.trial_days > 0 else None
        row = Model(
            id=str(uuid.uuid4()),
            name=body.name,
            owner_email=body.owner_email,
            status="trial" if body.trial_days > 0 else "active",
            tier=body.plan,
            features_json=json.dumps(valid_features),
            primary_color=body.primary_color or "#3b82f6",
            logo_url=body.logo_url or "",
            company_name=body.name,
            custom_domain=body.custom_domain,
            revenue_usd=0.0,
            user_count=0,
            trial_ends_at=trial_ends,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    except Exception as exc:
        db.rollback()
        logger.error("create_tenant error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create tenant") from None
    finally:
        db.close()


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, user: TokenPayload = Depends(get_current_user)):
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return _row_to_dict(row)
    finally:
        db.close()


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: UpdateTenantBody,
    user: TokenPayload = Depends(get_current_user),
):
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        if body.primary_color is not None:
            row.primary_color = body.primary_color
        if body.logo_url is not None:
            row.logo_url = body.logo_url
        if body.company_name is not None:
            row.company_name = body.company_name
        if body.custom_domain is not None:
            row.custom_domain = body.custom_domain
        if body.plan is not None:
            row.tier = body.plan
        row.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("update_tenant error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update tenant") from None
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/activate")
async def activate_tenant(tenant_id: str, user: TokenPayload = Depends(get_current_user)):
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        row.status = "active"
        row.updated_at = datetime.now(UTC)
        db.commit()
        return {"activated": True, "tenant_id": tenant_id}
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(tenant_id: str, user: TokenPayload = Depends(get_current_user)):
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        row.status = "suspended"
        row.updated_at = datetime.now(UTC)
        db.commit()
        return {"suspended": True, "tenant_id": tenant_id}
    finally:
        db.close()


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, user: TokenPayload = Depends(get_current_user)):
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        db.delete(row)
        db.commit()
        return {"deleted": True, "tenant_id": tenant_id}
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/features/{feature}")
async def enable_feature(
    tenant_id: str, feature: str, user: TokenPayload = Depends(get_current_user)
):
    try:
        flag_val = FeatureFlag(feature).value
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}") from None
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        features: list = []
        try:
            features = json.loads(row.features_json or "[]")
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        if flag_val not in features:
            features.append(flag_val)
        row.features_json = json.dumps(features)
        row.updated_at = datetime.now(UTC)
        db.commit()
        return {"enabled": True, "feature": feature, "tenant_id": tenant_id}
    finally:
        db.close()


@router.delete("/tenants/{tenant_id}/features/{feature}")
async def disable_feature(
    tenant_id: str, feature: str, user: TokenPayload = Depends(get_current_user)
):
    try:
        flag_val = FeatureFlag(feature).value
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}") from None
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        features: list = []
        try:
            features = json.loads(row.features_json or "[]")
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        row.features_json = json.dumps([f for f in features if f != flag_val])
        row.updated_at = datetime.now(UTC)
        db.commit()
        return {"disabled": True, "feature": feature, "tenant_id": tenant_id}
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/api-key")
async def generate_api_key(tenant_id: str, user: TokenPayload = Depends(get_current_user)):
    """Generate a new API key. Shown once — stored as SHA-256 hash."""
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        raw_key = f"hfx_{secrets.token_urlsafe(32)}"
        row.api_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        row.updated_at = datetime.now(UTC)
        db.commit()
        return {
            "api_key": raw_key,
            "tenant_id": tenant_id,
            "note": "Store this key securely — it will not be shown again.",
        }
    finally:
        db.close()


@router.get("/tenants/{tenant_id}/preview")
async def preview_tenant(tenant_id: str, user: TokenPayload = Depends(get_current_user)):
    """Return branded theme data for dashboard preview."""
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        features: list = []
        try:
            features = json.loads(row.features_json or "[]")
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        return {
            "tenant_id": tenant_id,
            "company_name": row.company_name or row.name,
            "primary_color": row.primary_color or "#3b82f6",
            "logo_url": row.logo_url or "",
            "features": features,
            "status": row.status,
        }
    finally:
        db.close()


@router.get("/features")
async def list_available_features(user: TokenPayload = Depends(get_current_user)):
    """Return all available feature flags."""
    return {"features": [f.value for f in FeatureFlag]}


# ── Internal helpers called by api/superadmin/infrastructure.py ──────────────

def _get_tenants() -> list[dict]:
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        return []
    try:
        return [_row_to_dict(r) for r in db.query(Model).order_by(Model.created_at.desc()).all()]
    finally:
        db.close()


def _get_tenant_by_id(tenant_id: str) -> dict | None:
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        return None
    try:
        row = db.query(Model).filter(Model.id == tenant_id).first()
        return _row_to_dict(row) if row else None
    finally:
        db.close()


def _create_tenant(tenant_data: dict) -> None:
    Model = _get_model()
    db = _db_session()
    if Model is None or db is None:
        return
    try:
        tid = tenant_data.get("tenant_id") or str(uuid.uuid4())
        if db.query(Model).filter(Model.id == tid).first():
            return
        now = datetime.now(UTC)
        row = Model(
            id=tid,
            name=tenant_data.get("name", ""),
            owner_email=tenant_data.get("domain", tenant_data.get("owner_email", "")),
            status=tenant_data.get("status", "trial"),
            tier=tenant_data.get("plan", "starter"),
            features_json=json.dumps(tenant_data.get("features", [])),
            primary_color=tenant_data.get("primary_color", "#3b82f6"),
            logo_url=tenant_data.get("logo_url", ""),
            company_name=tenant_data.get("name", ""),
            custom_domain=tenant_data.get("custom_domain"),
            revenue_usd=float(tenant_data.get("revenue_usd", 0.0)),
            user_count=int(tenant_data.get("users", 0)),
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.debug("_create_tenant error: %s", exc)
    finally:
        db.close()
