# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/portfolio.py
================
REST endpoints for the three new institutional-grade portfolio components:

  Factor Model  — live Barra/PCA factor attribution
  Rebalancer    — dynamic mean-variance / risk-parity portfolio optimisation
  Tick Feed     — real-time tick ingestion status and last-tick snapshot

Routes
------
GET  /api/portfolio/factor/status          — LiveFactorEngine status
GET  /api/portfolio/factor/exposures       — per-symbol beta loadings
POST /api/portfolio/factor/attribute       — attribute P&L to factors
GET  /api/portfolio/factor/var             — factor-level VaR contributions

GET  /api/portfolio/rebalancer/status      — DynamicRebalancer status
GET  /api/portfolio/rebalancer/weights     — current target weights
POST /api/portfolio/rebalancer/rebalance   — trigger a rebalance (force optional)
POST /api/portfolio/rebalancer/returns     — feed a strategy return series

GET  /api/portfolio/tick-feed/status       — TickFeedManager status
GET  /api/portfolio/tick-feed/last-tick    — latest validated tick per symbol
GET  /api/portfolio/tick-feed/execution    — execution engine tick cache status

GET  /api/portfolio/risk/factor-report     — combined factor risk report
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])


# ── helpers ───────────────────────────────────────────────────────────────────


def _get_app_state() -> Any:
    try:
        from core.app_state import app_state

        return app_state
    except ImportError:
        return None


def _get_factor_engine() -> Any:
    s = _get_app_state()
    if s is not None:
        engine = getattr(s, "factor_engine", None)
        if engine is not None:
            return engine
    try:
        from portfolio.factor_model import get_live_factor_engine

        return get_live_factor_engine()
    except Exception as exc:  # nosec B110 — graceful fallback when module unavailable
        logger.debug("_get_factor_engine unavailable: %s", exc)
        return None


def _get_rebalancer() -> Any:
    s = _get_app_state()
    if s is not None:
        rb = getattr(s, "rebalancer", None)
        if rb is not None:
            return rb
    try:
        from portfolio.rebalancer import get_rebalancer

        return get_rebalancer()
    except Exception as exc:  # nosec B110 — graceful fallback when module unavailable
        logger.debug("_get_rebalancer unavailable: %s", exc)
        return None


def _get_tick_feed() -> Any:
    s = _get_app_state()
    if s is not None:
        tf = getattr(s, "tick_feed", None)
        if tf is not None:
            return tf
    try:
        from data.tick_feed import get_tick_feed

        return get_tick_feed()
    except Exception as exc:  # nosec B110 — graceful fallback when module unavailable
        logger.debug("_get_tick_feed unavailable: %s", exc)
        return None


def _get_execution_engine() -> Any:
    s = _get_app_state()
    return getattr(s, "execution_engine", None) if s else None


# ── Pydantic models ───────────────────────────────────────────────────────────


class AttributeRequest(BaseModel):
    positions: dict[str, float] = Field(
        ...,
        description="Symbol -> dollar value (positive=long, negative=short)",
        json_schema_extra={"example": {"XAU_USD": 50000.0, "BTC_USD": -10000.0}},
    )
    total_pnl: float = Field(
        default=0.0,
        description="Total P&L for the period being attributed",
    )


class FactorVarRequest(BaseModel):
    positions: dict[str, float] = Field(
        ...,
        description="Symbol -> dollar value",
    )


class RebalanceRequest(BaseModel):
    force: bool = Field(
        default=False,
        description="Force rebalance even if scheduler says no trigger",
    )


class FeedReturnsRequest(BaseModel):
    strategy_id: str = Field(..., description="Strategy identifier")
    returns: list[float] = Field(
        ...,
        description="Daily return series (most recent last)",
        min_length=5,
    )
    drawdown: float = Field(
        default=0.0,
        description="Current drawdown fraction (0.0–1.0)",
        ge=0.0,
        le=1.0,
    )


# ── Factor Model routes ───────────────────────────────────────────────────────


