# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Signal Engine — bridges StrategyBrain to live order execution.

Runs as a background asyncio task. On each tick:
1. Fetches live OHLCV from yfinance (or broker price feed)
2. Runs StrategyBrain.analyze_joint()
3. If consensus reached → passes signal through RiskManager
4. If approved → places order via broker
5. Broadcasts result over WebSocket
6. Logs to ComplianceManager audit trail

Phase chain (Phases 1–4 are optional and gated by feature flags):
  Phase 1: MTFFusionStore — H4/D1 regime features appended at inference
  Phase 2: AnomalyWeightStore — down-weight signals on anomalous bars
  Phase 3: OnlineLearnerStore — incremental XGBoost blend on confirmed fills
  Phase 4: DeepEnsembleStore — LSTM/Transformer/TCN/Hybrid stacking
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── MacroStore (populated at startup by init_macro_store) ─────────────────────
# Imported lazily so the signal engine can start even if ml is unavailable.
def _get_macro_store() -> Any | None:
    """Return the module-level MacroStore singleton, or None if unavailable."""
    try:
        from ml.macro_store import macro_store

        return macro_store
    except ImportError:
        return None


def _get_macro_store_bridge() -> Any | None:
    """
    Return the MacroStoreBridge via the orchestrator — the single entry point.

    The bridge is the primary FRED-backed macro source.  It is started by
    init_macro_store() in startup_factories.py and populates the MacroStore
    singleton automatically.  This accessor is used here to pull the latest
    real-time snapshot values for feature augmentation at inference time.

    Architecture rule: access via orchestrator._macro_bridge, never by
    importing data_layer.feeds.macro.store_bridge directly.
    """
    try:
        from data_layer.orchestrator import orchestrator

        bridge = orchestrator._macro_bridge
        return bridge if bridge.is_loaded else None
    except ImportError:
        return None


# ── Advanced ML predictor (122-feature, 68% OOS accuracy) ────────────────────
try:
    from ml import get_active_model, get_advanced_predictor, get_model_version

    _ML_AVAILABLE: bool = True
except ImportError:
    _ML_AVAILABLE = False

# ── Anomaly weight store (Phase 2 — down-weight signals on anomalous bars) ────
_anomaly_store: Any | None = None

# ── Online learner store (Phase 3 — incremental XGBoost + drift detection) ───
_online_learner_store: Any | None = None

# ── Deep ensemble store (Phase 4 — LSTM/Transformer/TCN stacking) ────────────
_deep_ensemble_store: Any | None = None


def _get_deep_ensemble_store() -> Any | None:
    """Return the module-level DeepEnsembleStore singleton, loading on first call."""
    global _deep_ensemble_store
    try:
        from config.feature_flags import flags

        if not flags.DEEP_ENSEMBLE:
            return None
    except ImportError:
        return None
    if _deep_ensemble_store is None:
        try:
            from research.pipeline.models_ensemble import DeepEnsembleStore

            store = DeepEnsembleStore()
            if store.load():
                _deep_ensemble_store = store
                logger.info(
                    "DeepEnsembleStore active (OOS=%.1f%%, p=%.4f)",
                    store.oos_accuracy * 100,
                    store.p_value,
                )
            else:
                # Store a sentinel so we don't retry on every tick
                _deep_ensemble_store = False  # type: ignore[assignment]
        except Exception as exc:
            logger.debug("DeepEnsembleStore init failed: %s", exc)
            _deep_ensemble_store = False  # type: ignore[assignment]
    # Return None for the sentinel (False) so callers get a clean None
    return _deep_ensemble_store if _deep_ensemble_store else None


def _get_online_learner_store() -> Any | None:
    """Return the module-level OnlineLearnerStore singleton, creating it on first call."""
    global _online_learner_store
    try:
        from config.feature_flags import flags

        if not flags.ONLINE_LEARNING:
            return None
    except ImportError:
        return None
    if _online_learner_store is None:
        try:
            from research.pipeline.online_learning import OnlineLearnerStore

            _online_learner_store = OnlineLearnerStore()
            logger.info("OnlineLearnerStore initialised (Phase 3)")
        except Exception as exc:
            logger.debug("OnlineLearnerStore init failed: %s", exc)
    return _online_learner_store


def _get_anomaly_store() -> Any | None:
    """Return the module-level AnomalyWeightStore singleton, creating it on first call."""
    global _anomaly_store
    try:
        from config.feature_flags import flags

        if not flags.ANOMALY_WEIGHTING:
            return None
    except ImportError:
        return None
    if _anomaly_store is None:
        try:
            from research.pipeline.anomaly import AnomalyWeightStore

            _anomaly_store = AnomalyWeightStore()
            logger.info("AnomalyWeightStore initialised (Phase 2)")
        except Exception as exc:
            logger.debug("AnomalyWeightStore init failed: %s", exc)
    return _anomaly_store


if not _ML_AVAILABLE:
    # Provide no-op stubs so the rest of the module can reference these names
    def get_active_model() -> Any | None:  # type: ignore[misc]  # pylint: disable=function-redefined
        return None

    def get_model_version() -> str:  # type: ignore[misc]  # pylint: disable=function-redefined
        return "none"

    def get_advanced_predictor() -> Any | None:  # type: ignore[misc]  # pylint: disable=function-redefined
        return None


# Symbols the engine watches (overridden by ALLOWED_SYMBOLS env var)

_SYMBOLS = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")
_INTERVAL_SECONDS = int(os.getenv("SIGNAL_ENGINE_INTERVAL", "60"))
_AUTO_TRADE = os.getenv("SIGNAL_ENGINE_AUTO_TRADE", "false").lower() == "true"


