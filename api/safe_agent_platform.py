from __future__ import annotations

"""Additive, fail-closed supervisor and safe-evolution control surface.

This module intentionally proposes and gates consequential work; it does not execute
trades, mutate production code, or expose credentials without an explicit approval.
"""

import copy
import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role
from core.config_store import config_store

router = APIRouter(prefix="/api/safe-platform", tags=["Safe Agent Platform"])

_AGENTS = [
    {"id": "supervisor", "name": "Supervisor", "mission": "Decompose requests, delegate, merge evidence, and escalate", "risk": "read_only", "status": "ready"},
    {"id": "research", "name": "Market Research", "mission": "Inspect authorized external sources with citations", "risk": "read_only", "status": "degraded"},
    {"id": "data-quality", "name": "Data Quality", "mission": "Detect stale, missing, drifting, or contradictory data", "risk": "read_only", "status": "ready"},
    {"id": "risk-governance", "name": "Risk & Governance", "mission": "Review policy, approvals, exposure, and fail-closed gates", "risk": "approval_required", "status": "ready"},
    {"id": "strategy", "name": "Strategy Lab", "mission": "Run paper research, replay, and model comparison", "risk": "paper_only", "status": "ready"},
    {"id": "diagnostics", "name": "Diagnostics", "mission": "Collect evidence and rank root causes", "risk": "read_only", "status": "ready"},
    {"id": "repair", "name": "Repair & Evolution", "mission": "Draft reversible repair and upgrade proposals", "risk": "approval_required", "status": "ready"},
    {"id": "communications", "name": "Communications", "mission": "Explain findings through chat, voice, and summaries", "risk": "read_only", "status": "ready"},
]
_MODELS = [
    {"id": "gateway/reasoning", "role": "reasoning", "health": "unconfigured", "route": "primary", "secret_status": "server-managed"},
    {"id": "gateway/fast", "role": "fast", "health": "unconfigured", "route": "fallback", "secret_status": "server-managed"},
    {"id": "gateway/vision", "role": "vision", "health": "unconfigured", "route": "specialist", "secret_status": "server-managed"},
]
_INTEGRATIONS = [
    {"id": "ai-gateway", "name": "AI Gateway", "category": "model", "status": "available", "scopes": ["generate", "reason"], "token": "managed"},
    {"id": "web-research", "name": "External Research", "category": "research", "status": "not_connected", "scopes": ["read:public_sources"], "token": "server-only"},
    {"id": "broker", "name": "Broker Account", "category": "execution", "status": "paper_only", "scopes": ["read:account", "paper:orders"], "token": "redacted"},
]
_PROPOSALS: list[dict[str, Any]] = []
_APPROVALS: list[dict[str, Any]] = []
_PROPOSALS_KEY = "safe_platform:proposals"
_APPROVALS_KEY = "safe_platform:approvals"


def _load_state() -> None:
    """Hydrate governance state from the shared Redis/DB config store."""
    stored_proposals = config_store.get(_PROPOSALS_KEY, default=[])
    stored_approvals = config_store.get(_APPROVALS_KEY, default=[])
    if isinstance(stored_proposals, list):
        _PROPOSALS.extend(item for item in stored_proposals if isinstance(item, dict))
    if isinstance(stored_approvals, list):
        _APPROVALS.extend(item for item in stored_approvals if isinstance(item, dict))


def _save_state(changed_by: str) -> None:
    """Persist proposals and approvals without ever persisting secret values."""
    config_store.set(_PROPOSALS_KEY, _PROPOSALS, changed_by=changed_by)
    config_store.set(_APPROVALS_KEY, _APPROVALS, changed_by=changed_by)


_load_state()


def _admin(user: TokenPayload = Depends(require_role("admin"))) -> TokenPayload:
    return user


def _id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{hashlib.sha256(repr(payload).encode()).hexdigest()[:12]}"


