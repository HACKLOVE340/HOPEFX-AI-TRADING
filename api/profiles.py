# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Trader Profile API

Endpoints:
  GET  /api/profiles              — paginated list of public profiles
  GET  /api/profiles/me           — current user's profile
  PUT  /api/profiles/me           — update current user's profile
  GET  /api/profiles/{trader_id}  — public profile by trader_id
  GET  /api/profiles/{trader_id}/signals — recent public signals
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from social.profiles import TraderProfile, TraderProfileManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profiles", tags=["Profiles"])

_manager = TraderProfileManager()

# Persistent avatar storage (outside the gitignored static/ build dir, which is
# wiped on every deploy). Served back via GET /api/profiles/avatar/{name}.
_AVATAR_DIR = Path(os.getenv("AVATAR_UPLOAD_DIR", "data/uploads/avatars"))
_AVATAR_MAX_BYTES = int(os.getenv("AVATAR_MAX_BYTES", str(2 * 1024 * 1024)))  # 2 MiB
_AVATAR_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
_AVATAR_NAME_RE = re.compile(r"^[a-f0-9]{32}\.(png|jpg|webp|gif)$")


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


@router.get("")
async def list_profiles(
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
    sort_by: str = "total_pnl",
) -> dict:
    """
    Return a paginated list of public trader profiles.

    Query params:
      limit   — max results (default 20, max 100)
      offset  — pagination offset
      search  — filter by username prefix (case-insensitive)
      sort_by — field to sort by: total_pnl | win_rate | total_trades | sharpe_ratio
    """
    limit = min(max(1, limit), 100)
    all_profiles = _manager.list_profiles()
    public = [p for p in all_profiles if getattr(p, "is_public", True)]

    if search:
        q = search.lower()
        public = [p for p in public if p.username.lower().startswith(q)]

    _sort_fields = {"total_pnl", "win_rate", "total_trades", "sharpe_ratio"}
    if sort_by not in _sort_fields:
        sort_by = "total_pnl"

    public.sort(key=lambda p: getattr(p, sort_by, 0) or 0, reverse=True)

    page = public[offset : offset + limit]
    return {
        "profiles": [_profile_to_response(p) for p in page],
        "total": len(public),
        "limit": limit,
        "offset": offset,
    }


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


@router.get("/{trader_id}/followers")
async def get_followers(trader_id: str):
    """Return follower count for a trader."""
    profile = _manager.get_profile(trader_id)
    count = getattr(profile, "total_followers", 0) if profile else 0
    return {"trader_id": trader_id, "followers": [], "count": count}


@router.get("/{trader_id}/following")
async def get_following(trader_id: str):
    """Return following count for a trader."""
    profile = _manager.get_profile(trader_id)
    count = getattr(profile, "total_following", 0) if profile else 0
    return {"trader_id": trader_id, "following": [], "count": count}


@router.get("/{trader_id}/strategies")
async def get_trader_strategies(trader_id: str):
    """Return public strategies for a trader."""
    try:
        from api.db_store import db_get

        strategies = db_get(f"strategies:{trader_id}") or []
        public = [s for s in strategies if s.get("is_public", False)]
        return {"strategies": public, "total": len(public)}
    except Exception:
        return {"strategies": [], "total": 0}


@router.get("/{trader_id}/stats")
async def get_trader_stats(trader_id: str):
    """Return performance stats for a trader."""
    profile = _manager.get_profile(trader_id)
    if not profile:
        return {
            "trader_id": trader_id,
            "total_trades": 0,
            "win_rate": 0.0,
            "total_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "followers": 0,
            "following": 0,
        }
    return {
        "trader_id": trader_id,
        "total_trades": getattr(profile, "total_trades", 0),
        "win_rate": getattr(profile, "win_rate", 0.0),
        "total_return_pct": getattr(profile, "total_return_pct", 0.0),
        "sharpe_ratio": getattr(profile, "sharpe_ratio", 0.0),
        "max_drawdown_pct": getattr(profile, "max_drawdown_pct", 0.0),
        "followers": getattr(profile, "total_followers", 0),
        "following": getattr(profile, "total_following", 0),
    }


@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: TokenPayload = Depends(get_current_user),
):
    """Store the uploaded avatar image and return its served URL.

    Previously this ignored the uploaded file and returned a Gravatar — the
    user's chosen image was silently discarded. Now the file is validated and
    persisted, and a stable served URL is returned.
    """
    ext = _AVATAR_EXT.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Avatar must be a PNG, JPEG, WebP or GIF image",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Avatar exceeds the {_AVATAR_MAX_BYTES // (1024 * 1024)} MiB limit",
        )

    # Deterministic per-user filename → one avatar per user, bounded growth,
    # no user-controlled path component (no traversal).
    name = f"{hashlib.sha256(user.sub.encode()).hexdigest()[:32]}.{ext}"
    try:
        _AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        # Remove any prior avatar with a different extension for this user.
        stem = name.split(".")[0]
        for old in _AVATAR_DIR.glob(f"{stem}.*"):
            if old.name != name:
                old.unlink(missing_ok=True)
        (_AVATAR_DIR / name).write_bytes(data)
    except OSError as exc:
        logger.error("avatar store failed for %s: %s", user.sub, exc)
        raise HTTPException(status_code=500, detail="Could not store avatar") from exc

    avatar_url = f"/api/profiles/avatar/{name}"
    _manager.update_profile(user.sub, avatar_url=avatar_url)
    return {"success": True, "avatar_url": avatar_url}


@router.get("/avatar/{name}")
async def get_avatar(name: str):
    """Serve a previously-uploaded avatar image by its stored filename."""
    if not _AVATAR_NAME_RE.match(name):
        raise HTTPException(status_code=404, detail="Not found")
    path = _AVATAR_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(path))