async def _fetch_market_data(
    symbol: str,
    app_state: Any = None,
) -> dict[str, Any] | None:
    """
    Fetch latest OHLCV data for a symbol from the broker's market data feed.

    Returns None when OHLCV history is unavailable — callers must skip the
    signal tick rather than proceeding with insufficient data. A single-point
    degenerate bar (open=high=low=close, volume=0) produces zero ATR, zero
    range, and zero volume features that corrupt ML model inputs.
    """
    broker = getattr(app_state, "broker", None) if app_state is not None else None

    if broker is not None:
        try:
            bars = broker.get_market_data(symbol, timeframe="1h", limit=100)
            if bars:
                last = bars[-1]
                prices = [float(b["close"]) for b in bars]
                highs = [float(b["high"]) for b in bars]
                lows = [float(b["low"]) for b in bars]
                volumes = [float(b.get("volume", 0)) for b in bars]
                return {
                    "symbol": symbol,
                    "open": float(last["open"]),
                    "high": float(last["high"]),
                    "low": float(last["low"]),
                    "close": float(last["close"]),
                    "volume": float(last.get("volume", 0)),
                    "prices": prices,
                    "highs": highs,
                    "lows": lows,
                    "volumes": volumes,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
        except Exception as exc:
            logger.warning("Broker OHLCV fetch failed for %s: %s", symbol, exc)
    else:
        logger.warning("No broker available — cannot fetch market data for %s", symbol)

    return None


async def run_signal_engine(app_state: Any) -> None:
    """
    Main signal engine loop. Runs indefinitely until cancelled.
    Attach to app startup via asyncio.create_task().
    """
    logger.info(
        "Signal engine started — symbols=%s interval=%ss auto_trade=%s",
        _SYMBOLS,
        _INTERVAL_SECONDS,
        _AUTO_TRADE,
    )

    while True:
        try:
            await _tick(app_state)
        except asyncio.CancelledError:
            logger.info("Signal engine stopped")
            return
        except Exception as exc:
            logger.error("Signal engine tick error: %s", exc)

        await asyncio.sleep(_INTERVAL_SECONDS)


# ── _tick sub-functions ───────────────────────────────────────────────────────
# _tick() was 290 lines. Split into four focused functions (each ≤70 lines)
# so bugs in signal generation and order execution are easy to isolate.


def _compute_signal(
    brain: Any,
    data: dict[str, Any],
    symbol: str,
) -> dict[str, Any] | None:
    """
    Run StrategyBrain and return a signal dict, or None if no consensus.

    Returns dict with keys: direction, base_confidence, signal (raw object).
    """
    result: dict[str, Any] = brain.analyze_joint(data)
    if not result.get("consensus_reached"):
        logger.debug("No consensus for %s: %s", symbol, result.get("reason"))
        return None

    signal: Any = result.get("consensus_signal")
    if signal is None:
        return None

    direction: str = signal.signal_type.value if hasattr(signal.signal_type, "value") else str(signal.signal_type)
    return {
        "direction": direction,
        "base_confidence": getattr(signal, "confidence", 0.0),
        "signal": signal,
    }


def _build_ohlcv_df(data: dict[str, Any]) -> "pd.DataFrame":
    """
    Reconstruct a rolling OHLCV DataFrame from the broker bar list.

    The broker feed provides up to 100 bars. The advanced predictor needs
    >= 100 bars for reliable rolling-window feature computation.
    """
    import pandas as pd

    prices = data.get("prices", [data["close"]])
    highs = data.get("highs", [data["high"]])
    lows = data.get("lows", [data["low"]])
    volumes = data.get("volumes", [data.get("volume", 0)])
    n = len(prices)

    ohlcv_df = pd.DataFrame(
        {
            "open": prices,  # open not tracked per-bar; use close as proxy
            "high": highs if len(highs) == n else prices,
            "low": lows if len(lows) == n else prices,
            "close": prices,
            "volume": volumes if len(volumes) == n else [0.0] * n,
        },
    )
    # Overwrite last bar with actual OHLCV from the tick
    ohlcv_df.iloc[-1] = [
        data["open"],
        data["high"],
        data["low"],
        data["close"],
        data.get("volume", 0),
    ]
    return ohlcv_df


def _fetch_macro_df(
    ohlcv_df: "pd.DataFrame",
    symbol: str,
) -> Optional["pd.DataFrame"]:
    """
    Build a macro feature DataFrame for the given OHLCV window.

    Two-stage pipeline:
      1. Align MacroStore time-series to the OHLCV hourly index (historical
         context — the same path as before).
      2. Overlay the latest real-time FRED snapshot values from
         MacroStoreBridge onto the last row so the model always sees the
         most current macro state at inference time.

    Returns a DataFrame of macro features or None if both stages fail.
    None is safe — the predictor falls back to OHLCV-only features.
    """
    import pandas as pd

    _store = _get_macro_store()
    if _store is None or len(_store) == 0:
        logger.debug(
            "MacroStore empty for %s — advanced model on OHLCV features only (accuracy may be lower than 68%%)",
            symbol,
        )
        return None

    try:
        ohlcv_indexed = ohlcv_df.copy()
        if not isinstance(ohlcv_indexed.index, pd.DatetimeIndex):
            end_ts = datetime.now(UTC)
            idx = pd.date_range(
                end=end_ts,
                periods=len(ohlcv_indexed),
                freq=pd.tseries.frequencies.to_offset("1h"),
                tz="UTC",
            )
            ohlcv_indexed.index = idx

        macro_df = _store.align_to_hourly(ohlcv_indexed)
        if macro_df.empty or macro_df.shape[1] == 0:
            logger.debug(
                "MacroStore returned empty alignment for %s — running advanced model without macro features",
                symbol,
            )
            return None

        logger.debug("MacroStore aligned %d series for %s", macro_df.shape[1], symbol)

        # ── Stage 2: overlay real-time FRED snapshot on the last row ─────────
        # MacroStoreBridge.get_ml_features() returns the most recent FRED
        # observation for each series (prefixed macro_*).  We overwrite the
        # last row of macro_df so the model sees today's values rather than
        # yesterday's close-of-day values from the CSV/align path.
        bridge = _get_macro_store_bridge()
        if bridge is not None:
            try:
                rt_features = bridge.get_ml_features()
                if rt_features:
                    for col_key, val in rt_features.items():
                        # col_key is "macro_dxy", "macro_us10y", etc.
                        # macro_df columns may be "dxy", "us10y", etc. — strip prefix.
                        bare = col_key.replace("macro_", "")
                        if bare in macro_df.columns:
                            macro_df.iloc[-1, macro_df.columns.get_loc(bare)] = val
                        elif col_key in macro_df.columns:
                            macro_df.iloc[-1, macro_df.columns.get_loc(col_key)] = val
                    logger.debug(
                        "FRED real-time overlay applied to last row for %s (%d features)",
                        symbol,
                        len(rt_features),
                    )
            except Exception as rt_exc:
                logger.debug(
                    "FRED real-time overlay failed (non-fatal) for %s: %s",
                    symbol,
                    rt_exc,
                )

        return macro_df

    except Exception as exc:
        logger.warning(
            "MacroStore alignment failed for %s: %s — running advanced model without macro features",
            symbol,
            exc,
        )
        return None


def _fetch_mtf_df(
    ohlcv_df: "pd.DataFrame",
    app_state: Any = None,
) -> Any | None:
    """
    Fetch MTF regime features from MTFFusionStore if available and enabled.

    Returns a DataFrame with d_*/h_* columns aligned to ohlcv_df.index,
    or None when the store is unavailable or the flag is off.
    """
    try:
        from config.feature_flags import flags

        if not flags.MTF_FUSION:
            return None
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # Try app_state first (populated by init_mtf_store at startup)
    store = getattr(app_state, "mtf_store", None)
    if store is None:
        # Module-level singleton fallback
        try:
            from research.pipeline.mtf_fusion import _MTF_STORE_SINGLETON

            store = _MTF_STORE_SINGLETON
        except ImportError:
            return None

    if store is None or not getattr(store, "is_ready", False):
        return None

    try:
        return store.align_to_h1(ohlcv_df)
    except Exception as exc:
        logger.debug("MTF align_to_h1 failed: %s", exc)
        return None


def _apply_anomaly_weighting(prob: float, ohlcv_df: Any, symbol: str) -> float:
    """
    Phase 2: blend probability toward neutral when the bar is anomalous.

    Returns the adjusted probability unchanged when the store is unavailable
    or the anomaly weight is 1.0 (no anomaly detected).
    """
    store = _get_anomaly_store()
    if store is None:
        return prob
    try:
        weight = store.update_and_score(ohlcv_df)
        if weight < 1.0:
            adjusted = 0.5 + (prob - 0.5) * weight
            logger.debug("Phase2 anomaly: weight=%.2f %s %.4f→%.4f", weight, symbol, prob, adjusted)
            return adjusted
    except Exception as exc:
        logger.debug("Anomaly weighting failed (non-fatal): %s", exc)
    return prob


def _apply_online_blend(prob: float, ohlcv_df: Any, symbol: str) -> float:
    """Phase 3: incremental XGBoost blend on confirmed fills."""
    store = _get_online_learner_store()
    if store is None or not store.is_ready:
        return prob
    try:
        blended = store.blend(prob, ohlcv_df)
        logger.debug("Phase3 online blend: %s → %.4f", symbol, blended)
        return blended
    except Exception as exc:
        logger.debug("Online learner blend failed (non-fatal): %s", exc)
    return prob


def _apply_deep_ensemble_blend(prob: float, ohlcv_df: Any, symbol: str) -> float:
    """Phase 4: LSTM/Transformer/TCN stacking blend."""
    store = _get_deep_ensemble_store()
    if store is None or not store.is_active:
        return prob
    try:
        blended = store.blend(prob, ohlcv_df)
        logger.debug("Phase4 deep blend: %s → %.4f", symbol, blended)
        return blended
    except Exception as exc:
        logger.debug("Deep ensemble blend failed (non-fatal): %s", exc)
    return prob


def _predict_advanced(
    adv_predictor: Any,
    data: dict[str, Any],
    symbol: str,
    app_state: Any,
) -> tuple:
    """
    Run the full advanced ML chain (Phases 1–4) and return (prob, version).

    Phase 1: advanced_oos.pkl with macro + MTF features (122+ features, 68% OOS).
    Phase 2: anomaly weighting — down-weight on anomalous bars.
    Phase 3: online learning blend — incremental XGBoost.
    Phase 4: deep ensemble blend — LSTM/Transformer/TCN stacking.

    Timeframe alignment
    -------------------
    The model was trained on daily bars (GC=F, interval="1d").  The broker
    feed provides H1 bars (timeframe="1h").  Before calling the model, H1
    bars are resampled to daily so the model's rolling-window features and
    calibration thresholds remain valid.  Anomaly weighting, online blend,
    and deep ensemble blend all receive the same daily-resampled DataFrame.
    """
    import pandas as _pd

    ohlcv_df = _build_ohlcv_df(data)

    # ── Timeframe alignment: resample H1 → daily before model inference ───────
    model_df = ohlcv_df
    try:
        from ml.daily_aggregator import ensure_daily, needs_resampling

        if needs_resampling(ohlcv_df):
            # Assign a proper DatetimeIndex so the resampler can work
            if not isinstance(ohlcv_df.index, _pd.DatetimeIndex):
                from datetime import datetime, timezone as _tz

                idx = _pd.date_range(
                    end=datetime.now(_tz.utc),
                    periods=len(ohlcv_df),
                    freq="1h",
                    tz="UTC",
                )
                ohlcv_df = ohlcv_df.copy()
                ohlcv_df.index = idx
            resampled = ensure_daily(ohlcv_df, min_bars=100)
            if resampled is not None:
                model_df = resampled
                logger.debug(
                    "_predict_advanced: resampled %d H1 → %d daily bars for %s",
                    len(ohlcv_df),
                    len(model_df),
                    symbol,
                )
            else:
                logger.debug(
                    "_predict_advanced: insufficient daily bars after resampling "
                    "(%d H1 bars) — returning neutral 0.5 for %s",
                    len(ohlcv_df),
                    symbol,
                )
                return 0.5, adv_predictor.version
    except Exception as _re:
        logger.debug("_predict_advanced: resampling skipped: %s", _re)

    macro_df = _fetch_macro_df(model_df, symbol)
    mtf_df = _fetch_mtf_df(model_df, app_state=app_state)

    prob = adv_predictor.predict_proba(
        model_df,
        macro_df=macro_df,
        symbol=symbol,
        mtf_df=mtf_df,
    )
    prob = _apply_anomaly_weighting(prob, model_df, symbol)
    prob = _apply_online_blend(prob, model_df, symbol)
    prob = _apply_deep_ensemble_blend(prob, model_df, symbol)

    logger.debug(
        "ML chain (%s) %s: final=%.4f [macro=%s mtf=%s daily_bars=%d]",
        adv_predictor.version,
        symbol,
        prob,
        "yes" if macro_df is not None else "no",
        "yes" if mtf_df is not None else "no",
        len(model_df),
    )
    return float(prob), adv_predictor.version


def _predict_basic(
    active_model: Any,
    model_ver: str,
    data: dict[str, Any],
    symbol: str,
    base_confidence: float,
) -> tuple:
    """
    Run the basic fallback model (~50% OOS, stationary OHLCV features).

    Returns (prob, model_ver).
    """
    import pandas as pd

    prices = data.get("prices", [data["close"]])
    closes = pd.Series(prices)
    feat = {
        "close": data["close"],
        "open": data["open"],
        "high": data["high"],
        "low": data["low"],
        "volume": data.get("volume", 0),
        "ret_1": closes.pct_change(1).iloc[-1] if len(closes) > 1 else 0,
        "ret_5": closes.pct_change(5).iloc[-1] if len(closes) > 5 else 0,
        "ret_20": closes.pct_change(20).iloc[-1] if len(closes) > 20 else 0,
        "vol_20": (
            closes.pct_change().rolling(20).std().iloc[-1] if len(closes) > 20 else 0
        ),
    }
    X = pd.DataFrame([feat])

    if hasattr(active_model, "predict_proba"):
        proba = active_model.predict_proba(X)
        prob = float(proba[0][1]) if proba.shape[1] > 1 else float(proba[0][0])
    elif hasattr(active_model, "predict"):
        prob = float(active_model.predict(X)[0])
    else:
        prob = base_confidence

    logger.debug("Basic ML (%s) prob for %s: %.4f", model_ver, symbol, prob)
    return prob, model_ver


def _compute_ml_probability(
    data: dict[str, Any],
    symbol: str,
    base_confidence: float,
    app_state: Any = None,
) -> tuple:
    """
    Compute ML probability using the best available model.

    Returns (ml_probability: float, model_version: str).

    Path 1 (preferred): advanced_oos.pkl — full macro + MTF feature set.
    Path 2 (fallback):  basic xgb_macro.pkl — stationary OHLCV features.
    Path 3 (no model):  returns base_confidence unchanged.
    """
    if not _ML_AVAILABLE:
        return base_confidence, "none"

    try:
        adv_predictor = get_advanced_predictor()
        if adv_predictor is not None and adv_predictor.is_available:
            return _predict_advanced(adv_predictor, data, symbol, app_state)

        active_model = get_active_model()
        model_ver = get_model_version()
        if active_model is not None:
            return _predict_basic(active_model, model_ver, data, symbol, base_confidence)

    except Exception as exc:
        logger.debug("ML enrichment failed for %s: %s", symbol, exc)

    return base_confidence, "none"


def notify_fill(
    features: "pd.DataFrame",
    label: int,
    primary_prob: float | None = None,
) -> None:
    """
    Notify the online learner of a confirmed fill (Phase 3).

    Call this from the execution path after a trade is confirmed:
        from core.signal_engine import notify_fill
        notify_fill(feature_df, label=1, primary_prob=0.72)

    Parameters
    ----------
    features     : Feature DataFrame for the filled bar.
    label        : 1 if the trade was profitable, 0 otherwise.
    primary_prob : Primary model probability at signal time (used by
                   AdaptiveBlendWeights to update primary/online weights).

    Safe to call when FEATURE_ONLINE_LEARNING=false — no-op in that case.
    """
    store = _get_online_learner_store()
    if store is None:
        return
    try:
        store.on_fill(features, label, primary_prob=primary_prob)
    except Exception as exc:
        logger.debug("notify_fill failed (non-fatal): %s", exc)


# ── Factor model integration ──────────────────────────────────────────────────
# The LiveFactorEngine is started by startup_factories.py and stored on
# app_state.factor_engine.  The signal engine reads factor exposures and
# appends them to the signal payload so downstream consumers (risk manager,
# compliance, WebSocket) can see the factor breakdown without re-computing it.


def _get_factor_engine(app_state: Any = None) -> Any | None:
    """Return the LiveFactorEngine from app_state or the module singleton."""
    if app_state is not None:
        engine = getattr(app_state, "factor_engine", None)
        if engine is not None:
            return engine
    try:
        from portfolio.factor_model import get_live_factor_engine

        return get_live_factor_engine()
    except ImportError:
        return None


def _enrich_signal_with_factors(
    signal_payload: dict[str, Any],
    positions: dict[str, float],
    total_pnl: float,
    app_state: Any = None,
) -> dict[str, Any]:
    """
    Append live factor attribution to a signal payload.

    Adds ``factor_attribution`` key with factor P&L breakdown and
    ``factor_exposures`` key with per-symbol beta loadings.

    Non-blocking: returns the original payload unchanged on any error.
    """
    engine = _get_factor_engine(app_state)
    if engine is None:
        return signal_payload

    try:
        attribution = engine.attribute(positions, total_pnl)
        exposures = {sym: exp.to_dict() for sym, exp in engine.exposures.items()}
        signal_payload["factor_attribution"] = attribution.to_dict()
        signal_payload["factor_exposures"] = exposures
        logger.debug(
            "Factor attribution appended: residual_pnl=%.4f",
            attribution.residual_pnl,
        )
    except Exception as exc:
        logger.debug("Factor enrichment failed (non-fatal): %s", exc)

    return signal_payload


def get_signal_engine_status() -> dict[str, Any]:
    """
    Return a health-check dict for all active Phase 1–4 stores.

    Suitable for exposing via a /health or /status API endpoint.
    """
    status: dict[str, Any] = {
        "ml_available": _ML_AVAILABLE,
        "symbols": _SYMBOLS,
        "interval_seconds": _INTERVAL_SECONDS,
        "auto_trade": _AUTO_TRADE,
    }

    # Phase 1: MTF
    try:
        from config.feature_flags import flags

        status["phase1_mtf_enabled"] = getattr(flags, "MTF_FUSION", True)
    except ImportError:
        status["phase1_mtf_enabled"] = None

    try:
        from research.pipeline.mtf_fusion import _MTF_STORE_SINGLETON

        if _MTF_STORE_SINGLETON is not None:
            status["phase1_mtf"] = _MTF_STORE_SINGLETON.status()
        else:
            status["phase1_mtf"] = {"is_ready": False}
    except Exception:  # nosec B110
        status["phase1_mtf"] = {"is_ready": False}

    # Phase 2: Anomaly
    anomaly = _get_anomaly_store()
    if anomaly is not None and hasattr(anomaly, "status"):
        status["phase2_anomaly"] = anomaly.status()
    else:
        status["phase2_anomaly"] = {"fitted": False}

    # Phase 3: Online learner
    online = _get_online_learner_store()
    if online is not None and hasattr(online, "status"):
        status["phase3_online"] = online.status()
    else:
        status["phase3_online"] = {"ready": False}

    # Phase 4: Deep ensemble
    deep = _get_deep_ensemble_store()
    if deep is not None and hasattr(deep, "status"):
        status["phase4_deep"] = deep.status()
    else:
        status["phase4_deep"] = {"active": False}

    return status


async def _publish_and_broadcast(
    app_state: Any,
    symbol: str,
    signal_payload: dict[str, Any],
) -> None:
    """
    Publish a typed SignalEvent to the event bus and broadcast over WebSocket.

    Both steps are best-effort — failures are logged but do not block
    the auto-trade path.
    """
    direction = signal_payload["direction"]
    base_confidence = signal_payload["confidence"]
    ml_probability = signal_payload["probability"]
    model_ver = signal_payload["model_version"]

    # Typed event bus
    try:
        from events.typed_events import EventEnvelope, SignalEvent, publish_sync

        publish_sync(
            EventEnvelope.wrap(
                source="signal_engine",
                payload=SignalEvent(
                    symbol=symbol,
                    action=direction.upper(),
                    confidence=base_confidence,
                    probability=ml_probability,
                    entry_price=signal_payload["entry_price"],
                    stop_loss=signal_payload["stop_loss"],
                    take_profit=signal_payload["take_profit"],
                    model_version=model_ver,
                ),
                model_version=model_ver,
            ),
        )
    except Exception as ev_exc:
        logger.debug("Typed event publish failed: %s", ev_exc)

    logger.info(
        "Brain consensus: %s %s confidence=%.2f ml_prob=%.4f model=%s",
        symbol,
        direction,
        base_confidence,
        ml_probability,
        model_ver,
    )

    # WebSocket broadcast
    ws = getattr(app_state, "ws_manager", None)
    if ws is not None:
        try:
            await ws.broadcast_signal(symbol, signal_payload)
        except Exception as ws_exc:
            logger.warning("Signal broadcast failed: %s", ws_exc)

    # Ingest into RealTimeSignalService ring buffer so /api/signals/latest
    # reflects engine-generated signals (not just manually-submitted ones).
    try:
        from api.signals import _get_signal_service as _svc_factory

        _svc_factory().ingest_engine_signal(signal_payload)
    except Exception as _ingest_exc:
        logger.debug("ingest_engine_signal failed (non-fatal): %s", _ingest_exc)

    # Discord community bot — post signal embed to configured channel
    try:
        from notifications.discord_bot import discord_signal_bot

        await discord_signal_bot.post_signal(signal_payload)
    except Exception as discord_exc:
        logger.debug("Discord signal post failed: %s", discord_exc)


async def _execute_if_approved(
    app_state: Any,
    symbol: str,
    signal_payload: dict[str, Any],
    data: dict[str, Any] | None = None,
) -> None:
    """
    Apply risk filter and execute an auto-trade if approved.

    Only runs when SIGNAL_ENGINE_AUTO_TRADE=true. Skips silently if the
    risk manager blocks the trade or sizing is rejected.
    """
    if not _AUTO_TRADE:
        return

    # Live trading gate — all 5 checks must pass before any order is placed.
    # This is the authoritative pre-order safety check; it runs even when the
    # execution engine's PreTradeGate is also active.
    try:
        from core.live_trading_gate import get_gate

        gate_result = get_gate().check()
        if not gate_result.allowed:
            logger.warning(
                "Auto-trade blocked by LiveTradingGate: %s",
                gate_result.reason,
            )
            return
    except Exception as _gate_exc:
        # Gate unavailable → fail safe: block the trade.
        logger.error(
            "LiveTradingGate check raised an exception — blocking trade: %s",
            _gate_exc,
        )
        return

    broker: Any = getattr(app_state, "broker", None)
    risk_manager: Any = getattr(app_state, "risk_manager", None)
    ws: Any = getattr(app_state, "ws_manager", None)
    if broker is None:
        return

    direction = signal_payload["direction"].upper()
    if direction not in ("BUY", "SELL"):
        return

    # Risk gate + position sizing
    # No fallback lot — if the risk manager is absent we cannot size the
    # trade safely, so we block it entirely.
    if risk_manager is None:
        logger.error(
            "Auto-trade blocked for %s: risk_manager is not initialised. Cannot size position without risk controls.",
            symbol,
        )
        return

    quantity: float = 0.0
    if risk_manager is not None:
        try:
            account_info: dict[str, Any] = await broker.get_account_info()
            positions: list[Any] = await broker.get_positions()
            positions_dicts: list[dict[str, Any]] = [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "current_price": getattr(p, "current_price", 0),
                }
                for p in positions
            ]
            assessment: Any = risk_manager.assess_risk(account_info, positions_dicts)
            if not assessment.can_trade:
                logger.info(
                    "Auto-trade blocked by risk manager: %s",
                    assessment.messages,
                )
                return

            equity: float = account_info.get("equity", 100_000)

            # ── ML probability gate ───────────────────────────────────────────
            # ── Production-grade signal quality filter ────────────────────────
            # Runs four independent gates before any order is sent:
            # 1. Confidence gate (threshold per direction)
            # 2. Expected value gate (EV > 0 based on rolling trade outcomes)
            # 3. Regime filter (block HIGH_VOL / MEAN_REVERTING when enabled)
            # 4. MTF confluence (H4+D1 alignment when enabled)
            #
            # Root cause: 66% OOS accuracy ≠ tradeable edge when the accuracy
            # metric measures 1-bar direction but the hold period is 5 bars.
            # The EV gate catches this — it blocks signals when the rolling
            # win rate × avg_win < (1-win_rate) × avg_loss.
            try:
                from ml.signal_filter import get_signal_filter

                _filt = get_signal_filter()
                # Build a minimal OHLCV-like object from data dict for regime gate
                _ohlcv_proxy = None
                try:
                    import pandas as _pd

                    _prices = data.get("prices", [])
                    _highs = data.get("highs", [])
                    _lows = data.get("lows", [])
                    if _prices and _highs and _lows:
                        _ohlcv_proxy = _pd.DataFrame(
                            {
                                "close": _prices,
                                "high": _highs,
                                "low": _lows,
                            }
                        )
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)

                _filter_result = _filt.check(
                    signal_payload,
                    ohlcv=_ohlcv_proxy,
                    symbol=symbol,
                )
                if not _filter_result.passed:
                    logger.info(
                        "Signal filter blocked [%s]: %s (symbol=%s confidence=%.3f)",
                        _filter_result.gate,
                        _filter_result.reason,
                        symbol,
                        _filter_result.confidence,
                    )
                    return
            except Exception as _filt_exc:
                # Filter failure must never block execution — log and continue
                logger.debug("Signal filter error (pass-through): %s", _filt_exc)
                # Fall back to legacy confidence check
                ml_prob: float = signal_payload.get("probability", 0.5)
                _ML_MIN_PROB = float(os.getenv("ML_MIN_TRADE_PROB", "0.58"))
                if ml_prob < _ML_MIN_PROB:
                    logger.info(
                        "Auto-trade skipped (fallback): ML prob %.3f < %.3f (%s)",
                        ml_prob,
                        _ML_MIN_PROB,
                        symbol,
                    )
                    return

            # ── ATR-based SL/TP ───────────────────────────────────────────────
            # Use ATR(14) from the data buffer for volatility-adaptive levels.
            # Gold at $3,000: ATR ≈ $25–$40/day.
            # SL = 1.5× ATR below entry (tight enough to cut losers quickly).
            # TP = 3.0× ATR above entry (2:1 R:R minimum).
            # Falls back to percentage-based levels if ATR unavailable.
            entry: float = signal_payload["entry_price"]
            sl_price = signal_payload["stop_loss"]
            tp_price = signal_payload["take_profit"]

            if sl_price is None or tp_price is None:
                # Compute ATR from recent highs/lows if available in data
                try:
                    _data = data or {}
                    highs = _data.get("highs", [])
                    lows = _data.get("lows", [])
                    closes_list = _data.get("prices", [entry])
                    if len(highs) >= 14 and len(lows) >= 14:
                        import numpy as _np

                        h = _np.array(highs[-15:], dtype=float)
                        l = _np.array(lows[-15:], dtype=float)
                        c = _np.array(closes_list[-15:], dtype=float)
                        tr = _np.maximum(
                            h[1:] - l[1:],
                            _np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])),
                        )
                        atr = float(_np.mean(tr[-14:]))
                    else:
                        # Fallback: 0.8% of price (typical gold daily range)
                        atr = entry * 0.008
                    sl_atr_mult = float(os.getenv("SL_ATR_MULT", "1.5"))
                    tp_atr_mult = float(os.getenv("TP_ATR_MULT", "3.0"))
                    if direction.upper() == "BUY":
                        sl_price = entry - atr * sl_atr_mult
                        tp_price = entry + atr * tp_atr_mult
                    else:
                        sl_price = entry + atr * sl_atr_mult
                        tp_price = entry - atr * tp_atr_mult
                    logger.debug(
                        "ATR-based SL/TP: entry=%.2f atr=%.2f sl=%.2f tp=%.2f",
                        entry,
                        atr,
                        sl_price,
                        tp_price,
                    )
                except Exception as _atr_exc:
                    logger.debug("ATR SL/TP calc failed, using pct fallback: %s", _atr_exc)
                    sl_price = sl_price or (entry * 0.985 if direction.upper() == "BUY" else entry * 1.015)
                    tp_price = tp_price or (entry * 1.03 if direction.upper() == "BUY" else entry * 0.97)

            # ── Dynamic position sizing (volatility-scaled Kelly) ─────────────
            # PositionSizer computes a volatility-adaptive lot size using:
            # - Volatility method: risk_pct / ATR-based SL distance
            # - Kelly method: quarter-Kelly from rolling win rate / avg P&L
            # The result is passed as signal_strength to the risk manager which
            # applies its own caps and correlation checks.
            ml_prob: float = signal_payload.get("probability", 0.5)
            signal_strength = min(ml_prob, 0.80)  # cap at 80% to avoid over-sizing

            try:
                from ml.position_sizer import get_position_sizer
                import pandas as _pd_sz

                _ohlcv_sz = None
                _prices_sz = (data or {}).get("prices", [])
                _highs_sz = (data or {}).get("highs", [])
                _lows_sz = (data or {}).get("lows", [])
                if _prices_sz and _highs_sz and _lows_sz:
                    _ohlcv_sz = _pd_sz.DataFrame(
                        {
                            "close": _prices_sz,
                            "high": _highs_sz,
                            "low": _lows_sz,
                        }
                    )
                _sizer_lots = get_position_sizer().compute(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry,
                    stop_loss=sl_price,
                    account_equity=equity,
                    confidence=ml_prob,
                    ohlcv=_ohlcv_sz,
                )
                # Use sizer output as signal_strength proxy (normalised to [0,1])
                # so the risk manager's Kelly layer scales consistently
                _max_lots = float(os.getenv("MAX_LOTS", "10.0"))
                signal_strength = min(_sizer_lots / max(_max_lots, 1.0), 0.80)
                logger.debug(
                    "PositionSizer: %s lots=%.4f signal_strength=%.4f",
                    symbol,
                    _sizer_lots,
                    signal_strength,
                )
            except Exception as _sz_exc:
                logger.debug("PositionSizer error (fallback to ML prob): %s", _sz_exc)

            # ── Volatility estimate from recent returns ────────────────────────
            try:
                import numpy as _np2

                _prices = (data or {}).get("prices", [entry])
                if len(_prices) >= 20:
                    _rets = _np2.diff(_np2.log(_np2.array(_prices[-21:], dtype=float)))
                    _vol = float(_np2.std(_rets)) * (252**0.5)
                else:
                    _vol = 0.15  # gold annualised vol baseline
            except (ValueError, TypeError, KeyError):
                _vol = 0.15

            sizing: Any = risk_manager.calculate_position_size(
                symbol=symbol,
                signal_strength=signal_strength,
                entry_price=entry,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                account_equity=equity,
                volatility=_vol,
                existing_positions=positions_dicts,
            )
            if not sizing.approved:
                logger.info("Auto-trade sizing rejected: %s", sizing.reason)
                return
            quantity = sizing.recommended_size
        except Exception as risk_exc:
            logger.error("Risk check failed in signal engine: %s", risk_exc)
            return

    # Place order
    try:
        order = await broker.place_market_order(
            symbol=symbol,
            side=direction.lower(),
            quantity=quantity,
        )
        logger.info(
            "Auto-trade executed: %s %s confidence=%.2f qty=%s order_id=%s",
            direction,
            symbol,
            signal_payload["confidence"],
            quantity,
            order.id,
        )

        # Compliance log
        compliance = getattr(app_state, "compliance_manager", None)
        if compliance is not None:
            compliance.log_trade(
                user_id="signal_engine",
                trade_data={
                    "symbol": symbol,
                    "side": direction.lower(),
                    "quantity": quantity,
                    "source": "strategy_brain_auto",
                    "confidence": signal_payload["confidence"],
                },
            )

        # Broadcast fill
        if ws is not None:
            try:
                await ws.broadcast_trade(
                    symbol=symbol,
                    price=order.average_fill_price or signal_payload["entry_price"],
                    quantity=quantity,
                    side=direction.lower(),
                    trade_id=order.id,
                )
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        # Paper trading gate fill counter.
        try:
            from research.pipeline.paper_trading_gate import get_gate as _get_gate

            _get_gate().record_fill(pnl=0.0)
        except Exception as _gate_exc:
            logger.debug("gate.record_fill skipped in signal_engine: %s", _gate_exc)

        # Online learner feedback — notify Phase-3 store of the confirmed fill.
        # label=1 (trade was approved by risk + ML gates, so it's a positive sample).
        try:
            import pandas as _pd

            _fill_price = order.average_fill_price or signal_payload["entry_price"]
            _features = _pd.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "direction": direction,
                        "confidence": signal_payload.get("confidence", 0.0),
                        "fill_price": _fill_price,
                        "ml_prob": signal_payload.get("probability", 0.5),
                        "source": "signal_engine_auto",
                    }
                ]
            )
            notify_fill(
                _features,
                label=1,
                primary_prob=signal_payload.get("probability"),
            )
        except Exception as _ol_exc:
            logger.debug("notify_fill skipped after auto-trade: %s", _ol_exc)

    except Exception as order_exc:
        logger.error("Auto-trade order failed for %s: %s", symbol, order_exc)


