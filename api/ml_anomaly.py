# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/ml_anomaly.py
=================
HTTP endpoints for the anomaly detection subsystem.

Backed by ``research.pipeline.anomaly.AnomalyWeighter`` (batch fit/score) and
``research.pipeline.anomaly.AnomalyWeightStore`` (live rolling inference).

Routes
------
GET  /api/ml/anomaly/status          — detector status + diagnostics
GET  /api/ml/anomaly/config          — current detector configuration
POST /api/ml/anomaly/fit             — fit detector on OHLCV data for a symbol
POST /api/ml/anomaly/score           — score a batch of OHLCV rows
POST /api/ml/anomaly/flag            — flag anomalous bars (boolean mask)
GET  /api/ml/anomaly/report/{symbol} — top-N most anomalous bars for a symbol
POST /api/ml/anomaly/retrain         — background refit on latest market data (admin)
DELETE /api/ml/anomaly/reset         — reset the live store (admin)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user, require_role

UTC = timezone.utc
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml/anomaly", tags=["Anomaly Detection"])

# Persisted model path — shared between the API and the signal engine
_ANOMALY_MODEL_PATH = Path(
    os.getenv("ANOMALY_MODEL_PATH", "ml/saved_models/anomaly_weighter.pkl")
)

# ── Singleton live store ──────────────────────────────────────────────────────
# One AnomalyWeightStore per process, shared across requests.
_live_store: Any = None
_live_store_lock = asyncio.Lock()


def _get_live_store() -> Any:
    """Return the module-level AnomalyWeightStore singleton, creating it if needed."""
    global _live_store
    if _live_store is None:
        try:
            from research.pipeline.anomaly import AnomalyWeightStore

            _live_store = AnomalyWeightStore(
                window_size=int(os.getenv("ANOMALY_WINDOW_SIZE", "500")),
                refit_every=int(os.getenv("ANOMALY_REFIT_EVERY", "50")),
                contamination=float(os.getenv("ANOMALY_CONTAMINATION", "0.02")),
                anomaly_threshold=float(os.getenv("ANOMALY_THRESHOLD", "-0.05")),
                down_weight_factor=float(os.getenv("ANOMALY_DOWN_WEIGHT", "0.5")),
                use_lof=os.getenv("ANOMALY_USE_LOF", "true").lower() == "true",
                persist_path=str(_ANOMALY_MODEL_PATH) if _ANOMALY_MODEL_PATH else None,
            )
            logger.info("AnomalyWeightStore singleton created (persist=%s)", _ANOMALY_MODEL_PATH)
        except Exception as exc:
            logger.error("Failed to create AnomalyWeightStore: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Anomaly detection subsystem unavailable: {exc}",
            ) from exc
    return _live_store


def _load_ohlcv(symbol: str, lookback: int = 500) -> Any:
    """Load OHLCV data for a symbol from the market data layer."""

    # Try the inference engine's data loader first (uses the same pipeline as live trading)
    try:
        from ml.inference_engine import get_inference_engine

        engine = get_inference_engine()
        df = engine.load_ohlcv(symbol, lookback=lookback)
        if df is not None and len(df) >= 50:
            return df
    except Exception as exc:
        logger.debug("InferenceEngine OHLCV load failed for %s: %s", symbol, exc)

    # Fallback: yfinance
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y", interval="1d")
        if df.empty:
            raise ValueError(f"yfinance returned empty data for {symbol}")
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        return df.tail(lookback)
    except Exception as exc:
        logger.debug("yfinance OHLCV load failed for %s: %s", symbol, exc)

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"No OHLCV data available for {symbol}. Ensure market data feed is running.",
    )


# ── Request / Response models ─────────────────────────────────────────────────


class AnomalyStatusResponse(BaseModel):
    fitted: bool
    buffer_size: int
    bars_since_refit: int
    anomaly_count: int
    total_scored: int
    anomaly_rate: float
    use_lof: bool
    down_weight_factor: float
    model_path: str | None
    model_exists: bool
    checked_at: str