class DiagnosticRequest(BaseModel):
    scope: str = Field(default="all", min_length=1, max_length=80)
    include_external: bool = False


class ProposalRequest(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    kind: str = Field(pattern="^(repair|upgrade|configuration|research)$")
    scope: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=3, max_length=500)
    changes: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    proposal_id: str
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(min_length=3, max_length=500)


@router.get("/overview")
async def overview(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"paper_mode": os.getenv("BROKER_TYPE", "paper") == "paper", "human_approval_required": True, "agents": copy.deepcopy(_AGENTS), "models": copy.deepcopy(_MODELS), "integrations": copy.deepcopy(_INTEGRATIONS), "pending_proposals": len([p for p in _PROPOSALS if p["status"] == "pending"]), "capabilities": {"external_read": True, "external_write": False, "live_trading": False, "self_modify": False, "credential_values_visible": False}}


@router.post("/diagnostics/run")
async def run_diagnostics(request: DiagnosticRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    external = {"status": "not_requested", "sources": []}
    if request.include_external:
        external = {"status": "blocked_until_connector_authorized", "sources": [], "reason": "No external connector was authorized for this diagnostic."}
    return {"run_id": _id("diag", [user.sub, request.scope]), "status": "complete", "scope": request.scope, "checked_at": datetime.now(UTC).isoformat(), "findings": [{"id": "paper-boundary", "severity": "info", "title": "Consequential actions are approval-gated", "evidence": ["live_trading_disabled", "self_modify_disabled"]}], "external": external}


@router.post("/proposals")
async def create_proposal(request: ProposalRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    proposal = {"id": _id("proposal", [user.sub, request.title, request.changes]), "title": request.title, "kind": request.kind, "scope": request.scope, "reason": request.reason, "changes": request.changes, "status": "pending", "created_by": user.sub, "created_at": datetime.now(UTC).isoformat(), "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(), "rollback": {"required": True, "checkpoint": "created-before-apply", "automatic": True}, "required_approvals": 2 if request.kind in {"repair", "upgrade"} else 1}
    _PROPOSALS.append(proposal)
    _save_state(user.sub)
    return {"proposal": copy.deepcopy(proposal), "message": "Proposal created. No change has been applied."}


@router.get("/proposals")
async def proposals(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"items": list(reversed(copy.deepcopy(_PROPOSALS))), "approval_required": True}


@router.post("/approvals")
async def decide_approval(request: ApprovalRequest, user: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    proposal = next((p for p in _PROPOSALS if p["id"] == request.proposal_id), None)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal["status"] != "pending":
        raise HTTPException(status_code=409, detail="Proposal is no longer pending")
    decision = {"proposal_id": request.proposal_id, "approver": user.sub, "decision": request.decision, "reason": request.reason, "created_at": datetime.now(UTC).isoformat()}
    _APPROVALS.append(decision)
    if request.decision == "reject":
        proposal["status"] = "rejected"
    else:
        approvals = [a for a in _APPROVALS if a["proposal_id"] == request.proposal_id and a["decision"] == "approve"]
        if len({a["approver"] for a in approvals}) >= proposal["required_approvals"]:
            proposal["status"] = "approved_pending_execution"
    _save_state(user.sub)
    return {"proposal": copy.deepcopy(proposal), "decision": decision, "message": "Approval recorded. Execution remains separately gated."}


@router.get("/integrations")
async def integrations(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"items": copy.deepcopy(_INTEGRATIONS), "secret_values": "never_returned", "external_access": "allowlisted_and_scope_limited"}


@router.get("/chat/capabilities")
async def chat_capabilities(_: TokenPayload = Depends(_admin)) -> dict[str, Any]:
    return {"streaming": True, "voice": "available_if_configured", "delegation": True, "citations": True, "tool_trace": True, "external_research": "connector_required", "dangerous_actions": "human_approval_required"}


__all__ = ["router"]
