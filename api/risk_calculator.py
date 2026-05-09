# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/risk_calculator.py
======================
Risk/Reward Calculator endpoints.

Routes
------
GET  /api/risk/live-price/{symbol}      — live mid price for entry auto-fill
GET  /api/risk/calculator/history       — saved calculation history
POST /api/risk/calculator/history       — save a calculation
DELETE /api/risk/calculator/history/{id} — delete a saved calculation
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/risk", tags=["Risk Calculator"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_live_price(symbol: str) -> float | None:
    """Try multiple sources to get a live mid price for the symbol."""
    from utils.symbol import canonical as _canonical
    sym = _canonical(symbol)  # canonical MT5 form for internal lookups

    # 1. Try the trading app state (fastest — already in memory)
    try:
        from core.app_state import get_app_state
        state = get_app_state()
        if state and hasattr(state, "latest_tick") and state.latest_tick:
            tick = state.latest_tick
            if hasattr(tick, "mid") and tick.mid:
                return float(tick.mid)
    except Exception:  # nosec B110
        pass

    # 2. Try the data layer orchestrator
    try:
        from data_layer.orchestrator import get_orchestrator
        orch = get_orchestrator()
        tick = orch.get_latest_tick(sym)
        if tick and hasattr(tick, "mid"):
            return float(tick.mid)
    except Exception:  # nosec B110
        pass

    # 3. Try yfinance as a last resort
    try:
        import yfinance as yf
        yf_sym = sym.replace("_", "=X") if "_" in sym else sym + "=X"
        ticker = yf.Ticker(yf_sym)
        info = ticker.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price:
            return float(price)
    except Exception:  # nosec B110
        pass

    return None


def _calc_store_key(user_id: str) -> str:
    return f"risk_calc_history:{user_id}"


def _load_history(user_id: str) -> list[dict]:
    try:
        from api.db_store import db_get
        return db_get(_calc_store_key(user_id)) or []
    except Exception:
        return []


def _save_history(user_id: str, history: list[dict]) -> None:
    try:
        from api.db_store import db_set
        db_set(_calc_store_key(user_id), history[-100:])  # keep last 100
    except Exception:  # nosec B110
        pass


# ── Schemas ───────────────────────────────────────────────────────────────────

class SaveCalcRequest(BaseModel):
    symbol:       str   = Field(..., min_length=3, max_length=20)
    entry_price:  float = Field(..., gt=0)
    stop_loss:    float = Field(..., gt=0)
    take_profit:  float = Field(..., gt=0)
    position_size: float = Field(default=0.01, gt=0)
    account_balance: float = Field(default=10000.0, gt=0)
    risk_pct:     float = Field(default=1.0, gt=0, le=100)
    direction:    str   = Field(default="long", pattern="^(long|short)$")
    notes:        str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/live-price/{symbol}", summary="Live mid price for a symbol")
async def get_live_price(
    symbol: str = Path(..., min_length=3, max_length=20),
    user: TokenPayload = Depends(get_current_user),
):
    """Return the current live mid price for the given symbol.

    Used by the Risk/Reward Calculator to auto-fill the entry price field.
    """
    price = _get_live_price(symbol)
    if price is None:
        raise HTTPException(
            status_code=503,
            detail=f"Live price unavailable for {symbol}. Enter manually.",
        )
    return {
        "symbol":    symbol.upper(),
        "mid":       price,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/calculator/history", summary="Saved risk/reward calculations")
async def list_calculations(user: TokenPayload = Depends(get_current_user)):
    """Return the authenticated user's saved R:R calculations, newest first."""
    history = _load_history(user.sub)
    return {"calculations": list(reversed(history)), "total": len(history)}


@router.post("/calculator/history", summary="Save a risk/reward calculation", status_code=201)
async def save_calculation(
    body: SaveCalcRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """Persist a risk/reward calculation for later reference."""
    # Compute derived fields
    if body.direction == "long":
        risk_pts   = body.entry_price - body.stop_loss
        reward_pts = body.take_profit - body.entry_price
    else:
        risk_pts   = body.stop_loss - body.entry_price
        reward_pts = body.entry_price - body.take_profit

    rr_ratio = round(reward_pts / risk_pts, 2) if risk_pts > 0 else 0
    risk_usd = round(body.account_balance * body.risk_pct / 100, 2)

    calc = {
        "id":              str(uuid.uuid4()),
        "user_id":         user.sub,
        "symbol":          body.symbol.upper(),
        "direction":       body.direction,
        "entry_price":     body.entry_price,
        "stop_loss":       body.stop_loss,
        "take_profit":     body.take_profit,
        "position_size":   body.position_size,
        "account_balance": body.account_balance,
        "risk_pct":        body.risk_pct,
        "risk_usd":        risk_usd,
        "rr_ratio":        rr_ratio,
        "notes":           body.notes,
        "created_at":      datetime.now(UTC).isoformat(),
    }
    history = _load_history(user.sub)
    history.append(calc)
    _save_history(user.sub, history)
    return calc


@router.delete("/calculator/history/{calc_id}", summary="Delete a saved calculation")
async def delete_calculation(
    calc_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Remove a saved R:R calculation by ID."""
    history = _load_history(user.sub)
    new_history = [c for c in history if c.get("id") != calc_id]
    if len(new_history) == len(history):
        raise HTTPException(status_code=404, detail="Calculation not found")
    _save_history(user.sub, new_history)
    return {"ok": True, "deleted_id": calc_id}