_SL_ATR_MULT_DEFAULT = 1.5
_TP_ATR_MULT_DEFAULT = 3.0
_ATR_FALLBACK_FRAC = 0.008  # fraction of entry price when ATR unavailable
_SL_FALLBACK_FRAC = 0.015  # 1.5% fixed fallback stop distance
_TP_FALLBACK_FRAC = 0.030  # 3.0% fixed fallback take-profit distance
_ATR_MIN_BARS = 14  # minimum bars required for ATR calculation


def _compute_atr(highs: list, lows: list, closes: list, entry_price: float) -> float:
    """
    Compute 14-period ATR from bar lists.

    Returns entry_price * _ATR_FALLBACK_FRAC when fewer than _ATR_MIN_BARS
    are available — callers must not treat this as a real ATR value.
    """
    import numpy as np

    if len(highs) < _ATR_MIN_BARS or len(lows) < _ATR_MIN_BARS:
        return entry_price * _ATR_FALLBACK_FRAC

    h = np.array(highs[-(_ATR_MIN_BARS + 1) :], dtype=float)
    lo = np.array(lows[-(_ATR_MIN_BARS + 1) :], dtype=float)
    c = np.array(closes[-(_ATR_MIN_BARS + 1) :], dtype=float)
    tr = np.maximum(
        h[1:] - lo[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(lo[1:] - c[:-1])),
    )
    return float(np.mean(tr[-_ATR_MIN_BARS:])) if len(tr) >= _ATR_MIN_BARS else entry_price * _ATR_FALLBACK_FRAC


