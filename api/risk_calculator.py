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
from pydantic import BaseModel, Field, field_validator

from api.auth import TokenPayload, get_current_user

# ── F4-01b (continued) ───────────────────────────────────────────────────────
#
# `/calculator/*` is the `risk-calculator` feature, advertised as starter, and
# was gated in React only. Now gated here too.
#
# `/live-price/{symbol}` is deliberately left at authentication-only. It returns
# a mid price, not the paid feature: the sizing arithmetic runs in the browser,
# and what a subscription buys is the saved-calculation history above. Gating a
# quote would protect nothing and would break the entry auto-fill for any user
# who reaches the page by another route.
from monetization.subscription import require_plan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/risk", tags=["Risk Calculator"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _yahoo_ticker(canonical_symbol: str) -> str:
    """Map a canonical symbol (XAUUSD, BTCUSD) to its Yahoo Finance ticker.

    The previous expression was ``sym.replace("_", "=X") if "_" in sym else sym + "=X"``.
    ``canonical()`` strips every separator, so ``"_" in sym`` is never true and
    the first branch was dead: every symbol got ``=X`` appended. That is right
    for FX and metals and wrong for crypto — Yahoo lists Bitcoin as ``BTC-USD``,
    not ``BTCUSD=X`` — so this level could never price the two crypto
    instruments the terminal offers, and the endpoint 503'd for them.
    """
    if canonical_symbol in _CRYPTO_BASES_TO_YAHOO:
        return _CRYPTO_BASES_TO_YAHOO[canonical_symbol]
    return f"{canonical_symbol}=X"


_CRYPTO_BASES_TO_YAHOO: dict[str, str] = {
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "SOLUSD": "SOL-USD",
    "XRPUSD": "XRP-USD",
}


def _get_live_price(symbol: str) -> float | None:
    """Try multiple sources to get a live mid price for the symbol."""
    from utils.symbol import canonical as _canonical

    sym = _canonical(symbol)  # canonical MT5 form for internal lookups

    # 1. The shared live-price chain in api/ws_live.
    #
    #    This module used to open with its own level 1:
    #
    #        state = get_app_state()
    #        if state.latest_tick and state.latest_tick.mid:
    #            return float(state.latest_tick.mid)
    #
    #    `latest_tick` is the engine's single most recent tick — XAUUSD in every
    #    deployment — and the branch never looked at `symbol`. So asking for
    #    EUR/USD returned the price of gold, and the calculator sized a EUR/USD
    #    position against ~4,400. Because it was the FIRST level and app_state is
    #    always present, it also short-circuited the two symbol-aware levels
    #    below for every request. That is the same defect as the paper broker's
    #    3300.0 seed: an always-available value standing in for a quote.
    #
    #    ws_live._get_live_price is the hardened version of this chain — price
    #    engine, then broker prices screened by has_live_price(), then the Redis
    #    tick cache, then the EventBus last-known mid — and it is symbol-aware at
    #    every level. Two copies of a price chain is one too many; this defers to
    #    the one the WebSocket already uses, so the calculator and the header
    #    cannot disagree about what an instrument costs.
    try:
        from api.ws_live import _SLASH_SYMBOL, _get_live_price as _ws_live_price

        price = _ws_live_price(_SLASH_SYMBOL.get(sym, sym))
        if price and price > 0:
            return float(price)
    except Exception as exc:
        logger.debug("risk _get_live_price L1 (%s): %s", symbol, exc)

    # 2. Try the data layer orchestrator
    try:
        from data_layer.orchestrator import get_orchestrator

        orch = get_orchestrator()
        tick = orch.get_latest_tick(sym)
        mid = getattr(tick, "mid", None) if tick else None
        if mid and float(mid) > 0:
            return float(mid)
    except Exception as exc:
        logger.debug("risk _get_live_price L2 (%s): %s", symbol, exc)

    # 3. Try yfinance as a last resort
    try:
        import yfinance as yf

        ticker = yf.Ticker(_yahoo_ticker(sym))
        info = ticker.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price and float(price) > 0:
            return float(price)
    except Exception as exc:
        logger.debug("risk _get_live_price L3 (%s): %s", symbol, exc)

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
    except Exception:  # nosec B110  # noqa: S110
        pass


# ── Schemas ───────────────────────────────────────────────────────────────────


