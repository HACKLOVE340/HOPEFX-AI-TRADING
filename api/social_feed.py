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
from monetization.subscription import require_plan
from api.db_store import db_get, db_set

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feed", tags=["Social Feed"])

# ── Redis-backed stores ───────────────────────────────────────────────────────
# Feed items, reactions, and comments are stored in Redis so they survive
# restarts and are shared across replicas.  All helpers fall back to in-process
# dicts when Redis is unavailable.
#
# Key layout:
#   social:feed:{signal_id}          → JSON feed item dict
#   social:reactions:{signal_id}     → Redis hash  {user_id: "up"|"down"}
#   social:comments:{signal_id}      → Redis list  of JSON comment strings
#   social:feed:index                → Redis sorted set  signal_id → created_at ts

import json as _json

_FEED_TTL = 60 * 60 * 24 * 90  # 90 days

# In-process fallback stores
_feed_items: dict[str, dict] = {}
_reactions: dict[str, dict[str, str]] = {}
_comments: dict[str, list[dict]] = {}
_opted_in: set = set()  # user_ids who opted into public feed


def _get_sync_redis():
    try:
        from cache.redis_pool import get_sync_client

        return get_sync_client()
    except Exception:
        return None


def _feed_set(sid: str, item: dict) -> None:
    r = _get_sync_redis()
    if r:
        try:
            import time as _time

            r.setex(f"social:feed:{sid}", _FEED_TTL, _json.dumps(item))
            r.zadd("social:feed:index", {sid: _time.time()})
            return
        except Exception as _e:
            logger.debug("Redis feed_set failed: %s", _e)
    _feed_items[sid] = item


def _feed_get(sid: str) -> dict | None:
    r = _get_sync_redis()
    if r:
        try:
            raw = r.get(f"social:feed:{sid}")
            return _json.loads(raw) if raw else None
        except Exception as _e:
            logger.debug("Redis feed_get failed: %s", _e)
    return _feed_items.get(sid)


def _feed_all_public() -> list[dict]:
    r = _get_sync_redis()
    if r:
        try:
            sids = r.zrevrange("social:feed:index", 0, 499)
            items = []
            for sid in sids:
                raw = r.get(f"social:feed:{sid}")
                if raw:
                    item = _json.loads(raw)
                    if item.get("is_public"):
                        items.append(item)
            return items
        except Exception as _e:
            logger.debug("Redis feed_all_public failed: %s", _e)
    return [v for v in _feed_items.values() if v.get("is_public")]


def _reaction_set(sid: str, user_id: str, reaction: str) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.hset(f"social:reactions:{sid}", user_id, reaction)
            r.expire(f"social:reactions:{sid}", _FEED_TTL)
            return
        except Exception as _e:
            logger.debug("Redis reaction_set failed: %s", _e)
    _reactions.setdefault(sid, {})[user_id] = reaction


def _reaction_del(sid: str, user_id: str) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.hdel(f"social:reactions:{sid}", user_id)
            return
        except Exception as _e:
            logger.debug("Redis reaction_del failed: %s", _e)
    _reactions.get(sid, {}).pop(user_id, None)


def _reaction_get(sid: str, user_id: str) -> str | None:
    r = _get_sync_redis()
    if r:
        try:
            val = r.hget(f"social:reactions:{sid}", user_id)
            return val.decode() if val else None
        except Exception as _e:
            logger.debug("Redis reaction_get failed: %s", _e)
    return _reactions.get(sid, {}).get(user_id)


def _comment_append(sid: str, comment: dict) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.rpush(f"social:comments:{sid}", _json.dumps(comment))
            r.expire(f"social:comments:{sid}", _FEED_TTL)
            return
        except Exception as _e:
            logger.debug("Redis comment_append failed: %s", _e)
    _comments.setdefault(sid, []).append(comment)


