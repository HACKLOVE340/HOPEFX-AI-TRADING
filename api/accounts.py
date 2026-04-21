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

UTC = timezone.utc
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["Accounts"])

# ── DB-backed persistence via api/db_store (configurations table) ─────────────
# Keys: "accounts:sub:{user_id}" → {account_id: {...}, ...}
#       "accounts:teams:{team_id}" → {team_id, name, members, ...}
#       "accounts:team_index:{user_id}" → [team_id, ...]

_SUB_KEY = "accounts:sub:{uid}"
_TEAM_KEY = "accounts:team:{tid}"
_TIDX_KEY = "accounts:team_index:{uid}"


def _load_sub_accounts(user_id: str) -> dict[str, Any]:
    """Load sub-accounts for a user from DB; return empty dict on miss."""
    from api.db_store import db_get

    return db_get(_SUB_KEY.format(uid=user_id)) or {}


def _save_sub_accounts(user_id: str, accounts: dict[str, Any]) -> None:
    from api.db_store import db_set

    db_set(_SUB_KEY.format(uid=user_id), accounts, changed_by=user_id)


def _load_team(team_id: str) -> dict[str, Any] | None:
    from api.db_store import db_get

    return db_get(_TEAM_KEY.format(tid=team_id))


def _save_team(team: dict[str, Any]) -> None:
    from api.db_store import db_set

    db_set(
        _TEAM_KEY.format(tid=team["team_id"]),
        team,
        changed_by=team.get("creator_id", "system"),
    )


def _delete_team(team_id: str) -> None:
    from api.db_store import db_delete

    db_delete(_TEAM_KEY.format(tid=team_id))


def _load_team_index(user_id: str) -> list:
    """Return list of team_ids the user belongs to."""
    from api.db_store import db_get

    return db_get(_TIDX_KEY.format(uid=user_id)) or []


def _add_to_team_index(user_id: str, team_id: str) -> None:
    from api.db_store import db_get, db_set

    idx = db_get(_TIDX_KEY.format(uid=user_id)) or []
    if team_id not in idx:
        idx.append(team_id)
        db_set(_TIDX_KEY.format(uid=user_id), idx, changed_by=user_id)


def _remove_from_team_index(user_id: str, team_id: str) -> None:
    from api.db_store import db_get, db_set

    idx = db_get(_TIDX_KEY.format(uid=user_id)) or []
    idx = [t for t in idx if t != team_id]
    db_set(_TIDX_KEY.format(uid=user_id), idx, changed_by=user_id)


# ── Schemas ───────────────────────────────────────────────────────────────────


class CreateSubAccountRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    broker: str = Field(default="oanda_paper")
    initial_balance: float = Field(default=10_000.0, ge=0)


class UpdateSubAccountRequest(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=64)
    active: bool | None = None


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
async def list_sub_accounts(
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """List all sub-accounts owned by the current user."""
    accounts = list(_load_sub_accounts(user.sub).values())
    return {"accounts": accounts, "total": len(accounts)}


def _require_elite_plan(user: TokenPayload) -> None:
    """Raise 403 if the user's subscription is below Elite tier.

    Admins and superadmins bypass the plan gate — they always have full access.
    """
    role = getattr(user, "role", "user")
    if role in ("admin", "superadmin"):
        return
    try:
        from monetization.subscription import SubscriptionTier, subscription_manager

        sub = subscription_manager.get_user_subscription(user.sub)
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sub-accounts require an Elite subscription ($10,000/mo). Upgrade at /checkout.",
            )
        tier_order = [
            SubscriptionTier.FREE,
            SubscriptionTier.STARTER,
            SubscriptionTier.PROFESSIONAL,
            SubscriptionTier.ENTERPRISE,
            SubscriptionTier.ELITE,
        ]
        current_tier = getattr(sub, "tier", SubscriptionTier.FREE)
        if tier_order.index(current_tier) < tier_order.index(SubscriptionTier.ELITE):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Sub-accounts require an Elite subscription ($10,000/mo). "
                    f"Your current plan: {current_tier.value}. Upgrade at /checkout."
                ),
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Elite plan check failed (allowing through): %s", exc)