class AnomalyConfigResponse(BaseModel):
    window_size: int
    refit_every: int
    contamination: float
    anomaly_threshold: float
    down_weight_factor: float
    use_lof: bool
    persist_path: str | None


class FitRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol, e.g. XAUUSD")
    lookback: int = Field(500, ge=50, le=5000, description="Number of OHLCV bars to fit on")
    contamination: float = Field(0.02, ge=0.001, le=0.5, description="Expected anomaly fraction")
    use_lof: bool = Field(True, description="Include Local Outlier Factor in ensemble")
    save: bool = Field(True, description="Persist fitted model to disk")


class FitResponse(BaseModel):
    symbol: str
    bars_fitted: int
    anomaly_count: int
    anomaly_rate: float
    model_saved: bool
    fitted_at: str


class ScoreRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol")
    lookback: int = Field(200, ge=20, le=2000, description="Number of recent bars to score")


class ScoreResponse(BaseModel):
    symbol: str
    bars_scored: int
    scores: list[float]
    weights: list[float]
    anomaly_flags: list[bool]
    anomaly_count: int
    anomaly_rate: float
    scored_at: str


class FlagRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol")
    lookback: int = Field(200, ge=20, le=2000)


class FlagResponse(BaseModel):
    symbol: str
    bars_checked: int
    anomaly_indices: list[int]
    anomaly_count: int
    anomaly_rate: float
    flagged_at: str


class RetrainResponse(BaseModel):
    status: str
    message: str
    triggered_at: str


class ResetResponse(BaseModel):
    status: str
    message: str
    reset_at: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=AnomalyStatusResponse,
    summary="Live anomaly detector status",
)
async def anomaly_status(user: TokenPayload = Depends(get_current_user)) -> AnomalyStatusResponse:
    """Return the current state of the live AnomalyWeightStore."""
    store = _get_live_store()
    diag = store.status()
    model_path = str(_ANOMALY_MODEL_PATH) if _ANOMALY_MODEL_PATH else None
    return AnomalyStatusResponse(
        fitted=diag.get("fitted", False),
        buffer_size=diag.get("buffer_size", 0),
        bars_since_refit=diag.get("bars_since_refit", 0),
        anomaly_count=diag.get("anomaly_count", 0),
        total_scored=diag.get("total_scored", 0),
        anomaly_rate=diag.get("anomaly_rate", 0.0),
        use_lof=diag.get("use_lof", True),
        down_weight_factor=diag.get("down_weight_factor", 0.5),
        model_path=model_path,
        model_exists=_ANOMALY_MODEL_PATH.exists() if _ANOMALY_MODEL_PATH else False,
        checked_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/config",
    response_model=AnomalyConfigResponse,
    summary="Anomaly detector configuration",
)
async def anomaly_config(user: TokenPayload = Depends(get_current_user)) -> AnomalyConfigResponse:
    """Return the configuration of the live AnomalyWeightStore."""
    store = _get_live_store()
    return AnomalyConfigResponse(
        window_size=store.window_size,
        refit_every=store.refit_every,
        contamination=store._contamination,
        anomaly_threshold=store.anomaly_threshold,
        down_weight_factor=store.down_weight_factor,
        use_lof=store.use_lof,
        persist_path=str(store.persist_path) if store.persist_path else None,
    )


