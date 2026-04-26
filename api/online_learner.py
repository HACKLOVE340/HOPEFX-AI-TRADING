# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/online_learner.py
=====================
REST endpoints for both online learner layers:

  Layer A — SklearnOnlineLearner (ml/online_learner.py, SGD-based)
  Layer B — OnlineLearnerStore   (research/pipeline/online_learning.py, XGBoost Phase-3)

Endpoints
---------
  GET  /api/online-learner/status
       Combined status for both layers across all registered symbols.

  POST /api/online-learner/partial-fit
       Trigger an incremental SGD update (Layer A) for a symbol.
       Requires admin role.

  GET  /api/online-learner/diagnostics
       Deep diagnostics: drift counts, blend weights, buffer sizes, EWC lambda,
       circuit-breaker state, and recent error trend for both layers.

  POST /api/online-learner/reset
       Reset the OnlineLearnerStore singleton for a symbol (Layer B).
       Clears accumulated fills and drift counters. Requires admin role.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/online-learner", tags=["Online Learner"])

# Allowlist for symbol names — only alphanumeric and underscore permitted.
# This prevents path-traversal attacks when symbols are used in file paths.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")


def _validate_symbol(symbol: str) -> str:
    """Raise HTTPException 422 if symbol contains path-unsafe characters."""
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid symbol: only alphanumeric characters and underscores are allowed.",
        )
    return symbol


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_registry() -> dict[str, Any]:
    """Return the module-level learner registry from ml.online_learner."""
    try:
        from ml.online_learner import _learner_registry

        return _learner_registry
    except ImportError as exc:
        logger.error("ml.online_learner unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="ml.online_learner unavailable — check server logs",
        ) from None


def _get_learner(symbol: str):
    """Return or create the SklearnOnlineLearner for symbol."""
    try:
        from ml.online_learner import get_online_learner

        return get_online_learner(symbol=symbol)
    except ImportError as exc:
        logger.error("ml.online_learner unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="ml.online_learner unavailable — check server logs",
        ) from None


def _fetch_bars(symbol: str, lookback: int = 200):
    """Fetch recent OHLCV bars for symbol via yfinance."""
    try:
        import yfinance as yf

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
        logger.warning("Could not fetch OHLCV for %s: %s", symbol, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch OHLCV for {symbol} — check server logs",
        ) from None


# ── Schemas ───────────────────────────────────────────────────────────────────


class LearnerStatusItem(BaseModel):
    symbol: str
    fitted: bool
    update_count: int
    persist_path: str
    last_fit_at: str | None = None
    accuracy: float | None = None
    regime: str | None = None


class LearnerStatusResponse(BaseModel):
    learners: list[LearnerStatusItem]
    count: int
    checked_at: str


class PartialFitRequest(BaseModel):
    symbol: str = Field("XAU_USD", description="Symbol to update (e.g. XAU_USD, BTC_USD)")
    lookback: int = Field(200, ge=50, le=2000, description="Number of recent OHLCV bars to use")


class PartialFitResponse(BaseModel):
    symbol: str
    success: bool
    update_count: int
    fitted: bool
    bars_used: int
    updated_at: str
    message: str


class Phase3StatusItem(BaseModel):
    symbol: str
    ready: bool
    fill_count: int
    ph_drift_count: int
    adwin_drift_count: int
    recent_error: float | None = None
    primary_weight: float
    online_weight: float
    adaptive_weights: bool
    adwin_window: int


class DiagnosticsResponse(BaseModel):
    checked_at: str
    sklearn_layer: list[LearnerStatusItem]
    phase3_layer: list[Phase3StatusItem]


class ResetRequest(BaseModel):
    symbol: str = Field("XAUUSD", description="Symbol whose Phase-3 store to reset")


class ResetResponse(BaseModel):
    symbol: str
    reset: bool
    message: str
    reset_at: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


def _get_phase3_items(symbol: str | None = None) -> list[Phase3StatusItem]:
    """Collect Phase-3 OnlineLearnerStore status for all registered symbols."""
    items: list[Phase3StatusItem] = []
    try:
        from research.pipeline.online_learning import list_online_learners

        stores = list_online_learners()
        for sym, snap in stores.items():
            if symbol is not None and sym.upper() != symbol.upper():
                continue
            items.append(
                Phase3StatusItem(
                    symbol=sym,
                    ready=snap.get("ready", False),
                    fill_count=snap.get("fill_count", 0),
                    ph_drift_count=snap.get("ph_drift_count", 0),
                    adwin_drift_count=snap.get("adwin_drift_count", 0),
                    recent_error=snap.get("recent_error"),
                    primary_weight=snap.get("primary_weight", 0.7),
                    online_weight=snap.get("online_weight", 0.3),
                    adaptive_weights=snap.get("adaptive_weights", True),
                    adwin_window=snap.get("adwin_window", 0),
                )
            )
    except Exception as exc:
        logger.debug("_get_phase3_items failed: %s", exc)
    return items


