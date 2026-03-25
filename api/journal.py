"""
api/journal.py
==============
Trade Journal endpoints.

Routes
------
GET    /api/journal/trades              — list journal entries (paginated)
POST   /api/journal/trades              — create/update journal entry for a trade
GET    /api/journal/trades/{trade_id}   — get single entry
PATCH  /api/journal/trades/{trade_id}   — update notes/tags/emotion
GET    /api/journal/stats               — win rate by tag, emotion breakdown
GET    /api/journal/mistakes            — trades where rules were deviated from
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/journal", tags=["Trade Journal"])

# In-memory store (replace with DB in production)
_entries: Dict[str, dict] = {}


# ── Models ────────────────────────────────────────────────────────────────────

EMOTION_TAGS = ["patient", "fomo", "revenge", "disciplined", "hesitant", "overconfident", "fearful"]
TRADE_TAGS   = ["trend", "breakout", "reversal", "news", "scalp", "swing", "mistake", "best-trade"]


class JournalEntry(BaseModel):
    trade_id: str
    symbol: str
    side: str                          # long | short
    entry_price: float
    exit_price: Optional[float] = None
    size: float
    pnl: Optional[float] = None
    opened_at: str
    closed_at: Optional[str] = None
    notes: str = ""
    tags: List[str] = Field(default_factory=list)
    emotion: Optional[str] = None      # one of EMOTION_TAGS
    followed_rules: bool = True
    rule_deviation: Optional[str] = None
    screenshot_url: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class JournalUpdate(BaseModel):
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    emotion: Optional[str] = None
    followed_rules: Optional[bool] = None
    rule_deviation: Optional[str] = None
    screenshot_url: Optional[str] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    closed_at: Optional[str] = None


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
    by_tag: List[TagStats]
    by_emotion: List[TagStats]
    rule_deviation_count: int


# ── Seed data ─────────────────────────────────────────────────────────────────

def _seed():
    """Seed with realistic demo entries."""
    if _entries:
        return
    samples = [
        dict(symbol="XAUUSD", side="long",  entry_price=2045.0, exit_price=2062.0, size=0.5, pnl=85.0,
             notes="Clean breakout above 2050 resistance. Waited for retest.", tags=["breakout", "trend"],
             emotion="patient", followed_rules=True),
        dict(symbol="XAUUSD", side="short", entry_price=2078.0, exit_price=2091.0, size=0.3, pnl=-39.0,
             notes="Entered too early before NFP. Should have waited.", tags=["news", "mistake"],
             emotion="fomo", followed_rules=False, rule_deviation="Entered before high-impact news event"),
        dict(symbol="EURUSD", side="long",  entry_price=1.0842, exit_price=1.0871, size=1.0, pnl=29.0,
             notes="ECB dovish surprise. Caught the move perfectly.", tags=["news", "swing"],
             emotion="disciplined", followed_rules=True),
        dict(symbol="XAUUSD", side="long",  entry_price=2031.0, exit_price=2055.0, size=0.8, pnl=192.0,
             notes="Best trade this month. RSI oversold + DXY falling.", tags=["reversal", "best-trade"],
             emotion="patient", followed_rules=True),
        dict(symbol="XAUUSD", side="short", entry_price=2068.0, exit_price=2061.0, size=0.5, pnl=35.0,
             notes="Scalp at resistance. Quick in and out.", tags=["scalp"],
             emotion="disciplined", followed_rules=True),
    ]
    for i, s in enumerate(samples):
        tid = f"demo-{i+1}"
        now = datetime.now(timezone.utc).isoformat()
        entry = JournalEntry(
            trade_id=tid,
            opened_at=now,
            closed_at=now,
            created_at=now,
            updated_at=now,
            **s,
        )
        _entries[tid] = entry.model_dump()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/trades", response_model=List[JournalEntry])
async def list_trades(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tag: Optional[str] = None,
    emotion: Optional[str] = None,
    symbol: Optional[str] = None,
) -> List[JournalEntry]:
    _seed()
    entries = list(_entries.values())
    if tag:
        entries = [e for e in entries if tag in e.get("tags", [])]
    if emotion:
        entries = [e for e in entries if e.get("emotion") == emotion]
    if symbol:
        entries = [e for e in entries if e.get("symbol") == symbol.upper()]
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return [JournalEntry(**e) for e in entries[offset:offset + limit]]


@router.post("/trades", response_model=JournalEntry, status_code=status.HTTP_201_CREATED)
async def create_entry(entry: JournalEntry) -> JournalEntry:
    _seed()
    if not entry.trade_id:
        entry.trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    entry.created_at = now
    entry.updated_at = now
    _entries[entry.trade_id] = entry.model_dump()
    return entry


@router.get("/trades/{trade_id}", response_model=JournalEntry)
async def get_entry(trade_id: str) -> JournalEntry:
    _seed()
    if trade_id not in _entries:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    return JournalEntry(**_entries[trade_id])


@router.patch("/trades/{trade_id}", response_model=JournalEntry)
async def update_entry(trade_id: str, update: JournalUpdate) -> JournalEntry:
    _seed()
    if trade_id not in _entries:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    entry = _entries[trade_id]
    for field, value in update.model_dump(exclude_none=True).items():
        entry[field] = value
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    return JournalEntry(**entry)


@router.get("/stats", response_model=JournalStats)
async def get_stats() -> JournalStats:
    _seed()
    entries = list(_entries.values())
    closed = [e for e in entries if e.get("pnl") is not None]
    if not closed:
        return JournalStats(total_trades=0, win_rate=0, avg_pnl=0, best_trade_pnl=0,
                            worst_trade_pnl=0, by_tag=[], by_emotion=[], rule_deviation_count=0)

    pnls = [e["pnl"] for e in closed]
    wins = [p for p in pnls if p > 0]

    # By tag
    tag_stats = []
    all_tags = set(t for e in closed for t in e.get("tags", []))
    for tag in all_tags:
        tagged = [e for e in closed if tag in e.get("tags", [])]
        tag_pnls = [e["pnl"] for e in tagged]
        tag_wins = [p for p in tag_pnls if p > 0]
        tag_stats.append(TagStats(
            tag=tag, count=len(tagged),
            win_rate=round(len(tag_wins) / len(tagged) * 100, 1) if tagged else 0,
            avg_pnl=round(sum(tag_pnls) / len(tag_pnls), 2) if tag_pnls else 0,
        ))

    # By emotion
    emotion_stats = []
    all_emotions = set(e.get("emotion") for e in closed if e.get("emotion"))
    for em in all_emotions:
        em_entries = [e for e in closed if e.get("emotion") == em]
        em_pnls = [e["pnl"] for e in em_entries]
        em_wins = [p for p in em_pnls if p > 0]
        emotion_stats.append(TagStats(
            tag=em, count=len(em_entries),
            win_rate=round(len(em_wins) / len(em_entries) * 100, 1) if em_entries else 0,
            avg_pnl=round(sum(em_pnls) / len(em_pnls), 2) if em_pnls else 0,
        ))

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


@router.get("/mistakes", response_model=List[JournalEntry])
async def get_mistakes() -> List[JournalEntry]:
    """Trades where the user deviated from their rules."""
    _seed()
    mistakes = [e for e in _entries.values() if not e.get("followed_rules", True)]
    return [JournalEntry(**e) for e in mistakes]