@router.post(
    "/fit",
    response_model=FitResponse,
    summary="Fit anomaly detector on historical OHLCV data",
)
async def fit_anomaly_detector(
    body: FitRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> FitResponse:
    """
    Fit an IsolationForest + LOF ensemble on historical OHLCV bars for the
    given symbol and persist the model to disk.

    Requires admin role — fitting is CPU-intensive and modifies the shared model.
    """

    loop = asyncio.get_running_loop()

    def _fit() -> dict[str, Any]:
        from research.pipeline.anomaly import AnomalyWeighter, AnomalyWeightStore

        ohlcv = _load_ohlcv(body.symbol, lookback=body.lookback)
        feat = AnomalyWeightStore._extract_features(ohlcv)
        if feat is None or len(feat) < 50:
            raise ValueError(f"Insufficient OHLCV data for {body.symbol} (need ≥50 bars)")

        import pandas as pd
        feat_df = pd.DataFrame(feat)

        aw = AnomalyWeighter(
            contamination=body.contamination,
            use_lof=body.use_lof,
        )
        aw.fit(feat_df)
        flags = aw.flag(feat_df)
        n_anomalies = int(flags.sum())
        n_bars = len(feat_df)

        saved = False
        if body.save:
            try:
                aw.save(_ANOMALY_MODEL_PATH)
                saved = True
            except Exception as save_exc:
                logger.warning("Anomaly model save failed: %s", save_exc)

        return {
            "bars_fitted": n_bars,
            "anomaly_count": n_anomalies,
            "anomaly_rate": round(n_anomalies / n_bars, 4) if n_bars else 0.0,
            "model_saved": saved,
        }

    try:
        result = await loop.run_in_executor(None, _fit)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Anomaly fit failed for %s: %s", body.symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Anomaly detector fit failed: {exc}",
        ) from exc

    return FitResponse(
        symbol=body.symbol.upper(),
        bars_fitted=result["bars_fitted"],
        anomaly_count=result["anomaly_count"],
        anomaly_rate=result["anomaly_rate"],
        model_saved=result["model_saved"],
        fitted_at=datetime.now(UTC).isoformat(),
    )


@router.post(
    "/score",
    response_model=ScoreResponse,
    summary="Score recent OHLCV bars for anomalies",
)
async def score_bars(
    body: ScoreRequest,
    user: TokenPayload = Depends(get_current_user),
) -> ScoreResponse:
    """
    Score the most recent ``lookback`` OHLCV bars for the given symbol.

    Returns per-bar anomaly scores, sample weights, and boolean flags.
    Uses the persisted AnomalyWeighter if available; falls back to the live
    AnomalyWeightStore's internal weighter.
    """

    loop = asyncio.get_running_loop()

    def _score() -> dict[str, Any]:
        import pandas as pd
        from research.pipeline.anomaly import AnomalyWeighter, AnomalyWeightStore

        ohlcv = _load_ohlcv(body.symbol, lookback=body.lookback)
        feat = AnomalyWeightStore._extract_features(ohlcv)
        if feat is None or len(feat) < 20:
            raise ValueError(f"Insufficient OHLCV data for {body.symbol}")

        feat_df = pd.DataFrame(feat)

        # Prefer the persisted fitted model; fall back to live store's weighter
        aw = None
        if _ANOMALY_MODEL_PATH.exists():
            try:
                aw = AnomalyWeighter.load(_ANOMALY_MODEL_PATH)
            except Exception as load_exc:
                logger.debug("Persisted anomaly model load failed: %s", load_exc)

        if aw is None:
            store = _get_live_store()
            if store._weighter is not None and store._weighter._fitted:
                aw = store._weighter
            else:
                # Fit on the fly with the data we have
                aw = AnomalyWeighter(contamination=0.02)
                aw.fit(feat_df)

        scores = aw.decision_scores(feat_df).tolist()
        weights = aw.sample_weights(feat_df).tolist()
        flags = aw.flag(feat_df).tolist()
        n_anomalies = sum(1 for f in flags if f)
        n_bars = len(flags)

        return {
            "bars_scored": n_bars,
            "scores": [round(s, 6) for s in scores],
            "weights": [round(w, 6) for w in weights],
            "anomaly_flags": flags,
            "anomaly_count": n_anomalies,
            "anomaly_rate": round(n_anomalies / n_bars, 4) if n_bars else 0.0,
        }

    try:
        result = await loop.run_in_executor(None, _score)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Anomaly score failed for %s: %s", body.symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Anomaly scoring failed: {exc}",
        ) from exc

    return ScoreResponse(
        symbol=body.symbol.upper(),
        scored_at=datetime.now(UTC).isoformat(),
        **result,
    )


