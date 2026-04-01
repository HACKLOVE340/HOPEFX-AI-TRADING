# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/quant_analytics.py
========================
REST API endpoints for quantitative analytics modules:
  - HRP / Black-Litterman portfolio construction
  - Deflated Sharpe / PSR
  - Alpha decay / IC analysis
  - Realized volatility / HAR-RV
  - DCC-GARCH correlation
  - Kalman filter hedge ratio
  - Strategy capacity
  - EVT tail risk
  - CPCV cross-validation
  - Cross-asset signals
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quant", tags=["Quantitative Analytics"])


# ── HRP ───────────────────────────────────────────────────────────────────────

class HRPRequest(BaseModel):
    returns: dict[str, list[float]]
    """Asset name → list of daily returns."""
    linkage_method: str = "single"
    frequency: int = 252


@router.post("/hrp/optimise")
async def hrp_optimise(request: HRPRequest) -> dict[str, Any]:
    """Compute HRP portfolio weights."""
    try:
        from portfolio.hrp import HRP  # noqa: PLC0415
        ret_df = pd.DataFrame(request.returns)
        if ret_df.empty or len(ret_df) < 5:
            raise HTTPException(status_code=400, detail="Insufficient return data")
        hrp = HRP(linkage_method=request.linkage_method, frequency=request.frequency)
        result = hrp.fit(ret_df)
        return {
            "weights": result.weights,
            "cluster_order": result.cluster_order,
            "diversification_ratio": result.diversification_ratio,
            "portfolio_vol_annualised": result.portfolio_vol,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("HRP optimise error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Black-Litterman ───────────────────────────────────────────────────────────

class BLRequest(BaseModel):
    returns: dict[str, list[float]]
    market_caps: dict[str, float] | None = None
    views: list[dict[str, Any]] | None = None
    risk_aversion: float = 2.5
    tau: float = 0.05


@router.post("/black-litterman/optimise")
async def black_litterman_optimise(request: BLRequest) -> dict[str, Any]:
    """Compute Black-Litterman posterior and optimal weights."""
    try:
        from portfolio.black_litterman import BlackLitterman  # noqa: PLC0415
        ret_df = pd.DataFrame(request.returns)
        mc = pd.Series(request.market_caps) if request.market_caps else None
        bl = BlackLitterman(risk_aversion=request.risk_aversion, tau=request.tau)
        result = bl.fit(ret_df, market_caps=mc, views=request.views)
        return {
            "weights": result.weights,
            "bl_returns": result.bl_returns,
            "assets": result.assets,
        }
    except Exception as exc:
        logger.error("Black-Litterman error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Deflated Sharpe ───────────────────────────────────────────────────────────

class DSRRequest(BaseModel):
    returns_list: list[list[float]]
    """List of return arrays — one per strategy tested."""
    frequency: int = 252
    sr_benchmark: float = 0.0


@router.post("/deflated-sharpe")
async def deflated_sharpe(request: DSRRequest) -> dict[str, Any]:
    """Compute Deflated Sharpe Ratio and PSR."""
    try:
        from ml.deflated_sharpe import deflated_sharpe_ratio  # noqa: PLC0415
        if not request.returns_list:
            raise HTTPException(status_code=400, detail="returns_list is empty")
        result = deflated_sharpe_ratio(
            [np.array(r) for r in request.returns_list],
            frequency=request.frequency,
            sr_benchmark=request.sr_benchmark,
        )
        return {
            "sharpe_ratio": result.sharpe_ratio,
            "psr": result.psr,
            "dsr": result.dsr,
            "skewness": result.skewness,
            "kurtosis": result.kurtosis,
            "n_observations": result.n_observations,
            "n_trials": result.n_trials,
            "sr_benchmark_adjusted": result.sr_benchmark,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Realized Vol / HAR-RV ─────────────────────────────────────────────────────

class HARRVRequest(BaseModel):
    ohlcv: dict[str, list[float]] | None = None
    """Dict with 'open','high','low','close' arrays."""
    rv_series: list[float] | None = None
    """Pre-computed daily RV series."""
    method: str = "parkinson"


@router.post("/realized-vol/har-rv")
async def har_rv_forecast(request: HARRVRequest) -> dict[str, Any]:
    """Fit HAR-RV model and return forecasts."""
    try:
        from ml.realized_vol import HARV, daily_rv_from_ohlcv  # noqa: PLC0415
        if request.rv_series:
            rv = pd.Series(request.rv_series, dtype=float)
        elif request.ohlcv:
            df = pd.DataFrame(request.ohlcv)
            rv = daily_rv_from_ohlcv(df, method=request.method)
        else:
            raise HTTPException(status_code=400, detail="Provide ohlcv or rv_series")
        harv = HARV()
        result = harv.fit(rv)
        return {
            "forecast_1d": result.forecast_1d,
            "forecast_5d": result.forecast_5d,
            "forecast_22d": result.forecast_22d,
            "r_squared": result.r_squared,
            "model_coeffs": result.model_coeffs,
            "n_observations": result.n_observations,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── EVT Tail Risk ─────────────────────────────────────────────────────────────

class EVTRequest(BaseModel):
    returns: list[float]
    threshold_quantile: float = 0.90


@router.post("/evt/tail-risk")
async def evt_tail_risk(request: EVTRequest) -> dict[str, Any]:
    """Compute EVT/GPD tail risk metrics."""
    try:
        from risk.evt import EVTRiskModel  # noqa: PLC0415
        model = EVTRiskModel(threshold_quantile=request.threshold_quantile)
        result = model.fit(np.array(request.returns))
        return {
            "var_99": result.var_99,
            "var_999": result.var_999,
            "es_99": result.es_99,
            "es_999": result.es_999,
            "threshold": result.threshold,
            "gpd_xi": result.gpd_xi,
            "gpd_sigma": result.gpd_sigma,
            "n_exceedances": result.n_exceedances,
            "n_total": result.n_total,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Capacity Analysis ─────────────────────────────────────────────────────────

class CapacityRequest(BaseModel):
    returns: list[float]
    avg_daily_volume_usd: float
    turnover_per_year: float = 50.0


@router.post("/capacity/estimate")
async def capacity_estimate(request: CapacityRequest) -> dict[str, Any]:
    """Estimate strategy capacity."""
    try:
        from ml.capacity import CapacityAnalyzer  # noqa: PLC0415
        analyzer = CapacityAnalyzer()
        result = analyzer.estimate(
            pd.Series(request.returns),
            avg_daily_volume_usd=request.avg_daily_volume_usd,
            turnover_per_year=request.turnover_per_year,
        )
        return {
            "gross_alpha_bps": result.gross_alpha_bps,
            "breakeven_aum_usd": result.breakeven_aum_usd,
            "optimal_aum_usd": result.optimal_aum_usd,
            "optimal_dollar_profit": result.optimal_dollar_profit,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Model Monitor ─────────────────────────────────────────────────────────────

@router.get("/model-monitor/health")
async def model_monitor_health() -> dict[str, Any]:
    """Return live model monitoring status."""
    try:
        from ml.model_monitor import model_monitor  # noqa: PLC0415
        return model_monitor.health()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Universe ──────────────────────────────────────────────────────────────────

@router.get("/universe/snapshot")
async def universe_snapshot() -> dict[str, Any]:
    """Return current trading universe."""
    try:
        from core.universe import universe_engine  # noqa: PLC0415
        return universe_engine.snapshot()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── VPIN ──────────────────────────────────────────────────────────────────────

@router.get("/vpin/features")
async def vpin_features() -> dict[str, Any]:
    """Return current VPIN ML features."""
    try:
        from data_layer.microstructure.vpin import vpin_calculator  # noqa: PLC0415
        return vpin_calculator.get_ml_features()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Crowding ──────────────────────────────────────────────────────────────────

@router.get("/crowding/health")
async def crowding_health() -> dict[str, Any]:
    """Return strategy crowding risk status."""
    try:
        from risk.crowding import crowding_monitor  # noqa: PLC0415
        return crowding_monitor.health()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Feature Store ─────────────────────────────────────────────────────────────

@router.get("/feature-store/health")
async def feature_store_health() -> dict[str, Any]:
    """Return feature store health."""
    try:
        from data_layer.feature_store import feature_store  # noqa: PLC0415
        return feature_store.health()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── LaVaR ─────────────────────────────────────────────────────────────────────

class LaVaRRequest(BaseModel):
    returns: list[float]
    position_value: float
    avg_spread_pct: float = 0.0002
    avg_daily_volume_usd: float | None = None
    liquidation_horizon: int | None = None
    confidence: float = 0.99


@router.post("/lavar")
async def liquidity_adjusted_var(request: LaVaRRequest) -> dict[str, Any]:
    """Compute Liquidity-Adjusted VaR."""
    try:
        from risk.liquidity_var import LiquidityAdjustedVaR  # noqa: PLC0415
        model = LiquidityAdjustedVaR(confidence=request.confidence)
        result = model.calculate(
            np.array(request.returns),
            position_value=request.position_value,
            avg_spread_pct=request.avg_spread_pct,
            avg_daily_volume_usd=request.avg_daily_volume_usd,
            liquidation_horizon=request.liquidation_horizon,
        )
        return {
            "lavar": result.lavar,
            "var_market": result.var_market,
            "liquidity_cost": result.liquidity_cost,
            "liquidation_horizon": result.liquidation_horizon,
            "confidence": result.confidence,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