def _comments_get(sid: str) -> list[dict]:
    r = _get_sync_redis()
    if r:
        try:
            raws = r.lrange(f"social:comments:{sid}", 0, -1)
            return [_json.loads(x) for x in raws]
        except Exception as _e:
            logger.debug("Redis comments_get failed: %s", _e)
    return _comments.get(sid, [])


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
    _feed_set(sid, item)
    # Initialise in-memory reaction and comment stores for this signal so
    # callers can safely access _reactions[sid] and _comments[sid] immediately.
    _reactions.setdefault(sid, {})
    _comments.setdefault(sid, [])
    return item


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
async def get_feed(
    page: int = 1,
    limit: int = 20,
    symbol: str | None = None,
):
    """Return paginated community signal feed (public — no auth required)."""
    items = _feed_all_public()
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
    item = _feed_get(signal_id)
    if not item:
        raise HTTPException(status_code=404, detail="Signal not found")

    prev = _reaction_get(signal_id, user.sub)

    # Remove previous reaction counts
    if prev == "up":
        item["thumbs_up"] = max(0, item["thumbs_up"] - 1)
    elif prev == "down":
        item["thumbs_down"] = max(0, item["thumbs_down"] - 1)

    # Toggle: clicking same reaction removes it
    if prev == body.reaction:
        _reaction_del(signal_id, user.sub)
        new_reaction = None
    else:
        _reaction_set(signal_id, user.sub, body.reaction)
        new_reaction = body.reaction
        if body.reaction == "up":
            item["thumbs_up"] += 1
        else:
            item["thumbs_down"] += 1

    _feed_set(signal_id, item)
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
    item = _feed_get(signal_id)
    if not item:
        raise HTTPException(status_code=404, detail="Signal not found")

    comment = {
        "comment_id": str(uuid.uuid4()),
        "signal_id": signal_id,
        "user_id": user.sub,
        "username": getattr(user, "username", user.sub),
        "text": body.text,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _comment_append(signal_id, comment)
    item["comment_count"] = len(_comments_get(signal_id))
    _feed_set(signal_id, item)
    return comment


@router.get("/{signal_id}/comments")
async def get_comments(signal_id: str):
    """Return all comments for a signal (public)."""
    if not _feed_get(signal_id):
        raise HTTPException(status_code=404, detail="Signal not found")
    return {"comments": _comments_get(signal_id)}


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
    signal_count = sum(1 for item in _feed_all_public() if item.get("trader_id") == user.sub)

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
# GET /api/leaderboard — separate router to avoid prefix conflict with /api/feed.

from fastapi import Query as _Query

leaderboard_router = APIRouter(prefix="/api", tags=["Social Feed"])


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
                # ── Write-through cache: persist for next request ─────────────────
                try:
                    stored_write = db_get("leaderboard") or {}
                    stored_write[period] = result
                    db_set("leaderboard", stored_write, changed_by="leaderboard_builder")
                except Exception as exc:
                    logger.debug("Leaderboard cache write failed: %s", exc)
                return result
    except Exception as exc:
        logger.debug("Profile store leaderboard failed: %s", exc)

    # No real data yet — return empty list with a status hint
    return []


@leaderboard_router.get("/leaderboard/{trader_id}", summary="Trader leaderboard profile")
async def get_leaderboard_profile(trader_id: str):
    """Return a single trader's leaderboard profile."""
    try:
        from api.profiles import _manager
        profile = _manager.get_profile(trader_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Trader not found")
        return {
            "id": trader_id,
            "name": getattr(profile, "username", trader_id),
            "return_3m": round(getattr(profile, "total_pnl", 0.0) / max(getattr(profile, "total_trades", 1), 1), 2),
            "sharpe": round(getattr(profile, "sharpe_ratio", 0.0), 2),
            "followers": getattr(profile, "total_followers", 0),
            "win_rate": round(getattr(profile, "win_rate", 0.0), 1),
            "trades": getattr(profile, "total_trades", 0),
            "bio": getattr(profile, "bio", ""),
            "avatar_url": getattr(profile, "avatar_url", None),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug("leaderboard profile lookup failed: %s", exc)
        raise HTTPException(status_code=404, detail="Trader not found")


@leaderboard_router.get("/leaderboard/{trader_id}/stats", summary="Trader leaderboard stats")
async def get_leaderboard_stats(trader_id: str):
    """Return detailed performance stats for a leaderboard trader."""
    try:
        from api.profiles import _manager
        profile = _manager.get_profile(trader_id)
        if not profile:
            return {"trader_id": trader_id, "total_trades": 0, "win_rate": 0.0, "sharpe_ratio": 0.0}
        return {
            "trader_id": trader_id,
            "total_trades": getattr(profile, "total_trades", 0),
            "win_rate": getattr(profile, "win_rate", 0.0),
            "sharpe_ratio": getattr(profile, "sharpe_ratio", 0.0),
            "max_drawdown_pct": getattr(profile, "max_drawdown_pct", 0.0),
            "total_return_pct": getattr(profile, "total_return_pct", 0.0),
            "avg_trade_duration_h": getattr(profile, "avg_trade_duration_h", 0.0),
            "followers": getattr(profile, "total_followers", 0),
        }
    except Exception as exc:
        logger.debug("leaderboard stats lookup failed: %s", exc)
        return {"trader_id": trader_id, "total_trades": 0, "win_rate": 0.0, "sharpe_ratio": 0.0}


# ── Copy-trading router ───────────────────────────────────────────────────────
# Mounted at /api/social so the frontend can call:
#   POST   /api/social/copy/{trader_id}  — start copying a trader
#   GET    /api/social/copy/active       — list active copy relationships
#   DELETE /api/social/copy/{copy_id}    — stop copying

_copy_router = APIRouter(prefix="/api/social", tags=["Copy Trading"])

# In-memory store: user_id → list of copy relationship dicts
# Each entry: { id, trader_id, trader_name, allocation_amount, signal_id, started_at }
_copy_relationships: dict[str, list[dict]] = {}


def _user_copies(user_id: str) -> list[dict]:
    """Return the mutable copy list for *user_id*, loading from DB on first access."""
    if user_id not in _copy_relationships:
        stored = db_get(f"copy_trading:{user_id}") or []
        _copy_relationships[user_id] = stored if isinstance(stored, list) else []
    return _copy_relationships[user_id]


def _save_copies(user_id: str) -> None:
    db_set(f"copy_trading:{user_id}", _copy_relationships[user_id], changed_by="copy_trading")


class StartCopyBody(BaseModel):
    allocation_amount: float = Field(..., gt=0, description="Capital to allocate in account currency")
    signal_id: str | None = Field(None, description="Optional signal that triggered the copy")


@_copy_router.post(
    "/copy/{trader_id}",
    status_code=201,
    summary="Start copying a trader",
)
async def start_copy_trading(
    trader_id: str,
    body: StartCopyBody,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Begin copying all trades from *trader_id* with the given allocation.

    Returns the new copy relationship record. Idempotent per trader — if the
    user is already copying this trader the existing record is returned (200).
    """
    copies = _user_copies(user.sub)

    # Idempotency: return existing record if already copying this trader
    existing = next((c for c in copies if c["trader_id"] == trader_id), None)
    if existing:
        return existing

    # Resolve trader name from leaderboard / profile store
    trader_name = trader_id
    try:
        from social.profiles import TraderProfileManager as _TPM

        profile = _TPM().get_profile(trader_id)
        if profile:
            trader_name = profile.username
    except Exception as exc:
        logger.debug("copy_trading: could not resolve trader name for %s: %s", trader_id, exc)

    record = {
        "id": str(uuid.uuid4()),
        "trader_id": trader_id,
        "trader_name": trader_name,
        "allocation_amount": body.allocation_amount,
        "signal_id": body.signal_id,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "active",
    }
    copies.append(record)
    _save_copies(user.sub)

    # Increment copy count on the feed item if a signal_id was provided
    if body.signal_id:
        _item = _feed_get(body.signal_id)
        if _item:
            _item["copies"] = _item.get("copies", 0) + 1
            _feed_set(body.signal_id, _item)

    logger.info(
        "copy_trading: user %s started copying trader %s (alloc=%.2f)", user.sub, trader_id, body.allocation_amount
    )
    return record


@_copy_router.get(
    "/copy/active",
    summary="List active copy relationships",
)
async def list_active_copies(user: TokenPayload = Depends(require_plan("professional"))):
    """Return all active copy-trading relationships for the authenticated user."""
    copies = _user_copies(user.sub)
    return [c for c in copies if c.get("status") == "active"]


@_copy_router.delete(
    "/copy/{copy_id}",
    summary="Stop copying a trader",
)
async def stop_copy_trading(
    copy_id: str,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Stop an active copy-trading relationship by its *copy_id*.

    The record is marked inactive rather than deleted so the history is
    preserved. Returns 404 if the copy_id does not belong to the user.
    """
    copies = _user_copies(user.sub)
    record = next((c for c in copies if c["id"] == copy_id), None)
    if not record:
        raise HTTPException(status_code=404, detail="Copy relationship not found")

    record["status"] = "stopped"
    record["stopped_at"] = datetime.now(UTC).isoformat()
    _save_copies(user.sub)

    logger.info("copy_trading: user %s stopped copy %s (trader=%s)", user.sub, copy_id, record["trader_id"])
    return {"status": "stopped", "copy_id": copy_id}


# ── Leaderboard background writer ─────────────────────────────────────────────
# Builds a leaderboard snapshot from live TraderProfile data and persists it
# to db_store so GET /leaderboard can serve it without hitting the profile
# store on every request.  Called by the scheduler every 15 minutes.

_LEADERBOARD_PERIODS = ("monthly", "quarterly", "all")
_LEADERBOARD_LIMIT = 100


def _build_leaderboard_snapshot() -> dict[str, list[dict]]:
    """
    Build a leaderboard snapshot keyed by period.

    Returns a dict mapping period → ranked list of trader dicts.
    Falls back to an empty dict if the profile store is unavailable.
    """
    snapshot: dict[str, list[dict]] = {}
    try:
        from social.profiles import TraderProfileManager as _TPM

        mgr = _TPM()
        profiles = mgr.list_profiles(public_only=True)
        if not profiles:
            return snapshot

        def _rank(profiles_list: list, limit: int) -> list[dict]:
            ranked = sorted(profiles_list, key=lambda p: p.sharpe_ratio, reverse=True)
            return [
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
                for i, p in enumerate(ranked[:limit], 1)
            ]

        for period in _LEADERBOARD_PERIODS:
            snapshot[period] = _rank(profiles, _LEADERBOARD_LIMIT)

    except Exception as exc:
        logger.debug("leaderboard snapshot build failed: %s", exc)

    return snapshot


def refresh_leaderboard_cache() -> None:
    """
    Rebuild and persist the leaderboard snapshot to db_store.

    Called by the scheduler (every 15 minutes) and on demand.
    """
    snapshot = _build_leaderboard_snapshot()
    if snapshot:
        db_set("leaderboard", snapshot, changed_by="leaderboard_refresh")
        logger.info(
            "leaderboard cache refreshed: %s",
            {p: len(v) for p, v in snapshot.items()},
        )
    else:
        logger.debug("leaderboard cache refresh skipped — no profile data")


# =============================================================================
# FRONTEND COMPATIBILITY ALIAS — /api/leaderboard
# =============================================================================
# The frontend (hooks/useApi.ts leaderboardApi.list) calls GET /api/leaderboard
# but the canonical backend route is GET /api/social/leaderboard.
# This alias router bridges the gap.

_lb_compat_router = APIRouter(prefix="/api", tags=["Social Feed"])


@_lb_compat_router.get("/leaderboard", include_in_schema=False)
async def _compat_leaderboard(
    period: str = _Query("monthly", pattern="^(monthly|quarterly|all)$"),
    limit: int = _Query(20, ge=1, le=100),
):
    """Alias: GET /api/leaderboard → get_leaderboard (/api/social/leaderboard)."""
    return await get_leaderboard(period=period, limit=limit)


# =============================================================================
# COPY-TRADING  —  POST /api/social/copy/:trader_id
# Called by CopyTrading.tsx and SocialFeed.tsx
# =============================================================================


class CopyTradeRequest(BaseModel):
    allocation_amount: float = Field(..., gt=0, description="USD amount to allocate to this trader")
    signal_id: str = Field("", description="Optional: copy a specific signal ID")
    risk_per_trade_pct: float = Field(1.0, ge=0.1, le=10.0, description="Risk % per copied trade")
    max_drawdown_pct: float = Field(10.0, ge=1.0, le=50.0, description="Stop copying if DD exceeds this %")
    stop_loss_override: float | None = Field(None, description="Override the signal's stop-loss distance")


@leaderboard_router.post(
    "/copy/{trader_id}",
    response_model=None,
    status_code=201,
    summary="Subscribe to copy a trader's signals",
)
async def copy_trader(
    trader_id: str,
    req: CopyTradeRequest,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Start copy-trading a specific trader.

    - Validates the target trader exists and has opted in to copy-trading.
    - Records the copy relationship in the social profile store.
    - Any future signals from `trader_id` will be mirrored to the subscriber
      subject to their `allocation_amount` and risk settings.

    Returns the copy subscription ID so the frontend can cancel later.
    """
    if trader_id == user.sub:
        raise HTTPException(status_code=400, detail="You cannot copy yourself.")

    # Validate that the target trader has opted in
    try:
        from social.profiles import TraderProfileManager as _TPM

        mgr = _TPM()
        profile = mgr.get_profile(trader_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Trader '{trader_id}' not found.")
        if not getattr(profile, "copy_trading_enabled", False):
            raise HTTPException(
                status_code=403,
                detail=f"Trader '{trader_id}' has not enabled copy-trading.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Profile store unavailable — proceed optimistically (paper mode)
        logger.warning("Copy trade profile lookup failed for %s: %s", trader_id, exc)

    subscription_id = f"copy-{user.sub[:8]}-{trader_id[:8]}-{uuid.uuid4().hex[:8]}"

    # Persist the copy subscription
    try:
        existing = db_get("copy_subscriptions") or {}
        user_subs = existing.get(user.sub, [])
        # Remove any existing subscription to this trader
        user_subs = [s for s in user_subs if s.get("trader_id") != trader_id]
        user_subs.append(
            {
                "subscription_id": subscription_id,
                "trader_id": trader_id,
                "allocation_amount": req.allocation_amount,
                "signal_id": req.signal_id or None,
                "risk_per_trade_pct": req.risk_per_trade_pct,
                "max_drawdown_pct": req.max_drawdown_pct,
                "stop_loss_override": req.stop_loss_override,
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        existing[user.sub] = user_subs
        db_set("copy_subscriptions", existing, changed_by="copy_trader")
    except Exception as exc:
        logger.warning("Copy subscription persist failed: %s", exc)

    logger.info(
        "Copy trade subscribed: user=%s → trader=%s alloc=%.2f sub_id=%s",
        user.sub,
        trader_id,
        req.allocation_amount,
        subscription_id,
    )
    return {
        "status": "subscribed",
        "subscription_id": subscription_id,
        "trader_id": trader_id,
        "allocation_amount": req.allocation_amount,
        "message": f"Now copying trader {trader_id}. Signals will be mirrored automatically.",
    }



# ── /api/copy/* alias router ──────────────────────────────────────────────────
# Frontend calls /api/copy/* (without /social prefix).
# These aliases forward to the same logic as _copy_router.

_copy_alias_router = APIRouter(prefix="/api/copy", tags=["Copy Trading"])


@_copy_alias_router.get("/active", summary="List active copy relationships")
async def _copy_active_alias(user: TokenPayload = Depends(require_plan("professional"))):
    copies = _user_copies(user.sub)
    return [c for c in copies if c.get("status") == "active"]


@_copy_alias_router.post("/{trader_id}", summary="Start copying a trader")
async def _copy_start_alias(
    trader_id: str,
    req: CopyTradeRequest,
    user: TokenPayload = Depends(require_plan("professional")),
):
    return await copy_trader(trader_id, req, user)


@_copy_alias_router.delete("/{trader_id}", summary="Stop copying a trader")
async def _copy_stop_alias(
    trader_id: str,
    user: TokenPayload = Depends(require_plan("professional")),
):
    copies = _user_copies(user.sub)
    record = next(
        (c for c in copies if c.get("trader_id") == trader_id and c.get("status") == "active"),
        None,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Copy relationship not found")
    record["status"] = "stopped"
    record["stopped_at"] = datetime.now(UTC).isoformat()
    _save_copies(user.sub)
    return {"status": "stopped", "trader_id": trader_id}


@_copy_alias_router.patch("/{trader_id}/allocation", summary="Update copy allocation")
async def _copy_update_allocation(
    trader_id: str,
    body: dict,
    user: TokenPayload = Depends(require_plan("professional")),
):
    copies = _user_copies(user.sub)
    record = next(
        (c for c in copies if c.get("trader_id") == trader_id and c.get("status") == "active"),
        None,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Copy relationship not found")
    record["allocation_amount"] = body.get("allocation_amount", record.get("allocation_amount", 0))
    _save_copies(user.sub)
    return {"success": True, "trader_id": trader_id, "allocation_amount": record["allocation_amount"]}


@_copy_alias_router.get("/history", summary="Copy trading history")
async def _copy_history(
    limit: int = 50,
    user: TokenPayload = Depends(get_current_user),
):
    copies = _user_copies(user.sub)
    stopped = sorted(
        [c for c in copies if c.get("status") == "stopped"],
        key=lambda x: x.get("stopped_at", ""),
        reverse=True,
    )
    return {"history": stopped[:limit], "total": len(stopped)}


@_copy_alias_router.get("/{trader_id}/performance", summary="Copy trader performance")
async def _copy_performance(
    trader_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    try:
        from api.profiles import _manager
        profile = _manager.get_profile(trader_id)
        if not profile:
            return {"trader_id": trader_id, "total_return_pct": 0.0, "win_rate": 0.0, "followers": 0}
        return {
            "trader_id": trader_id,
            "total_return_pct": getattr(profile, "total_return_pct", 0.0),
            "win_rate": getattr(profile, "win_rate", 0.0),
            "sharpe_ratio": getattr(profile, "sharpe_ratio", 0.0),
            "max_drawdown_pct": getattr(profile, "max_drawdown_pct", 0.0),
            "followers": getattr(profile, "total_followers", 0),
            "total_trades": getattr(profile, "total_trades", 0),
        }
    except Exception as exc:
        logger.debug("copy performance lookup failed: %s", exc)
        return {"trader_id": trader_id, "total_return_pct": 0.0, "win_rate": 0.0, "followers": 0}


# ── /ws/social-feed  WebSocket endpoint ──────────────────────────────────────
# The frontend SocialFeed.tsx opens:
#   new WebSocket(`${wsBase}/ws/social-feed?token=${wsToken}`)
# and listens for {"type": "new_signal", "signal": FeedItem} frames.
# We subscribe to the ws_live signal broadcaster so every new signal emitted by
# the trading engine gets forwarded here in real time.

from fastapi import WebSocket, WebSocketDisconnect

_social_feed_ws_router = APIRouter(tags=["Social Feed WebSocket"])

# Lightweight in-process pub/sub: set of active ws connections for /ws/social-feed
_sf_connections: set[WebSocket] = set()


async def _social_feed_broadcast(signal_item: dict) -> None:
    """Push a new signal to all connected social-feed WebSocket clients."""
    dead: set[WebSocket] = set()
    frame = _json.dumps({"type": "new_signal", "signal": signal_item})
    for ws in list(_sf_connections):
        try:
            await ws.send_text(frame)
        except Exception:
            dead.add(ws)
    _sf_connections.difference_update(dead)


@_social_feed_ws_router.websocket("/ws/social-feed")
async def ws_social_feed(websocket: WebSocket) -> None:
    """
    WebSocket endpoint — streams live signal feed to SocialFeed.tsx.

    Auth: token query-param (JWT).  Closes 4001 on invalid/missing token.
    Messages sent:
      {"type": "new_signal",  "signal": FeedItem}
      {"type": "heartbeat"}           — every 30 s
    Messages accepted from client:
      {"type": "ping"}                — resets heartbeat timer
    """
    import asyncio as _asyncio
    from api.auth import decode_token

    token = websocket.query_params.get("token", "")
    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    _sf_connections.add(websocket)
    try:
        while True:
            # Wait up to 30 s for a client message; send heartbeat on timeout
            try:
                await _asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # ignore content — just a keep-alive ping
            except TimeoutError:
                try:
                    await websocket.send_text(_json.dumps({"type": "heartbeat"}))
                except Exception:
                    break
            except WebSocketDisconnect:
                break
            except Exception:
                break
    finally:
        _sf_connections.discard(websocket)
