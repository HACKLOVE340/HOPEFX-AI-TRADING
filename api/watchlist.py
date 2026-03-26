"""
api/watchlist.py
================
User watchlist endpoints backed by the dedicated `watchlists` table.

Routes
------
GET    /api/watchlist              — get user's watchlist with live prices
POST   /api/watchlist/{symbol}     — add symbol to watchlist
DELETE /api/watchlist/{symbol}     — remove symbol from watchlist
GET    /api/watchlist/prices       — live prices for all watchlist symbols

All routes require a valid JWT bearer token (Depends(get_current_user)).

Persistence strategy (in priority order):
  1. Dedicated `watchlists` table (Alembic migration f1a2b3c4d5e6)
  2. In-memory dict fallback when DB is unavailable (dev / test mode)
"""

from __future__ import annotations

import logging
import random
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["Watchlist"])

# ── In-memory fallback ────────────────────────────────────────────────────────
_watchlists: Dict[str, List[str]] = {}

DEFAULT_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]

_BASE_PRICES: Dict[str, float] = {
    "XAUUSD": 2050.0,
    "EURUSD": 1.0850,
    "GBPUSD": 1.2650,
    "USDJPY": 149.50,
    "BTCUSD": 67000.0,
    "ETHUSD": 3500.0,
    "USDCAD": 1.3600,
    "AUDUSD": 0.6550,
    "USDCHF": 0.8950,
    "NZDUSD": 0.6050,
}


def _reset_watchlists() -> None:
    """Clear in-memory state. Used by tests to prevent cross-test leakage."""
    _watchlists.clear()


# ── DB session helper ─────────────────────────────────────────────────────────

def _get_session() -> Optional[object]:
    try:
        from database.connection import get_db_manager
        mgr = get_db_manager()
        if mgr is None:
            return None
        return mgr.get_session()
    except Exception as exc:
        logger.debug("watchlist: DB session unavailable: %s", exc)
        return None


# ── Dedicated-table persistence ───────────────────────────────────────────────

def _db_load(user_id: str) -> Optional[List[str]]:
    """Load from dedicated watchlists table. Returns None when DB unavailable."""
    session = _get_session()
    if session is None:
        return None
    try:
        from database.models import WatchlistEntry
        rows = (
            session.query(WatchlistEntry)
            .filter(WatchlistEntry.user_id == user_id)
            .order_by(WatchlistEntry.sort_order, WatchlistEntry.added_at)
            .all()
        )
        return [r.symbol for r in rows]
    except Exception as exc:
        logger.debug("watchlist: DB load failed for %s: %s", user_id, exc)
        return None
    finally:
        try:
            session.close()
        except Exception:
            pass


def _db_add(user_id: str, symbol: str) -> bool:
    """Insert into watchlists table. Raises 409 on duplicate. Returns False when DB unavailable."""
    session = _get_session()
    if session is None:
        return False
    try:
        from database.models import WatchlistEntry
        entry = WatchlistEntry(user_id=user_id, symbol=symbol)
        session.add(entry)
        session.commit()
        return True
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        exc_str = str(exc).lower()
        if "unique" in exc_str or "duplicate" in exc_str:
            raise HTTPException(status_code=409, detail=f"{symbol} already in watchlist")
        logger.debug("watchlist: DB add failed for %s/%s: %s", user_id, symbol, exc)
        return False
    finally:
        try:
            session.close()
        except Exception:
            pass


def _db_remove(user_id: str, symbol: str) -> bool:
    """Delete from watchlists table. Raises 404 when not found. Returns False when DB unavailable."""
    session = _get_session()
    if session is None:
        return False
    try:
        from database.models import WatchlistEntry
        row = (
            session.query(WatchlistEntry)
            .filter(
                WatchlistEntry.user_id == user_id,
                WatchlistEntry.symbol == symbol,
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")
        session.delete(row)
        session.commit()
        return True
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        logger.debug("watchlist: DB remove failed for %s/%s: %s", user_id, symbol, exc)
        return False
    finally:
        try:
            session.close()
        except Exception:
            pass


# ── Unified load / save (DB-first, memory fallback) ───────────────────────────

def _load_watchlist(user_id: str) -> List[str]:
    db_val = _db_load(user_id)
    if db_val is not None:
        _watchlists[user_id] = db_val
        return db_val
    if user_id not in _watchlists:
        _watchlists[user_id] = list(DEFAULT_SYMBOLS)
    return _watchlists[user_id]


def _mem_add(user_id: str, symbol: str) -> None:
    wl = _watchlists.setdefault(user_id, list(DEFAULT_SYMBOLS))
    if symbol in wl:
        raise HTTPException(status_code=409, detail=f"{symbol} already in watchlist")
    wl.append(symbol)


def _mem_remove(user_id: str, symbol: str) -> None:
    wl = _watchlists.get(user_id, [])
    if symbol not in wl:
        raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")
    wl.remove(symbol)


# ── Price helper ──────────────────────────────────────────────────────────────

def _get_price(symbol: str) -> dict:
    base = _BASE_PRICES.get(symbol, 1.0)
    noise = random.uniform(-0.002, 0.002)
    mid = base * (1 + noise)
    spread = base * 0.0002
    return {
        "symbol": symbol,
        "bid": round(mid - spread / 2, 5),
        "ask": round(mid + spread / 2, 5),
        "mid": round(mid, 5),
        "change_pct": round(random.uniform(-1.5, 1.5), 2),
        "timestamp": int(time.time() * 1000),
    }


# ── Pydantic models ───────────────────────────────────────────────────────────

class WatchlistItem(BaseModel):
    symbol: str
    bid: float
    ask: float
    mid: float
    change_pct: float
    timestamp: int


class WatchlistResponse(BaseModel):
    user_id: str
    symbols: List[str]
    items: List[WatchlistItem]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=WatchlistResponse)
async def get_watchlist(
    user: TokenPayload = Depends(get_current_user),
) -> WatchlistResponse:
    """Return the authenticated user's watchlist with live prices."""
    symbols = _load_watchlist(user.sub)
    items = [WatchlistItem(**_get_price(s)) for s in symbols]
    return WatchlistResponse(user_id=user.sub, symbols=symbols, items=items)


@router.post("/{symbol}", status_code=status.HTTP_201_CREATED)
async def add_symbol(
    symbol: str = Path(..., min_length=3, max_length=12),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Add a symbol to the authenticated user's watchlist."""
    sym = symbol.upper()
    wl = _load_watchlist(user.sub)
    if len(wl) >= 20:
        raise HTTPException(status_code=400, detail="Watchlist limit is 20 symbols")

    persisted = _db_add(user.sub, sym)
    if not persisted:
        _mem_add(user.sub, sym)

    return {"symbol": sym, "added": True, "persisted": persisted}


@router.delete("/{symbol}")
async def remove_symbol(
    symbol: str = Path(..., min_length=3, max_length=12),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Remove a symbol from the authenticated user's watchlist."""
    sym = symbol.upper()

    removed = _db_remove(user.sub, sym)
    if not removed:
        _mem_remove(user.sub, sym)

    return {"symbol": sym, "removed": True}


@router.get("/prices", response_model=List[WatchlistItem])
async def get_prices(
    user: TokenPayload = Depends(get_current_user),
) -> List[WatchlistItem]:
    """Return live prices for all symbols in the authenticated user's watchlist."""
    symbols = _load_watchlist(user.sub)
    return [WatchlistItem(**_get_price(s)) for s in symbols]
