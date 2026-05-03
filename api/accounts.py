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
GET    /api/accounts/sub-accounts/{id}     — get a specific sub-account
DELETE /api/accounts/sub-accounts/{id}     — remove sub-account
PATCH  /api/accounts/sub-accounts/{id}     — update label / role
POST   /api/accounts/sub-accounts/{id}/transfer — transfer balance between sub-accounts
GET    /api/accounts/teams                 — list teams the user belongs to
POST   /api/accounts/teams                 — create team
POST   /api/accounts/teams/{id}/members    — invite member
DELETE /api/accounts/teams/{id}/members/{uid} — remove member
PATCH  /api/accounts/teams/{id}/members/{uid} — change role

Storage
-------
Sub-accounts are persisted via api.db_store (backed by the configurations table
or an in-memory fallback). Keys follow the pattern:
  sub_account:{owner_id}:{account_id}  -> account dict
  sub_accounts_index:{owner_id}        -> list of account_ids

This allows the test suite to patch api.db_store.db_get/db_set/db_delete with
an in-memory dict without requiring a live database.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["Accounts"])

_MAX_ACCOUNTS_PER_USER = 10


# ── db_store helpers ──────────────────────────────────────────────────────────

def _store_get(key: str) -> Any | None:
    from api.db_store import db_get
    return db_get(key)


def _store_set(key: str, value: Any) -> None:
    from api.db_store import db_set
    db_set(key, value)


def _store_delete(key: str) -> None:
    from api.db_store import db_delete
    db_delete(key)


def _index_key(owner_id: str) -> str:
    return f"sub_accounts_index:{owner_id}"


def _account_key(owner_id: str, account_id: str) -> str:
    return f"sub_account:{owner_id}:{account_id}"


def _get_index(owner_id: str) -> list[str]:
    return _store_get(_index_key(owner_id)) or []


def _save_index(owner_id: str, ids: list[str]) -> None:
    _store_set(_index_key(owner_id), ids)


def _get_account(owner_id: str, account_id: str) -> dict | None:
    return _store_get(_account_key(owner_id, account_id))


def _save_account(owner_id: str, account: dict) -> None:
    _store_set(_account_key(owner_id, account["account_id"]), account)


def _delete_account(owner_id: str, account_id: str) -> None:
    _store_delete(_account_key(owner_id, account_id))


# ── Schemas ───────────────────────────────────────────────────────────────────


class CreateSubAccountRequest(BaseModel):
    # Accept both "label" (canonical) and "name" (alias).
    label: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    account_type: str = Field(default="personal", pattern="^(personal|prop_firm|team|managed)$")
    currency: str = Field(default="USD", max_length=10)
    initial_balance: float | None = Field(default=None, ge=0)
    max_drawdown_pct: float | None = Field(default=None, ge=0, le=100)
    daily_loss_limit: float | None = Field(default=None, ge=0)
    broker: str | None = None
    broker_account_id: str | None = None

    @model_validator(mode="after")
    def require_label_or_name(self) -> "CreateSubAccountRequest":
        if not (self.label or self.name):
            raise ValueError("Either 'label' or 'name' must be provided")
        return self

    @property
    def resolved_label(self) -> str:
        return (self.label or self.name) or ""


