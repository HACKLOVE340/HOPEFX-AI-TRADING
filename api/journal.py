# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/journal.py
==============
Trade Journal endpoints with DB persistence.

Routes
------
GET    /api/journal/trades              — list journal entries (paginated)
POST   /api/journal/trades              — create/update journal entry for a trade
GET    /api/journal/trades/{trade_id}   — get single entry
PATCH  /api/journal/trades/{trade_id}   — update notes/tags/emotion
GET    /api/journal/stats               — win rate by tag, emotion breakdown
GET    /api/journal/mistakes            — trades where rules were deviated from

Persistence: configurations table via api.db_store.
Falls back to in-memory dict when DB is unavailable.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from api.db_store import db_get, db_keys_prefix, db_set

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/journal", tags=["Trade Journal"])

# In-memory fallback
_entries: dict[str, dict] = {}

_JOURNAL_PREFIX = "journal_entry"

EMOTION_TAGS = [
    "patient",
    "fomo",
    "revenge",
    "disciplined",
    "hesitant",
    "overconfident",
    "fearful",
]
TRADE_TAGS = [
    "trend",
    "breakout",
    "reversal",
    "news",
    "scalp",
    "swing",
    "mistake",
    "best-trade",
]


# ── Models ────────────────────────────────────────────────────────────────────


class JournalEntry(BaseModel):
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float | None = None
    size: float
    pnl: float | None = None
    opened_at: str
    closed_at: str | None = None
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    emotion: str | None = None
    followed_rules: bool = True
    rule_deviation: str | None = None
    screenshot_url: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )


class JournalUpdate(BaseModel):
    notes: str | None = None
    tags: list[str] | None = None
    emotion: str | None = None
    followed_rules: bool | None = None
    rule_deviation: str | None = None
    screenshot_url: str | None = None
    exit_price: float | None = None
    pnl: float | None = None
    closed_at: str | None = None


class TagStats(BaseModel):
    tag: str
    count: int
    win_rate: float
    avg_pnl: float


class JournalStats(BaseModel):
    total_trades: int
    win_rate: float
    avg_pnl: float
    best_trade_pnl: float
    worst_trade_pnl: float
    by_tag: list[TagStats]
    by_emotion: list[TagStats]
    rule_deviation_count: int


# ── Persistence helpers ───────────────────────────────────────────────────────


def _entry_key(trade_id: str) -> str:
    return f"{_JOURNAL_PREFIX}:{trade_id}"


def _save_entry(entry: dict) -> None:
    tid = entry["trade_id"]
    _entries[tid] = entry
    db_set(_entry_key(tid), entry, changed_by="journal")


def _load_all_entries() -> dict[str, dict]:
    """Load all journal entries from DB into the in-memory cache."""
    if _entries:
        return _entries
    keys = db_keys_prefix(f"{_JOURNAL_PREFIX}:")
    for key in keys:
        val = db_get(key)
        if isinstance(val, dict) and "trade_id" in val:
            _entries[val["trade_id"]] = val
    return _entries


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/trades", response_model=list[JournalEntry])
async def list_trades(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tag: str | None = None,
    emotion: str | None = None,
    symbol: str | None = None,
    user: TokenPayload = Depends(get_current_user),
) -> list[JournalEntry]:
    entries = list(_load_all_entries().values())
    if tag:
        entries = [e for e in entries if tag in e.get("tags", [])]
    if emotion:
        entries = [e for e in entries if e.get("emotion") == emotion]
    if symbol:
        entries = [e for e in entries if e.get("symbol") == symbol.upper()]
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return [JournalEntry(**e) for e in entries[offset : offset + limit]]


@router.post(
    "/trades",
    response_model=JournalEntry,
    status_code=status.HTTP_201_CREATED,
)
async def create_entry(
    entry: JournalEntry,
    user: TokenPayload = Depends(get_current_user),
) -> JournalEntry:
    _load_all_entries()
    if not entry.trade_id:
        entry.trade_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    entry.created_at = now
    entry.updated_at = now
    _save_entry(entry.model_dump())
    return entry