def _resolve_sl_tp(
    signal: Any,
    data: dict[str, Any],
    direction: str,
    entry_price: float,
) -> tuple:
    """
    Return (stop_loss, take_profit) for a signal.

    Uses strategy-provided values when present; falls back to ATR-based
    levels computed from the OHLCV bar list.  A fixed-percentage fallback
    is used when ATR computation fails.

    Every published signal must carry real SL/TP values so downstream
    consumers (ws_live.py, event bus, execution path) see consistent data.
    """
    sl_raw = getattr(signal, "stop_loss", None)
    tp_raw = getattr(signal, "take_profit", None)

    if sl_raw is not None and tp_raw is not None:
        return sl_raw, tp_raw

    is_long = direction.upper() == "BUY"
    sl_mult = float(os.getenv("SL_ATR_MULT", str(_SL_ATR_MULT_DEFAULT)))
    tp_mult = float(os.getenv("TP_ATR_MULT", str(_TP_ATR_MULT_DEFAULT)))

    try:
        atr = _compute_atr(
            data.get("highs", []),
            data.get("lows", []),
            data.get("prices", [entry_price]),
            entry_price,
        )
        sl = sl_raw if sl_raw is not None else (entry_price - atr * sl_mult if is_long else entry_price + atr * sl_mult)
        tp = tp_raw if tp_raw is not None else (entry_price + atr * tp_mult if is_long else entry_price - atr * tp_mult)
        return sl, tp

    except Exception as exc:
        logger.debug("ATR SL/TP computation failed (using fixed fallback): %s", exc)
        sl = sl_raw or (entry_price * (1 - _SL_FALLBACK_FRAC) if is_long else entry_price * (1 + _SL_FALLBACK_FRAC))
        tp = tp_raw or (entry_price * (1 + _TP_FALLBACK_FRAC) if is_long else entry_price * (1 - _TP_FALLBACK_FRAC))
        return sl, tp


