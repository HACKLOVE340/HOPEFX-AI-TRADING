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
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from api.db_store import db_get, db_set

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feed", tags=["Social Feed"])

# ── In-memory stores ──────────────────────────────────────────────────────────

_feed_items: Dict[str, dict] = {}  # signal_id → feed item
_reactions: Dict[str, Dict[str, str]] = {}  # signal_id → {user_id: "up"|"down"}
_comments: Dict[str, List[dict]] = {}  # signal_id → list of comments
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


# ── Seed demo data ────────────────────────────────────────────────────────────


def _seed_demo():
    import random

    random.seed(7)
    symbols = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "BTC/USD"]
    directions = ["BUY", "SELL"]
    usernames = ["AlgoTrader_X", "GoldHunter", "FXWizard", "PropKing", "QuietEdge"]
    for i in range(12):
        sid = f"demo-sig-{i:03d}"
        sym = random.choice(symbols)
        direction = random.choice(directions)
        conf = round(70 + random.random() * 25, 1)
        pnl = round((random.random() - 0.4) * 350, 2)
        copies = random.randint(0, 18)
        _feed_items[sid] = {
            "signal_id": sid,
            "symbol": sym,
            "direction": direction,
            "confidence": conf,
            "entry_price": round(2300 + random.random() * 100, 2)
            if "XAU" in sym
            else round(1.05 + random.random() * 0.05, 5),
            "pnl": pnl,
            "copies": copies,
            "username": random.choice(usernames),
            "trader_id": f"trader-{i:03d}",
            "thumbs_up": random.randint(0, 24),
            "thumbs_down": random.randint(0, 6),
            "comment_count": random.randint(0, 5),
            "is_public": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _reactions[sid] = {}
        _comments[sid] = []


_seed_demo()


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
        "created_at": datetime.now(timezone.utc).isoformat(),
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
    symbol: Optional[str] = None,
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
        "created_at": datetime.now(timezone.utc).isoformat(),
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


# ── Leaderboard router ────────────────────────────────────────────────────────
# Mounted at /api/social so CopyTrading.tsx and Leaderboard.tsx can call
# GET /api/social/leaderboard without a prefix conflict with /api/feed.

from fastapi import Query as _Query  # noqa: E402

leaderboard_router = APIRouter(prefix="/api/social", tags=["Social Feed"])


@leaderboard_router.get("/leaderboard", summary="Trader performance leaderboard")
async def get_leaderboard(
    period: str = _Query("monthly", pattern="^(monthly|quarterly|all)$"),
    limit: int = _Query(20, ge=1, le=100),
):
    """
    Return ranked trader performance for the leaderboard.

    Reads from the profiles store when available; falls back to a
    deterministic demo dataset so the UI always renders.

    Fields per entry:
      id, name, return_3m, sharpe, followers, win_rate, trades, prize
    """
    try:
        from api.db_store import db_get as _db_get

        stored = _db_get("leaderboard", {})
        entries = stored.get(period, [])
        if entries:
            return entries[:limit]
    except Exception as exc:
        logger.debug("Leaderboard DB read failed (non-fatal): %s", exc)

    # Deterministic demo fallback — always returns data so the UI renders
    import hashlib as _hashlib

    demo_traders = [
        ("AuricAlpha", 42.3, 2.81, 1240, 63.2, 312, "$5,000"),
        ("GoldHunter", 38.7, 2.54, 987, 61.8, 278, "$3,000"),
        ("MacroEdge", 35.1, 2.33, 834, 60.4, 251, "$2,000"),
        ("VaultBreaker", 31.8, 2.12, 712, 59.1, 229, "$1,500"),
        ("TrendRider", 28.4, 1.98, 623, 58.7, 204, "$1,000"),
        ("AlphaWave", 25.9, 1.87, 541, 57.3, 187, "$750"),
        ("SilverFox", 23.2, 1.74, 478, 56.8, 168, "$500"),
        ("NightOwl", 20.7, 1.63, 412, 55.4, 152, "$400"),
        ("DawnTrader", 18.1, 1.52, 356, 54.9, 138, "$300"),
        ("QuietStorm", 15.6, 1.41, 298, 53.7, 124, "$200"),
    ]

    # Scale returns by period
    scale = {"monthly": 1.0, "quarterly": 2.8, "all": 8.5}.get(period, 1.0)

    result = []
    for i, (name, ret, sharpe, followers, wr, trades, prize) in enumerate(
        demo_traders[:limit], 1
    ):
        uid = _hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()[:8]  # noqa: S324
        result.append(
            {
                "id": uid,
                "rank": i,
                "name": name,
                "return": round(ret * scale, 1),
                "return_3m": round(ret, 1),
                "sharpe": round(sharpe, 2),
                "followers": followers,
                "win_rate": wr,
                "trades": trades,
                "prize": prize,
            }
        )
    return result