@router.post(
    "/flag",
    response_model=FlagResponse,
    summary="Return indices of anomalous bars",
)
async def flag_anomalies(
    body: FlagRequest,
    user: TokenPayload = Depends(get_current_user),
) -> FlagResponse:
    """
    Return the indices of anomalous bars in the most recent ``lookback`` OHLCV
    bars for the given symbol.
    """

    loop = asyncio.get_running_loop()

    def _flag() -> dict[str, Any]:
        import pandas as pd
        from research.pipeline.anomaly import AnomalyWeighter, AnomalyWeightStore

        ohlcv = _load_ohlcv(body.symbol, lookback=body.lookback)
        feat = AnomalyWeightStore._extract_features(ohlcv)
        if feat is None or len(feat) < 20:
            raise ValueError(f"Insufficient OHLCV data for {body.symbol}")

        feat_df = pd.DataFrame(feat)

        aw = None
        if _ANOMALY_MODEL_PATH.exists():
            try:
                aw = AnomalyWeighter.load(_ANOMALY_MODEL_PATH)
            except Exception:
                logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

        if aw is None:
            store = _get_live_store()
            if store._weighter is not None and store._weighter._fitted:
                aw = store._weighter
            else:
                aw = AnomalyWeighter(contamination=0.02)
                aw.fit(feat_df)

        flags = aw.flag(feat_df)
        anomaly_indices = [int(i) for i, f in enumerate(flags) if f]
        n_bars = len(flags)

        return {
            "bars_checked": n_bars,
            "anomaly_indices": anomaly_indices,
            "anomaly_count": len(anomaly_indices),
            "anomaly_rate": round(len(anomaly_indices) / n_bars, 4) if n_bars else 0.0,
        }

    try:
        result = await loop.run_in_executor(None, _flag)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Anomaly flag failed for %s: %s", body.symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Anomaly flagging failed: {exc}",
        ) from exc

    return FlagResponse(
        symbol=body.symbol.upper(),
        flagged_at=datetime.now(UTC).isoformat(),
        **result,
    )