@router.post("/sub-accounts", status_code=status.HTTP_201_CREATED)
async def create_sub_account(
    req: CreateSubAccountRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new sub-account under the current user. Requires Elite plan."""
    _require_elite_plan(user)
    existing = _load_sub_accounts(user.sub)
    if len(existing) >= 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 sub-accounts per user",
        )
    acc_id = str(uuid.uuid4())
    account: dict[str, Any] = {
        "account_id": acc_id,
        "owner_id": user.sub,
        "label": req.label,
        "broker": req.broker,
        "balance": req.initial_balance,
        "equity": req.initial_balance,
        "daily_pnl": 0.0,
        "role": "trader",
        "active": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    existing[acc_id] = account
    _save_sub_accounts(user.sub, existing)
    logger.info("Sub-account created: %s for user %s", acc_id, user.sub)
    return account


@router.patch("/sub-accounts/{account_id}")
async def update_sub_account(
    account_id: str,
    req: UpdateSubAccountRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Update sub-account label or active status."""
    existing = _load_sub_accounts(user.sub)
    acc = existing.get(account_id)
    if not acc or acc["owner_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    if req.label is not None:
        acc["label"] = req.label
    if req.active is not None:
        acc["active"] = req.active
    existing[account_id] = acc
    _save_sub_accounts(user.sub, existing)
    return acc


@router.delete("/sub-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sub_account(
    account_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Delete a sub-account. Cannot delete the last active account."""
    existing = _load_sub_accounts(user.sub)
    acc = existing.get(account_id)
    if not acc or acc["owner_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    active = [a for a in existing.values() if a.get("active")]
    if len(active) <= 1 and acc.get("active"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the last active sub-account",
        )
    del existing[account_id]
    _save_sub_accounts(user.sub, existing)


# ── Team endpoints ────────────────────────────────────────────────────────────


@router.get("/teams")
async def list_teams(user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
    """List teams the current user belongs to."""
    team_ids = _load_team_index(user.sub)
    teams = [t for tid in team_ids if (t := _load_team(tid)) is not None]
    return {"teams": teams, "total": len(teams)}


@router.post("/teams", status_code=status.HTTP_201_CREATED)
async def create_team(
    req: CreateTeamRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new team. The creator is automatically added as admin."""
    team_id = str(uuid.uuid4())
    team: dict[str, Any] = {
        "team_id": team_id,
        "name": req.name,
        "creator_id": user.sub,
        "created_at": datetime.now(UTC).isoformat(),
        "members": [
            {
                "user_id": user.sub,
                "username": getattr(user, "username", user.sub),
                "email": getattr(user, "email", ""),
                "role": "admin",
                "joined_at": datetime.now(UTC).isoformat(),
            }
        ],
    }
    _save_team(team)
    _add_to_team_index(user.sub, team_id)
    logger.info("Team created: %s by %s", team_id, user.sub)
    return team


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    team_id: str,
    req: InviteMemberRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Invite a member to a team. Requires admin or manager role in the team."""
    team = _load_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    caller = next((m for m in team["members"] if m["user_id"] == user.sub), None)
    if not caller or caller["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Insufficient team permissions")

    if any(m["user_id"] == req.user_id for m in team["members"]):
        raise HTTPException(status_code=400, detail="User already in team")

    member = {
        "user_id": req.user_id,
        "username": req.username,
        "email": req.email,
        "role": req.role,
        "joined_at": datetime.now(UTC).isoformat(),
    }
    team["members"].append(member)
    _save_team(team)
    _add_to_team_index(req.user_id, team_id)
    return member


@router.patch("/teams/{team_id}/members/{member_id}")
async def update_member_role(
    team_id: str,
    member_id: str,
    req: UpdateMemberRoleRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Change a team member's role. Requires admin role."""
    team = _load_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    caller = next((m for m in team["members"] if m["user_id"] == user.sub), None)
    if not caller or caller["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    member = next((m for m in team["members"] if m["user_id"] == member_id), None)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member["role"] = req.role
    _save_team(team)
    return member


@router.delete("/teams/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: str,
    member_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Remove a member from a team. Requires admin role or self-removal."""
    team = _load_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    caller = next((m for m in team["members"] if m["user_id"] == user.sub), None)
    if not caller:
        raise HTTPException(status_code=403, detail="Not a team member")

    if caller["role"] != "admin" and user.sub != member_id:
        raise HTTPException(status_code=403, detail="Admin role required to remove others")

    team["members"] = [m for m in team["members"] if m["user_id"] != member_id]
    _save_team(team)
    _remove_from_team_index(member_id, team_id)