@router.get(
    "/factor/status",
    summary="LiveFactorEngine status",
    response_model=dict[str, Any],
)
async def factor_status(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return LiveFactorEngine running status and last fit timestamp."""
    engine = _get_factor_engine()
    if engine is None:
        return {"available": False, "reason": "factor_engine_not_started"}
    return {"available": True, **engine.status()}


@router.get(
    "/factor/exposures",
    summary="Per-symbol factor beta loadings",
    response_model=dict[str, Any],
)
async def factor_exposures(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return Ridge regression beta loadings for each tracked symbol."""
    engine = _get_factor_engine()
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Factor engine not available",
        )
    exposures = engine.exposures
    if not exposures:
        return {"exposures": {}, "note": "No symbols fitted yet — engine may still be warming up"}
    return {
        "exposures": {sym: exp.to_dict() for sym, exp in exposures.items()},
        "factor_names": next(iter(exposures.values())).betas.keys() if exposures else [],
    }


@router.post(
    "/factor/attribute",
    summary="Attribute portfolio P&L to systematic factors",
    response_model=dict[str, Any],
)
async def factor_attribute(
    body: AttributeRequest,
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Decompose total_pnl into factor contributions (rates, vol, momentum,
    carry, macro, DXY) plus residual idiosyncratic alpha.
    """
    engine = _get_factor_engine()
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Factor engine not available",
        )
    attribution = engine.attribute(body.positions, body.total_pnl)
    return attribution.to_dict()


@router.post(
    "/factor/var",
    summary="Factor-level VaR contributions",
    response_model=dict[str, Any],
)
async def factor_var(
    body: FactorVarRequest,
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return annualised 95% VaR contribution of each systematic factor
    for the given portfolio positions.
    """
    engine = _get_factor_engine()
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Factor engine not available",
        )
    var_contribs = engine.factor_var(body.positions)
    return {
        "factor_var_95": {k: round(v, 2) for k, v in var_contribs.items()},
        "total_factor_var": round(sum(var_contribs.values()), 2),
    }


# ── Rebalancer routes ─────────────────────────────────────────────────────────


@router.get(
    "/rebalancer/status",
    summary="DynamicRebalancer status",
    response_model=dict[str, Any],
)
async def rebalancer_status(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return rebalancer method, current weights, and last rebalance timestamp."""
    rb = _get_rebalancer()
    if rb is None:
        return {"available": False, "reason": "rebalancer_not_initialised"}
    return {"available": True, **rb.status()}


@router.get(
    "/rebalancer/weights",
    summary="Current target weights",
    response_model=dict[str, Any],
)
async def rebalancer_weights(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the current target allocation weights across all strategies."""
    rb = _get_rebalancer()
    if rb is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rebalancer not initialised",
        )
    weights = rb.current_weights
    last = rb.last_result
    return {
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "last_rebalance": last.to_dict() if last else None,
    }


@router.post(
    "/rebalancer/rebalance",
    summary="Trigger a portfolio rebalance",
    response_model=dict[str, Any],
)
async def trigger_rebalance(
    body: RebalanceRequest,
    _user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Trigger a rebalance check.  Returns the RebalanceResult if a rebalance
    was executed, or a ``skipped`` response if the scheduler blocked it.

    Requires admin role.  Use ``force=true`` to bypass the scheduler.
    """
    rb = _get_rebalancer()
    if rb is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rebalancer not initialised",
        )
    result = await rb.rebalance_async(force=body.force)
    if result is None:
        return {
            "rebalanced": False,
            "reason": "scheduler_blocked — use force=true to override",
        }
    return {"rebalanced": True, **result.to_dict()}


@router.post(
    "/rebalancer/returns",
    summary="Feed a strategy return series into the rebalancer",
    response_model=dict[str, Any],
)
async def feed_returns(
    body: FeedReturnsRequest,
    _user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Feed a daily return series for a strategy into the rebalancer's
    CorrelationTracker.  Also updates the strategy's current drawdown.

    Requires admin role.
    """
    rb = _get_rebalancer()
    if rb is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rebalancer not initialised",
        )
    import pandas as pd

    returns_series = pd.Series(body.returns)
    rb.update_strategy_returns(body.strategy_id, returns_series)
    rb.update_drawdown(body.strategy_id, body.drawdown)
    return {
        "accepted": True,
        "strategy_id": body.strategy_id,
        "n_returns": len(body.returns),
        "drawdown": body.drawdown,
    }


