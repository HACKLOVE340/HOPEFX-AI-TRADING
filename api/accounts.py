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

Sub-accounts are lightweight account aliases owned by the same user.
They share the parent's authentication but have independent P&L tracking,
risk limits, and broker connections.

Teams are multi-user groups with role-based access (admin/manager/trader/viewer).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["Accounts"])


# ── DB session helper ─────────────────────────────────────────────────────────

def _get_db():
    """Return a synchronous SQLAlchemy session, or None."""
    try:
        from database.connection import SessionLocal
        return SessionLocal()
    except Exception as exc:
        logger.warning("accounts: DB unavailable: %s", exc)
        return None


# ── Schemas ───────────────────────────────────────────────────────────────────


class CreateSubAccountRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    account_type: str = Field(default="personal", pattern="^(personal|prop_firm|team|managed)$")
    currency: str = Field(default="USD", max_length=10)
    initial_balance: float | None = Field(default=None, ge=0)
    max_drawdown_pct: float | None = Field(default=None, ge=0, le=100)
    daily_loss_limit: float | None = Field(default=None, ge=0)
    broker: str | None = None
    broker_account_id: str | None = None


class UpdateSubAccountRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    is_active: bool | None = None
    max_drawdown_pct: float | None = Field(default=None, ge=0, le=100)
    daily_loss_limit: float | None = Field(default=None, ge=0)
    broker: str | None = None
    broker_account_id: str | None = None


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class InviteMemberRequest(BaseModel):
    user_id: str
    role: str = Field(default="trader", pattern="^(owner|trader|viewer|risk_manager)$")


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(owner|trader|viewer|risk_manager)$")


# ── Sub-account endpoints ─────────────────────────────────────────────────────


