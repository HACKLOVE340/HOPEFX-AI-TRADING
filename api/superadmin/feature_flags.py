# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin feature flags sub-router."""

import logging

from fastapi import APIRouter, Depends

from api.auth import TokenPayload

from ._shared import (
    SetFeatureFlagBody,
    SetUserFlagOverrideBody,
    _get_config_store,
    _log_superadmin_action,
    _require_superadmin,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Feature flags ─────────────────────────────────────────────────────────────


@router.get("/feature-flags")
async def get_feature_flags(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from config.feature_flags import flags

        result = []
        for name, enabled in vars(flags).items():
            if name.startswith("_"):
                continue
            result.append(
                {
                    "name": name,
                    "enabled": bool(enabled),
                    "description": name.replace("_", " ").title(),
                    "env_var": f"FEATURE_{name.upper()}",
                    "rollout_pct": 100,
                    "user_overrides": 0,
                }
            )
        return {"flags": result}
    except Exception as exc:
        logger.debug("feature_flags: %s", exc)
        return {"flags": []}


@router.patch("/feature-flags/{flag_name}")
async def set_feature_flag(
    flag_name: str,
    body: SetFeatureFlagBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from config.feature_flags import flags

        if hasattr(flags, flag_name):
            setattr(flags, flag_name, body.enabled)
        cs = _get_config_store()
        if cs:
            cs.set(f"feature_flag:{flag_name}", "1" if body.enabled else "0")
    except Exception as exc:
        logger.debug("set_feature_flag: %s", exc)
    _log_superadmin_action(user, "set_feature_flag", f"{flag_name}={body.enabled}")
    return {"ok": True, "flag": flag_name, "enabled": body.enabled}


@router.get("/feature-flags/overrides/{target_user_id}")
async def get_user_flag_overrides(target_user_id: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    overrides = []
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.hgetall(f"feature_flags:user:{target_user_id}")
            for flag, val in raw.items():
                overrides.append(
                    {
                        "flag": flag.decode() if isinstance(flag, bytes) else flag,
                        "enabled": val in (b"1", "1", True),
                    }
                )
    except Exception as exc:
        logger.debug("user_flag_overrides: %s", exc)
    return {"overrides": overrides}


@router.patch("/feature-flags/overrides/{target_user_id}/{flag_name}")
async def set_user_flag_override(
    target_user_id: str,
    flag_name: str,
    body: SetUserFlagOverrideBody,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            rc.hset(f"feature_flags:user:{target_user_id}", flag_name, "1" if body.enabled else "0")
    except Exception as exc:
        logger.debug("set_user_flag_override: %s", exc)
    _log_superadmin_action(user, "set_user_flag_override", f"user={target_user_id} {flag_name}={body.enabled}")
    return {"ok": True}
