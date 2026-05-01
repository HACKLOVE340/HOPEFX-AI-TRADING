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
from datetime import datetime, timezone

UTC = timezone.utc

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
    """Load journal entries, merging db_store entries with DB Trade rows.

    Explicit journal entries (created via POST /api/journal/trades) take
    precedence over auto-synthesised entries from the Trade table so user
    notes/tags/emotions are never overwritten.
    """
    # Load explicit journal entries from db_store first
    if not _entries:
        keys = db_keys_prefix(f"{_JOURNAL_PREFIX}:")
        for key in keys:
            val = db_get(key)
            if isinstance(val, dict) and "trade_id" in val:
                _entries[val["trade_id"]] = val

    # Merge closed Trade rows from the DB as synthesised journal entries.
    # Trades that already have an explicit journal entry are skipped.
    try:
        from database.connection import SessionLocal as _SL
        from database.models import Trade, TradeStatus

        db = _SL()
        try:
            rows = (
                db.query(Trade)
                .filter(Trade.status == TradeStatus.CLOSED)
                .order_by(Trade.entry_time.desc())
                .limit(500)
                .all()
            )
            for t in rows:
                tid = getattr(t, "trade_id", None) or str(t.id)
                if tid in _entries:
                    continue  # explicit entry takes precedence
                qty = (
                    getattr(t, "entry_quantity", None)
                    or getattr(t, "size", None)
                    or 0.0
                )
                raw_side = getattr(t, "side", "buy")
                side_str = raw_side.value if hasattr(raw_side, "value") else str(raw_side or "buy")
                entry_time = t.entry_time
                exit_time = t.exit_time
                # Parse emotion/tags from notes field (seed script stores them there)
                notes_raw = getattr(t, "notes", "") or ""
                emotion: str | None = None
                tags: list[str] = []
                for part in notes_raw.split():
                    if part.startswith("emotion:"):
                        emotion = part.split(":", 1)[1]
                    elif part not in ("demo_seed",):
                        tags.append(part)
                _entries[tid] = {
                    "trade_id": tid,
                    "symbol": t.symbol or "UNKNOWN",
                    "side": side_str,
                    "entry_price": float(t.entry_price or 0.0),
                    "exit_price": float(t.exit_price) if t.exit_price is not None else None,
                    "size": float(qty or 0.0),
                    "pnl": float(t.realized_pnl or 0.0),
                    "opened_at": entry_time.isoformat() if entry_time else "",
                    "closed_at": exit_time.isoformat() if exit_time else None,
                    "notes": notes_raw,
                    "tags": tags,
                    "emotion": emotion,
                    "followed_rules": True,
                    "rule_deviation": None,
                    "screenshot_url": None,
                    "created_at": entry_time.isoformat() if entry_time else datetime.now(UTC).isoformat(),
                    "updated_at": exit_time.isoformat() if exit_time else datetime.now(UTC).isoformat(),
                }
        finally:
            db.close()
    except Exception as exc:
        logger.debug("journal _load_all_entries DB merge failed: %s", exc)

    return _entries


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[JournalEntry], summary="List journal entries (root alias)")
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


# ── Extended analytics endpoints ──────────────────────────────────────────────


@router.get("/tags", summary="List all tags used across journal entries")
async def get_tags(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return every unique tag used in journal entries with usage counts."""
    entries = _load_all_entries()
    counts: dict[str, int] = {}
    for entry in entries.values():
        for tag in entry.get("tags") or []:
            counts[tag] = counts.get(tag, 0) + 1
    tags = [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda x: -x[1])]
    return {"tags": tags, "total": len(tags)}


@router.get("/emotion-stats", summary="Emotion breakdown across journal entries")
async def get_emotion_stats(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return win rate and average PnL grouped by emotion tag."""
    entries = list(_load_all_entries().values())
    closed = [e for e in entries if e.get("pnl") is not None]

    emotion_map: dict[str, list[float]] = {}
    for entry in closed:
        em = entry.get("emotion")
        if em:
            emotion_map.setdefault(em, []).append(float(entry["pnl"]))

    stats = []
    for emotion, pnls in emotion_map.items():
        wins = [p for p in pnls if p > 0]
        stats.append(
            {
                "emotion": emotion,
                "count": len(pnls),
                "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
                "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
                "total_pnl": round(sum(pnls), 2),
            }
        )

    stats.sort(key=lambda x: x["count"], reverse=True)
    return {"emotion_stats": stats, "total_emotions": len(stats)}


@router.get("/weekly-report", summary="Weekly performance summary from journal")
async def get_weekly_report(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return a summary of trades closed in the current calendar week."""
    from datetime import date, timedelta  # noqa: PLC0415

    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    week_start_iso = week_start.isoformat()

    entries = list(_load_all_entries().values())
    this_week = [
        e for e in entries
        if e.get("pnl") is not None and (e.get("closed_at") or e.get("created_at") or "") >= week_start_iso
    ]

    pnls = [float(e["pnl"]) for e in this_week]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Collect all tags and emotions from this week
    all_tags: dict[str, int] = {}
    all_emotions: dict[str, int] = {}
    for e in this_week:
        for t in e.get("tags") or []:
            all_tags[t] = all_tags.get(t, 0) + 1
        em = e.get("emotion")
        if em:
            all_emotions[em] = all_emotions.get(em, 0) + 1

    return {
        "week_start": week_start_iso,
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "total_trades": len(this_week),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(this_week) * 100, 1) if this_week else 0,
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
        "best_trade": max(pnls) if pnls else 0,
        "worst_trade": min(pnls) if pnls else 0,
        "top_tags": sorted(all_tags.items(), key=lambda x: -x[1])[:5],
        "top_emotions": sorted(all_emotions.items(), key=lambda x: -x[1])[:5],
        "rule_deviations": sum(1 for e in this_week if not e.get("followed_rules", True)),
    }
