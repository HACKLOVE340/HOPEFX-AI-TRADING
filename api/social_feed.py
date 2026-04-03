# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Social Signal Feed API

Endpoints:
  GET  /api/feed                    — paginated community signal feed
  POST /api/feed/{signal_id}/react  — thumbs up / thumbs down
  POST /api/feed/{signal_id}/comment — add a comment
  GET  /api/feed/{signal_id}/comments — list comments
  POST /api/feed/opt-in             — opt current user into public feed
  POST /api/feed/opt-out            — opt current user out of public feed

High-confidence signals (>= 70%) from the signal engine are published here.
Users can react and comment. Copy-count is tracked per signal.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from api.db_store import db_get, db_set

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feed", tags=["Social Feed"])

# ── In-memory stores ──────────────────────────────────────────────────────────

_feed_items: dict[str, dict] = {}  # signal_id → feed item
_reactions: dict[str, dict[str, str]] = {}  # signal_id → {user_id: "up"|"down"}
_comments: dict[str, list[dict]] = {}  # signal_id → list of comments
_opted_in: set = set()  # user_ids who opted into public feed

# ── Persistence helpers ───────────────────────────────────────────────────────


def _load_opted_in() -> None:
    """Load opted-in user set from DB on first access."""
    global _opted_in
    if _opted_in:
        return
    val = db_get("social_feed:opted_in")
    if isinstance(val, list):
        _opted_in = set(val)


def _save_opted_in() -> None:
    db_set("social_feed:opted_in", list(_opted_in), changed_by="social_feed")


# Feed starts empty — items are added by _publish_signal() when the signal
# engine emits high-confidence signals from opted-in users.


# ── Models ────────────────────────────────────────────────────────────────────


class ReactionBody(BaseModel):
    reaction: str = Field(..., pattern="^(up|down)$")


class CommentBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _publish_signal(signal: dict, username: str, trader_id: str) -> dict:
    """Called by the signal engine to publish a high-confidence signal."""
    sid = signal.get("signal_id") or str(uuid.uuid4())
    item = {
        "signal_id": sid,
        "symbol": signal.get("symbol", "XAU/USD"),
        "direction": signal.get("direction", "BUY"),
        "confidence": signal.get("confidence", 70.0),
        "entry_price": signal.get("entry_price", 0.0),
        "pnl": signal.get("pnl", 0.0),
        "copies": 0,
        "username": username,
        "trader_id": trader_id,
        "thumbs_up": 0,
        "thumbs_down": 0,
        "comment_count": 0,
        "is_public": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _feed_items[sid] = item
    _reactions[sid] = {}
    _comments[sid] = []
    return item


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
async def get_feed(
    page: int = 1,
    limit: int = 20,
    symbol: str | None = None,
):
    """Return paginated community signal feed (public — no auth required)."""
    items = [v for v in _feed_items.values() if v.get("is_public")]
    if symbol:
        items = [i for i in items if i["symbol"] == symbol]
    items.sort(key=lambda x: x["created_at"], reverse=True)
    start = (page - 1) * limit
    return {
        "items": items[start : start + limit],
        "total": len(items),
        "page": page,
        "pages": max(1, (len(items) + limit - 1) // limit),
    }


@router.post("/{signal_id}/react")
async def react_to_signal(
    signal_id: str,
    body: ReactionBody,
    user: TokenPayload = Depends(get_current_user),
):
    """Toggle a thumbs-up or thumbs-down reaction on a signal."""
    if signal_id not in _feed_items:
        raise HTTPException(status_code=404, detail="Signal not found")

    item = _feed_items[signal_id]
    prev = _reactions[signal_id].get(user.sub)

    # Remove previous reaction counts
    if prev == "up":
        item["thumbs_up"] = max(0, item["thumbs_up"] - 1)
    elif prev == "down":
        item["thumbs_down"] = max(0, item["thumbs_down"] - 1)

    # Toggle: clicking same reaction removes it
    if prev == body.reaction:
        _reactions[signal_id].pop(user.sub, None)
        new_reaction = None
    else:
        _reactions[signal_id][user.sub] = body.reaction
        new_reaction = body.reaction
        if body.reaction == "up":
            item["thumbs_up"] += 1
        else:
            item["thumbs_down"] += 1

    return {
        "signal_id": signal_id,
        "thumbs_up": item["thumbs_up"],
        "thumbs_down": item["thumbs_down"],
        "your_reaction": new_reaction,
    }


@router.post("/{signal_id}/comment")
async def add_comment(
    signal_id: str,
    body: CommentBody,
    user: TokenPayload = Depends(get_current_user),
):
    """Add a comment to a feed signal."""
    if signal_id not in _feed_items:
        raise HTTPException(status_code=404, detail="Signal not found")

    comment = {
        "comment_id": str(uuid.uuid4()),
        "signal_id": signal_id,
        "user_id": user.sub,
        "username": getattr(user, "username", user.sub),
        "text": body.text,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _comments[signal_id].append(comment)
    _feed_items[signal_id]["comment_count"] = len(_comments[signal_id])
    return comment


@router.get("/{signal_id}/comments")
async def get_comments(signal_id: str):
    """Return all comments for a signal (public)."""
    if signal_id not in _feed_items:
        raise HTTPException(status_code=404, detail="Signal not found")
    return {"comments": _comments.get(signal_id, [])}


@router.post("/opt-in")
async def opt_in(user: TokenPayload = Depends(get_current_user)):
    """Opt the current user into having their signals appear in the public feed."""
    _load_opted_in()
    _opted_in.add(user.sub)
    _save_opted_in()
    return {"opted_in": True, "user_id": user.sub}


@router.post("/opt-out")
async def opt_out(user: TokenPayload = Depends(get_current_user)):
    """Opt the current user out of the public feed."""
    _load_opted_in()
    _opted_in.discard(user.sub)
    _save_opted_in()
    return {"opted_in": False, "user_id": user.sub}


@router.get("/status/me")
async def my_feed_status(user: TokenPayload = Depends(get_current_user)):
    """Return whether the current user is opted into the public feed."""
    _load_opted_in()
    return {"opted_in": user.sub in _opted_in}


@router.get("/status")
async def feed_status(user: TokenPayload = Depends(get_current_user)):
    """
    Return the current user's feed opt-in state plus signal and follower counts.

    Used by the FeedSettings UI component.
    """
    _load_opted_in()
    opted_in = user.sub in _opted_in

    # Count signals this user has published to the feed
    signal_count = sum(
        1 for item in _feed_items.values() if item.get("trader_id") == user.sub and item.get("is_public")
    )

    # Follower count from profile store
    follower_count = 0
    try:
        from social.profiles import TraderProfileManager as _TPM

        mgr = _TPM()
        profile = mgr.get_profile(user.sub)
        if profile:
            follower_count = getattr(profile, "total_followers", 0)
    except Exception as exc:
        logger.warning("feed_status: failed to fetch follower count for %s: %s", user.sub, exc)

    return {
        "opted_in": opted_in,
        "trader_id": user.sub,
        "signal_count": signal_count,
        "follower_count": follower_count,
    }


# ── Leaderboard router ────────────────────────────────────────────────────────
# Mounted at /api/social so CopyTrading.tsx and Leaderboard.tsx can call
# GET /api/social/leaderboard without a prefix conflict with /api/feed.

from fastapi import Query as _Query

leaderboard_router = APIRouter(prefix="/api/social", tags=["Social Feed"])


@leaderboard_router.get("/leaderboard", summary="Trader performance leaderboard")
async def get_leaderboard(
    period: str = _Query("monthly", pattern="^(monthly|quarterly|all)$"),
    limit: int = _Query(20, ge=1, le=100),
):
    """
    Return ranked trader performance for the leaderboard.

    Data sources (in priority order):
    1. Persisted leaderboard snapshot in db_store (written by a background job)
    2. Live TraderProfile records from the profile manager (opted-in users only)

    Returns an empty list when no real data is available — the frontend
    must handle this case and show an appropriate empty state.

    Fields per entry:
      id, rank, name, return_3m, sharpe, followers, win_rate, trades
    """
    # ── 1. Persisted leaderboard snapshot ────────────────────────────────────
    try:
        stored = db_get("leaderboard") or {}
        entries = stored.get(period, [])
        if entries:
            return entries[:limit]
    except Exception as exc:
        logger.debug("Leaderboard DB read failed: %s", exc)

    # ── 2. Live profile store — opted-in traders only ─────────────────────────
    try:
        from social.profiles import TraderProfileManager as _TPM

        mgr = _TPM()
        profiles = mgr.list_profiles(public_only=True)
        if profiles:
            ranked = sorted(profiles, key=lambda p: p.sharpe_ratio, reverse=True)
            result = []
            for i, p in enumerate(ranked[:limit], 1):
                result.append(
                    {
                        "id": p.trader_id,
                        "rank": i,
                        "name": p.username,
                        "return_3m": round(p.total_pnl / max(p.total_trades, 1), 2),
                        "sharpe": round(p.sharpe_ratio, 2),
                        "followers": p.total_followers,
                        "win_rate": round(p.win_rate, 1),
                        "trades": p.total_trades,
                    }
                )
            if result:
                return result
    except Exception as exc:
        logger.debug("Profile store leaderboard failed: %s", exc)

    # No real data yet — return empty list with a status hint
    return []