# ── Tick Feed routes ──────────────────────────────────────────────────────────


@router.get(
    "/tick-feed/status",
    summary="TickFeedManager status",
    response_model=dict[str, Any],
)
async def tick_feed_status(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return tick feed running status, source health, and tick counts."""
    tf = _get_tick_feed()
    if tf is None:
        return {"available": False, "reason": "tick_feed_not_started"}
    return {"available": True, **tf.status()}


@router.get(
    "/tick-feed/last-tick",
    summary="Latest validated tick",
    response_model=dict[str, Any],
)
async def tick_feed_last_tick(
    symbol: str = Query(default="XAU_USD", description="Symbol to query"),
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the most recent validated tick for the given symbol."""
    tf = _get_tick_feed()
    if tf is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tick feed not started",
        )
    tick = tf.last_tick
    if tick is None:
        return {"symbol": symbol, "tick": None, "note": "No ticks received yet"}
    return {"symbol": symbol, "tick": tick.to_dict()}


@router.get(
    "/tick-feed/execution",
    summary="Execution engine tick cache status",
    response_model=dict[str, Any],
)
async def tick_feed_execution_status(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the execution engine's last-tick cache (used for MARKET order pricing)."""
    ee = _get_execution_engine()
    if ee is None:
        return {"available": False, "reason": "execution_engine_not_initialised"}
    if not hasattr(ee, "get_tick_feed_status"):
        return {"available": False, "reason": "execution_engine_does_not_support_tick_feed"}
    return {"available": True, **ee.get_tick_feed_status()}


# ── Combined factor risk report ───────────────────────────────────────────────


@router.get(
    "/risk/factor-report",
    summary="Combined factor risk report",
    response_model=dict[str, Any],
)
async def factor_risk_report(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return a combined factor risk report for the current portfolio.

    Includes:
    - Factor attribution of today's P&L
    - Factor-level VaR contributions
    - Per-symbol beta loadings
    - Rebalancer current weights
    - Tick feed status
    """
    s = _get_app_state()

    # Gather positions from portfolio manager or broker
    positions: dict[str, float] = {}
    total_pnl = 0.0
    try:
        pms = getattr(s, "portfolio_manager", None) if s else None
        if pms is not None:
            summary = pms.get_portfolio_summary()
            for sym, pos_data in summary.get("positions", {}).items():
                positions[sym] = float(pos_data.get("market_value", 0.0))
            total_pnl = float(summary.get("total_pnl", 0.0))
        elif s is not None:
            broker = getattr(s, "broker", None)
            if broker is not None and hasattr(broker, "get_positions"):
                for p in await broker.get_positions():
                    sym = getattr(p, "symbol", "")
                    if sym:
                        positions[sym] = float(getattr(p, "market_value", 0.0))
    except Exception as exc:
        logger.debug("factor_risk_report: position fetch failed: %s", exc)

    # Factor attribution
    factor_section: dict[str, Any] = {"available": False}
    engine = _get_factor_engine()
    if engine is not None:
        try:
            attribution = engine.attribute(positions, total_pnl)
            factor_var = engine.factor_var(positions)
            factor_section = {
                "available": True,
                "attribution": attribution.to_dict(),
                "factor_var": {k: round(v, 2) for k, v in factor_var.items()},
                "engine_status": engine.status(),
            }
        except Exception as exc:
            logger.warning("factor analysis unavailable: %s", exc)
            factor_section = {"available": False, "error": "Factor analysis unavailable — check server logs"}

    # Rebalancer weights
    rebalancer_section: dict[str, Any] = {"available": False}
    rb = _get_rebalancer()
    if rb is not None:
        rebalancer_section = {"available": True, **rb.status()}

    # Tick feed
    tick_section: dict[str, Any] = {"available": False}
    tf = _get_tick_feed()
    if tf is not None:
        tick_section = {"available": True, **tf.status()}

    return {
        "positions": positions,
        "total_pnl": total_pnl,
        "factor": factor_section,
        "rebalancer": rebalancer_section,
        "tick_feed": tick_section,
    }