@router.get("/trades/{trade_id}", response_model=JournalEntry)
async def get_entry(
    trade_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> JournalEntry:
    entries = _load_all_entries()
    if trade_id not in entries:
        raise HTTPException(status_code=404, detail="Trade not found")
    return JournalEntry(**entries[trade_id])


@router.patch("/trades/{trade_id}", response_model=JournalEntry)
async def update_entry(
    trade_id: str,
    update: JournalUpdate,
    user: TokenPayload = Depends(get_current_user),
) -> JournalEntry:
    entries = _load_all_entries()
    if trade_id not in entries:
        raise HTTPException(status_code=404, detail="Trade not found")
    entry = entries[trade_id]
    for field, value in update.model_dump(exclude_none=True).items():
        entry[field] = value
    entry["updated_at"] = datetime.now(UTC).isoformat()
    _save_entry(entry)
    return JournalEntry(**entry)


@router.get("/stats", response_model=JournalStats)
async def get_stats(user: TokenPayload = Depends(get_current_user)) -> JournalStats:
    entries = list(_load_all_entries().values())
    closed = [e for e in entries if e.get("pnl") is not None]
    if not closed:
        return JournalStats(
            total_trades=0,
            win_rate=0,
            avg_pnl=0,
            best_trade_pnl=0,
            worst_trade_pnl=0,
            by_tag=[],
            by_emotion=[],
            rule_deviation_count=0,
        )

    pnls = [e["pnl"] for e in closed]
    wins = [p for p in pnls if p > 0]

    all_tags = {t for e in closed for t in e.get("tags", [])}
    tag_stats = []
    for tag in all_tags:
        tagged = [e for e in closed if tag in e.get("tags", [])]
        tag_pnls = [e["pnl"] for e in tagged]
        tag_wins = [p for p in tag_pnls if p > 0]
        tag_stats.append(
            TagStats(
                tag=tag,
                count=len(tagged),
                win_rate=round(len(tag_wins) / len(tagged) * 100, 1) if tagged else 0,
                avg_pnl=round(sum(tag_pnls) / len(tag_pnls), 2) if tag_pnls else 0,
            ),
        )

    all_emotions = {e.get("emotion") for e in closed if e.get("emotion")}
    emotion_stats = []
    for em in all_emotions:
        em_entries = [e for e in closed if e.get("emotion") == em]
        em_pnls = [e["pnl"] for e in em_entries]
        em_wins = [p for p in em_pnls if p > 0]
        emotion_stats.append(
            TagStats(
                tag=em,
                count=len(em_entries),
                win_rate=round(len(em_wins) / len(em_entries) * 100, 1) if em_entries else 0,
                avg_pnl=round(sum(em_pnls) / len(em_pnls), 2) if em_pnls else 0,
            ),
        )

    return JournalStats(
        total_trades=len(closed),
        win_rate=round(len(wins) / len(closed) * 100, 1),
        avg_pnl=round(sum(pnls) / len(pnls), 2),
        best_trade_pnl=max(pnls),
        worst_trade_pnl=min(pnls),
        by_tag=sorted(tag_stats, key=lambda x: x.count, reverse=True),
        by_emotion=sorted(emotion_stats, key=lambda x: x.count, reverse=True),
        rule_deviation_count=sum(1 for e in entries if not e.get("followed_rules", True)),
    )


@router.get("/mistakes", response_model=list[JournalEntry])
async def get_mistakes(
    user: TokenPayload = Depends(get_current_user),
) -> list[JournalEntry]:
    """Trades where the user deviated from their rules."""
    entries = _load_all_entries()
    mistakes = [e for e in entries.values() if not e.get("followed_rules", True)]
    return [JournalEntry(**e) for e in mistakes]
