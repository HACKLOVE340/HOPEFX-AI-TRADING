# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/ml.py
=========
ML model endpoints consumed by the frontend mlApi hook.

Routes
------
GET  /ml/accuracy          — current model accuracy metrics
GET  /ml/models            — list available trained models
POST /ml/predict/{symbol}  — get a prediction for a symbol (includes ATR SL/TP)
POST /ml/retrain           — trigger background model retraining (admin)
GET  /ml/features          — list feature importances for the active model
GET  /ml/health            — InferenceEngine health (any authenticated user)
GET  /ml/engine-health     — InferenceEngine detailed diagnostics (admin only)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user, require_role

logger = logging.getLogger(__name__)
ML_MODELS_DIR = (Path(os.getenv("ML_MODELS_DIR", "models"))).resolve()
# Prefix must match the frontend useApi.ts mlApi calls (/api/ml/*)
router = APIRouter(prefix="/api/ml", tags=["ML Models"])


# ── Lazy model loader ─────────────────────────────────────────────────────────


def _load_model_registry() -> dict[str, Any]:
    """Return a dict of available saved models with metadata."""
    import pathlib

    saved_dir = pathlib.Path(__file__).parent.parent / "ml" / "saved_models"
    registry: dict[str, Any] = {}

    model_files = {
        "xgb_macro": "xgb_macro.pkl",
        "rf_xauusd": "rf_xauusd.pkl",
        "rf_macro": "rf_macro.pkl",
    }

    for name, fname in model_files.items():
        path = saved_dir / fname
        if path.exists():
            try:
                stat = path.stat()
                registry[name] = {
                    "model_id": name,
                    "name": name.replace("_", " ").title(),
                    "file": fname,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "trained_at": datetime.fromtimestamp(
                        stat.st_mtime,
                        tz=UTC,
                    ).isoformat(),
                    "available": True,
                }
            except Exception as exc:
                logger.debug("Could not stat model %s: %s", fname, exc)
                registry[name] = {"model_id": name, "available": False}
        else:
            registry[name] = {"model_id": name, "available": False}

    return registry


def _get_predictor():
    """Return the active ML predictor.

    Priority:
    1. InferenceEngine (full pipeline: MacroStore + MTF + 200 features + calibration)
    2. AdvancedModelPredictor (advanced_oos.pkl — direct)
    3. EnsemblePredictor (ml/models/ensemble.py)
    4. Raw joblib-loaded xgb_macro.pkl
    """
    try:
        from ml.inference_engine import get_inference_engine

        return get_inference_engine()
    except Exception as exc:
        logger.debug("InferenceEngine unavailable: %s", exc)

    try:
        from ml.live_inference import get_advanced_predictor

        p = get_advanced_predictor()
        if p.is_available:
            return p
    except Exception as exc:
        logger.debug("AdvancedModelPredictor unavailable: %s", exc)

    try:
        from ml.models.ensemble import EnsemblePredictor

        return EnsemblePredictor()
    except Exception as exc:
        logger.debug("EnsemblePredictor unavailable: %s", exc)

    try:
        import pathlib

        import joblib

        path = pathlib.Path(__file__).parent.parent / "ml" / "saved_models" / "xgb_macro.pkl"
        if path.exists():
            return joblib.load(str(path))  # nosec B301 - path is hardcoded to ml/saved_models
    except Exception as exc:
        logger.warning("Saved ML model load failed: %s", exc)
    return None