@router.get(
    "/status",
    response_model=LearnerStatusResponse,
    summary="Online learner status for all registered symbols",
)
async def online_learner_status(
    symbol: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return the current state of all registered SklearnOnlineLearner instances
    (Layer A — SGD) and Phase-3 OnlineLearnerStore instances (Layer B — XGBoost).

    Each sklearn entry reports: fitted, update_count, persist_path, last_fit_at,
    accuracy, regime.

    Pass ``?symbol=XAU_USD`` to filter to a single symbol.
    """
    registry = _get_registry()

    items: list[LearnerStatusItem] = []
    for sym, learner in registry.items():
        if symbol is not None and sym.upper() != symbol.upper():
            continue
        try:
            raw = learner.status()
        except Exception as exc:
            logger.warning("online_learner_status: status() failed for %s: %s", sym, exc)
            raw = {
                "symbol": sym,
                "fitted": False,
                "update_count": 0,
                "persist_path": "",
            }

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
        checked_at=datetime.now(UTC).isoformat(),
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

    symbol = _validate_symbol(req.symbol)
    learner = _get_learner(symbol)
    bars = _fetch_bars(symbol, lookback=req.lookback)

    loop = asyncio.get_running_loop()
    try:
        success = await loop.run_in_executor(
            None,
            functools.partial(learner.partial_fit, bars),
        )
    except Exception:
        logger.exception("partial_fit failed for %s", req.symbol)
        raise HTTPException(
            status_code=500,
            detail="Online learning update failed — check server logs",
        ) from None

    updated_at = datetime.now(UTC).isoformat()
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
            f"partial_fit completed for {req.symbol} — {len(bars)} bars, update #{raw.get('update_count', 0)}"
            if success
            else f"partial_fit returned False for {req.symbol} — check logs"
        ),
    )


@router.get(
    "/diagnostics",
    response_model=DiagnosticsResponse,
    summary="Deep diagnostics for both online learner layers",
)
async def online_learner_diagnostics(
    symbol: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return deep diagnostics for both online learner layers.

    **Layer A (sklearn SGD)** — per-symbol: fitted, update_count, accuracy,
    persist_path, last_fit_at, regime.

    **Layer B (Phase-3 XGBoost)** — per-symbol: ready, fill_count,
    Page-Hinkley drift count, ADWIN drift count, recent prediction error,
    primary/online blend weights, adaptive_weights flag, ADWIN window size.

    Pass ``?symbol=XAUUSD`` to filter to a single symbol.
    """
    # Layer A — sklearn
    registry = _get_registry()
    sklearn_items: list[LearnerStatusItem] = []
    for sym, learner in registry.items():
        if symbol is not None and sym.upper() != symbol.upper():
            continue
        try:
            raw = learner.status()
        except Exception as exc:
            logger.warning("diagnostics: sklearn status() failed for %s: %s", sym, exc)
            raw = {
                "symbol": sym,
                "fitted": False,
                "update_count": 0,
                "persist_path": "",
            }
        sklearn_items.append(
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

    # Layer B — Phase-3 XGBoost
    phase3_items = _get_phase3_items(symbol=symbol)

    return DiagnosticsResponse(
        checked_at=datetime.now(UTC).isoformat(),
        sklearn_layer=sklearn_items,
        phase3_layer=phase3_items,
    )


@router.post(
    "/reset",
    response_model=ResetResponse,
    summary="Reset the Phase-3 OnlineLearnerStore for a symbol",
)
async def reset_online_learner(
    req: ResetRequest,
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Remove the Phase-3 ``OnlineLearnerStore`` singleton for *symbol* from the
    registry.  The next inference call will create a fresh instance, discarding
    all accumulated fills, drift counters, and blend-weight history.

    Use this after a major model retrain to prevent stale online weights from
    contaminating the new primary model's blend.

    Requires admin role.
    """
    reset_at = datetime.now(UTC).isoformat()
    symbol = _validate_symbol(req.symbol)
    try:
        from research.pipeline.online_learning import reset_online_learner as _reset

        removed = _reset(symbol=symbol)
    except Exception as exc:
        logger.error("reset_online_learner failed for %s: %s", symbol, type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Online learner reset failed — check server logs",
        ) from None

    msg = (
        f"OnlineLearnerStore for {symbol.upper()} removed from registry — "
        "fresh instance will be created on next inference call."
        if removed
        else f"No OnlineLearnerStore found for {symbol.upper()} — nothing to reset."
    )
    logger.info("online_learner reset: symbol=%s removed=%s", symbol.upper(), removed)
    return ResetResponse(
        symbol=symbol.upper(),
        reset=removed,
        message=msg,
        reset_at=reset_at,
    )
