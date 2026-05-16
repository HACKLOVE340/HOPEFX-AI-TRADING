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

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/journal", tags=["Trade Journal"])


def _get_db():
    """Return a synchronous DB session for legacy sync paths (journal uses sync ORM)."""
    try:
        from database.connection import SessionLocal

        return SessionLocal()
    except Exception as exc:
        logger.warning("journal: DB unavailable: %s", exc)
        return None


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


import json as _json


# ── Persistence helpers ───────────────────────────────────────────────────────


def _row_to_dict(row) -> dict:
    """Convert a DB row to a plain dict, deserialising JSON tags."""
    d = dict(row._mapping)
    if isinstance(d.get("tags"), str):
        try:
            d["tags"] = _json.loads(d["tags"])
        except Exception:
            d["tags"] = []
    return d


from sqlalchemy import text as _text


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
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        conditions = ["user_id = :uid"]
        params: dict = {"uid": user.sub, "limit": limit, "offset": offset}
        if emotion:
            conditions.append("emotion = :emotion")
            params["emotion"] = emotion
        where = " AND ".join(conditions)
        rows = db.execute(
            _text(
                f"SELECT * FROM trade_journal WHERE {where} "  # nosec B608
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        entries = [_row_to_dict(r) for r in rows]
        # Filter by tag in Python (JSON array stored as text)
        if tag:
            entries = [e for e in entries if tag in (e.get("tags") or [])]
        if symbol:
            entries = [e for e in entries if (e.get("symbol") or "").upper() == symbol.upper()]
        return [JournalEntry(**e) for e in entries]
    finally:
        db.close()


@router.post("/trades", response_model=JournalEntry, status_code=status.HTTP_201_CREATED)
async def create_entry(
    entry: JournalEntry,
    user: TokenPayload = Depends(get_current_user),
) -> JournalEntry:
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        now = datetime.now(UTC)
        if not entry.trade_id:
            entry.trade_id = str(uuid.uuid4())
        entry.created_at = now.isoformat()
        entry.updated_at = now.isoformat()
        tags_json = _json.dumps(entry.tags or [])
        db.execute(
            _text(
                "INSERT INTO trade_journal "
                "(user_id, trade_id, title, notes, tags, emotion, rating, "
                "setup_quality, lessons_learned, screenshot_url, created_at, updated_at) "
                "VALUES (:uid, :trade_id, :title, :notes, :tags, :emotion, :rating, "
                ":setup_quality, :lessons_learned, :screenshot_url, :created_at, :updated_at)"
            ),
            {
                "uid": user.sub,
                "trade_id": entry.trade_id,
                "title": None,
                "notes": entry.notes,
                "tags": tags_json,
                "emotion": entry.emotion,
                "rating": None,
                "setup_quality": None,
                "lessons_learned": entry.rule_deviation,
                "screenshot_url": entry.screenshot_url,
                "created_at": now,
                "updated_at": now,
            },
        )
        db.commit()
        return entry
    except Exception as exc:
        db.rollback()
        logger.error("create_entry error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create journal entry") from exc
    finally:
        db.close()


@router.get("/trades/{trade_id}", response_model=JournalEntry)
async def get_entry(
    trade_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> JournalEntry:
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.execute(
            _text("SELECT * FROM trade_journal WHERE trade_id = :tid AND user_id = :uid"),
            {"tid": trade_id, "uid": user.sub},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Journal entry not found")
        d = _row_to_dict(row)
        return JournalEntry(**d)
    finally:
        db.close()


@router.patch("/trades/{trade_id}", response_model=JournalEntry)
async def update_entry(
    trade_id: str,
    update: JournalUpdate,
    user: TokenPayload = Depends(get_current_user),
) -> JournalEntry:
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        row = db.execute(
            _text("SELECT id FROM trade_journal WHERE trade_id = :tid AND user_id = :uid"),
            {"tid": trade_id, "uid": user.sub},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Journal entry not found")
        updates: dict = {"updated_at": datetime.now(UTC)}
        data = update.model_dump(exclude_none=True)
        if "notes" in data:
            updates["notes"] = data["notes"]
        if "tags" in data:
            updates["tags"] = _json.dumps(data["tags"])
        if "emotion" in data:
            updates["emotion"] = data["emotion"]
        if "rule_deviation" in data:
            updates["lessons_learned"] = data["rule_deviation"]
        if "screenshot_url" in data:
            updates["screenshot_url"] = data["screenshot_url"]
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["trade_id"] = trade_id
        db.execute(
            _text(f"UPDATE trade_journal SET {set_clause} WHERE trade_id = :trade_id"),  # nosec B608
            updates,
        )
        db.commit()
        updated = db.execute(
            _text("SELECT * FROM trade_journal WHERE trade_id = :tid"),
            {"tid": trade_id},
        ).fetchone()
        return JournalEntry(**_row_to_dict(updated))
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("update_entry error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update journal entry") from exc
    finally:
        db.close()


@router.get("/stats", response_model=JournalStats)
async def get_stats(user: TokenPayload = Depends(get_current_user)) -> JournalStats:
    db = _get_db()
    if db is None:
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
    try:
        # Join trade_journal with trades to get PnL
        rows = db.execute(
            _text(
                "SELECT tj.tags, tj.emotion, tj.lessons_learned, t.realized_pnl "
                "FROM trade_journal tj "
                "LEFT JOIN trades t ON t.trade_id = tj.trade_id "
                "WHERE tj.user_id = :uid"
            ),
            {"uid": user.sub},
        ).fetchall()
        entries = [_row_to_dict(r) for r in rows]
        closed = [e for e in entries if e.get("realized_pnl") is not None]
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
        pnls = [float(e["realized_pnl"]) for e in closed]
        wins = [p for p in pnls if p > 0]
        all_tags = {t for e in closed for t in (e.get("tags") or [])}
        tag_stats = []
        for tag in all_tags:
            tagged = [e for e in closed if tag in (e.get("tags") or [])]
            tag_pnls = [float(e["realized_pnl"]) for e in tagged]
            tag_wins = [p for p in tag_pnls if p > 0]
            tag_stats.append(
                TagStats(
                    tag=tag,
                    count=len(tagged),
                    win_rate=round(len(tag_wins) / len(tagged) * 100, 1) if tagged else 0,
                    avg_pnl=round(sum(tag_pnls) / len(tag_pnls), 2) if tag_pnls else 0,
                )
            )
        all_emotions = {e.get("emotion") for e in closed if e.get("emotion")}
        emotion_stats = []
        for em in all_emotions:
            em_entries = [e for e in closed if e.get("emotion") == em]
            em_pnls = [float(e["realized_pnl"]) for e in em_entries]
            em_wins = [p for p in em_pnls if p > 0]
            emotion_stats.append(
                TagStats(
                    tag=em,
                    count=len(em_entries),
                    win_rate=round(len(em_wins) / len(em_entries) * 100, 1) if em_entries else 0,
                    avg_pnl=round(sum(em_pnls) / len(em_pnls), 2) if em_pnls else 0,
                )
            )
        return JournalStats(
            total_trades=len(closed),
            win_rate=round(len(wins) / len(closed) * 100, 1),
            avg_pnl=round(sum(pnls) / len(pnls), 2),
            best_trade_pnl=max(pnls),
            worst_trade_pnl=min(pnls),
            by_tag=sorted(tag_stats, key=lambda x: x.count, reverse=True),
            by_emotion=sorted(emotion_stats, key=lambda x: x.count, reverse=True),
            rule_deviation_count=sum(1 for e in entries if e.get("lessons_learned")),
        )
    finally:
        db.close()


@router.get("/mistakes", response_model=list[JournalEntry])
async def get_mistakes(user: TokenPayload = Depends(get_current_user)) -> list[JournalEntry]:
    """Trades where the user recorded a rule deviation (lessons_learned is set)."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rows = db.execute(
            _text(
                "SELECT * FROM trade_journal WHERE user_id = :uid AND lessons_learned IS NOT NULL ORDER BY created_at DESC"
            ),
            {"uid": user.sub},
        ).fetchall()
        return [JournalEntry(**_row_to_dict(r)) for r in rows]
    finally:
        db.close()


# ── Extended analytics endpoints ──────────────────────────────────────────────


@router.get("/tags", summary="List all tags used across journal entries")
async def get_tags(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return every unique tag used in journal entries with usage counts."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rows = db.execute(
            _text("SELECT tags FROM trade_journal WHERE user_id = :uid"),
            {"uid": user.sub},
        ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            tags_raw = row._mapping.get("tags") or "[]"
            try:
                tag_list = _json.loads(tags_raw)
            except Exception:
                tag_list = []
            for tag in tag_list:
                counts[tag] = counts.get(tag, 0) + 1
        tags = [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda x: -x[1])]
        return {"tags": tags, "total": len(tags)}
    finally:
        db.close()


@router.get("/emotion-stats", summary="Emotion breakdown across journal entries")
async def get_emotion_stats(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return win rate and average PnL grouped by emotion tag."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rows = db.execute(
            _text(
                "SELECT tj.emotion, t.realized_pnl "
                "FROM trade_journal tj "
                "LEFT JOIN trades t ON t.trade_id = tj.trade_id "
                "WHERE tj.user_id = :uid AND tj.emotion IS NOT NULL"
            ),
            {"uid": user.sub},
        ).fetchall()
        emotion_map: dict[str, list[float]] = {}
        for row in rows:
            em = row._mapping.get("emotion")
            pnl = row._mapping.get("realized_pnl")
            if em and pnl is not None:
                emotion_map.setdefault(em, []).append(float(pnl))
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
    finally:
        db.close()


@router.get("/weekly-report", summary="Weekly performance summary from journal")
async def get_weekly_report(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return a summary of trades closed in the current calendar week."""
    from datetime import date, timedelta

    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday

    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rows = db.execute(
            _text(
                "SELECT tj.tags, tj.emotion, tj.lessons_learned, t.realized_pnl, t.exit_time "
                "FROM trade_journal tj "
                "LEFT JOIN trades t ON t.trade_id = tj.trade_id "
                "WHERE tj.user_id = :uid AND t.exit_time >= :week_start"
            ),
            {"uid": user.sub, "week_start": datetime.combine(week_start, datetime.min.time())},
        ).fetchall()
        entries = [dict(r._mapping) for r in rows]
        pnls = [float(e["realized_pnl"]) for e in entries if e.get("realized_pnl") is not None]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        all_tags: dict[str, int] = {}
        all_emotions: dict[str, int] = {}
        for e in entries:
            try:
                for t in _json.loads(e.get("tags") or "[]"):
                    all_tags[t] = all_tags.get(t, 0) + 1
            except Exception:  # nosec B110
                pass
            em = e.get("emotion")
            if em:
                all_emotions[em] = all_emotions.get(em, 0) + 1
        return {
            "week_start": week_start.isoformat(),
            "week_end": (week_start + timedelta(days=6)).isoformat(),
            "total_trades": len(entries),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(entries) * 100, 1) if entries else 0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "best_trade": max(pnls) if pnls else 0,
            "worst_trade": min(pnls) if pnls else 0,
            "top_tags": sorted(all_tags.items(), key=lambda x: -x[1])[:5],
            "top_emotions": sorted(all_emotions.items(), key=lambda x: -x[1])[:5],
            "rule_deviations": sum(1 for e in entries if e.get("lessons_learned")),
        }
    finally:
        db.close()


# ── Export ────────────────────────────────────────────────────────────────────


@router.get("/export", summary="Export journal entries as CSV or JSON")
async def export_journal(
    format: str = Query("csv", pattern="^(csv|json)$"),
    user: TokenPayload = Depends(get_current_user),
):
    """Download all journal entries for the authenticated user."""
    db = _get_db()
    try:
        rows = db.execute(
            "SELECT * FROM journal WHERE user_id = :uid ORDER BY created_at DESC",
            {"uid": user.sub},
        ).fetchall()
        entries = [_row_to_dict(dict(r)) for r in rows]
    except Exception:
        entries = []
    finally:
        db.close()

    if format == "json":
        import json as _j

        content = _j.dumps(entries, indent=2, default=str)
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=journal.json"},
        )

    # CSV
    if not entries:
        csv_content = "id,trade_id,title,notes,tags,emotion,rating,pnl,created_at\n"
    else:
        buf = io.StringIO()
        fieldnames = [
            "id",
            "trade_id",
            "title",
            "notes",
            "tags",
            "emotion",
            "rating",
            "pnl",
            "setup_quality",
            "lessons_learned",
            "screenshot_url",
            "created_at",
            "updated_at",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            row = {k: e.get(k, "") for k in fieldnames}
            if isinstance(row.get("tags"), list):
                row["tags"] = ",".join(row["tags"])
            writer.writerow(row)
        csv_content = buf.getvalue()

    return StreamingResponse(
        io.BytesIO(csv_content.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=journal.csv"},
    )


# ── Screenshot upload ─────────────────────────────────────────────────────────


@router.post("/trades/{trade_id}/screenshot", summary="Attach a screenshot to a journal entry")
async def upload_screenshot(
    trade_id: str,
    file: UploadFile = File(...),
    user: TokenPayload = Depends(get_current_user),
):
    """Store a chart screenshot for a journal entry.

    Saves the file to the local filesystem under ``static/screenshots/`` and
    returns the public URL.  Falls back to a base64 data-URI when the
    filesystem is not writable.
    """
    import base64
    import os as _os2

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(status_code=413, detail="Screenshot must be under 10 MB")

    # Verify the entry belongs to this user
    db = _get_db()
    try:
        row = db.execute(
            "SELECT id FROM journal WHERE id = :tid AND user_id = :uid",
            {"tid": trade_id, "uid": user.sub},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Journal entry not found")
    finally:
        db.close()

    # Try to save to disk
    ext = (file.filename or "screenshot.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        ext = "png"
    filename = f"{user.sub}_{trade_id}.{ext}"
    save_dir = _os2.path.join("static", "screenshots")
    url: str
    try:
        _os2.makedirs(save_dir, exist_ok=True)
        filepath = _os2.path.join(save_dir, filename)
        with open(filepath, "wb") as fh:
            fh.write(content)
        url = f"/static/screenshots/{filename}"
    except Exception:
        # Fallback: base64 data URI (not ideal for large files but functional)
        mime = f"image/{ext}"
        url = f"data:{mime};base64,{base64.b64encode(content).decode()}"

    # Persist URL on the journal entry
    db2 = _get_db()
    try:
        db2.execute(
            "UPDATE journal SET screenshot_url = :url, updated_at = :now WHERE id = :tid AND user_id = :uid",
            {
                "url": url,
                "now": datetime.now(UTC).isoformat(),
                "tid": trade_id,
                "uid": user.sub,
            },
        )
        db2.commit()
    except Exception as exc:
        logger.debug("screenshot URL persist error: %s", exc)
    finally:
        db2.close()

    return {"screenshot_url": url, "trade_id": trade_id}
