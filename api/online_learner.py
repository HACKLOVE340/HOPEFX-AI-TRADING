# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/online_learner.py
=====================
REST endpoints for the SklearnOnlineLearner (ml/online_learner.py).

Endpoints
---------
  GET  /api/online-learner/status
       Return per-symbol learner state: fitted, update_count, last_fit_at,
       accuracy, regime. Lists all registered symbols or filters by ?symbol=.

  POST /api/online-learner/partial-fit
       Trigger an incremental SGD update for a given symbol using the most
       recent N bars of OHLCV data fetched from yfinance.
       Requires admin role.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import get_current_user, require_role, TokenPayload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/online-learner", tags=["Online Learner"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_registry() -> Dict[str, Any]:
    """Return the module-level learner registry from ml.online_learner."""
    try:
        from ml.online_learner import _learner_registry  # noqa: PLC0415

        return _learner_registry
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ml.online_learner unavailable: {exc}",
        )


def _get_learner(symbol: str):
    """Return or create the SklearnOnlineLearner for symbol."""
    try:
        from ml.online_learner import get_online_learner  # noqa: PLC0415

        return get_online_learner(symbol=symbol)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ml.online_learner unavailable: {exc}",
        )


def _fetch_bars(symbol: str, lookback: int = 200):
    """Fetch recent OHLCV bars for symbol via yfinance."""
    try:
        import yfinance as yf  # noqa: PLC0415

        # Map internal symbol names to yfinance tickers
        ticker_map = {
            "XAU_USD": "GC=F",
            "XAUUSD": "GC=F",
            "BTC_USD": "BTC-USD",
            "BTCUSD": "BTC-USD",
            "ETH_USD": "ETH-USD",
            "ETHUSD": "ETH-USD",
            "EUR_USD": "EURUSD=X",
            "EURUSD": "EURUSD=X",
            "GBP_USD": "GBPUSD=X",
            "GBPUSD": "GBPUSD=X",
            "SILVER": "SI=F",
            "XAGUSD": "SI=F",
            "OIL": "CL=F",
            "CRUDE": "CL=F",
        }
        ticker = ticker_map.get(symbol.upper(), symbol)
        df = yf.download(ticker, period="60d", interval="1h", progress=False)
        if df is None or df.empty:
            raise ValueError(f"No data returned for {ticker}")
        df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
        return df.tail(lookback)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch OHLCV for {symbol}: {exc}",
        )


# ── Schemas ───────────────────────────────────────────────────────────────────


class LearnerStatusItem(BaseModel):
    symbol: str
    fitted: bool
    update_count: int
    persist_path: str
    last_fit_at: Optional[str] = None
    accuracy: Optional[float] = None
    regime: Optional[str] = None


class LearnerStatusResponse(BaseModel):
    learners: List[LearnerStatusItem]
    count: int
    checked_at: str


class PartialFitRequest(BaseModel):
    symbol: str = Field("XAU_USD", description="Symbol to update (e.g. XAU_USD, BTC_USD)")
    lookback: int = Field(
        200, ge=50, le=2000, description="Number of recent OHLCV bars to use"
    )


class PartialFitResponse(BaseModel):
    symbol: str
    success: bool
    update_count: int
    fitted: bool
    bars_used: int
    updated_at: str
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=LearnerStatusResponse,
    summary="Online learner status for all registered symbols",
)
async def online_learner_status(
    symbol: Optional[str] = None,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return the current state of all registered SklearnOnlineLearner instances.

    Each entry reports:
    - `fitted`        — whether partial_fit() has been called at least once
    - `update_count`  — number of incremental updates applied
    - `persist_path`  — path to the persisted .pkl file
    - `last_fit_at`   — ISO timestamp of the last partial_fit call (if tracked)
    - `accuracy`      — most recent OOS accuracy estimate (if available)
    - `regime`        — current detected market regime (if available)

    Pass `?symbol=XAU_USD` to filter to a single symbol.
    """
    registry = _get_registry()

    if not registry:
        # No learners registered yet — return empty but valid response
        return LearnerStatusResponse(
            learners=[],
            count=0,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    items: List[LearnerStatusItem] = []
    for sym, learner in registry.items():
        if symbol is not None and sym.upper() != symbol.upper():
            continue
        try:
            raw = learner.status()
        except Exception as exc:
            logger.warning("online_learner_status: status() failed for %s: %s", sym, exc)
            raw = {"symbol": sym, "fitted": False, "update_count": 0, "persist_path": ""}

        items.append(
            LearnerStatusItem(
                symbol=raw.get("symbol", sym),
                fitted=raw.get("fitted", False),
                update_count=raw.get("update_count", 0),
                persist_path=raw.get("persist_path", ""),
                last_fit_at=getattr(learner, "_last_fit_at", None),
                accuracy=getattr(learner, "_last_accuracy", None),
                regime=getattr(learner, "_current_regime", None),
            )
        )

    return LearnerStatusResponse(
        learners=items,
        count=len(items),
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post(
    "/partial-fit",
    response_model=PartialFitResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger incremental SGD update for a symbol",
)
async def partial_fit(
    req: PartialFitRequest,
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Trigger an incremental partial_fit() update for the given symbol.

    Fetches the most recent `lookback` OHLCV bars from yfinance, then calls
    `SklearnOnlineLearner.partial_fit(bars)`. The learner state is persisted
    to disk after a successful update.

    Requires admin role. Runs synchronously — for large lookback values this
    may take a few seconds.
    """
    import asyncio
    import functools

    learner = _get_learner(req.symbol)
    bars = _fetch_bars(req.symbol, lookback=req.lookback)

    loop = asyncio.get_event_loop()
    try:
        success = await loop.run_in_executor(
            None,
            functools.partial(learner.partial_fit, bars),
        )
    except Exception as exc:
        logger.exception("partial_fit failed for %s: %s", req.symbol, exc)
        raise HTTPException(
            status_code=500,
            detail=f"partial_fit raised: {exc}",
        )

    updated_at = datetime.now(timezone.utc).isoformat()
    # Stamp last_fit_at on the learner for status reporting
    learner._last_fit_at = updated_at  # type: ignore[attr-defined]

    raw = learner.status()
    return PartialFitResponse(
        symbol=req.symbol,
        success=bool(success),
        update_count=raw.get("update_count", 0),
        fitted=raw.get("fitted", False),
        bars_used=len(bars),
        updated_at=updated_at,
        message=(
            f"partial_fit completed for {req.symbol} — "
            f"{len(bars)} bars, update #{raw.get('update_count', 0)}"
            if success
            else f"partial_fit returned False for {req.symbol} — check logs"
        ),
    )
