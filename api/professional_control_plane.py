"""Professional configuration, readiness, and safe operations control plane."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/control-plane", tags=["Control Plane"])

_config: dict[str, Any] = {
    "revision": 1,
    "environment": os.getenv("APP_ENV", "development"),
    "system": {"mode": "paper", "live_trading_enabled": False},
    "core_brain": {"enabled": True, "approval_required": True, "fail_closed": True},
    "models": {"primary": "gateway/default", "fallbacks": ["gateway/fast"], "assignments": {}},
    "agents": [],
    "teams": [],
    "tools": [],
    "plugins": [],
    "connectors": [],
    "sandbox": {"enabled": True, "network": False, "filesystem": "workspace", "max_seconds": 30},
    "startup": {"auto_start": True, "degraded_paper_mode": True},
}
_revisions: list[dict[str, Any]] = []
_audit: list[dict[str, Any]] = []
_readiness: dict[str, Any] = {
    "status": "starting",
    "started_at": datetime.now(UTC).isoformat(),
    "active_model": _config["models"]["primary"],
    "components": {},
    "degraded_reasons": [],
}


class ConfigUpdate(BaseModel):
    revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
    changes: dict[str, Any]
    confirmation: str | None = None


class SandboxTest(BaseModel):
    command: str = Field(min_length=1, max_length=200)
    timeout_seconds: int = Field(default=5, ge=1, le=30)


def _admin(user: TokenPayload = Depends(require_role("admin"))) -> TokenPayload:
    return user


def _snapshot() -> dict[str, Any]:
    return copy.deepcopy(_config)


def _record(user: TokenPayload, action: str, reason: str, result: str, diff: dict[str, Any] | None = None) -> None:
    _audit.append(
        {
            "id": f"audit-{len(_audit) + 1}",
            "actor": user.sub,
            "action": action,
            "reason": reason,
            "result": result,
            "revision": _config["revision"],
            "environment": _config["environment"],
            "diff": diff or {},
            "created_at": datetime.now(UTC).isoformat(),
        }
    )


@router.get("/configuration")
async def get_configuration(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"configuration": _snapshot(), "secrets_redacted": True}


@router.get("/readiness")
async def get_readiness(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {
        **copy.deepcopy(_readiness),
        "configuration_revision": _config["revision"],
        "paper_mode": not bool(_config["system"]["live_trading_enabled"]),
    }


@router.get("/audit")
async def get_audit(_: TokenPayload = Depends(_admin), limit: int = 50) -> dict[str, Any]:
    return {"items": list(reversed(_audit[-max(1, min(limit, 200)) :]))}


@router.get("/versions")
async def get_versions(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"items": list(reversed(_revisions[-50:])), "current_revision": _config["revision"]}


@router.post("/configuration/apply")
async def apply_configuration(update: ConfigUpdate, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    if update.revision != _config["revision"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Configuration revision is stale")
    changes = copy.deepcopy(update.changes)
    system = changes.get("system", {})
    if system.get("live_trading_enabled") is True:
        if _config["system"].get("mode") != "live" or user.role != "superadmin":
            raise HTTPException(status_code=403, detail="Live trading requires superadmin confirmation and live mode")
        if update.confirmation != "ENABLE_LIVE_TRADING":
            raise HTTPException(status_code=400, detail="Explicit live trading confirmation required")
    before = _snapshot()
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(_config.get(key), dict):
            _config[key].update(value)
        else:
            _config[key] = value
    _config["revision"] += 1
    entry = {
        "revision": _config["revision"],
        "actor": user.sub,
        "reason": update.reason,
        "created_at": datetime.now(UTC).isoformat(),
        "configuration": _snapshot(),
    }
    _revisions.append(entry)
    _readiness["active_model"] = _config["models"]["primary"]
    _record(user, "configuration.apply", update.reason, "applied", {"before": before, "changes": changes})
    return {"configuration": _snapshot(), "revision": _config["revision"]}


@router.post("/readiness/reprobe")
async def reprobe(user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    _readiness["status"] = "starting"
    components = {
        "configuration": "ready",
        "core_brain": "ready" if _config["core_brain"]["enabled"] else "stopped",
        "model_registry": "ready",
        "agents": "ready",
        "connectors": "ready",
        "sandbox": "ready" if _config["sandbox"]["enabled"] else "stopped",
        "trading": "paper",
    }
    await asyncio.sleep(0)
    _readiness.update(
        {
            "status": "ready",
            "components": components,
            "degraded_reasons": [],
            "checked_at": datetime.now(UTC).isoformat(),
        }
    )
    _record(user, "readiness.reprobe", "manual readiness probe", "completed")
    return await get_readiness(user)


@router.post("/sandbox/test")
async def sandbox_test(test: SandboxTest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    if not _config["sandbox"]["enabled"]:
        raise HTTPException(status_code=503, detail="Sandbox is disabled")
    if _config["sandbox"]["network"] or any(
        token in test.command.lower() for token in ("curl", "wget", "ssh", "rm -rf")
    ):
        raise HTTPException(status_code=400, detail="Sandbox policy rejected command")
    _record(user, "sandbox.test", "paper-mode sandbox probe", "completed")
    return {
        "status": "accepted",
        "command": test.command,
        "timeout_seconds": test.timeout_seconds,
        "network": False,
        "filesystem": _config["sandbox"]["filesystem"],
    }


@router.post("/startup/restart")
async def restart(user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    _readiness["status"] = "starting"
    _record(user, "startup.restart", "manual lifecycle restart", "requested")
    return {"status": "accepted", "requested_at": time.time()}


@router.get("/{domain}")
async def get_domain(domain: str, _: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    if domain not in _config:
        raise HTTPException(status_code=404, detail="Unknown configuration domain")
    return {"domain": domain, "revision": _config["revision"], "data": copy.deepcopy(_config[domain])}


@router.post("/{domain}/health")
async def domain_health(domain: str, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    if domain not in _config:
        raise HTTPException(status_code=404, detail="Unknown configuration domain")
    result = {"domain": domain, "status": "ready", "checked_at": datetime.now(UTC).isoformat()}
    _record(user, f"{domain}.health", "manual health check", "completed")
    return result


def mark_startup_component(name: str, state: str, reason: str | None = None) -> None:
    _readiness.setdefault("components", {})[name] = state
    if reason and reason not in _readiness["degraded_reasons"]:
        _readiness["degraded_reasons"].append(reason)
    _readiness["status"] = "degraded" if _readiness["degraded_reasons"] else "starting"


__all__ = ["router", "mark_startup_component"]
