"""
api/watchlist.py
================
User watchlist endpoints.

Routes
------
GET    /api/watchlist              — get user's watchlist with live prices
POST   /api/watchlist/{symbol}     — add symbol to watchlist
DELETE /api/watchlist/{symbol}     — remove symbol from watchlist
GET    /api/watchlist/prices       — live prices for all watchlist symbols
"""

from __future__ import annotations

import logging
import random
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["Watchlist"])

# In-memory store keyed by user_id (replace with DB in production)
_watchlists: Dict[str, List[str]] = {}

# Default symbols for new users
DEFAULT_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]

# Simulated base prices
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
    """Return a simulated live price tick for a symbol."""
    base = _BASE_PRICES.get(symbol, 1.0)
    noise = random.uniform(-0.002, 0.002)
    mid = base * (1 + noise)
    spread = base * 0.0002
    change_pct = random.uniform(-1.5, 1.5)
    return {
        "symbol": symbol,
        "bid": round(mid - spread / 2, 5),
        "ask": round(mid + spread / 2, 5),
        "mid": round(mid, 5),
        "change_pct": round(change_pct, 2),
        "timestamp": int(time.time() * 1000),
    }


def _get_watchlist(user_id: str) -> List[str]:
    if user_id not in _watchlists:
        _watchlists[user_id] = list(DEFAULT_SYMBOLS)
    return _watchlists[user_id]


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
async def get_watchlist(user_id: str = "demo") -> WatchlistResponse:
    symbols = _get_watchlist(user_id)
    items = [WatchlistItem(**_get_price(s)) for s in symbols]
    return WatchlistResponse(user_id=user_id, symbols=symbols, items=items)


@router.post("/{symbol}", status_code=status.HTTP_201_CREATED)
async def add_symbol(
    symbol: str = Path(..., min_length=3, max_length=12),
    user_id: str = "demo",
) -> dict:
    sym = symbol.upper()
    wl = _get_watchlist(user_id)
    if sym in wl:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{sym} already in watchlist")
    if len(wl) >= 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Watchlist limit is 20 symbols")
    wl.append(sym)
    logger.info("Added %s to watchlist for %s", sym, user_id)
    return {"symbol": sym, "added": True}


@router.delete("/{symbol}")
async def remove_symbol(
    symbol: str = Path(..., min_length=3, max_length=12),
    user_id: str = "demo",
) -> dict:
    sym = symbol.upper()
    wl = _get_watchlist(user_id)
    if sym not in wl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{sym} not in watchlist")
    wl.remove(sym)
    logger.info("Removed %s from watchlist for %s", sym, user_id)
    return {"symbol": sym, "removed": True}


@router.get("/prices", response_model=List[WatchlistItem])
async def get_prices(user_id: str = "demo") -> List[WatchlistItem]:
    symbols = _get_watchlist(user_id)
    return [WatchlistItem(**_get_price(s)) for s in symbols]
