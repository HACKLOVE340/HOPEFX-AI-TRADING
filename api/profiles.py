# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Trader Profile API

Endpoints:
  GET  /api/profiles/me           — current user's profile
  PUT  /api/profiles/me           — update current user's profile
  GET  /api/profiles/{trader_id}  — public profile by trader_id
  GET  /api/profiles/{trader_id}/signals — recent public signals
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from social.profiles import TraderProfile, TraderProfileManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profiles", tags=["Profiles"])

_manager = TraderProfileManager()


# ── Models ────────────────────────────────────────────────────────────────────


class ProfileUpdate(BaseModel):
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = None
    website: str | None = None
    is_public: bool | None = None


class ProfileResponse(BaseModel):
    trader_id: str
    username: str
    bio: str
    avatar_url: str | None
    website: str | None
    verified: bool
    is_public: bool
    total_followers: int
    total_following: int
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    sharpe_ratio: float
    created_at: str | None


def _profile_to_response(p: TraderProfile, include_email: bool = False) -> dict:
    d = p.to_dict()
    if not include_email:
        d.pop("email", None)
    d.setdefault("is_public", getattr(p, "is_public", True))
    return d


def _get_or_create(user: TokenPayload) -> TraderProfile:
    profile = _manager.get_profile(user.sub)
    if not profile:
        profile = _manager.create_profile(
            trader_id=user.sub,
            username=getattr(user, "username", user.sub),
            email=getattr(user, "email", ""),
        )
    return profile


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/me")
async def get_my_profile(user: TokenPayload = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    profile = _get_or_create(user)
    return _profile_to_response(profile, include_email=True)


@router.put("/me")
async def update_my_profile(
    body: ProfileUpdate,
    user: TokenPayload = Depends(get_current_user),
):
    """Update the authenticated user's profile fields."""
    _get_or_create(user)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    profile = _manager.update_profile(user.sub, **updates)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_to_response(profile, include_email=True)


@router.get("/{trader_id}")
async def get_public_profile(trader_id: str):
    """Return a public trader profile. Returns 404 when the trader does not exist."""
    profile = _manager.get_profile(trader_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Trader profile not found")
    return _profile_to_response(profile)


@router.get("/{trader_id}/signals")
async def get_trader_signals(trader_id: str, limit: int = 10):
    """
    Return recent public signals for a trader.

    Reads from the live social feed store — only signals that were
    published by the signal engine from opted-in users are returned.
    Returns an empty list when the trader has no public signals yet.
    """
    from api.social_feed import _feed_items

    signals = [item for item in _feed_items.values() if item.get("trader_id") == trader_id and item.get("is_public")]
    signals.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"signals": signals[:limit], "total": len(signals)}


@router.post("/{trader_id}/follow")
async def follow_trader(
    trader_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Follow a trader (increments follower count)."""
    if trader_id == user.sub:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    target = _manager.get_profile(trader_id)
    if target:
        _manager.update_profile(trader_id, total_followers=target.total_followers + 1)
    me = _get_or_create(user)
    _manager.update_profile(user.sub, total_following=me.total_following + 1)
    return {"followed": True, "trader_id": trader_id}


@router.delete("/{trader_id}/follow")
async def unfollow_trader(
    trader_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Unfollow a trader."""
    target = _manager.get_profile(trader_id)
    if target and target.total_followers > 0:
        _manager.update_profile(trader_id, total_followers=target.total_followers - 1)
    me = _get_or_create(user)
    if me.total_following > 0:
        _manager.update_profile(user.sub, total_following=me.total_following - 1)
    return {"unfollowed": True, "trader_id": trader_id}