@router.get(
    "/report/{symbol}",
    summary="Top-N most anomalous bars for a symbol",
)
async def anomaly_report(
    symbol: str,
    top_n: int = 10,
    lookback: int = 500,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the top-N most anomalous bars for the given symbol, sorted by
    anomaly score (most anomalous first).
    """
    loop = asyncio.get_running_loop()

    def _report() -> dict[str, Any]:
        import pandas as pd
        from research.pipeline.anomaly import AnomalyWeighter, AnomalyWeightStore

        ohlcv = _load_ohlcv(symbol, lookback=lookback)
        feat = AnomalyWeightStore._extract_features(ohlcv)
        if feat is None or len(feat) < 20:
            raise ValueError(f"Insufficient OHLCV data for {symbol}")

        feat_df = pd.DataFrame(feat)

        aw = None
        if _ANOMALY_MODEL_PATH.exists():
            try:
                aw = AnomalyWeighter.load(_ANOMALY_MODEL_PATH)
            except Exception:
                logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

        if aw is None:
            store = _get_live_store()
            if store._weighter is not None and store._weighter._fitted:
                aw = store._weighter
            else:
                aw = AnomalyWeighter(contamination=0.02)
                aw.fit(feat_df)

        report_df = aw.annotate(ohlcv)
        top = report_df.nsmallest(min(top_n, len(report_df)), "anomaly_score")

        rows = []
        for idx, row in top.iterrows():
            rows.append({
                "index": str(idx),
                "anomaly_score": round(float(row.get("anomaly_score", 0)), 6),
                "is_anomaly": bool(row.get("is_anomaly", False)),
                "anomaly_weight": round(float(row.get("anomaly_weight", 1.0)), 6),
                "close": round(float(row.get("close", 0)), 5),
                "high": round(float(row.get("high", 0)), 5),
                "low": round(float(row.get("low", 0)), 5),
                "volume": float(row.get("volume", 0)),
            })

        return {
            "symbol": symbol.upper(),
            "top_n": top_n,
            "lookback": lookback,
            "bars_analysed": len(feat_df),
            "rows": rows,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    try:
        return await loop.run_in_executor(None, _report)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Anomaly report failed for %s: %s", symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Anomaly report failed: {exc}",
        ) from exc


@router.post(
    "/retrain",
    response_model=RetrainResponse,
    summary="Background refit on latest market data (admin)",
)
async def retrain_anomaly_detector(
    background_tasks: BackgroundTasks,
    symbols: list[str] | None = None,
    lookback: int = 500,
    user: TokenPayload = Depends(require_role("admin")),
) -> RetrainResponse:
    """
    Trigger a background refit of the anomaly detector on the latest market
    data for the given symbols (defaults to ALLOWED_SYMBOLS from env).

    The refit runs in a background thread so the response is immediate.
    """
    target_symbols: list[str] = symbols or [
        s.strip()
        for s in os.getenv("ALLOWED_SYMBOLS", "XAUUSD,EURUSD,GBPUSD").split(",")
        if s.strip()
    ]

    def _background_refit() -> None:
        import numpy as np
        import pandas as pd
        from research.pipeline.anomaly import AnomalyWeighter, AnomalyWeightStore

        all_feats: list[Any] = []
        for sym in target_symbols:
            try:
                ohlcv = _load_ohlcv(sym, lookback=lookback)
                feat = AnomalyWeightStore._extract_features(ohlcv)
                if feat is not None and len(feat) >= 50:
                    all_feats.append(feat)
                    logger.info("Anomaly retrain: loaded %d bars for %s", len(feat), sym)
            except Exception as exc:
                logger.warning("Anomaly retrain: skipping %s — %s", sym, exc)

        if not all_feats:
            logger.error("Anomaly retrain: no data loaded for any symbol — aborting")
            return

        combined = np.vstack(all_feats)
        feat_df = pd.DataFrame(combined)
        aw = AnomalyWeighter(contamination=0.02, use_lof=True)
        aw.fit(feat_df)
        try:
            aw.save(_ANOMALY_MODEL_PATH)
            logger.info(
                "Anomaly retrain complete: %d bars across %d symbols → %s",
                len(combined),
                len(all_feats),
                _ANOMALY_MODEL_PATH,
            )
        except Exception as save_exc:
            logger.error("Anomaly retrain: model save failed: %s", save_exc)

    background_tasks.add_task(_background_refit)

    return RetrainResponse(
        status="accepted",
        message=f"Background refit triggered for {len(target_symbols)} symbol(s): {', '.join(target_symbols)}",
        triggered_at=datetime.now(UTC).isoformat(),
    )


@router.delete(
    "/reset",
    response_model=ResetResponse,
    summary="Reset the live anomaly store (admin)",
)
async def reset_anomaly_store(
    user: TokenPayload = Depends(require_role("admin")),
) -> ResetResponse:
    """
    Reset the live AnomalyWeightStore singleton — clears the rolling buffer,
    fitted model, and counters.  The next incoming bar will trigger a fresh fit
    once enough data accumulates.

    Use this after a major market regime change or data feed interruption.
    """
    global _live_store
    async with _live_store_lock:
        _live_store = None  # next call to _get_live_store() creates a fresh instance
    logger.info("AnomalyWeightStore singleton reset by admin %s", user.sub)
    return ResetResponse(
        status="ok",
        message="Live anomaly store reset. A fresh instance will be created on the next request.",
        reset_at=datetime.now(UTC).isoformat(),
    )
