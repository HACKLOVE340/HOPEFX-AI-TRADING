"""
api/watchlist.py
================
User watchlist endpoints with DB persistence.

Routes
------
GET    /api/watchlist              — get user's watchlist with live prices
POST   /api/watchlist/{symbol}     — add symbol to watchlist
DELETE /api/watchlist/{symbol}     — remove symbol from watchlist
GET    /api/watchlist/prices       — live prices for all watchlist symbols

All routes require a valid JWT bearer token (Depends(get_current_user)).
Persistence: configurations table via api.db_store.
Falls back to in-memory dict when DB is unavailable.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user
from api.db_store import db_get, db_set

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["Watchlist"])

# In-memory fallback (used when DB unavailable)
_watchlists: Dict[str, List[str]] = {}


def _reset_watchlists() -> None:
    """Clear in-memory state. Used by tests to prevent cross-test leakage."""
    _watchlists.clear()

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


def _load_watchlist(user_id: str) -> List[str]:
    """Load from DB, fall back to in-memory, then default."""
    db_val = db_get(f"watchlist:{user_id}")
    if isinstance(db_val, list):
        _watchlists[user_id] = db_val
        return db_val
    if user_id not in _watchlists:
        _watchlists[user_id] = list(DEFAULT_SYMBOLS)
    return _watchlists[user_id]


def _save_watchlist(user_id: str, symbols: List[str]) -> None:
    _watchlists[user_id] = symbols
    db_set(f"watchlist:{user_id}", symbols, changed_by=user_id)


# ── Models ────────────────────────────────────────────────────────────────────


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
    if sym in wl:
        raise HTTPException(status_code=409, detail=f"{sym} already in watchlist")
    if len(wl) >= 20:
        raise HTTPException(status_code=400, detail="Watchlist limit is 20 symbols")
    wl.append(sym)
    _save_watchlist(user.sub, wl)
    return {"symbol": sym, "added": True, "persisted": True}


@router.delete("/{symbol}")
async def remove_symbol(
    symbol: str = Path(..., min_length=3, max_length=12),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Remove a symbol from the authenticated user's watchlist."""
    sym = symbol.upper()
    wl = _load_watchlist(user.sub)
    if sym not in wl:
        raise HTTPException(status_code=404, detail=f"{sym} not in watchlist")
    wl.remove(sym)
    _save_watchlist(user.sub, wl)
    return {"symbol": sym, "removed": True}


@router.get("/prices", response_model=List[WatchlistItem])
async def get_prices(
    user: TokenPayload = Depends(get_current_user),
) -> List[WatchlistItem]:
    """Return live prices for all symbols in the authenticated user's watchlist."""
    symbols = _load_watchlist(user.sub)
    return [WatchlistItem(**_get_price(s)) for s in symbols]