def _load_ohlcv_for_symbol(symbol: str, lookback: int = 200) -> pd.DataFrame:
    """
    Load real OHLCV data for a symbol.

    Priority:
    1. Live price engine (app_state.price_engine) — most recent bars
    2. CSV files in data/ directory — XAU_USD_H1.csv etc.
    3. Paper broker get_market_data() — paper account OHLCV history

    Returns a DataFrame with columns [open, high, low, close, volume]
    and a DatetimeIndex, length >= lookback where possible.
    Returns an empty DataFrame when no source has data — callers must
    check len(df) >= minimum_bars before proceeding.
    """
    import pathlib

    symbol_upper = symbol.upper().replace("-", "/").replace("/", "_")
    # Normalise: XAU/USD → XAU_USD, XAUUSD → XAU_USD
    if "_" not in symbol_upper and len(symbol_upper) == 6:
        symbol_upper = symbol_upper[:3] + "_" + symbol_upper[3:]

    # 1. Live price engine async buffer — skip (sync context here)

    # 2. CSV files
    data_dir = pathlib.Path(__file__).parent.parent / "data"
    candidates = [
        data_dir / f"{symbol_upper}_H1.csv",
        data_dir / f"{symbol_upper.replace('_', '')}_H1.csv",
        data_dir / f"{symbol_upper}_H1.csv".replace("XAU_USD", "XAUUSD"),
    ]
    for csv_path in candidates:
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path, parse_dates=["timestamp"])
                df = df.rename(columns={"timestamp": "time"}).set_index("time")
                df = df[["open", "high", "low", "close", "volume"]].dropna()
                df = df.tail(lookback)
                if len(df) >= 20:
                    logger.debug("ML predict: loaded %d bars from %s", len(df), csv_path.name)
                    return df
            except Exception as exc:
                logger.debug("CSV load failed (%s): %s", csv_path, exc)

    # 3. Paper broker simulated prices
    try:
        from app import app_state

        broker = getattr(app_state, "broker", None)
        if broker and hasattr(broker, "get_market_data"):
            raw = broker.get_market_data(symbol.upper().replace("_", ""), "1h", lookback)
            if raw:
                df = pd.DataFrame(raw)
                df["time"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
                df = df.set_index("time")[["open", "high", "low", "close", "volume"]].dropna()
                if len(df) >= 20:
                    logger.debug("ML predict: loaded %d bars from paper broker", len(df))
                    return df
    except Exception as exc:
        logger.debug("Paper broker OHLCV load failed: %s", exc)

    # No OHLCV data available from any source — return empty DataFrame.
    # Callers must check len(df) >= minimum_bars before proceeding.
    logger.warning(
        "_load_ohlcv_for_symbol: no OHLCV data available for %s "
        "(checked price_engine, CSV files, paper broker). "
        "Ensure the data layer is running or place a CSV in data/%s_H1.csv.",
        symbol,
        symbol.upper().replace("/", "_").replace("-", "_"),
    )
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _compute_atr_sl_tp(
    ohlcv: pd.DataFrame,
    entry_price: float,
    direction: str,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 3.0,
) -> tuple[float, float]:
    """
    Compute ATR(14)-based stop-loss and take-profit from an OHLCV DataFrame.

    Multipliers are read from SL_ATR_MULT / TP_ATR_MULT env vars so they
    can be tuned without a restart.  Falls back to 1.5% / 3.0% of entry
    price when fewer than 15 bars are available.

    Returns (stop_loss, take_profit) rounded to 5 decimal places.
    """
    import numpy as _np

    sl_mult = float(os.getenv("SL_ATR_MULT", str(sl_atr_mult)))
    tp_mult = float(os.getenv("TP_ATR_MULT", str(tp_atr_mult)))

    atr: float | None = None

    try:
        if ohlcv is not None and len(ohlcv) >= 15:
            highs = ohlcv["high"].to_numpy(dtype=float)[-15:]
            lows = ohlcv["low"].to_numpy(dtype=float)[-15:]
            closes = ohlcv["close"].to_numpy(dtype=float)[-15:]
            tr = _np.maximum(
                highs[1:] - lows[1:],
                _np.maximum(
                    _np.abs(highs[1:] - closes[:-1]),
                    _np.abs(lows[1:] - closes[:-1]),
                ),
            )
            if len(tr) >= 14:
                atr = float(_np.mean(tr[-14:]))
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    if atr is None or atr <= 0:
        atr = entry_price * 0.01  # 1% fallback

    is_long = direction in ("long", "buy", "BUY")
    if is_long:
        sl = round(entry_price - atr * sl_mult, 5)
        tp = round(entry_price + atr * tp_mult, 5)
    else:
        sl = round(entry_price + atr * sl_mult, 5)
        tp = round(entry_price - atr * tp_mult, 5)

    return sl, tp


def _get_macro_df_for_symbol(symbol: str, lookback: int = 200) -> pd.DataFrame | None:
    """
    Fetch aligned macro features from MacroStore for the given symbol.

    Returns a DataFrame with macro columns aligned to hourly bars, or None
    if MacroStore is empty / unavailable.  This is the MacroStore → live
    inference bridge: every predict call gets fresh macro context.
    """
    try:
        from ml.macro_store import macro_store

        if len(macro_store) == 0:
            return None

        df = macro_store.get_aligned(symbol, lookback=lookback)
        return df if df is not None and not df.empty else None
    except Exception as exc:
        logger.debug("MacroStore alignment failed (non-fatal): %s", exc)
        return None


# ── Models ────────────────────────────────────────────────────────────────────


class PredictRequest(BaseModel):
    timeframe: str = Field("H1", description="Candle timeframe: M15, H1, H4, D1")
    lookback: int = Field(100, ge=20, le=500, description="Number of candles to use")


class PredictResponse(BaseModel):
    symbol: str
    direction: str  # BUY | SELL | HOLD
    confidence: float  # 0–100
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    features_used: int = 0
    model_id: str = "xgb_macro"
    generated_at: str


class AccuracyResponse(BaseModel):
    model_id: str
    accuracy: float
    precision: float
    recall: float
    f1: float
    sharpe: float
    win_rate: float
    total_signals: int
    evaluated_at: str
    note: str = ""


class ModelInfo(BaseModel):
    model_id: str
    name: str
    available: bool
    size_kb: float | None = None
    trained_at: str | None = None


class FeatureEntry(BaseModel):
    name: str
    importance: float


class FeatureImportancesResponse(BaseModel):
    features: list[FeatureEntry]
    model_id: str | None = None
    note: str | None = None


class RetrainResponse(BaseModel):
    status: str
    message: str


class MLHealthResponse(BaseModel):
    """Response schema for GET /api/ml/health."""

    status: str  # "ok" | "degraded" | "unavailable"
    model_loaded: bool
    model_id: str | None
    feature_count: int
    oos_accuracy: float | None
    last_trained_at: str | None
    predict_count: int
    fallback_count: int
    fallback_rate: float = 0.0
    non_neutral_rate: float = 0.0  # fraction of last N signals that were directional
    signal_window_size: int = 0  # number of signals in the rolling window
    last_latency_ms: float
    uptime_seconds: float | None = None
    calibrator_available: bool
    online_learning_enabled: bool
    mtf_fusion_enabled: bool
    threshold_long: float
    threshold_short: float
    signal_filter: dict[str, Any] = Field(default_factory=dict)
    pipeline: dict[str, Any] = Field(default_factory=dict)
    checked_at: str


class MLEngineHealthResponse(BaseModel):
    """Response schema for GET /api/ml/engine-health (admin)."""

    status: str  # "ok" | "degraded" | "unavailable"
    engine: dict[str, Any]
    macro_store: dict[str, Any]
    mtf_store: dict[str, Any]
    saved_model_files_kb: dict[str, float]
    checked_at: str
    error: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/accuracy", response_model=AccuracyResponse)
async def get_accuracy(user: TokenPayload = Depends(get_current_user)):
    """
    Return accuracy metrics for the active model.

    Resolution order:
    1. ml/saved_models/advanced_oos_meta.json  — written by train_with_macro.py
    2. ml/evaluation_results.json              — written by evaluation pipeline
    3. ml/saved_models/metrics.json            — legacy metrics file
    4. Live InferenceEngine predict_count / fallback_count ratio
    5. Zeros with a note directing the user to run training (model not yet trained)

    Requires: authenticated user (any role).
    """
    import json
    import pathlib

    base_dir = pathlib.Path(__file__).parent.parent / "ml"
    saved_dir = base_dir / "saved_models"

    eval_paths = [
        saved_dir / "advanced_oos_meta.json",
        base_dir / "evaluation_results.json",
        saved_dir / "metrics.json",
    ]

    for p in eval_paths:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                # Normalise field names across different file formats
                accuracy = float(data.get("accuracy") or data.get("oos_accuracy") or data.get("test_accuracy") or 0.0)
                precision = float(data.get("precision") or data.get("test_precision") or data.get("oos_f1") or 0.0)
                recall = float(data.get("recall") or data.get("test_recall") or data.get("oos_auc") or 0.0)
                f1 = float(data.get("f1") or data.get("f1_score") or data.get("oos_f1") or 0.0)
                # Sharpe: prefer multi-symbol pooled, then sharpe_gate, then direct key
                sharpe_gate = data.get("sharpe_gate") or {}
                multi = data.get("multi_symbol_backtest_extended") or data.get("multi_symbol_backtest") or {}
                sharpe = float(
                    data.get("sharpe")
                    or data.get("sharpe_ratio")
                    or multi.get("pooled_sharpe")
                    or sharpe_gate.get("sharpe")
                    or 0.0
                )
                # win_rate: prefer multi-symbol pooled win rate, else accuracy
                win_rate = float(data.get("win_rate") or accuracy)
                # total_signals: prefer oos_n (number of OOS bars evaluated)
                total_signals = int(
                    data.get("total_signals")
                    or data.get("oos_n")
                    or data.get("n_samples")
                    or multi.get("pooled_n_trades")
                    or 0
                )
                model_id = str(data.get("model_id") or data.get("model_file") or "advanced_oos")
                evaluated_at = data.get("evaluated_at") or data.get("validated_at") or datetime.now(UTC).isoformat()
                note = data.get("note") or data.get("validation_notes") or data.get("sharpe_note") or ""

                # If accuracy is still 0 try to derive from InferenceEngine counters
                if accuracy == 0.0:
                    try:
                        from ml.inference_engine import get_inference_engine

                        eng = get_inference_engine()
                        h = eng.health()
                        total = h.get("predict_count", 0)
                        fallback = h.get("fallback_count", 0)
                        if total > 0:
                            accuracy = round(1.0 - fallback / total, 4)
                            win_rate = accuracy
                            total_signals = total
                            note = note or "Accuracy derived from live predict/fallback ratio"
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)

                return AccuracyResponse(
                    model_id=model_id,
                    accuracy=accuracy,
                    precision=precision,
                    recall=recall,
                    f1=f1,
                    sharpe=sharpe,
                    win_rate=win_rate,
                    total_signals=total_signals,
                    evaluated_at=evaluated_at,
                    note=note,
                )
            except Exception as exc:
                logger.debug("Could not parse eval file %s: %s", p, exc)

    # ── Live engine counters as last resort ───────────────────────────────────
    try:
        from ml.inference_engine import get_inference_engine

        eng = get_inference_engine()
        h = eng.health()
        total = h.get("predict_count", 0)
        fallback = h.get("fallback_count", 0)
        if total > 0:
            live_accuracy = round(1.0 - fallback / total, 4)
            return AccuracyResponse(
                model_id=h.get("model_version", "inference_engine"),
                accuracy=live_accuracy,
                precision=0.0,
                recall=0.0,
                f1=0.0,
                sharpe=0.0,
                win_rate=live_accuracy,
                total_signals=total,
                evaluated_at=datetime.now(UTC).isoformat(),
                note=f"Live ratio: {total - fallback}/{total} non-fallback predictions",
            )
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # No evaluation data and no live engine counters — model not yet trained.
    # Return zeros with a clear note; the UI should prompt the user to train.
    return AccuracyResponse(
        model_id="xgb_macro",
        accuracy=0.0,
        precision=0.0,
        recall=0.0,
        f1=0.0,
        sharpe=0.0,
        win_rate=0.0,
        total_signals=0,
        evaluated_at=datetime.now(UTC).isoformat(),
        note="No evaluation data found. Run: python ml/train_with_macro.py --years 8",
    )


