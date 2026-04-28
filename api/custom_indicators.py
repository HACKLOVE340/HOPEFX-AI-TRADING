# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/custom_indicators.py
========================
Custom indicator management API.

Routes
------
GET    /api/indicators                    — list user's custom indicators
POST   /api/indicators                    — create a new custom indicator
GET    /api/indicators/{id}               — get a specific indicator
PATCH  /api/indicators/{id}               — update an indicator
DELETE /api/indicators/{id}               — delete an indicator
POST   /api/indicators/{id}/apply         — apply indicator to a symbol/timeframe
GET    /api/indicators/builtin            — list all built-in indicators
POST   /api/indicators/calculate          — calculate a built-in indicator on data
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user
from api.db_store import db_get, db_set

logger = logging.getLogger(__name__)
UTC = timezone.utc

router = APIRouter(prefix="/api/indicators", tags=["Custom Indicators"])

_INDICATORS_KEY = "custom_indicators:{uid}"

# ── Models ────────────────────────────────────────────────────────────────────


class IndicatorCreate(BaseModel):
    name: str
    type: str  # 'sma' | 'ema' | 'rsi' | 'macd' | 'bollinger' | 'custom_pine'
    params: dict = {}
    description: str = ""
    color: str = "#3b82f6"
    visible: bool = True


class IndicatorUpdate(BaseModel):
    name: str | None = None
    params: dict | None = None
    description: str | None = None
    color: str | None = None
    visible: bool | None = None


class CalculateRequest(BaseModel):
    indicator_type: str
    params: dict = {}
    data: list[float]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_indicators(user_id: str) -> list[dict]:
    stored = db_get(_INDICATORS_KEY.format(uid=user_id))
    if stored and isinstance(stored, list):
        return stored
    return []


def _save_indicators(user_id: str, indicators: list[dict]) -> None:
    db_set(_INDICATORS_KEY.format(uid=user_id), indicators)


# ── Built-in indicator catalogue ──────────────────────────────────────────────

_BUILTIN_INDICATORS = [
    {"type": "sma", "name": "Simple Moving Average", "params": [{"key": "period", "default": 14, "min": 2, "max": 500}]},
    {"type": "ema", "name": "Exponential Moving Average", "params": [{"key": "period", "default": 14, "min": 2, "max": 500}]},
    {"type": "wma", "name": "Weighted Moving Average", "params": [{"key": "period", "default": 14, "min": 2, "max": 500}]},
    {"type": "rsi", "name": "Relative Strength Index", "params": [{"key": "period", "default": 14, "min": 2, "max": 100}]},
    {"type": "macd", "name": "MACD", "params": [
        {"key": "fast", "default": 12}, {"key": "slow", "default": 26}, {"key": "signal", "default": 9}
    ]},
    {"type": "bollinger", "name": "Bollinger Bands", "params": [
        {"key": "period", "default": 20}, {"key": "std_dev", "default": 2.0}
    ]},
    {"type": "atr", "name": "Average True Range", "params": [{"key": "period", "default": 14}]},
    {"type": "stochastic", "name": "Stochastic Oscillator", "params": [
        {"key": "k_period", "default": 14}, {"key": "d_period", "default": 3}
    ]},
    {"type": "adx", "name": "Average Directional Index", "params": [{"key": "period", "default": 14}]},
    {"type": "cci", "name": "Commodity Channel Index", "params": [{"key": "period", "default": 20}]},
    {"type": "obv", "name": "On-Balance Volume", "params": []},
    {"type": "vwap", "name": "Volume Weighted Average Price", "params": []},
    {"type": "ichimoku", "name": "Ichimoku Cloud", "params": [
        {"key": "tenkan", "default": 9}, {"key": "kijun", "default": 26}, {"key": "senkou_b", "default": 52}
    ]},
    {"type": "williams_r", "name": "Williams %R", "params": [{"key": "period", "default": 14}]},
    {"type": "mfi", "name": "Money Flow Index", "params": [{"key": "period", "default": 14}]},
]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="List user's custom indicators")
async def list_indicators(user: TokenPayload = Depends(get_current_user)) -> dict:
    indicators = _load_indicators(user.sub)
    return {"indicators": indicators, "total": len(indicators)}


