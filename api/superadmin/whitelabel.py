# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/whitelabel.py
=============================
White-Label tenant management sub-router.

Routes
------
GET    /superadmin/whitelabel/tenants                    — list tenants
GET    /superadmin/whitelabel/tenants/{id}               — get tenant
POST   /superadmin/whitelabel/tenants                    — create tenant
PATCH  /superadmin/whitelabel/tenants/{id}               — update tenant
POST   /superadmin/whitelabel/tenants/{id}/suspend       — suspend tenant
POST   /superadmin/whitelabel/tenants/{id}/activate      — activate tenant
DELETE /superadmin/whitelabel/tenants/{id}               — delete tenant
GET    /superadmin/whitelabel/tenants/{id}/api-keys      — list API keys
POST   /superadmin/whitelabel/tenants/{id}/api-keys/rotate — rotate API key
GET    /superadmin/whitelabel/tenants/{id}/usage         — tenant usage stats
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()

_TENANTS_KEY = "superadmin:whitelabel:tenants"


def _load_tenants() -> list[dict]:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_TENANTS_KEY)
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return []


def _save_tenants(tenants: list[dict]) -> None:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            rc.set(_TENANTS_KEY, json.dumps(tenants), ex=86400 * 90)
    except Exception:
        pass


@router.get("/whitelabel/tenants")
async def list_tenants(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    if status:
        tenants = [t for t in tenants if t.get("status") == status]
    return {"tenants": tenants[:limit], "total": len(tenants)}


@router.get("/whitelabel/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    t = next((t for t in tenants if t["tenant_id"] == tenant_id), None)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return t


@router.post("/whitelabel/tenants")
async def create_tenant(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenant_id = str(uuid.uuid4())
    api_key = f"wl_{secrets.token_urlsafe(32)}"
    tenant: dict[str, Any] = {
        "tenant_id": tenant_id,
        "name": body.get("name", "New Tenant"),
        "domain": body.get("domain", ""),
        "status": "trial",
        "plan": body.get("plan", "starter"),
        "user_count": 0,
        "created_at": _utcnow().isoformat(),
        "monthly_revenue": 0.0,
        "branding": body.get("branding", {
            "primary_color": "#3b82f6",
            "logo_url": "",
            "company_name": body.get("name", "New Tenant"),
        }),
        "api_keys": [{"key_id": str(uuid.uuid4()), "key": api_key, "created_at": _utcnow().isoformat()}],
        "created_by": user.sub,
    }
    tenants = _load_tenants()
    tenants.insert(0, tenant)
    _save_tenants(tenants)
    _log_superadmin_action(user, "tenant_create", {"tenant_id": tenant_id, "name": tenant["name"]})
    return {"ok": True, "tenant": tenant}


@router.patch("/whitelabel/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    for t in tenants:
        if t["tenant_id"] == tenant_id:
            for k, v in body.items():
                if k not in ("tenant_id", "created_at", "api_keys"):
                    t[k] = v
            t["updated_at"] = _utcnow().isoformat()
            _save_tenants(tenants)
            _log_superadmin_action(user, "tenant_update", {"tenant_id": tenant_id})
            return {"ok": True, "tenant": t}
    raise HTTPException(status_code=404, detail="Tenant not found")


@router.post("/whitelabel/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    for t in tenants:
        if t["tenant_id"] == tenant_id:
            t["status"] = "suspended"
            t["suspended_at"] = _utcnow().isoformat()
            _save_tenants(tenants)
            _log_superadmin_action(user, "tenant_suspend", {"tenant_id": tenant_id})
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Tenant not found")


@router.post("/whitelabel/tenants/{tenant_id}/activate")
async def activate_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    for t in tenants:
        if t["tenant_id"] == tenant_id:
            t["status"] = "active"
            t["activated_at"] = _utcnow().isoformat()
            _save_tenants(tenants)
            _log_superadmin_action(user, "tenant_activate", {"tenant_id": tenant_id})
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Tenant not found")


@router.delete("/whitelabel/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    before = len(tenants)
    tenants = [t for t in tenants if t["tenant_id"] != tenant_id]
    if len(tenants) == before:
        raise HTTPException(status_code=404, detail="Tenant not found")
    _save_tenants(tenants)
    _log_superadmin_action(user, "tenant_delete", {"tenant_id": tenant_id})
    return {"ok": True}


@router.get("/whitelabel/tenants/{tenant_id}/api-keys")
async def get_tenant_api_keys(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    t = next((t for t in tenants if t["tenant_id"] == tenant_id), None)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    keys = t.get("api_keys", [])
    # Mask key values
    masked = [{"key_id": k["key_id"], "key": k["key"][:8] + "…", "created_at": k.get("created_at")} for k in keys]
    return {"api_keys": masked}


@router.post("/whitelabel/tenants/{tenant_id}/api-keys/rotate")
async def rotate_tenant_api_key(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    for t in tenants:
        if t["tenant_id"] == tenant_id:
            new_key = f"wl_{secrets.token_urlsafe(32)}"
            t["api_keys"] = [{"key_id": str(uuid.uuid4()), "key": new_key, "created_at": _utcnow().isoformat()}]
            _save_tenants(tenants)
            _log_superadmin_action(user, "tenant_key_rotate", {"tenant_id": tenant_id})
            return {"ok": True, "new_key": new_key}
    raise HTTPException(status_code=404, detail="Tenant not found")


@router.get("/whitelabel/tenants/{tenant_id}/usage")
async def get_tenant_usage(
    tenant_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    tenants = _load_tenants()
    t = next((t for t in tenants if t["tenant_id"] == tenant_id), None)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "tenant_id": tenant_id,
        "user_count": t.get("user_count", 0),
        "api_calls_today": 0,
        "api_calls_mtd": 0,
        "monthly_revenue": t.get("monthly_revenue", 0.0),
        "storage_mb": 0.0,
        "computed_at": _utcnow().isoformat(),
    }