class UpdateSubAccountRequest(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    active: bool | None = None
    is_active: bool | None = None
    max_drawdown_pct: float | None = Field(default=None, ge=0, le=100)
    daily_loss_limit: float | None = Field(default=None, ge=0)
    broker: str | None = None
    broker_account_id: str | None = None

    @property
    def resolved_label(self) -> str | None:
        return self.label or self.name

    @property
    def resolved_active(self) -> bool | None:
        if self.active is not None:
            return self.active
        return self.is_active


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class InviteMemberRequest(BaseModel):
    user_id: str
    role: str = Field(default="trader", pattern="^(owner|trader|viewer|risk_manager)$")


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(owner|trader|viewer|risk_manager)$")


class TransferRequest(BaseModel):
    to_account_id: str
    amount: float = Field(..., gt=0)
    note: str = Field("", max_length=200)


# ── Sub-account endpoints ─────────────────────────────────────────────────────


@router.get("/sub-accounts")
async def list_sub_accounts(
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """List all sub-accounts owned by the current user."""
    ids = _get_index(user.sub)
    accounts = []
    for acc_id in ids:
        acc = _get_account(user.sub, acc_id)
        if acc is not None:
            accounts.append(acc)
    return {"accounts": accounts, "total": len(accounts)}


@router.post("/sub-accounts", status_code=status.HTTP_201_CREATED)
async def create_sub_account(
    req: CreateSubAccountRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new sub-account."""
    ids = _get_index(user.sub)
    if len(ids) >= _MAX_ACCOUNTS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {_MAX_ACCOUNTS_PER_USER} sub-accounts per user",
        )
    acc_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    balance = req.initial_balance if req.initial_balance is not None else 0.0
    account: dict[str, Any] = {
        "account_id": acc_id,
        "owner_id": user.sub,
        "label": req.resolved_label,
        "name": req.resolved_label,
        "description": req.description,
        "account_type": req.account_type,
        "currency": req.currency,
        "initial_balance": balance,
        "balance": balance,
        "current_balance": balance,
        "max_drawdown_pct": req.max_drawdown_pct,
        "daily_loss_limit": req.daily_loss_limit,
        "active": True,
        "is_active": True,
        "broker": req.broker,
        "broker_account_id": req.broker_account_id,
        "created_at": now,
        "updated_at": now,
    }
    _save_account(user.sub, account)
    ids.append(acc_id)
    _save_index(user.sub, ids)
    logger.info("Sub-account created: %s for user %s", acc_id, user.sub)
    return account


@router.get("/sub-accounts/{account_id}", summary="Get a specific sub-account")
async def get_sub_account(
    account_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return details of a single sub-account owned by the current user."""
    acc = _get_account(user.sub, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    return acc


@router.patch("/sub-accounts/{account_id}")
async def update_sub_account(
    account_id: str,
    req: UpdateSubAccountRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Update sub-account fields."""
    acc = _get_account(user.sub, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    if req.resolved_label is not None:
        acc["label"] = req.resolved_label
        acc["name"] = req.resolved_label
    if req.description is not None:
        acc["description"] = req.description
    if req.resolved_active is not None:
        acc["active"] = req.resolved_active
        acc["is_active"] = req.resolved_active
    if req.max_drawdown_pct is not None:
        acc["max_drawdown_pct"] = req.max_drawdown_pct
    if req.daily_loss_limit is not None:
        acc["daily_loss_limit"] = req.daily_loss_limit
    if req.broker is not None:
        acc["broker"] = req.broker
    if req.broker_account_id is not None:
        acc["broker_account_id"] = req.broker_account_id

    acc["updated_at"] = datetime.now(UTC).isoformat()
    _save_account(user.sub, acc)
    return acc


@router.delete("/sub-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sub_account(
    account_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Delete a sub-account. Cannot delete the last active account."""
    acc = _get_account(user.sub, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Sub-account not found")

    if acc.get("active", True) or acc.get("is_active", True):
        ids = _get_index(user.sub)
        active_count = sum(
            1 for aid in ids
            if (a := _get_account(user.sub, aid)) and (a.get("active", True) or a.get("is_active", True))
        )
        if active_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last active sub-account",
            )

    _delete_account(user.sub, account_id)
    ids = _get_index(user.sub)
    ids = [i for i in ids if i != account_id]
    _save_index(user.sub, ids)


@router.post("/sub-accounts/{account_id}/transfer", summary="Transfer balance between sub-accounts")
async def transfer_between_sub_accounts(
    account_id: str,
    req: TransferRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Transfer funds between two sub-accounts owned by the same user."""
    if account_id == req.to_account_id:
        raise HTTPException(status_code=400, detail="Source and destination must be different accounts")

    src = _get_account(user.sub, account_id)
    dst = _get_account(user.sub, req.to_account_id)

    if src is None:
        raise HTTPException(status_code=404, detail="Source sub-account not found")
    if dst is None:
        raise HTTPException(status_code=404, detail="Destination sub-account not found")

    src_bal = float(src.get("balance") or src.get("current_balance") or 0)
    dst_bal = float(dst.get("balance") or dst.get("current_balance") or 0)

    if src_bal < req.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance: {src_bal:.2f}",
        )

    new_src_bal = round(src_bal - req.amount, 2)
    new_dst_bal = round(dst_bal + req.amount, 2)

    src["balance"] = new_src_bal
    src["current_balance"] = new_src_bal
    src["updated_at"] = datetime.now(UTC).isoformat()

    dst["balance"] = new_dst_bal
    dst["current_balance"] = new_dst_bal
    dst["updated_at"] = datetime.now(UTC).isoformat()

    _save_account(user.sub, src)
    _save_account(user.sub, dst)

    logger.info(
        "Transfer %.2f from %s to %s by user %s",
        req.amount, account_id, req.to_account_id, user.sub,
    )
    return {
        "ok": True,
        "from_account_id": account_id,
        "to_account_id": req.to_account_id,
        "amount": req.amount,
        "from_balance": new_src_bal,
        "to_balance": new_dst_bal,
        "note": req.note,
    }


# ── Team endpoints ────────────────────────────────────────────────────────────

def _team_members_key(team_id: str) -> str:
    return f"team_members:{team_id}"


def _get_team_members(team_id: str) -> list[dict]:
    return _store_get(_team_members_key(team_id)) or []


def _save_team_members(team_id: str, members: list[dict]) -> None:
    _store_set(_team_members_key(team_id), members)


@router.get("/teams")
async def list_teams(user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
    """List teams the current user belongs to."""
    teams = []
    ids = _get_index(user.sub)
    for acc_id in ids:
        acc = _get_account(user.sub, acc_id)
        if acc and acc.get("account_type") == "team":
            members = _get_team_members(acc_id)
            my_role = next((m["role"] for m in members if m["user_id"] == user.sub), "owner")
            teams.append({**acc, "my_role": my_role})
    return {"teams": teams, "total": len(teams)}


@router.post("/teams", status_code=status.HTTP_201_CREATED)
async def create_team(
    req: CreateTeamRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new team. Creator is added as owner member."""
    ids = _get_index(user.sub)
    if len(ids) >= _MAX_ACCOUNTS_PER_USER:
        raise HTTPException(status_code=400, detail="Maximum accounts limit reached")

    team_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    team: dict[str, Any] = {
        "account_id": team_id,
        "owner_id": user.sub,
        "label": req.name,
        "name": req.name,
        "account_type": "team",
        "currency": "USD",
        "balance": 0.0,
        "current_balance": 0.0,
        "active": True,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    _save_account(user.sub, team)
    ids.append(team_id)
    _save_index(user.sub, ids)

    members = [{"user_id": user.sub, "role": "owner", "joined_at": now}]
    _save_team_members(team_id, members)

    logger.info("Team created: %s by %s", team_id, user.sub)
    return {"team_id": team_id, "name": req.name, "owner_id": user.sub, "created_at": now}


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    team_id: str,
    req: InviteMemberRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Invite a member to a team. Requires owner role."""
    members = _get_team_members(team_id)
    caller = next((m for m in members if m["user_id"] == user.sub), None)
    if caller is None or caller["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only team owners can invite members")
    if any(m["user_id"] == req.user_id for m in members):
        raise HTTPException(status_code=409, detail="User is already a member")

    now = datetime.now(UTC).isoformat()
    members.append({"user_id": req.user_id, "role": req.role, "joined_at": now})
    _save_team_members(team_id, members)
    return {"team_id": team_id, "user_id": req.user_id, "role": req.role}


@router.delete("/teams/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: str,
    member_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Remove a member from a team. Requires owner role."""
    members = _get_team_members(team_id)
    caller = next((m for m in members if m["user_id"] == user.sub), None)
    if caller is None or caller["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only team owners can remove members")
    updated = [m for m in members if m["user_id"] != member_id]
    if len(updated) == len(members):
        raise HTTPException(status_code=404, detail="Member not found")
    _save_team_members(team_id, updated)


@router.patch("/teams/{team_id}/members/{member_id}")
async def update_member_role(
    team_id: str,
    member_id: str,
    req: UpdateMemberRoleRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Change a team member's role. Requires owner role."""
    members = _get_team_members(team_id)
    caller = next((m for m in members if m["user_id"] == user.sub), None)
    if caller is None or caller["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only team owners can change roles")
    target = next((m for m in members if m["user_id"] == member_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")
    target["role"] = req.role
    _save_team_members(team_id, members)
    return {"team_id": team_id, "user_id": member_id, "role": req.role}