@router.post("", summary="Create a custom indicator")
async def create_indicator(
    body: IndicatorCreate,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    indicators = _load_indicators(user.sub)
    new_indicator = {
        "indicator_id": f"ind_{uuid.uuid4().hex[:8]}",
        "name": body.name,
        "type": body.type,
        "params": body.params,
        "description": body.description,
        "color": body.color,
        "visible": body.visible,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    indicators.append(new_indicator)
    _save_indicators(user.sub, indicators)
    return new_indicator


@router.get("/builtin", summary="List all built-in indicators")
async def list_builtin_indicators() -> dict:
    return {"indicators": _BUILTIN_INDICATORS, "total": len(_BUILTIN_INDICATORS)}


@router.post("/calculate", summary="Calculate a built-in indicator on provided data")
async def calculate_indicator(body: CalculateRequest) -> dict:
    """Apply a built-in indicator to a data series and return the result."""
    try:
        from charting.indicators import SMA, EMA, WMA, RSI, MACD, BollingerBands, ATR, StochasticOscillator, ADX, CCI, OBV, VWAP, WilliamsR, MFI

        ind_type = body.indicator_type.lower()
        data = body.data
        params = body.params

        if ind_type == "sma":
            result = SMA(period=int(params.get("period", 14))).calculate(data)
        elif ind_type == "ema":
            result = EMA(period=int(params.get("period", 14))).calculate(data)
        elif ind_type == "wma":
            result = WMA(period=int(params.get("period", 14))).calculate(data)
        elif ind_type == "rsi":
            result = RSI(period=int(params.get("period", 14))).calculate(data)
        elif ind_type == "macd":
            macd = MACD(
                fast=int(params.get("fast", 12)),
                slow=int(params.get("slow", 26)),
                signal=int(params.get("signal", 9)),
            )
            r = macd.calculate(data)
            return {"type": ind_type, "result": r if isinstance(r, dict) else {"values": r}}
        elif ind_type == "bollinger":
            bb = BollingerBands(period=int(params.get("period", 20)), std_dev=float(params.get("std_dev", 2.0)))
            r = bb.calculate(data)
            return {"type": ind_type, "result": r if isinstance(r, dict) else {"values": r}}
        elif ind_type == "cci":
            result = CCI(period=int(params.get("period", 20))).calculate(data)
        elif ind_type == "williams_r":
            result = WilliamsR(period=int(params.get("period", 14))).calculate(data)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown indicator type: {ind_type}")

        return {"type": ind_type, "result": {"values": result}}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("calculate_indicator: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/{indicator_id}", summary="Get a specific custom indicator")
async def get_indicator(
    indicator_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    indicators = _load_indicators(user.sub)
    for ind in indicators:
        if ind.get("indicator_id") == indicator_id:
            return ind
    raise HTTPException(status_code=404, detail="Indicator not found")


@router.patch("/{indicator_id}", summary="Update a custom indicator")
async def update_indicator(
    indicator_id: str,
    body: IndicatorUpdate,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    indicators = _load_indicators(user.sub)
    for ind in indicators:
        if ind.get("indicator_id") == indicator_id:
            if body.name is not None:
                ind["name"] = body.name
            if body.params is not None:
                ind["params"] = body.params
            if body.description is not None:
                ind["description"] = body.description
            if body.color is not None:
                ind["color"] = body.color
            if body.visible is not None:
                ind["visible"] = body.visible
            ind["updated_at"] = datetime.now(UTC).isoformat()
            _save_indicators(user.sub, indicators)
            return ind
    raise HTTPException(status_code=404, detail="Indicator not found")


@router.delete("/{indicator_id}", summary="Delete a custom indicator")
async def delete_indicator(
    indicator_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    indicators = _load_indicators(user.sub)
    updated = [i for i in indicators if i.get("indicator_id") != indicator_id]
    if len(updated) == len(indicators):
        raise HTTPException(status_code=404, detail="Indicator not found")
    _save_indicators(user.sub, updated)
    return {"ok": True, "indicator_id": indicator_id}


@router.post("/{indicator_id}/apply", summary="Apply indicator to a symbol/timeframe")
async def apply_indicator(
    indicator_id: str,
    body: dict,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """
    Apply a saved custom indicator to a symbol/timeframe.
    Fetches recent OHLCV data and returns computed values.
    """
    indicators = _load_indicators(user.sub)
    ind = next((i for i in indicators if i.get("indicator_id") == indicator_id), None)
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")

    symbol = body.get("symbol", "XAUUSD")
    timeframe = body.get("timeframe", "H1")
    limit = int(body.get("limit", 200))

    # Fetch price data from the nuclear streamer / data feed
    closes: list[float] = []
    try:
        from core.app_state import app_state
        nuclear = getattr(app_state, "nuclear_streamer", None)
        if nuclear and hasattr(nuclear, "get_ohlcv"):
            candles = nuclear.get_ohlcv(symbol, timeframe, limit)
            closes = [float(c["close"]) for c in candles if "close" in c]
    except Exception as exc:
        logger.debug("apply_indicator data fetch: %s", exc)

    if not closes:
        return {
            "indicator_id": indicator_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "values": [],
            "note": "No price data available — connect a live data feed",
        }

    # Calculate
    try:
        calc_result = await calculate_indicator(CalculateRequest(
            indicator_type=ind["type"],
            params=ind.get("params", {}),
            data=closes,
        ))
        return {
            "indicator_id": indicator_id,
            "symbol": symbol,
            "timeframe": timeframe,
            **calc_result,
        }
    except Exception as exc:
        logger.warning("apply_indicator calculate: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from None
