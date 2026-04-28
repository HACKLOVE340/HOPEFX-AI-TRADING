# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/rate_limiting.py
================================
Rate Limiting management sub-router.

Routes
------
GET   /superadmin/rate-limits                            — list all rate limit rules
POST  /superadmin/rate-limits                            — create rule
PATCH /superadmin/rate-limits/{rule_id}                  — update rule
DELETE /superadmin/rate-limits/{rule_id}                 — delete rule
GET   /superadmin/rate-limits/stats                      — live hit counts per endpoint
POST  /superadmin/rate-limits/{rule_id}/reset            — reset hit counter
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()

_RULES_KEY = "superadmin:rate_limits:rules"
_HITS_PREFIX = "rate_limit:hits:"


def _load_rules() -> list[dict]:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_RULES_KEY)
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    # Bootstrap with sensible defaults matching core/middleware.py
    return [
        {"rule_id": "rl_auth",       "endpoint": "/api/auth/*",       "limit": 10,   "window_seconds": 60,  "scope": "per_ip",   "enabled": True, "current_hits": 0},
        {"rule_id": "rl_trade",      "endpoint": "/api/trading/*",    "limit": 100,  "window_seconds": 60,  "scope": "per_user", "enabled": True, "current_hits": 0},
        {"rule_id": "rl_global",     "endpoint": "/api/*",            "limit": 1000, "window_seconds": 60,  "scope": "global",   "enabled": True, "current_hits": 0},
        {"rule_id": "rl_superadmin", "endpoint": "/api/superadmin/*", "limit": 200,  "window_seconds": 60,  "scope": "per_user", "enabled": True, "current_hits": 0},
        {"rule_id": "rl_ws",         "endpoint": "/ws/*",             "limit": 50,   "window_seconds": 60,  "scope": "per_ip",   "enabled": True, "current_hits": 0},
    ]


def _save_rules(rules: list[dict]) -> None:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            rc.set(_RULES_KEY, json.dumps(rules), ex=86400 * 30)
    except Exception:
        pass


@router.get("/rate-limits")
async def get_rate_limit_rules(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rules = _load_rules()
    # Enrich with live hit counts from Redis
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            for rule in rules:
                key = f"{_HITS_PREFIX}{rule['rule_id']}"
                val = rc.get(key)
                rule["current_hits"] = int(val) if val else 0
    except Exception:
        pass
    return {"rules": rules, "total": len(rules)}


@router.post("/rate-limits")
async def create_rate_limit_rule(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rule_id = f"rl_{uuid.uuid4().hex[:8]}"
    rule: dict[str, Any] = {
        "rule_id": rule_id,
        "endpoint": body.get("endpoint", "/api/*"),
        "limit": int(body.get("limit", 100)),
        "window_seconds": int(body.get("window_seconds", 60)),
        "scope": body.get("scope", "global"),
        "enabled": bool(body.get("enabled", True)),
        "current_hits": 0,
        "created_at": _utcnow().isoformat(),
        "created_by": user.sub,
    }
    rules = _load_rules()
    rules.append(rule)
    _save_rules(rules)
    await _log_superadmin_action(user.sub, "rate_limit_create", {"rule_id": rule_id})
    return {"ok": True, "rule": rule}


@router.patch("/rate-limits/{rule_id}")
async def update_rate_limit_rule(
    rule_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rules = _load_rules()
    for r in rules:
        if r["rule_id"] == rule_id:
            for k, v in body.items():
                if k not in ("rule_id", "created_at"):
                    r[k] = v
            r["updated_at"] = _utcnow().isoformat()
            _save_rules(rules)
            await _log_superadmin_action(user.sub, "rate_limit_update", {"rule_id": rule_id})
            return {"ok": True, "rule": r}
    raise HTTPException(status_code=404, detail="Rule not found")


@router.delete("/rate-limits/{rule_id}")
async def delete_rate_limit_rule(
    rule_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rules = _load_rules()
    before = len(rules)
    rules = [r for r in rules if r["rule_id"] != rule_id]
    if len(rules) == before:
        raise HTTPException(status_code=404, detail="Rule not found")
    _save_rules(rules)
    await _log_superadmin_action(user.sub, "rate_limit_delete", {"rule_id": rule_id})
    return {"ok": True}


@router.get("/rate-limits/stats")
async def get_rate_limit_stats(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    stats: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            # Scan for all rate limit hit keys
            keys = list(rc.scan_iter(f"{_HITS_PREFIX}*"))
            for key in keys[:100]:
                val = rc.get(key)
                endpoint = key.replace(_HITS_PREFIX, "")
                stats.append({"endpoint": endpoint, "hits": int(val) if val else 0})
    except Exception as exc:
        logger.debug("Rate limit stats: %s", exc)
    return {"stats": stats, "computed_at": _utcnow().isoformat()}


@router.post("/rate-limits/{rule_id}/reset")
async def reset_rate_limit_counter(
    rule_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            rc.delete(f"{_HITS_PREFIX}{rule_id}")
    except Exception:
        pass
    await _log_superadmin_action(user.sub, "rate_limit_reset", {"rule_id": rule_id})
    return {"ok": True, "rule_id": rule_id}