@router.get("/models", response_model=list[ModelInfo])
async def list_models(user: TokenPayload = Depends(get_current_user)):
    """List all available trained models with metadata. Requires authentication."""
    registry = _load_model_registry()
    return [ModelInfo(**v) for v in registry.values()]


def _check_subscription_gate(user: Any) -> None:
    """Raise HTTP 403 if user's plan does not include ML predictions."""
    if getattr(user, "role", "") == "admin":
        return
    try:
        from monetization.subscription import subscription_manager, plan_gate

        sub = subscription_manager.get_user_subscription(user.sub)
        user_plan = sub.tier.value if (sub and sub.is_active() and hasattr(sub.tier, "value")) else "free"
        if not plan_gate("professional", user_plan):
            from fastapi import HTTPException as _HTTPException, status as _status

            raise _HTTPException(
                status_code=_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "PLAN_LIMIT_EXCEEDED",
                    "required_plan": "professional",
                    "current_plan": user_plan,
                    "message": "ML predictions require a Professional subscription or above.",
                },
            )
    except ImportError:
        pass


def _predict_with_inference_engine(predictor: Any, ohlcv: Any, symbol_upper: str, now_iso: str) -> Any:
    """Run prediction via InferenceEngine path."""
    result = predictor.predict(ohlcv, symbol=symbol_upper)
    direction_map = {"long": "BUY", "short": "SELL", "neutral": "HOLD"}
    direction = direction_map.get(result.get("direction", "neutral"), "HOLD")
    confidence = round(float(result.get("confidence", 0.0)) * 100, 1)
    entry_price = result.get("last_close")
    sl, tp = (None, None)
    if entry_price and direction != "HOLD":
        sl, tp = _compute_atr_sl_tp(ohlcv, entry_price, direction)
    return PredictResponse(
        symbol=symbol_upper,
        direction=direction,
        confidence=confidence,
        entry_price=entry_price,
        stop_loss=sl,
        take_profit=tp,
        features_used=result.get("bars_used", 0),
        model_id=result.get("model_version", "inference_engine"),
        generated_at=now_iso,
    )


def _predict_with_advanced_predictor(predictor: Any, ohlcv: Any, symbol_upper: str, lookback: int, now_iso: str) -> Any:
    """Run prediction via AdvancedModelPredictor path."""
    macro_df = _get_macro_df_for_symbol(symbol_upper, lookback=lookback)
    result = predictor.predict_signal(ohlcv, macro_df=macro_df, symbol=symbol_upper)
    direction_map = {"long": "BUY", "short": "SELL", "neutral": "HOLD"}
    direction = direction_map.get(result.get("direction", "neutral"), "HOLD")
    confidence = round(float(result.get("confidence", 0.0)) * 100, 1)
    entry_price = result.get("last_close")
    sl, tp = (None, None)
    if entry_price and direction != "HOLD":
        sl, tp = _compute_atr_sl_tp(ohlcv, entry_price, direction)
    return PredictResponse(
        symbol=symbol_upper,
        direction=direction,
        confidence=confidence,
        entry_price=entry_price,
        stop_loss=sl,
        take_profit=tp,
        features_used=result.get("bars_used", 0),
        model_id=result.get("model_version", "advanced_oos"),
        generated_at=now_iso,
    )


def _hold_response(symbol_upper: str, now_iso: str, model_id: str = "fallback") -> Any:
    """Return a safe HOLD PredictResponse."""
    return PredictResponse(
        symbol=symbol_upper,
        direction="HOLD",
        confidence=0.0,
        entry_price=None,
        stop_loss=None,
        take_profit=None,
        features_used=0,
        model_id=model_id,
        generated_at=now_iso,
    )


