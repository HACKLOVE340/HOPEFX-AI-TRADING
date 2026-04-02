# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
import time

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["Watchlist"])

# ── App state (injected at startup) ──────────────────────────────────────────
app_state = None


def set_state(state) -> None:
    global app_state
    app_state = state


# ── In-memory fallback ────────────────────────────────────────────────────────
_watchlists: dict[str, list[str]] = {}

DEFAULT_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]


def _reset_watchlists() -> None:
    """Clear in-memory state. Used by tests to prevent cross-test leakage."""
    _watchlists.clear()


# ── DB session helper ─────────────────────────────────────────────────────────


def _get_session():  # type: ignore[return]
    """Return a live SQLAlchemy Session, or None when the DB is unavailable."""
    try:
        from database.connection import get_db_manager

        mgr = get_db_manager()
        if mgr is None:
            return None
        ctx = mgr.session()
        return ctx.__enter__()  # caller is responsible for close/rollback in finally
    except Exception as exc:
        logger.debug("watchlist: DB session unavailable: %s", exc)
        return None


# ── Dedicated-table persistence ───────────────────────────────────────────────


def _db_load(user_id: str) -> list[str] | None:
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
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)


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
            raise HTTPException(status_code=409, detail=f"{symbol} already in watchlist") from exc
        logger.debug("watchlist: DB add failed for %s/%s: %s", user_id, symbol, exc)
        return False
    finally:
        try:
            session.close()
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)


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
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)


# ── Unified load / save (DB-first, memory fallback) ───────────────────────────


def _load_watchlist(user_id: str) -> list[str]:
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


def _get_price(symbol: str) -> dict | None:
    """
    Return a live price dict for *symbol*, or None if no feed is available.

    Priority:
    1. Live price from app_state.price_engine (real-time feed)
    2. Live price from app_state.broker.market_prices (paper broker cache)

    Returns None when both sources are unavailable — callers must handle
    the missing-price case and must not substitute synthetic data.
    """
    # 1. Price engine
    try:
        pe = getattr(app_state, "price_engine", None) if app_state else None
        if pe is not None:
            tick = pe.get_last_price(symbol)
            if tick is not None:
                bid = float(getattr(tick, "bid", 0) or getattr(tick, "last_price", 0))
                ask = float(getattr(tick, "ask", 0) or bid)
                mid = (bid + ask) / 2 if bid and ask else bid or ask
                return {
                    "symbol": symbol,
                    "bid": round(bid, 5),
                    "ask": round(ask, 5),
                    "mid": round(mid, 5),
                    "change_pct": round(float(getattr(tick, "change_pct", 0) or 0), 2),
                    "timestamp": int(time.time() * 1000),
                }
    except Exception as exc:
        logger.debug("watchlist price_engine miss for %s: %s", symbol, exc)

    # 2. Broker market_prices cache
    try:
        broker = getattr(app_state, "broker", None) if app_state else None
        if broker is not None:
            prices = getattr(broker, "market_prices", {})
            if symbol in prices:
                p = prices[symbol]
                bid = float(getattr(p, "bid", p) if hasattr(p, "bid") else p)
                ask = float(getattr(p, "ask", bid) if hasattr(p, "ask") else bid)
                mid = (bid + ask) / 2
                return {
                    "symbol": symbol,
                    "bid": round(bid, 5),
                    "ask": round(ask, 5),
                    "mid": round(mid, 5),
                    "change_pct": 0.0,
                    "timestamp": int(time.time() * 1000),
                }
    except Exception as exc:
        logger.debug("watchlist broker price miss for %s: %s", symbol, exc)

    # No live price available
    logger.debug("watchlist: no live price for %s — omitting from response", symbol)
    return None


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
    symbols: list[str]
    items: list[WatchlistItem]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=WatchlistResponse)
async def get_watchlist(
    user: TokenPayload = Depends(get_current_user),
) -> WatchlistResponse:
    """Return the authenticated user's watchlist with live prices."""
    symbols = _load_watchlist(user.sub)
    items = [WatchlistItem(**p) for s in symbols if (p := _get_price(s)) is not None]
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


@router.get("/prices", response_model=list[WatchlistItem])
async def get_prices(
    user: TokenPayload = Depends(get_current_user),
) -> list[WatchlistItem]:
    """Return live prices for all symbols in the authenticated user's watchlist."""
    symbols = _load_watchlist(user.sub)
    return [WatchlistItem(**p) for s in symbols if (p := _get_price(s)) is not None]