@router.get("/sub-accounts")
async def list_sub_accounts(
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """List all sub-accounts owned by the current user from the sub_accounts table."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rows = db.execute(
            text(
                "SELECT id, owner_id, name, description, account_type, currency, "
                "initial_balance, current_balance, max_drawdown_pct, daily_loss_limit, "
                "is_active, broker, broker_account_id, created_at, updated_at "
                "FROM sub_accounts WHERE owner_id = :uid ORDER BY created_at ASC"
            ),
            {"uid": user.sub},
        ).fetchall()
        accounts = [dict(r._mapping) for r in rows]
        return {"accounts": accounts, "total": len(accounts)}
    finally:
        db.close()


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
    """Create a new sub-account in the sub_accounts table."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        count = db.execute(
            text("SELECT COUNT(*) FROM sub_accounts WHERE owner_id = :uid"),
            {"uid": user.sub},
        ).scalar()
        if count >= 10:
            raise HTTPException(status_code=400, detail="Maximum 10 sub-accounts per user")
        acc_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        db.execute(
            text(
                "INSERT INTO sub_accounts "
                "(id, owner_id, name, description, account_type, currency, "
                "initial_balance, current_balance, max_drawdown_pct, daily_loss_limit, "
                "is_active, broker, broker_account_id, created_at, updated_at) "
                "VALUES (:id, :owner_id, :name, :description, :account_type, :currency, "
                ":initial_balance, :current_balance, :max_drawdown_pct, :daily_loss_limit, "
                ":is_active, :broker, :broker_account_id, :created_at, :updated_at)"
            ),
            {
                "id": acc_id,
                "owner_id": user.sub,
                "name": req.name,
                "description": req.description,
                "account_type": req.account_type,
                "currency": req.currency,
                "initial_balance": req.initial_balance,
                "current_balance": req.initial_balance,
                "max_drawdown_pct": req.max_drawdown_pct,
                "daily_loss_limit": req.daily_loss_limit,
                "is_active": True,
                "broker": req.broker,
                "broker_account_id": req.broker_account_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        db.commit()
        logger.info("Sub-account created: %s for user %s", acc_id, user.sub)
        return {
            "id": acc_id, "owner_id": user.sub, "name": req.name,
            "account_type": req.account_type, "currency": req.currency,
            "initial_balance": req.initial_balance, "current_balance": req.initial_balance,
            "is_active": True, "created_at": now.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("create_sub_account error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create sub-account")
    finally:
        db.close()


@router.get("/sub-accounts/{account_id}", summary="Get a specific sub-account")
async def get_sub_account(
    account_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return details of a single sub-account owned by the current user."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.execute(
            text("SELECT * FROM sub_accounts WHERE id = :id AND owner_id = :uid"),
            {"id": account_id, "uid": user.sub},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Sub-account not found")
        return dict(row._mapping)
    finally:
        db.close()


@router.patch("/sub-accounts/{account_id}")
async def update_sub_account(
    account_id: str,
    req: UpdateSubAccountRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Update sub-account fields."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.execute(
            text("SELECT id FROM sub_accounts WHERE id = :id AND owner_id = :uid"),
            {"id": account_id, "uid": user.sub},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Sub-account not found")

        updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if req.name is not None:
            updates["name"] = req.name
        if req.description is not None:
            updates["description"] = req.description
        if req.is_active is not None:
            updates["is_active"] = req.is_active
        if req.max_drawdown_pct is not None:
            updates["max_drawdown_pct"] = req.max_drawdown_pct
        if req.daily_loss_limit is not None:
            updates["daily_loss_limit"] = req.daily_loss_limit
        if req.broker is not None:
            updates["broker"] = req.broker
        if req.broker_account_id is not None:
            updates["broker_account_id"] = req.broker_account_id

        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = account_id
        db.execute(
            text(f"UPDATE sub_accounts SET {set_clause} WHERE id = :id"),  # nosec B608
            updates,
        )
        db.commit()
        updated = db.execute(
            text("SELECT * FROM sub_accounts WHERE id = :id"),
            {"id": account_id},
        ).fetchone()
        return dict(updated._mapping)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("update_sub_account error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update sub-account")
    finally:
        db.close()


@router.delete("/sub-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sub_account(
    account_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Delete a sub-account. Cannot delete the last active account."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.execute(
            text("SELECT is_active FROM sub_accounts WHERE id = :id AND owner_id = :uid"),
            {"id": account_id, "uid": user.sub},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Sub-account not found")
        if row.is_active:
            active_count = db.execute(
                text("SELECT COUNT(*) FROM sub_accounts WHERE owner_id = :uid AND is_active = true"),
                {"uid": user.sub},
            ).scalar()
            if active_count <= 1:
                raise HTTPException(status_code=400, detail="Cannot delete the last active sub-account")
        db.execute(text("DELETE FROM sub_accounts WHERE id = :id"), {"id": account_id})
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("delete_sub_account error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete sub-account")
    finally:
        db.close()


class TransferRequest(BaseModel):
    to_account_id: str
    amount: float = Field(..., gt=0)
    note: str = Field("", max_length=200)


@router.post("/sub-accounts/{account_id}/transfer", summary="Transfer balance between sub-accounts")
async def transfer_between_sub_accounts(
    account_id: str,
    req: TransferRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Transfer funds between two sub-accounts owned by the same user."""
    if account_id == req.to_account_id:
        raise HTTPException(status_code=400, detail="Source and destination must differ")
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        src = db.execute(
            text("SELECT id, current_balance FROM sub_accounts WHERE id = :id AND owner_id = :uid"),
            {"id": account_id, "uid": user.sub},
        ).fetchone()
        dst = db.execute(
            text("SELECT id, current_balance FROM sub_accounts WHERE id = :id AND owner_id = :uid"),
            {"id": req.to_account_id, "uid": user.sub},
        ).fetchone()
        if src is None:
            raise HTTPException(status_code=404, detail="Source sub-account not found")
        if dst is None:
            raise HTTPException(status_code=404, detail="Destination sub-account not found")
        src_bal = float(src.current_balance or 0)
        if src_bal < req.amount:
            raise HTTPException(status_code=400, detail=f"Insufficient balance: {src_bal:.2f}")
        now = datetime.now(UTC)
        db.execute(
            text("UPDATE sub_accounts SET current_balance = current_balance - :amt, updated_at = :now WHERE id = :id"),
            {"amt": req.amount, "now": now, "id": account_id},
        )
        db.execute(
            text("UPDATE sub_accounts SET current_balance = current_balance + :amt, updated_at = :now WHERE id = :id"),
            {"amt": req.amount, "now": now, "id": req.to_account_id},
        )
        db.commit()
        logger.info("Transfer %.2f from %s to %s by user %s", req.amount, account_id, req.to_account_id, user.sub)
        return {
            "ok": True,
            "from_account_id": account_id,
            "to_account_id": req.to_account_id,
            "amount": req.amount,
            "from_balance": round(src_bal - req.amount, 2),
            "to_balance": round(float(dst.current_balance or 0) + req.amount, 2),
            "note": req.note,
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("transfer error: %s", exc)
        raise HTTPException(status_code=500, detail="Transfer failed")
    finally:
        db.close()


# ── Team endpoints — backed by sub_accounts + sub_account_members tables ──────
# Teams are modelled as sub_accounts with account_type="team".
# Members are rows in sub_account_members.


@router.get("/teams")
async def list_teams(user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
    """List teams the current user belongs to (as owner or member)."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rows = db.execute(
            text(
                "SELECT sa.id, sa.owner_id, sa.name, sa.description, sa.created_at, "
                "sam.role AS my_role "
                "FROM sub_accounts sa "
                "JOIN sub_account_members sam ON sam.sub_account_id = sa.id "
                "WHERE sam.user_id = :uid AND sa.account_type = 'team' "
                "ORDER BY sa.created_at ASC"
            ),
            {"uid": user.sub},
        ).fetchall()
        teams = [dict(r._mapping) for r in rows]
        return {"teams": teams, "total": len(teams)}
    finally:
        db.close()


@router.post("/teams", status_code=status.HTTP_201_CREATED)
async def create_team(
    req: CreateTeamRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new team sub-account. Creator is added as owner member."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        team_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        db.execute(
            text(
                "INSERT INTO sub_accounts (id, owner_id, name, account_type, currency, is_active, created_at, updated_at) "
                "VALUES (:id, :owner_id, :name, 'team', 'USD', true, :now, :now)"
            ),
            {"id": team_id, "owner_id": user.sub, "name": req.name, "now": now},
        )
        db.execute(
            text(
                "INSERT INTO sub_account_members (sub_account_id, user_id, role, joined_at) "
                "VALUES (:tid, :uid, 'owner', :now)"
            ),
            {"tid": team_id, "uid": user.sub, "now": now},
        )
        db.commit()
        logger.info("Team created: %s by %s", team_id, user.sub)
        return {"team_id": team_id, "name": req.name, "owner_id": user.sub, "created_at": now.isoformat()}
    except Exception as exc:
        db.rollback()
        logger.error("create_team error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create team")
    finally:
        db.close()


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    team_id: str,
    req: InviteMemberRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Invite a member to a team. Requires owner role."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        # Verify caller is owner
        caller = db.execute(
            text("SELECT role FROM sub_account_members WHERE sub_account_id = :tid AND user_id = :uid"),
            {"tid": team_id, "uid": user.sub},
        ).fetchone()
        if caller is None or caller.role not in ("owner",):
            raise HTTPException(status_code=403, detail="Only team owners can invite members")
        now = datetime.now(UTC)
        db.execute(
            text(
                "INSERT INTO sub_account_members (sub_account_id, user_id, role, joined_at) "
                "VALUES (:tid, :uid, :role, :now) "
                "ON CONFLICT (sub_account_id, user_id) DO UPDATE SET role = :role"
            ),
            {"tid": team_id, "uid": req.user_id, "role": req.role, "now": now},
        )
        db.commit()
        return {"team_id": team_id, "user_id": req.user_id, "role": req.role, "joined_at": now.isoformat()}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("invite_member error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to invite member")
    finally:
        db.close()


@router.delete("/teams/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: str,
    member_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Remove a member from a team. Requires owner role."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        caller = db.execute(
            text("SELECT role FROM sub_account_members WHERE sub_account_id = :tid AND user_id = :uid"),
            {"tid": team_id, "uid": user.sub},
        ).fetchone()
        if caller is None or caller.role not in ("owner",):
            raise HTTPException(status_code=403, detail="Only team owners can remove members")
        db.execute(
            text("DELETE FROM sub_account_members WHERE sub_account_id = :tid AND user_id = :uid"),
            {"tid": team_id, "uid": member_id},
        )
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to remove member")
    finally:
        db.close()


@router.patch("/teams/{team_id}/members/{member_id}")
async def update_member_role(
    team_id: str,
    member_id: str,
    req: UpdateMemberRoleRequest,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Change a team member's role. Requires owner role."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        caller = db.execute(
            text("SELECT role FROM sub_account_members WHERE sub_account_id = :tid AND user_id = :uid"),
            {"tid": team_id, "uid": user.sub},
        ).fetchone()
        if caller is None or caller.role not in ("owner",):
            raise HTTPException(status_code=403, detail="Only team owners can change roles")
        db.execute(
            text("UPDATE sub_account_members SET role = :role WHERE sub_account_id = :tid AND user_id = :uid"),
            {"role": req.role, "tid": team_id, "uid": member_id},
        )
        db.commit()
        return {"team_id": team_id, "user_id": member_id, "role": req.role}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update role")
    finally:
        db.close()