@router.post("/predict/{symbol}", response_model=PredictResponse)
async def predict(
    symbol: str,
    body: PredictRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Generate a trading prediction for the given symbol.

    Uses the XGBoost macro model if available; falls back to a
    rule-based regime signal when no model is loaded.

    Requires: Professional plan or above (enforced via plan_gate on user subscription).
    """
    # Subscription gate — Professional plan required for ML predictions.
    # Admin role bypasses the plan gate (internal tooling / ops access).
    if getattr(user, "role", "") != "admin":
        try:
            from monetization.subscription import plan_gate, subscription_manager

            sub = subscription_manager.get_user_subscription(user.sub)
            user_plan = sub.tier.value if (sub and sub.is_active() and hasattr(sub.tier, "value")) else "free"
            if not plan_gate("professional", user_plan):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "PLAN_LIMIT_EXCEEDED",
                        "required_plan": "professional",
                        "current_plan": user_plan,
                        "message": "ML predictions require a Professional subscription or above.",
                    },
                )
        except ImportError:
            ...  # nosec B110
    symbol_upper = symbol.upper().replace("-", "/")
    now_iso = datetime.now(UTC).isoformat()
    predictor = _get_predictor()

    if predictor is not None:
        try:
            ohlcv = _load_ohlcv_for_symbol(symbol_upper, body.lookback)
            if hasattr(predictor, "predict") and hasattr(predictor, "health"):
                result = predictor.predict(ohlcv, symbol=symbol_upper)
                direction_map = {"long": "BUY", "short": "SELL", "neutral": "HOLD"}
                direction = direction_map.get(result.get("direction", "neutral"), "HOLD")
                confidence = round(float(result.get("confidence", 0.0)) * 100, 1)
                entry_price = result.get("last_close")
                sl, tp = (None, None)
                if entry_price and direction != "HOLD":
                    sl, tp = _compute_atr_sl_tp(ohlcv, entry_price, direction)
                return PredictResponse(
                    symbol=symbol_upper,
                    direction=direction,
                    confidence=confidence,
                    entry_price=entry_price,
                    stop_loss=sl,
                    take_profit=tp,
                    features_used=result.get("bars_used", 0),
                    model_id=result.get("model_version", "inference_engine"),
                    generated_at=now_iso,
                )

            # AdvancedModelPredictor path
            if hasattr(predictor, "predict_signal"):
                macro_df = _get_macro_df_for_symbol(symbol_upper, lookback=body.lookback)
                result = predictor.predict_signal(ohlcv, macro_df=macro_df, symbol=symbol_upper)
                direction_map = {"long": "BUY", "short": "SELL", "neutral": "HOLD"}
                direction = direction_map.get(result.get("direction", "neutral"), "HOLD")
                confidence = round(float(result.get("confidence", 0.0)) * 100, 1)
                entry_price = result.get("last_close")
                sl, tp = (None, None)
                if entry_price and direction != "HOLD":
                    sl, tp = _compute_atr_sl_tp(ohlcv, entry_price, direction)
                return PredictResponse(
                    symbol=symbol_upper,
                    direction=direction,
                    confidence=confidence,
                    entry_price=entry_price,
                    stop_loss=sl,
                    take_profit=tp,
                    features_used=result.get("bars_used", 0),
                    model_id=result.get("model_version", "advanced_oos"),
                    generated_at=now_iso,
                )

            # EnsemblePredictor / legacy path
            if hasattr(predictor, "predict_symbol"):
                result = predictor.predict_symbol(symbol_upper, timeframe=body.timeframe)
                return PredictResponse(
                    symbol=symbol_upper,
                    direction=result.get("direction", "HOLD"),
                    confidence=float(result.get("confidence", 50.0)),
                    entry_price=result.get("entry_price"),
                    stop_loss=result.get("stop_loss"),
                    take_profit=result.get("take_profit"),
                    features_used=result.get("features_used", 0),
                    model_id=result.get("model_id", "xgb_macro"),
                    generated_at=now_iso,
                )
        except Exception as exc:
            logger.warning("Predictor failed for %s: %s", symbol, exc)
            return _hold_response(symbol_upper, now_iso, "fallback")

    # No predictor loaded — return a safe HOLD fallback
    logger.warning("No ML predictor loaded for %s — returning HOLD fallback", symbol_upper)
    return PredictResponse(
        symbol=symbol_upper,
        direction="HOLD",
        confidence=0.0,
        entry_price=None,
        stop_loss=None,
        take_profit=None,
        features_used=0,
        model_id="no_model",
        generated_at=now_iso,
    )


@router.get(
    "/features",
    response_model=FeatureImportancesResponse,
    summary="Feature importances for the active XGBoost model",
)
async def get_feature_importances(user: TokenPayload = Depends(require_role("admin"))):
    """
    Return feature importances for the active XGBoost model.
    Used by the explainability panel.

    Requires: admin role. Raw feature importances reveal the model's
    internal weighting structure and must not be publicly accessible.
    """
    import pathlib

    import joblib

    model_path = pathlib.Path(__file__).parent.parent / "ml" / "saved_models" / "xgb_macro.pkl"
    if not model_path.exists():
        return {"features": [], "note": "Model not trained yet"}

    try:
        model = joblib.load(str(model_path))  # nosec B301 - path is hardcoded to ml/saved_models
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_.tolist()
            # Try to get feature names
            names = getattr(model, "feature_names_in_", None)
            names = [f"feature_{i}" for i in range(len(importances))] if names is None else list(names)

            pairs = sorted(
                zip(names, importances, strict=False),
                key=lambda x: x[1],
                reverse=True,
            )[:20]

            return {
                "features": [{"name": n, "importance": round(v, 6)} for n, v in pairs],
                "model_id": "xgb_macro",
            }
    except Exception as exc:
        logger.warning("Could not load feature importances: %s", exc)

    return {"features": [], "note": "Feature importances unavailable"}


@router.post(
    "/retrain",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RetrainResponse,
    summary="Trigger background model retraining (admin only)",
)
async def trigger_retrain(
    background_tasks: BackgroundTasks,
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Trigger a background model retraining job.
    Admin only. Returns immediately; training runs in background.

    Requires: admin role enforced via require_role dependency (not manual check).
    """

    def _retrain():
        try:
            import subprocess  # nosec B404 - list-form call with sys.executable; no shell=True, no user input
            import sys

            script = os.path.join(
                Path(__file__).parent,
                "..",
                "ml",
                "train_with_macro.py",
            )
            if Path(script).exists():
                subprocess.run(  # nosec B603 B607 - list-form call with sys.executable; no shell=True, no user input
                    [sys.executable, script, "--years", "8"],
                    timeout=3600,
                    capture_output=True,
                    check=False,
                )
                logger.info("Model retraining completed")
            else:
                logger.warning("train_with_macro.py not found — skipping retrain")
        except Exception as exc:
            logger.error("Retrain failed: %s", exc)

    background_tasks.add_task(_retrain)
    return {
        "status": "queued",
        "message": "Model retraining started in background. Check /ml/accuracy in ~10 minutes.",
    }


@router.get(
    "/signal-filter/stats",
    summary="Signal filter EV statistics — rolling win rate, avg win/loss, EV gate status",
)
async def signal_filter_stats(
    symbol: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return rolling expected value statistics from the production signal quality filter.

    The EV gate blocks signals when win_rate × avg_win + (1-win_rate) × avg_loss <= 0.
    This endpoint shows whether the filter has enough trade outcomes (n >= 10) to
    make reliable EV estimates and whether the current edge is positive.

    Parameters
    ----------
    symbol : optional symbol (e.g. XAUUSD). Omit for global stats.
    """
    try:
        from ml.signal_filter import get_signal_filter

        filt = get_signal_filter()
        stats = filt.ev_stats(symbol)
        return {
            "symbol": symbol or "global",
            "stats": stats,
            "filter_config": {
                "ev_min_threshold": float(os.getenv("EV_MIN_THRESHOLD", "0.0")),
                "ev_window": int(os.getenv("EV_WINDOW", "50")),
                "threshold_long": float(os.getenv("SIGNAL_THRESHOLD_LONG", "0.58")),
                "threshold_short": float(os.getenv("SIGNAL_THRESHOLD_SHORT", "0.42")),
                "regime_filter_enabled": os.getenv("REGIME_FILTER_ENABLED", "true").lower() == "true",
                "mtf_confluence_required": os.getenv("MTF_CONFLUENCE_REQUIRED", "false").lower() == "true",
                "sizing_method": os.getenv("POSITION_SIZING_METHOD", "volatility"),
            },
        }
    except Exception as exc:
        logger.error("signal_filter_stats failed: %s", exc)
        raise HTTPException(status_code=500, detail="Signal filter stats unavailable — check server logs") from None


@router.get(
    "/health",
    response_model=MLHealthResponse,
    summary="ML model health check",
    responses={
        200: {"description": "Model loaded and healthy"},
        206: {"description": "Model degraded (loaded but no trained weights)"},
        503: {"description": "Model unavailable — inference disabled"},
    },
)
def _ml_health_meta(saved_dir: Any) -> tuple:
    """Read model metadata from disk. Returns (oos_accuracy, feature_count, model_file, last_trained_at)."""
    import json as _json
    import pathlib

    # Constrain saved_dir to the configured ML_MODELS_DIR to avoid path traversal.
    oos_accuracy: float | None = None
    feature_count: int = 0
    model_file: str = "advanced_oos.pkl"
    last_trained_at: str | None = None
    try:
        raw_dir = pathlib.Path(str(saved_dir))
        # Disallow absolute paths; interpret saved_dir as a subdirectory name.
        if raw_dir.is_absolute():
            raise ValueError("Absolute paths are not allowed for saved_dir")
        candidate_dir = (ML_MODELS_DIR / raw_dir).resolve()
        # Ensure the resolved path is within the ML_MODELS_DIR tree.
        if ML_MODELS_DIR not in (candidate_dir, *candidate_dir.parents):
            raise ValueError("saved_dir escapes ML_MODELS_DIR")
        meta_path = candidate_dir / "advanced_oos_meta.json"
    except Exception as exc:
        logger.warning("ml_health: invalid saved_dir %r: %s", saved_dir, exc)
        return oos_accuracy, feature_count, model_file, last_trained_at
    if meta_path.exists():
        try:
            meta = _json.loads(meta_path.read_text())
            oos_accuracy = float(meta.get("oos_accuracy", 0.0)) or None
            feature_count = int(meta.get("feature_count", 0))
            model_file = meta.get("model_file", "advanced_oos.pkl")
            last_trained_at = meta.get("validated_at") or meta.get("trained_at")
        except Exception as exc:
            logger.debug("ml_health: meta parse failed: %s", exc)
    return oos_accuracy, feature_count, model_file, last_trained_at


def _ml_health_feature_count_from_predictor() -> int:
    """Derive feature count from the live predictor when meta file is missing."""
    try:
        from ml.live_inference import get_advanced_predictor

        pred = get_advanced_predictor()
        if pred.is_available and hasattr(pred, "_model"):
            n = getattr(pred._model, "n_features_in_", 0)
            return int(n) if n else 0
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return 0


async def ml_health(user: TokenPayload = Depends(get_current_user)):
    """
    Return the current health status of the production ML model.

    HTTP 200: model loaded and ready. HTTP 503: unavailable.
    """
    import pathlib

    checked_at = datetime.now(UTC).isoformat()
    saved_dir = pathlib.Path(__file__).parent.parent / "ml" / "saved_models"

    try:
        from ml.inference_engine import get_inference_engine

        engine = get_inference_engine()
        engine_health = engine.health()

        oos_accuracy, feature_count, model_file, last_trained_at = _ml_health_meta(saved_dir)
        if feature_count == 0:
            feature_count = _ml_health_feature_count_from_predictor()

        # Prefer live engine values over meta file
        feature_count = engine_health.get("feature_count", 0) or feature_count
        oos_accuracy = (
            engine_health.get("oos_accuracy") if engine_health.get("oos_accuracy") is not None else oos_accuracy
        )
        last_trained_at = engine_health.get("last_trained_at") or last_trained_at
        model_available = engine_health.get("model_available", False)

        payload = MLHealthResponse(
            status=engine_health.get("status", "ok" if model_available else "degraded"),
            model_loaded=model_available,
            model_id=engine_health.get("model_version", model_file),
            feature_count=feature_count,
            oos_accuracy=oos_accuracy,
            last_trained_at=last_trained_at,
            predict_count=engine_health.get("predict_count", 0),
            fallback_count=engine_health.get("fallback_count", 0),
            fallback_rate=engine_health.get("fallback_rate", 0.0),
            non_neutral_rate=engine_health.get("non_neutral_rate", 0.0),
            signal_window_size=engine_health.get("signal_window_size", 0),
            last_latency_ms=engine_health.get("last_latency_ms", 0.0),
            uptime_seconds=engine_health.get("uptime_seconds"),
            calibrator_available=engine_health.get("calibrator_available", False),
            online_learning_enabled=engine_health.get("online_learning_enabled", False),
            mtf_fusion_enabled=engine_health.get("mtf_fusion_enabled", True),
            threshold_long=engine_health.get("threshold_long", 0.58),
            threshold_short=engine_health.get("threshold_short", 0.42),
            signal_filter=engine_health.get("signal_filter", {}),
            pipeline=engine_health.get("pipeline", {}),
            checked_at=engine_health.get("checked_at", checked_at),
        )
        if not model_available:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload.model_dump())
        return payload

    except Exception as exc:
        logger.warning("ml_health: InferenceEngine unavailable: %s", exc)

    predictor = _get_predictor()
    model_loaded = predictor is not None
    payload = MLHealthResponse(
        status="ok" if model_loaded else "unavailable",
        model_loaded=model_loaded,
        model_id=None,
        feature_count=0,
        oos_accuracy=None,
        last_trained_at=None,
        predict_count=0,
        fallback_count=0,
        fallback_rate=0.0,
        non_neutral_rate=0.0,
        signal_window_size=0,
        last_latency_ms=0.0,
        uptime_seconds=None,
        calibrator_available=False,
        online_learning_enabled=False,
        mtf_fusion_enabled=False,
        threshold_long=0.58,
        threshold_short=0.42,
        signal_filter={},
        pipeline={},
        checked_at=checked_at,
    )
    if not model_loaded:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload.model_dump())
    return payload


@router.get(
    "/engine-health",
    response_model=MLEngineHealthResponse,
    summary="InferenceEngine detailed health (admin)",
    responses={
        200: {"description": "Engine healthy"},
        503: {"description": "Engine unavailable or model not loaded"},
    },
)
def _engine_macro_status() -> dict:
    """Return MacroStore availability dict."""
    try:
        from ml.macro_store import macro_store

        return {"available": len(macro_store) > 0, "series_count": len(macro_store)}
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return {"available": False, "series_count": 0}


def _engine_mtf_status() -> dict:
    """Return MTF store availability dict."""
    try:
        from research.pipeline.mtf_fusion import _MTF_STORE_SINGLETON

        if _MTF_STORE_SINGLETON is not None:
            return {"available": True, "ready": getattr(_MTF_STORE_SINGLETON, "is_ready", False)}
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return {"available": False, "ready": False}


def _engine_model_files(saved_dir: Any) -> dict:
    """Return {filename: size_kb} for all pkl/json files in saved_dir."""
    import pathlib

    model_files: dict[str, float] = {}
    p = pathlib.Path(saved_dir)
    if p.exists():
        for ext in ("*.pkl", "*.json"):
            for f in p.glob(ext):
                try:
                    model_files[f.name] = round(f.stat().st_size / 1024, 1)
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
    return model_files


async def ml_engine_health(user: TokenPayload = Depends(require_role("admin"))):
    """
    Return detailed InferenceEngine diagnostics (admin only).

    HTTP 200: engine healthy. HTTP 503: unavailable or model not loaded.
    """
    import pathlib

    checked_at = datetime.now(UTC).isoformat()
    saved_dir = pathlib.Path(__file__).parent.parent / "ml" / "saved_models"

    try:
        from ml.inference_engine import get_inference_engine

        engine = get_inference_engine()
        health = engine.health()

        macro_status = _engine_macro_status()
        mtf_status = _engine_mtf_status()
        model_files = _engine_model_files(saved_dir)

        model_available = health.get("model_available", False)
        engine_status = health.get("status", "ok" if model_available else "degraded")
        if "macro_series_count" in health.get("pipeline", {}):
            macro_status["series_count"] = health["pipeline"]["macro_series_count"]

        payload = MLEngineHealthResponse(
            status=engine_status,
            engine=health,
            macro_store=macro_status,
            mtf_store=mtf_status,
            saved_model_files_kb=model_files,
            checked_at=health.get("checked_at", checked_at),
        )
        if not model_available:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload.model_dump())
        return payload

    except Exception as exc:
        logger.warning("ml_engine_health: %s", exc)
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=MLEngineHealthResponse(
                status="unavailable",
                engine={},
                macro_store={},
                mtf_store={},
                saved_model_files_kb={},
                checked_at=checked_at,
                error="ML engine unavailable — check server logs",
            ).model_dump(),
        )


# ── RL Agent endpoints ────────────────────────────────────────────────────────


class RLTrainRequest(BaseModel):
    symbol: str = "XAU_USD"
    timeframe: str = "H1"
    candles: int = 2000
    timesteps: int = 100_000
    train_split: float = 0.8


class RLWalkForwardRequest(BaseModel):
    symbol: str = "XAU_USD"
    timeframe: str = "H1"
    candles: int = 3000
    n_folds: int = 5
    timesteps_per_fold: int = 50_000
    train_pct: float = 0.70


@router.post("/rl/train", tags=["ML Models"])
async def rl_train(
    req: RLTrainRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """
    Trigger PPO RL agent training on OANDA candles.
    Runs synchronously (use a background task queue for production).
    Requires: admin role.
    """
    try:
        import asyncio

        from ml.rl_agent import ForexTradingEnv, RLAgent

        # Load candles from the data layer
        df = _load_ohlcv_for_symbol(req.symbol, req.candles)
        candles_list = df.to_dict("records")

        split = int(len(candles_list) * req.train_split)
        train_c = candles_list[:split]
        test_c = candles_list[split:]

        agent = RLAgent(model_name=f"hopefx_ppo_{req.symbol.lower()}")

        train_env = ForexTradingEnv(train_c)
        test_env = ForexTradingEnv(test_c)

        # Run in thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: agent.train(train_env, timesteps=req.timesteps, verbose=0),
        )
        metrics = await loop.run_in_executor(None, lambda: agent.evaluate(test_env))

        return {
            "status": "trained",
            "symbol": req.symbol,
            "timeframe": req.timeframe,
            "train_candles": len(train_c),
            "test_candles": len(test_c),
            "timesteps": req.timesteps,
            "model_path": agent.model_path,
            "metrics": metrics,
        }
    except ImportError as exc:
        logger.error("rl_train: missing RL dependencies: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RL dependencies not installed — check server logs",
        ) from None
    except Exception as exc:
        logger.error("rl_train failed: %s", exc)
        raise HTTPException(status_code=500, detail="RL training failed — check server logs") from None


@router.post("/rl/walk-forward", tags=["ML Models"])
async def rl_walk_forward(
    req: RLWalkForwardRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    """
    Run walk-forward evaluation of the PPO agent.
    Returns per-fold metrics and aggregate stability score.
    Requires: admin role.
    """
    try:
        import asyncio
        from dataclasses import asdict

        from ml.rl_agent import walk_forward_eval

        df = _load_ohlcv_for_symbol(req.symbol, req.candles)
        candles_list = df.to_dict("records")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: walk_forward_eval(
                candles=candles_list,
                symbol=req.symbol,
                timeframe=req.timeframe,
                n_folds=req.n_folds,
                timesteps_per_fold=req.timesteps_per_fold,
                train_pct=req.train_pct,
            ),
        )

        return asdict(result)

    except ImportError as exc:
        logger.error("rl_walk_forward: missing RL dependencies: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RL dependencies not installed — check server logs",
        ) from None
    except Exception as exc:
        logger.error("rl_walk_forward failed: %s", exc)
        raise HTTPException(status_code=500, detail="RL walk-forward failed — check server logs") from None


@router.get("/rl/status", tags=["ML Models"])
async def rl_status(user: TokenPayload = Depends(get_current_user)) -> dict:
    """Return saved RL model files and their sizes."""
    from ml.rl_agent import _MODEL_DIR

    models = []
    if Path(_MODEL_DIR).is_dir():
        for fname in sorted(os.listdir(_MODEL_DIR)):
            if fname.endswith(".zip"):
                fpath = Path(_MODEL_DIR) / fname
                models.append(
                    {
                        "name": fname,
                        "size_kb": round(os.path.getsize(fpath) / 1024, 1),
                        "modified": os.path.getmtime(fpath),
                    }
                )

    return {
        "model_dir": _MODEL_DIR,
        "models": models,
        "count": len(models),
    }


# ── Model Card ─────────────────────────────────────────────────────────────────


@router.get(
    "/model-card",
    summary="Formal Model Card — metadata, performance, drift status, limitations",
    response_description=(
        "Structured Model Card for the currently active production model, following the Google Model Card 1.0 schema."
    ),
)
async def get_model_card(
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return a formal Model Card for the active production ML model.

    The card includes:
    - **model_details**: name, version, type, training date, authors
    - **intended_use**: trading signals for XAU/USD, not financial advice
    - **training_data**: source, date range, feature count, OOS split
    - **evaluation_results**: OOS accuracy, AUC, F1, Sharpe, walk-forward fold stats
    - **drift_status**: live feature-distribution drift from the inference engine
    - **quantitative_analysis**: feature importances (top 10), regime filter status
    - **caveats_and_recommendations**: known limitations and risk warnings

    Accessible by any authenticated user.  Useful for regulatory transparency,
    model governance, and live monitoring dashboards.
    """
    import json
    import pathlib

    saved_dir = pathlib.Path(__file__).parent.parent / "ml" / "saved_models"
    registry_path = saved_dir / "registry.json"
    report_path = saved_dir / "advanced_training_report.json"
    feature_stats_path = saved_dir / "feature_stats.json"
    feat_imp_path = saved_dir / "feature_importances.json"

    # ── Load model registry ──────────────────────────────────────────────
    registry: dict[str, Any] = {}
    active_meta: dict[str, Any] = {}
    try:
        if registry_path.exists():
            registry = json.loads(registry_path.read_text())
            active_version = registry.get("active_version", "")
            active_meta = registry.get("versions", {}).get(active_version, {})
    except Exception as exc:
        logger.warning("model_card: could not read registry.json: %s", exc)

    # ── Load training report ─────────────────────────────────────────────
    training_report: dict[str, Any] = {}
    try:
        if report_path.exists():
            training_report = json.loads(report_path.read_text())
    except Exception as exc:
        logger.warning("model_card: could not read training report: %s", exc)

    # ── Load drift / feature stats ───────────────────────────────────────
    feature_stats: dict[str, Any] = {}
    try:
        if feature_stats_path.exists():
            _raw_stats = json.loads(feature_stats_path.read_text())
            # surface top-level keys for the drift section
            feature_stats["_available"] = True
            feature_stats.update({k: v for k, v in _raw_stats.items() if not isinstance(v, dict)})
    except Exception as exc:
        logger.warning("model_card: could not read feature_stats.json: %s", exc)

    # ── Load feature importances ─────────────────────────────────────────
    feature_importances: list[dict] = []
    try:
        if feat_imp_path.exists():
            raw = json.loads(feat_imp_path.read_text())
            # Accept list[{feature, importance}] or dict{feature: importance}
            if isinstance(raw, dict):
                feature_importances = sorted(
                    [{"feature": k, "importance": v} for k, v in raw.items() if v is not None],
                    key=lambda x: x["importance"],
                    reverse=True,
                )[:10]
            elif isinstance(raw, list):
                feature_importances = raw[:10]
        elif active_meta.get("top_features"):
            # Fall back to registry top_features list
            feature_importances = [{"feature": f, "importance": None} for f in active_meta["top_features"][:10]]
    except Exception as exc:
        logger.warning("model_card: could not load feature importances: %s", exc)

    # ── Live drift status from inference engine ──────────────────────────
    drift_status: dict[str, Any] = {"available": False}
    try:
        eng = _get_predictor()
        if eng is not None:
            drift_status = {
                "available": True,
                "drift_detected": getattr(eng, "_drift_detected", False),
                "drift_z_max": round(getattr(eng, "_drift_z_max", 0.0), 3),
                "drift_z_threshold": float(os.getenv("DRIFT_Z_THRESHOLD", "4.0")),
                "drift_window": int(os.getenv("DRIFT_WINDOW", "50")),
                "block_on_drift": os.getenv("DRIFT_BLOCK", "false").lower() == "true",
            }
        # Enhance with PSI + KS-test from DriftMonitor
        try:
            from ml.drift_monitor import get_drift_monitor

            monitor = get_drift_monitor()
            # Expose monitor configuration in the card
            drift_status["psi_monitor_loaded"] = monitor._stats != {}
            drift_status["psi_red_threshold"] = 0.25
            drift_status["psi_yellow_threshold"] = 0.10
            drift_status["ks_p_threshold"] = 0.05
            drift_status["framework"] = "z-score + PSI + KS-test (production)"
        except Exception:
            drift_status["framework"] = "z-score (lightweight)"
    except Exception as exc:
        logger.debug("model_card: could not get drift status: %s", exc)

    # ── Walk-forward fold summary ────────────────────────────────────────
    wf = active_meta.get("walk_forward") or training_report.get("walk_forward") or {}

    # ── Build the Model Card response ────────────────────────────────────
    version = active_meta.get("name") or registry.get("active_version") or "unknown"
    promoted_at = active_meta.get("promoted_at") or active_meta.get("registered_at") or ""

    card: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "model_details": {
            "name": "HOPEFX XAU/USD Signal Classifier",
            "version": version,
            "type": active_meta.get("ensemble", "XGBoost gradient boosted trees"),
            "task": "Binary classification — next-N-bar directional signal (BUY / SELL)",
            "horizon_bars": active_meta.get("horizon", 5),
            "symbol": active_meta.get("symbol", "GC=F (XAU/USD)"),
            "promoted_at": promoted_at,
            "registry_state": active_meta.get("state", "active"),
            "pkl_file": active_meta.get("file", ""),
            "sha256": active_meta.get("sha256", ""),
            "authors": ["HOPEFX AI Team"],
            "license": "AGPL-3.0",
        },
        "intended_use": {
            "primary_use": (
                "Generate directional trading signals for XAU/USD (Gold) on daily bars. "
                "Signals are consumed by the HopeFXEngine for paper and live execution."
            ),
            "out_of_scope": [
                "Financial advice or investment recommendations for end users",
                "Real-time tick-level prediction (model uses daily bars)",
                "Instruments other than XAU/USD without re-training",
                "Leveraged position sizing beyond configured risk limits",
            ],
            "intended_users": ["Automated trading system only — not for direct human trading decisions"],
        },
        "training_data": {
            "source": "Yahoo Finance (yfinance GC=F) — daily OHLCV bars",
            "symbol": active_meta.get("symbol", "GC=F"),
            "years": active_meta.get("years", "~50"),
            "oos_years": active_meta.get("oos_years", 8),
            "oos_period": active_meta.get("oos_period", ""),
            "feature_count": active_meta.get("feature_count", 0),
            "feature_layers": active_meta.get("feature_layers", ["base", "extended"]),
            "macro_features": active_meta.get("macro_features", True),
            "n_trades_oos": active_meta.get("n_trades", 0),
        },
        "evaluation_results": {
            "oos_accuracy": active_meta.get("oos_accuracy"),
            "oos_auc": active_meta.get("oos_auc"),
            "oos_f1": active_meta.get("oos_f1"),
            "oos_p_value": active_meta.get("oos_p_value"),
            "oos_significant": active_meta.get("oos_significant", True),
            "sharpe": active_meta.get("sharpe"),
            "sharpe_se": active_meta.get("sharpe_se"),
            "sharpe_gate_passed": active_meta.get("sharpe_gate_passed"),
            "cv_accuracy": active_meta.get("cv_accuracy"),
            "cv_accuracy_std": active_meta.get("cv_accuracy_std"),
            "walk_forward": {
                "folds": wf.get("folds", 6),
                "mean_accuracy": wf.get("mean_accuracy"),
                "std_accuracy": wf.get("std_accuracy"),
                "mean_f1": wf.get("mean_f1"),
                "mean_auc": wf.get("mean_auc"),
                "regime_filter_applied": wf.get("regime_filter_applied", True),
                "fold2_note": wf.get(
                    "fold2_note",
                    "Fold-2 below-chance accuracy caused by parabolic-bubble regime. "
                    "Filter active. See docs/FOLD2_REGIME_ANALYSIS.md.",
                ),
            },
        },
        "quantitative_analysis": {
            "feature_importances_top10": feature_importances,
            "abstain_threshold": active_meta.get("abstain_threshold"),
            "abstain_rate": active_meta.get("abstain_rate"),
            "regime_filter": {
                "enabled": True,
                "type": "HIGH_VOL_PARABOLIC",
                "rule": ("Abstain when close > 1.30 × MA200 OR (RV14 > 2.5 × RV90 AND close ≤ 75% of 200-bar peak)"),
                "reference": "docs/FOLD2_REGIME_ANALYSIS.md",
            },
        },
        "drift_monitoring": drift_status,
        "caveats_and_recommendations": {
            "known_limitations": [
                "Walk-forward Fold-2 (gold parabolic bubble ~2011-2012) showed 44.4% accuracy. "
                "Regime filter mitigates this but extreme market regimes may still degrade performance.",
                "CV accuracy (99%) is inflated by CalibratedClassifierCV in-sample leakage. "
                "OOS accuracy (59.9%) is the reliable performance estimate.",
                "Model is trained on daily bars only. Intraday volatility is not captured.",
                "Macro features (WGC data, DXY) are fetched at startup and may lag by 1–2 days.",
            ],
            "risk_warnings": [
                "PAST PERFORMANCE IS NOT INDICATIVE OF FUTURE RESULTS.",
                "This model produces signals, not guarantees. All trades carry risk of loss.",
                "Daily loss limits, drawdown limits, and kill-switch mechanisms must remain active.",
                "Paper trading mode is the default. Live trading requires explicit opt-in.",
            ],
            "recommended_monitoring": [
                "Check /api/ml/model-card?drift_status.drift_detected daily",
                "If drift_z_max > 4.0, investigate feature pipeline health",
                "Compare rolling 30-day accuracy vs OOS baseline (target: within 5pp)",
                "Review walk-forward Fold-2 regime filter activation rate weekly",
            ],
        },
        "notes": active_meta.get("notes", ""),
    }

    return card


@router.get(
    "/drift-report",
    summary="Real-time feature drift report (PSI + KS-test)",
    tags=["ML Models"],
)
async def get_drift_report() -> dict:
    """
    Compute and return a statistical drift report for the live feature distribution.

    Uses PSI (Population Stability Index) and the two-sample Kolmogorov-Smirnov
    test to identify features whose distribution has shifted significantly from
    the training distribution.

    Thresholds:
    - PSI < 0.10 → green (no significant drift)
    - PSI 0.10–0.25 → yellow (investigate)
    - PSI > 0.25 → red (retrain recommended)
    - KS p-value < 0.05 → distributions significantly different

    Returns:
        Full ``DriftReport`` in JSON — overall_status, requires_retrain flag,
        per-feature PSI/KS/z-score breakdown (top 20 by PSI).
    """
    try:
        from ml.drift_monitor import get_drift_monitor

        monitor = get_drift_monitor()

        # Pull live feature buffer from InferenceEngine if available
        live_features = None
        try:
            eng = _get_predictor()
            if eng is not None and hasattr(eng, "_drift_buffer") and len(eng._drift_buffer) >= 50:
                import numpy as np
                import pandas as pd

                arr = np.array(list(eng._drift_buffer))
                # Column names from cached feature list
                col_names = getattr(eng, "_last_feature_names", None)
                if col_names and len(col_names) == arr.shape[1]:
                    live_features = pd.DataFrame(arr, columns=col_names)
                else:
                    live_features = pd.DataFrame(arr)
        except Exception:
            pass

        if live_features is None:
            return {
                "overall_status": "unknown",
                "message": "Insufficient live feature data (need ≥50 ticks). "
                "Start live inference to populate the drift buffer.",
                "requires_retrain": False,
                "live_samples": 0,
            }

        report = monitor.compute(live_features)
        return report.to_dict()

    except Exception as exc:
        logger.error("drift_report: unexpected error: %s", exc)
        return {
            "overall_status": "error",
            "error": str(exc),
            "requires_retrain": False,
            "live_samples": 0,
        }