class SaveCalcRequest(BaseModel):
    symbol: str = Field(..., min_length=3, max_length=20)
    # direction MUST be declared before stop_loss and take_profit so that
    # Pydantic v2 field_validators on those fields can read info.data["direction"].
    # Pydantic v2 populates info.data with fields declared *before* the current
    # field in source order; fields declared after are absent from info.data.
    direction: str = Field(default="long", pattern="^(long|short)$")
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    position_size: float = Field(default=0.01, gt=0)
    account_balance: float = Field(default=10000.0, gt=0)
    risk_pct: float = Field(default=1.0, gt=0, le=100)
    notes: str | None = None

    @field_validator("stop_loss")
    @classmethod
    def _validate_stop_loss(cls, v: float, info) -> float:
        data = info.data
        entry = data.get("entry_price")
        direction = data.get("direction", "long")
        if entry is None:
            return v
        if direction == "long" and v >= entry:
            raise ValueError(f"stop_loss ({v}) must be below entry_price ({entry}) for a long trade")
        if direction == "short" and v <= entry:
            raise ValueError(f"stop_loss ({v}) must be above entry_price ({entry}) for a short trade")
        return v

    @field_validator("take_profit")
    @classmethod
    def _validate_take_profit(cls, v: float, info) -> float:
        data = info.data
        entry = data.get("entry_price")
        direction = data.get("direction", "long")
        if entry is None:
            return v
        if direction == "long" and v <= entry:
            raise ValueError(f"take_profit ({v}) must be above entry_price ({entry}) for a long trade")
        if direction == "short" and v >= entry:
            raise ValueError(f"take_profit ({v}) must be below entry_price ({entry}) for a short trade")
        return v


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
        "symbol": symbol.upper(),
        "mid": price,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/calculator/history", summary="Saved risk/reward calculations")
async def list_calculations(user: TokenPayload = Depends(require_plan("starter"))):
    """Return the authenticated user's saved R:R calculations, newest first."""
    history = _load_history(user.sub)
    return {"calculations": list(reversed(history)), "total": len(history)}


@router.post("/calculator/history", summary="Save a risk/reward calculation", status_code=201)
async def save_calculation(
    body: SaveCalcRequest,
    user: TokenPayload = Depends(require_plan("starter")),
):
    """Persist a risk/reward calculation for later reference."""
    # Compute derived fields.
    # Validators on SaveCalcRequest guarantee SL/TP are on the correct side of
    # entry, so risk_pts and reward_pts are always positive here.  The explicit
    # guards below defend against floating-point edge cases (e.g. entry == sl).
    if body.direction == "long":
        risk_pts = body.entry_price - body.stop_loss
        reward_pts = body.take_profit - body.entry_price
    else:
        risk_pts = body.stop_loss - body.entry_price
        reward_pts = body.entry_price - body.take_profit

    if risk_pts <= 0:
        raise HTTPException(
            status_code=422,
            detail="stop_loss must differ from entry_price (risk distance is zero)",
        )
    rr_ratio = round(reward_pts / risk_pts, 2) if reward_pts > 0 else 0.0
    risk_usd = round(body.account_balance * body.risk_pct / 100, 2)

    calc = {
        "id": str(uuid.uuid4()),
        "user_id": user.sub,
        "symbol": body.symbol.upper(),
        "direction": body.direction,
        "entry_price": body.entry_price,
        "stop_loss": body.stop_loss,
        "take_profit": body.take_profit,
        "position_size": body.position_size,
        "account_balance": body.account_balance,
        "risk_pct": body.risk_pct,
        "risk_usd": risk_usd,
        "rr_ratio": rr_ratio,
        "notes": body.notes,
        "created_at": datetime.now(UTC).isoformat(),
    }
    history = _load_history(user.sub)
    history.append(calc)
    _save_history(user.sub, history)
    return calc


@router.delete("/calculator/history/{calc_id}", summary="Delete a saved calculation")
async def delete_calculation(
    calc_id: str,
    user: TokenPayload = Depends(require_plan("starter")),
):
    """Remove a saved R:R calculation by ID."""
    history = _load_history(user.sub)
    new_history = [c for c in history if c.get("id") != calc_id]
    if len(new_history) == len(history):
        raise HTTPException(status_code=404, detail="Calculation not found")
    _save_history(user.sub, new_history)
    return {"ok": True, "deleted_id": calc_id}
