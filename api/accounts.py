# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/accounts.py
===============
Sub-account and team management API.

Endpoints
---------
GET    /api/accounts/sub-accounts          — list sub-accounts for current user
POST   /api/accounts/sub-accounts          — create sub-account
DELETE /api/accounts/sub-accounts/{id}     — remove sub-account
PATCH  /api/accounts/sub-accounts/{id}     — update label / role
GET    /api/accounts/teams                 — list teams the user belongs to
POST   /api/accounts/teams                 — create team
POST   /api/accounts/teams/{id}/members    — invite member
DELETE /api/accounts/teams/{id}/members/{uid} — remove member
PATCH  /api/accounts/teams/{id}/members/{uid} — change role

Sub-accounts are lightweight account aliases owned by the same user.
They share the parent's authentication but have independent P&L tracking,
risk limits, and broker connections.

Teams are multi-user groups with role-based access (admin/manager/trader/viewer).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["Accounts"])

# ── In-memory stores (swap for DB in production) ──────────────────────────────

_sub_accounts: Dict[str, Dict[str, Any]] = {}   # account_id → account
_teams: Dict[str, Dict[str, Any]] = {}           # team_id → team

# Seed demo data
def _seed() -> None:
    demo_uid = "user-001"
    acc_id = "sub-001"
    _sub_accounts[acc_id] = {
        "account_id": acc_id,
        "owner_id": demo_uid,
        "label": "Paper Trading",
        "broker": "oanda_paper",
        "balance": 100_000.0,
        "equity": 101_234.56,
        "daily_pnl": 1_234.56,
        "role": "trader",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    acc_id2 = "sub-002"
    _sub_accounts[acc_id2] = {
        "account_id": acc_id2,
        "owner_id": demo_uid,
        "label": "Live XAUUSD",
        "broker": "oanda_live",
        "balance": 25_000.0,
        "equity": 24_800.0,
        "daily_pnl": -200.0,
        "role": "trader",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    team_id = "team-001"
    _teams[team_id] = {
        "team_id": team_id,
        "name": "Alpha Desk",
        "creator_id": demo_uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "members": [
            {"user_id": demo_uid, "username": "HACKLOVE340", "email": "admin@hopefx.com", "role": "admin", "joined_at": datetime.now(timezone.utc).isoformat()},
            {"user_id": "user-002", "username": "trader_x", "email": "trader@hopefx.com", "role": "trader", "joined_at": datetime.now(timezone.utc).isoformat()},
        ],
    }

_seed()

# ── Schemas ───────────────────────────────────────────────────────────────────

class CreateSubAccountRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    broker: str = Field(default="oanda_paper")
    initial_balance: float = Field(default=10_000.0, ge=0)

class UpdateSubAccountRequest(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=64)
    active: Optional[bool] = None

class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)

class InviteMemberRequest(BaseModel):
    user_id: str
    username: str
    email: str
    role: str = Field(default="trader", pattern="^(admin|manager|trader|viewer)$")

class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(admin|manager|trader|viewer)$")

# ── Sub-account endpoints ─────────────────────────────────────────────────────

@router.get("/sub-accounts")
async def list_sub_accounts(user: TokenPayload = Depends(get_current_user)) -> Dict[str, Any]:
    """List all sub-accounts owned by the current user."""
    accounts = [a for a in _sub_accounts.values() if a["owner_id"] == user.sub]
    return {"accounts": accounts, "total": len(accounts)}


@router.post("/sub-accounts", status_code=status.HTTP_201_CREATED)
async def create_sub_account(
    req: CreateSubAccountRequest,
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a new sub-account under the current user."""
    # Limit: 10 sub-accounts per user
    existing = [a for a in _sub_accounts.values() if a["owner_id"] == user.sub]
    if len(existing) >= 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 sub-accounts per user",
        )
    acc_id = str(uuid.uuid4())
    account: Dict[str, Any] = {
        "account_id": acc_id,
        "owner_id": user.sub,
        "label": req.label,
        "broker": req.broker,
        "balance": req.initial_balance,
        "equity": req.initial_balance,
        "daily_pnl": 0.0,
        "role": "trader",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sub_accounts[acc_id] = account
    logger.info("Sub-account created: %s for user %s", acc_id, user.sub)
    return account


@router.patch("/sub-accounts/{account_id}")
async def update_sub_account(
    account_id: str,
    req: UpdateSubAccountRequest,
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update sub-account label or active status."""
    acc = _sub_accounts.get(account_id)
    if not acc or acc["owner_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    if req.label is not None:
        acc["label"] = req.label
    if req.active is not None:
        acc["active"] = req.active
    return acc


@router.delete("/sub-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sub_account(
    account_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Delete a sub-account. Cannot delete the last active account."""
    acc = _sub_accounts.get(account_id)
    if not acc or acc["owner_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    active = [a for a in _sub_accounts.values() if a["owner_id"] == user.sub and a["active"]]
    if len(active) <= 1 and acc.get("active"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the last active sub-account",
        )
    del _sub_accounts[account_id]

# ── Team endpoints ────────────────────────────────────────────────────────────

@router.get("/teams")
async def list_teams(user: TokenPayload = Depends(get_current_user)) -> Dict[str, Any]:
    """List teams the current user belongs to."""
    teams = [
        t for t in _teams.values()
        if any(m["user_id"] == user.sub for m in t["members"])
    ]
    return {"teams": teams, "total": len(teams)}


@router.post("/teams", status_code=status.HTTP_201_CREATED)
async def create_team(
    req: CreateTeamRequest,
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a new team. The creator is automatically added as admin."""
    team_id = str(uuid.uuid4())
    team: Dict[str, Any] = {
        "team_id": team_id,
        "name": req.name,
        "creator_id": user.sub,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "members": [
            {
                "user_id": user.sub,
                "username": getattr(user, "username", user.sub),
                "email": getattr(user, "email", ""),
                "role": "admin",
                "joined_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    _teams[team_id] = team
    logger.info("Team created: %s by %s", team_id, user.sub)
    return team


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    team_id: str,
    req: InviteMemberRequest,
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Invite a member to a team. Requires admin or manager role in the team."""
    team = _teams.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check caller is admin/manager
    caller = next((m for m in team["members"] if m["user_id"] == user.sub), None)
    if not caller or caller["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Insufficient team permissions")

    # Prevent duplicate
    if any(m["user_id"] == req.user_id for m in team["members"]):
        raise HTTPException(status_code=400, detail="User already in team")

    member = {
        "user_id": req.user_id,
        "username": req.username,
        "email": req.email,
        "role": req.role,
        "joined_at": datetime.now(timezone.utc).isoformat(),
    }
    team["members"].append(member)
    return member


@router.patch("/teams/{team_id}/members/{member_id}")
async def update_member_role(
    team_id: str,
    member_id: str,
    req: UpdateMemberRoleRequest,
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Change a team member's role. Requires admin role."""
    team = _teams.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    caller = next((m for m in team["members"] if m["user_id"] == user.sub), None)
    if not caller or caller["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    member = next((m for m in team["members"] if m["user_id"] == member_id), None)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member["role"] = req.role
    return member


@router.delete("/teams/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: str,
    member_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Remove a member from a team. Requires admin role or self-removal."""
    team = _teams.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    caller = next((m for m in team["members"] if m["user_id"] == user.sub), None)
    if not caller:
        raise HTTPException(status_code=403, detail="Not a team member")

    # Allow self-removal or admin removal
    if caller["role"] != "admin" and user.sub != member_id:
        raise HTTPException(status_code=403, detail="Admin role required to remove others")

    team["members"] = [m for m in team["members"] if m["user_id"] != member_id]