async def _tick(app_state: Any) -> None:
    """
    Process one tick for all watched symbols.

    Orchestrates four focused sub-functions:
      _compute_signal()         — StrategyBrain consensus
      _compute_ml_probability() — advanced/fallback ML enrichment with macro
      _publish_and_broadcast()  — event bus + WebSocket
      _execute_if_approved()    — risk filter + auto-trade execution
    """
    brain: Any = getattr(app_state, "strategy_brain", None)
    if brain is None:
        return

    for sym in _SYMBOLS:
        symbol: str = sym.strip().upper()

        data: dict[str, Any] | None = await _fetch_market_data(symbol, app_state=app_state)
        if not data:
            continue

        sig_info = _compute_signal(brain, data, symbol)
        if sig_info is None:
            continue

        direction = sig_info["direction"]
        base_confidence = sig_info["base_confidence"]
        signal = sig_info["signal"]

        ml_probability, model_ver = _compute_ml_probability(
            data,
            symbol,
            base_confidence,
            app_state=app_state,
        )

        entry_price = getattr(signal, "entry_price", data["close"])
        sl_raw, tp_raw = _resolve_sl_tp(signal, data, direction, entry_price)

        signal_payload: dict[str, Any] = {
            "symbol": symbol,
            "direction": direction,
            "confidence": base_confidence,
            "probability": ml_probability,
            "model_version": model_ver,
            "entry_price": entry_price,
            "stop_loss": round(sl_raw, 5) if sl_raw is not None else None,
            "take_profit": round(tp_raw, 5) if tp_raw is not None else None,
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "strategy_brain",
        }

        await _publish_and_broadcast(app_state, symbol, signal_payload)
        await _execute_if_approved(app_state, symbol, signal_payload, data=data)
