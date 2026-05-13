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

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── MacroStore (populated at startup by init_macro_store) ─────────────────────
# Imported lazily so the signal engine can start even if ml is unavailable.
def _get_macro_store() -> Any | None:
    """Return the module-level MacroStore singleton, or None if unavailable."""
    try:
        from ml.macro_store import macro_store

        return macro_store
    except Exception as _exc:
        logger.debug("_get_macro_store: ml.macro_store unavailable: %s", _exc)
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
    except Exception as _exc:
        logger.debug("_get_macro_store_bridge: orchestrator bridge unavailable: %s", _exc)
        return None


# ── Advanced ML predictor (122-feature, 68% OOS accuracy) ────────────────────
try:
    from ml import get_active_model, get_advanced_predictor, get_model_version

    _ML_AVAILABLE: bool = True
except Exception:
    _ML_AVAILABLE = False
    logger.debug("ml package unavailable — signal engine will use fallback logic")

# ── Hybrid Ensemble predictor (XGBoost + LSTM + RL, Phase 5) ─────────────────
_hybrid_predictor: Any | None = None
_HYBRID_ENABLED: bool = os.getenv("HYBRID_ENSEMBLE_ENABLED", "true").lower() in ("1", "true", "yes")


def _get_hybrid_predictor() -> Any | None:
    """Return HybridEnsemblePredictor singleton (XGBoost + LSTM + RL blend)."""
    global _hybrid_predictor
    if not _HYBRID_ENABLED or not _ML_AVAILABLE:
        return None
    if _hybrid_predictor is not None:
        return _hybrid_predictor
    try:
        from ml.advanced_predictor import get_hybrid_predictor

        _hybrid_predictor = get_hybrid_predictor()
        status = _hybrid_predictor.component_status
        logger.info(
            "HybridEnsemblePredictor loaded — xgb=%s lstm=%s rl=%s",
            status.get("xgb_available"),
            status.get("lstm_available"),
            status.get("rl_available"),
        )
        return _hybrid_predictor
    except Exception as exc:
        logger.debug("HybridEnsemblePredictor unavailable: %s", exc)
        return None


# ── Anomaly weight store (Phase 2 — down-weight signals on anomalous bars) ────
_anomaly_store: Any | None = None

# ── Online learner store (Phase 3 — incremental XGBoost + drift detection) ───
_online_learner_store: Any | None = None

# ── Deep ensemble store (Phase 4 — LSTM/Transformer/TCN stacking) ────────────
_deep_ensemble_store: Any | None = None

# ── LSTM signal layer (Phase 4b — standalone LSTM blend) ─────────────────────
# Separate from DeepEnsembleStore: a lightweight single-model LSTM that blends
# with the XGBoost probability when LSTM_SIGNAL_ENABLED=true.
_lstm_signal_layer: Any | None = None
_LSTM_SIGNAL_ENABLED: bool = os.getenv("LSTM_SIGNAL_ENABLED", "false").lower() in ("1", "true", "yes")
_LSTM_SIGNAL_WEIGHT: float = float(os.getenv("LSTM_SIGNAL_WEIGHT", "0.0"))


def _get_lstm_signal_layer() -> Any | None:
    """Return the LSTMSignalLayer singleton, loading on first call."""
    global _lstm_signal_layer
    if not _LSTM_SIGNAL_ENABLED or _LSTM_SIGNAL_WEIGHT <= 0.0:
        return None
    if _lstm_signal_layer is not None:
        return _lstm_signal_layer
    try:
        from ml.lstm_signal_layer import get_lstm_signal_layer

        _lstm_signal_layer = get_lstm_signal_layer()
        return _lstm_signal_layer
    except Exception as exc:
        logger.debug("_get_lstm_signal_layer: unavailable: %s", exc)
        return None


# ── Regime-conditional position sizing ───────────────────────────────────────
# Maps MarketRegime → position size scalar (applied to base lot size).
# Loaded from REGIME_SIZE_MAP env-var (JSON) or falls back to defaults.
_DEFAULT_REGIME_SIZE_MAP: dict[str, float] = {
    "TRENDING_UP": 1.0,
    "TRENDING_DOWN": 1.0,
    "MEAN_REVERTING": 0.6,
    "RANGE_BOUND": 0.5,
    "HIGH_VOL": 0.3,
    "LOW_VOL": 0.8,
    "UNKNOWN": 0.5,
}


def _load_regime_size_map() -> dict[str, float]:
    raw = os.getenv("REGIME_SIZE_MAP", "")
    if raw:
        try:
            import json

            parsed = json.loads(raw)
            return {k.upper(): float(v) for k, v in parsed.items()}
        except Exception as exc:
            logger.warning("REGIME_SIZE_MAP parse error — using defaults: %s", exc)
    return _DEFAULT_REGIME_SIZE_MAP.copy()


_REGIME_SIZE_MAP: dict[str, float] = _load_regime_size_map()


def get_regime_position_scalar(regime_name: str) -> float:
    """Return the position size scalar for the given regime name (0–1).

    Used by the risk manager and execution engine to scale lot size based on
    the current market regime detected by RegimeDetector.
    """
    return _REGIME_SIZE_MAP.get(regime_name.upper(), 0.5)


def _get_deep_ensemble_store() -> Any | None:
    """Return the module-level DeepEnsembleStore singleton, loading on first call."""
    global _deep_ensemble_store

    # Check feature flag; fall back to env-var when flags module is unavailable.
    enabled = False
    try:
        from config.feature_flags import flags

        enabled = bool(flags.DEEP_ENSEMBLE)
    except Exception as _exc:
        logger.debug("_get_deep_ensemble_store: feature-flags unavailable: %s", _exc)
        import os

        enabled = os.getenv("FEATURE_DEEP_ENSEMBLE", "").lower() in ("1", "true", "yes")

    if not enabled:
        return None

    # Already loaded (or already failed — sentinel False)
    if _deep_ensemble_store is not None:
        return _deep_ensemble_store or None

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
            # Sentinel: don't retry on every tick
            _deep_ensemble_store = False  # type: ignore[assignment]
    except Exception as exc:
        logger.debug("DeepEnsembleStore init failed: %s", exc)
        _deep_ensemble_store = False  # type: ignore[assignment]

    # Return None for the sentinel (False) so callers get a clean None
    return _deep_ensemble_store or None


def _get_online_learner_store() -> Any | None:
    """Return the module-level OnlineLearnerStore singleton, creating it on first call."""
    global _online_learner_store
    # Check feature flag; fall back to env-var check if flags module unavailable
    enabled = False
    try:
        from config.feature_flags import flags

        enabled = bool(flags.ONLINE_LEARNING)
    except Exception as _exc:
        logger.debug("_get_online_learner_store: feature-flags unavailable: %s", _exc)
        import os

        enabled = os.getenv("FEATURE_ONLINE_LEARNING", "").lower() in ("1", "true", "yes")

    if not enabled:
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
    # Check feature flag; fall back to env-var check if flags module unavailable
    enabled = False
    try:
        from config.feature_flags import flags

        enabled = bool(flags.ANOMALY_WEIGHTING)
    except Exception as _exc:
        logger.debug("_get_anomaly_store: feature-flags unavailable: %s", _exc)
        import os

        enabled = os.getenv("FEATURE_ANOMALY_WEIGHTING", "").lower() in ("1", "true", "yes")

    if not enabled:
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
    app_state: Any | None = None,
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

    _close = data.get("close", 0.0)
    prices = data.get("prices", [_close])
    highs = data.get("highs", [data.get("high", _close)])
    lows = data.get("lows", [data.get("low", _close)])
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
        data.get("open", _close),
        data.get("high", _close),
        data.get("low", _close),
        _close,
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
    app_state: Any | None = None,
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


def _apply_lstm_signal_blend(
    prob: float,
    ohlcv_df: Any,
    macro_df: Any,
    symbol: str,
) -> float:
    """Phase 4b: Blend standalone LSTMSignalLayer probability with XGBoost chain.

    Weight is controlled by LSTM_SIGNAL_WEIGHT env-var (default 0.0 = disabled).
    The LSTM receives the same daily-resampled OHLCV and macro features as the
    XGBoost model so the feature space is identical.

    Blending formula:
        final = (1 - w) * xgb_prob + w * lstm_prob
    where w = LSTM_SIGNAL_WEIGHT.

    Falls back to the original prob on any error — never raises.
    """
    layer = _get_lstm_signal_layer()
    if layer is None:
        return prob
    if not layer.is_available():
        return prob
    try:
        result = layer.predict(ohlcv_df, macro_df=macro_df, symbol=symbol)
        if result.get("abstain", True):
            # LSTM abstained — don't blend, keep XGBoost probability
            logger.debug("Phase4b LSTM abstained for %s — keeping XGBoost prob %.4f", symbol, prob)
            return prob
        lstm_prob = float(result["probability"])
        w = _LSTM_SIGNAL_WEIGHT
        blended = (1.0 - w) * prob + w * lstm_prob
        blended = float(np.clip(blended, 0.0, 1.0))
        logger.debug(
            "Phase4b LSTM blend: %s xgb=%.4f lstm=%.4f w=%.2f → %.4f",
            symbol,
            prob,
            lstm_prob,
            w,
            blended,
        )
        return blended
    except Exception as exc:
        logger.debug("Phase4b LSTM blend failed (non-fatal): %s", exc)
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
    ohlcv_df = _build_ohlcv_df(data)

    # ── Timeframe alignment: resample H1 → daily before model inference ───────
    model_df = ohlcv_df
    try:
        from ml.daily_aggregator import ensure_daily, needs_resampling

        if needs_resampling(ohlcv_df):
            # Assign a proper DatetimeIndex so the resampler can work
            if not isinstance(ohlcv_df.index, pd.DatetimeIndex):
                idx = pd.date_range(
                    end=datetime.now(UTC),
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

    # ── Phase 4b: LSTM signal layer blend ────────────────────────────────────
    # Blend the standalone LSTMSignalLayer probability with the XGBoost chain.
    # Weight is controlled by LSTM_SIGNAL_WEIGHT (default 0.0 = disabled).
    # The LSTM receives the same daily-resampled OHLCV and macro features.
    prob = _apply_lstm_signal_blend(prob, model_df, macro_df, symbol)

    logger.debug(
        "ML chain (%s) %s: final=%.4f [macro=%s mtf=%s daily_bars=%d lstm=%s]",
        adv_predictor.version,
        symbol,
        prob,
        "yes" if macro_df is not None else "no",
        "yes" if mtf_df is not None else "no",
        len(model_df),
        "yes" if _LSTM_SIGNAL_ENABLED and _LSTM_SIGNAL_WEIGHT > 0 else "no",
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

    prices = data.get("prices", [data.get("close", 0.0)])
    closes = pd.Series(prices, dtype=float)

    def _safe_pct(n: int) -> float:
        """Return pct_change(n) for the last element, 0.0 on NaN/inf/insufficient data."""
        if len(closes) <= n:
            return 0.0
        val = closes.pct_change(n).iloc[-1]
        return float(val) if np.isfinite(val) else 0.0

    def _safe_vol(window: int) -> float:
        """Return rolling std of pct_change, 0.0 on NaN/inf/insufficient data."""
        if len(closes) <= window:
            return 0.0
        val = closes.dropna().pct_change().rolling(window).std().iloc[-1]
        return float(np.nan_to_num(val, nan=0.0, posinf=0.0, neginf=0.0))

    feat = {
        "close": float(data.get("close", 0.0)) if np.isfinite(float(data.get("close", 0.0))) else 0.0,
        "open": float(data.get("open", 0.0)) if np.isfinite(float(data.get("open", 0.0))) else 0.0,
        "high": float(data.get("high", 0.0)) if np.isfinite(float(data.get("high", 0.0))) else 0.0,
        "low": float(data.get("low", 0.0)) if np.isfinite(float(data.get("low", 0.0))) else 0.0,
        "volume": float(data.get("volume", 0) or 0),
        "ret_1": _safe_pct(1),
        "ret_5": _safe_pct(5),
        "ret_20": _safe_pct(20),
        "vol_20": _safe_vol(20),
    }
    X = pd.DataFrame([feat])

    if hasattr(active_model, "predict_proba"):
        proba = active_model.predict_proba(X)
        prob = float(proba[0][1]) if proba.shape[1] > 1 else float(proba[0][0])
    elif hasattr(active_model, "predict"):
        prob = float(active_model.predict(X)[0])
    else:
        prob = base_confidence

    # Final NaN guard — never return a non-finite probability
    if not np.isfinite(prob):
        prob = base_confidence
    logger.debug("Basic ML (%s) prob for %s: %.4f", model_ver, symbol, prob)
    return prob, model_ver


def _compute_ml_probability(
    data: dict[str, Any],
    symbol: str,
    base_confidence: float,
    app_state: Any | None = None,
) -> tuple:
    """
    Compute ML probability using the best available model.

    Returns (ml_probability: float, model_version: str).

    Path 1 (preferred): HybridEnsemblePredictor — XGBoost + LSTM + RL ensemble.
    Path 2:             AdvancedPredictor — XGBoost with full macro + MTF features.
    Path 3 (fallback):  basic xgb_macro.pkl — stationary OHLCV features.
    Path 4 (no model):  returns base_confidence unchanged.
    """
    if not _ML_AVAILABLE:
        return base_confidence, "none"

    try:
        # Path 1: Full hybrid ensemble (XGBoost + LSTM + RL)
        hybrid = _get_hybrid_predictor()
        if hybrid is not None:
            adv_predictor = get_advanced_predictor()
            if adv_predictor is not None and adv_predictor.is_available:
                ohlcv_df = _build_ohlcv_df(data)
                macro_df = _fetch_macro_df(ohlcv_df, symbol)
                try:
                    prob = hybrid.predict_proba(ohlcv_df, macro_df=macro_df)
                    if isinstance(prob, (int, float)) and 0.0 <= prob <= 1.0:
                        logger.debug("HybridEnsemble prob=%.4f for %s", prob, symbol)
                        return float(prob), "hybrid_ensemble_v1"
                except Exception as _he:
                    logger.debug("HybridEnsemble predict failed (%s) — falling back to AdvancedPredictor", _he)

        # Path 2: Advanced XGBoost (Phase 1-4 chain)
        adv_predictor = get_advanced_predictor()
        if adv_predictor is not None and adv_predictor.is_available:
            return _predict_advanced(adv_predictor, data, symbol, app_state)

        # Path 3: Basic macro XGBoost
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
    except Exception as _exc:
        logger.debug("_get_factor_engine: portfolio factor engine unavailable: %s", _exc)
        return None


def _enrich_signal_with_factors(
    signal_payload: dict[str, Any],
    positions: dict[str, float],
    total_pnl: float,
    app_state: Any | None = None,
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
    except Exception as _exc:
        logger.debug("get_signal_engine_status: flags unavailable: %s", _exc)
        status["phase1_mtf_enabled"] = None

    try:
        from research.pipeline.mtf_fusion import _MTF_STORE_SINGLETON

        if _MTF_STORE_SINGLETON is not None:
            status["phase1_mtf"] = _MTF_STORE_SINGLETON.status()
        else:
            status["phase1_mtf"] = {"is_ready": False}
    except Exception as _exc:
        logger.debug("get_signal_engine_status: mtf_fusion unavailable: %s", _exc)
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

    # WebSocket broadcast — route through LiveConnectionManager (FastAPI /ws/live)
    # which is the connection pool the frontend actually uses.  Fall back to the
    # legacy WebSocketManager on app_state for non-FastAPI deployments.
    _signal_broadcast_ok = False
    try:
        from api.ws_live import get_live_manager as _get_live_mgr

        await _get_live_mgr().broadcast_signal(symbol, signal_payload)
        _signal_broadcast_ok = True
    except Exception as _live_ws_exc:
        logger.debug("LiveConnectionManager signal broadcast failed: %s", _live_ws_exc)

    if not _signal_broadcast_ok:
        ws = getattr(app_state, "ws_manager", None)
        if ws is not None:
            try:
                _msg = {"type": "signal", "data": signal_payload}
                await ws.broadcast(_msg)
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


def _check_live_trading_gate() -> bool:
    """
    Verify the LiveTradingGate allows trading.

    Returns True when trading is permitted. Returns False and logs a warning
    when blocked. Returns False and logs an error when the gate itself raises —
    fail-safe behaviour blocks the trade on gate unavailability.
    """
    try:
        from core.live_trading_gate import get_gate

        result = get_gate().check()
        if not result.allowed:
            logger.warning("Auto-trade blocked by LiveTradingGate: %s", result.reason)
            return False
        return True
    except Exception as exc:
        logger.error("LiveTradingGate raised — blocking trade: %s", exc)
        return False


def _build_ohlcv_proxy(data: dict[str, Any] | None) -> "pd.DataFrame | None":
    """
    Build a minimal close/high/low DataFrame from a tick data dict.

    Returns None when the data dict lacks price lists — callers must handle
    None gracefully (signal filter falls back to OHLCV-less mode).
    """
    if not data:
        return None
    prices = data.get("prices", [])
    highs = data.get("highs", [])
    lows = data.get("lows", [])
    if not (prices and highs and lows):
        return None
    return pd.DataFrame({"close": prices, "high": highs, "low": lows})


def _enrich_with_signal_score(
    signal_payload: dict[str, Any],
    ohlcv_proxy: "pd.DataFrame | None",
    symbol: str,
    macro_df: "pd.DataFrame | None" = None,
) -> None:
    """
    Compute multi-factor signal strength score and inject results into payload.

    Adds to signal_payload:
      signal_strength_score  : float 0–1 composite score
      signal_grade           : STRONG / GOOD / FAIR / WEAK
      signal_score_dimensions: per-dimension breakdown dict
      signal_score_latency_ms: scorer latency

    Silently skips on any error — scoring is advisory, never blocking.
    """
    try:
        from ml.signal_scorer import get_signal_scorer

        score_result = get_signal_scorer().score(
            signal_payload=signal_payload,
            ohlcv=ohlcv_proxy,
            macro_df=macro_df,
            symbol=symbol,
        )
        signal_payload["signal_strength_score"] = round(score_result.composite, 4)
        signal_payload["signal_grade"] = score_result.grade
        signal_payload["signal_score_dimensions"] = {
            k: round(v, 4)
            for k, v in {
                "ml_confidence": score_result.dimensions.ml_confidence,
                "technical": score_result.dimensions.technical,
                "macro_alignment": score_result.dimensions.macro_alignment,
                "regime": score_result.dimensions.regime,
                "mtf_confluence": score_result.dimensions.mtf_confluence,
                "volatility": score_result.dimensions.volatility,
            }.items()
        }
        signal_payload["signal_score_latency_ms"] = round(score_result.latency_ms, 2)
        logger.debug(
            "Signal scored [%s]: %s score=%.3f grade=%s",
            symbol,
            signal_payload.get("direction"),
            score_result.composite,
            score_result.grade,
        )
    except Exception as exc:
        logger.debug("Signal scoring failed (non-blocking): %s", exc)
        signal_payload.setdefault("signal_strength_score", 0.5)
        signal_payload.setdefault("signal_grade", "UNKNOWN")


def _run_signal_filter(
    signal_payload: dict[str, Any],
    ohlcv_proxy: "pd.DataFrame | None",
    symbol: str,
) -> bool:
    """
    Run the production signal quality filter (confidence, EV, regime, MTF).

    Returns True when the signal passes all gates.
    Falls back to a legacy ML-probability threshold when the filter module
    is unavailable — filter failure must never silently pass bad signals.
    """
    try:
        from ml.signal_filter import get_signal_filter

        result = get_signal_filter().check(signal_payload, ohlcv=ohlcv_proxy, symbol=symbol)
        if not result.passed:
            logger.info(
                "Signal filter blocked [%s]: %s (symbol=%s confidence=%.3f)",
                result.gate,
                result.reason,
                symbol,
                result.confidence,
            )
            return False
        return True
    except Exception as exc:
        logger.debug("Signal filter error (falling back to ML prob gate): %s", exc)

    # Legacy fallback: raw ML probability threshold
    ml_prob: float = signal_payload.get("probability", 0.5)
    min_prob = float(os.getenv("ML_MIN_TRADE_PROB", "0.58"))
    if ml_prob < min_prob:
        logger.info(
            "Auto-trade skipped (fallback gate): ML prob %.3f < %.3f (%s)",
            ml_prob,
            min_prob,
            symbol,
        )
        return False
    return True


def _resolve_execution_sl_tp(
    signal_payload: dict[str, Any],
    data: dict[str, Any] | None,
    direction: str,
) -> tuple[float, float]:
    """
    Return (stop_loss, take_profit) for order submission.

    Uses signal-provided values when present. Falls back to ATR-based levels
    computed via _compute_atr() / _resolve_sl_tp() which already handle the
    fixed-percentage fallback internally.
    """
    sl_price = signal_payload.get("stop_loss")
    tp_price = signal_payload.get("take_profit")
    if sl_price is not None and tp_price is not None:
        return sl_price, tp_price

    entry: float = signal_payload["entry_price"]
    return _resolve_sl_tp(
        signal=None,
        data=data or {},
        direction=direction,
        entry_price=entry,
    )


def _compute_signal_strength(
    signal_payload: dict[str, Any],
    symbol: str,
    direction: str,
    entry: float,
    sl_price: float,
    equity: float,
    data: dict[str, Any] | None,
) -> float:
    """
    Compute normalised signal strength for risk manager position sizing.

    Tries PositionSizer first (volatility-scaled Kelly). Falls back to the
    raw ML probability capped at 0.80 to prevent over-sizing.
    """
    ml_prob: float = signal_payload.get("probability", 0.5)
    fallback_strength = min(ml_prob, 0.80)

    try:
        from ml.position_sizer import get_position_sizer

        ohlcv = _build_ohlcv_proxy(data)
        lots = get_position_sizer().compute(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=sl_price,
            account_equity=equity,
            confidence=ml_prob,
            ohlcv=ohlcv,
        )
        max_lots = float(os.getenv("MAX_LOTS", "10.0"))
        strength = min(lots / max(max_lots, 1.0), 0.80)
        logger.debug("PositionSizer: %s lots=%.4f signal_strength=%.4f", symbol, lots, strength)
        return strength
    except Exception as exc:
        logger.debug("PositionSizer error (fallback to ML prob): %s", exc)
        return fallback_strength


def _estimate_annualised_volatility(data: dict[str, Any] | None, entry: float) -> float:
    """
    Estimate annualised volatility from recent log-returns.

    Returns 0.15 (gold baseline) when fewer than 20 price observations are
    available or when the computation fails.
    """
    _GOLD_VOL_BASELINE = 0.15
    _MIN_PRICES_FOR_VOL = 20
    try:
        import numpy as np

        prices = (data or {}).get("prices", [entry])
        if len(prices) < _MIN_PRICES_FOR_VOL:
            return _GOLD_VOL_BASELINE
        p_arr = np.nan_to_num(np.array(prices[-21:], dtype=float), nan=0.0)
        # Guard: replace non-positive prices to avoid log(0) = -inf
        p_arr = np.where(p_arr > 0, p_arr, 1e-9)
        log_returns = np.diff(np.log(p_arr))
        # Guard: replace any remaining NaN/inf in log_returns before std
        log_returns = np.nan_to_num(log_returns, nan=0.0, posinf=0.0, neginf=0.0)
        std = float(np.std(log_returns))
        if not np.isfinite(std):
            return _GOLD_VOL_BASELINE
        if std == 0.0:
            return 0.0  # constant prices → zero volatility
        return std * (252**0.5)
    except Exception as _exc:
        logger.debug("_estimate_current_vol: numpy calculation failed: %s", _exc)
        return _GOLD_VOL_BASELINE


async def _assess_risk_and_size(
    broker: Any,
    risk_manager: Any,
    symbol: str,
    direction: str,
    signal_payload: dict[str, Any],
    data: dict[str, Any] | None,
) -> float | None:
    """
    Run risk assessment and compute approved position size.

    Returns the approved quantity, or None when the trade is blocked.
    Raises on unexpected broker/risk errors — caller logs and returns.
    """
    account_info: dict[str, Any] = await broker.get_account_info()
    raw_positions: list[Any] = await broker.get_positions()
    positions_dicts: list[dict[str, Any]] = [
        {
            "symbol": p.symbol,
            "quantity": p.quantity,
            "current_price": getattr(p, "current_price", 0),
        }
        for p in raw_positions
    ]

    assessment = risk_manager.assess_risk(account_info, positions_dicts)
    if not assessment.can_trade:
        logger.info("Auto-trade blocked by risk manager: %s", assessment.messages)
        return None

    equity: float = account_info.get("equity", 100_000)
    entry: float = signal_payload["entry_price"]
    sl_price, tp_price = _resolve_execution_sl_tp(signal_payload, data, direction)

    ohlcv_proxy = _build_ohlcv_proxy(data)
    if not _run_signal_filter(signal_payload, ohlcv_proxy, symbol):
        return None

    signal_strength = _compute_signal_strength(signal_payload, symbol, direction, entry, sl_price, equity, data)
    volatility = _estimate_annualised_volatility(data, entry)

    sizing = risk_manager.calculate_position_size(
        symbol=symbol,
        signal_strength=signal_strength,
        entry_price=entry,
        stop_loss_price=sl_price,
        take_profit_price=tp_price,
        account_equity=equity,
        volatility=volatility,
        existing_positions=positions_dicts,
    )
    if not sizing.approved:
        logger.info("Auto-trade sizing rejected: %s", sizing.reason)
        return None

    # ── Regime-conditional position size scaling ──────────────────────────────
    # Scale the approved size by the current market regime scalar.
    # The regime is read from the signal payload (set by _build_signal_payload).
    # This is a multiplicative overlay — it never increases size above the
    # risk-manager-approved maximum, only reduces it in adverse regimes.
    regime_name: str = signal_payload.get("regime", "UNKNOWN")
    regime_scalar: float = get_regime_position_scalar(regime_name)
    if regime_scalar < 1.0:
        scaled_size = sizing.recommended_size * regime_scalar
        logger.info(
            "Regime-conditional sizing: %s regime=%s scalar=%.2f approved=%.4f → scaled=%.4f",
            symbol,
            regime_name,
            regime_scalar,
            sizing.recommended_size,
            scaled_size,
        )
        return scaled_size

    return sizing.recommended_size


async def _place_order_and_notify(
    broker: Any,
    app_state: Any,
    symbol: str,
    direction: str,
    quantity: float,
    signal_payload: dict[str, Any],
) -> None:
    """
    Place a market order and fire all post-fill side-effects.

    Side-effects (all best-effort, never raise):
      - Compliance audit log
      - WebSocket fill broadcast
      - Paper trading gate fill counter
      - Online learner Phase-3 feedback
    """
    try:
        order = await broker.place_market_order(
            symbol=symbol,
            side=direction.lower(),
            quantity=quantity,
        )
    except Exception as broker_exc:
        logger.error(
            "Auto-trade broker call failed — order NOT placed: %s %s qty=%s error=%s",
            direction,
            symbol,
            quantity,
            broker_exc,
        )
        return

    # Validate the order result before recording the fill.
    order_status = getattr(order, "status", None) or (order.get("status") if isinstance(order, dict) else None)
    if order_status in ("rejected", "error", "cancelled"):
        reason = getattr(order, "reason", None) or (order.get("reason") if isinstance(order, dict) else "unknown")
        logger.error(
            "Auto-trade order rejected: %s %s qty=%s status=%s reason=%s",
            direction,
            symbol,
            quantity,
            order_status,
            reason,
        )
        return

    order_id = getattr(order, "id", None) or (order.get("order_id") if isinstance(order, dict) else "unknown")
    logger.info(
        "Auto-trade executed: %s %s confidence=%.2f qty=%s order_id=%s",
        direction,
        symbol,
        signal_payload["confidence"],
        quantity,
        order_id,
    )

    _log_compliance(app_state, symbol, direction, quantity, signal_payload)
    await _broadcast_fill(app_state, symbol, direction, quantity, order, signal_payload)
    _record_paper_gate_fill()
    _notify_online_learner(symbol, direction, quantity, order, signal_payload)


def _log_compliance(
    app_state: Any,
    symbol: str,
    direction: str,
    quantity: float,
    signal_payload: dict[str, Any],
) -> None:
    """Write a compliance audit record for the auto-trade fill."""
    compliance = getattr(app_state, "compliance_manager", None)
    if compliance is None:
        return
    try:
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
    except Exception as exc:
        logger.warning("Compliance log_trade failed: %s", exc)


async def _broadcast_fill(
    app_state: Any,
    symbol: str,
    direction: str,
    quantity: float,
    order: Any,
    signal_payload: dict[str, Any],
) -> None:
    """Broadcast the fill over WebSocket — best-effort."""
    try:
        fill_price = (
            getattr(order, "average_fill_price", None)
            or getattr(order, "average_price", None)
            or (order.get("fill_price") if isinstance(order, dict) else None)
            or signal_payload["entry_price"]
        )
        trade_id = (
            getattr(order, "id", None) or (order.get("order_id") if isinstance(order, dict) else None) or "unknown"
        )
        trade_msg = {
            "type": "trade_fill",
            "data": {
                "symbol": symbol,
                "price": fill_price,
                "quantity": quantity,
                "side": direction.lower(),
                "trade_id": trade_id,
            },
        }
        # Primary: LiveConnectionManager (FastAPI /ws/live — what the frontend uses)
        try:
            from api.ws_live import get_live_manager as _get_live_mgr

            await _get_live_mgr().broadcast("trades", trade_msg)
            return
        except Exception as _live_exc:
            logger.debug("LiveConnectionManager fill broadcast failed: %s", _live_exc)

        # Fallback: legacy WebSocketManager
        ws = getattr(app_state, "ws_manager", None)
        if ws is not None:
            await ws.broadcast(trade_msg)
    except Exception as exc:
        logger.debug("WebSocket fill broadcast failed: %s", exc)


def _record_paper_gate_fill() -> None:
    """Increment the paper trading gate fill counter — best-effort."""
    try:
        from research.pipeline.paper_trading_gate import get_gate as _get_gate

        _get_gate().record_fill(pnl=0.0)
    except Exception as exc:
        logger.debug("gate.record_fill skipped: %s", exc)


def _notify_online_learner(
    symbol: str,
    direction: str,
    quantity: float,
    order: Any,
    signal_payload: dict[str, Any],
) -> None:
    """Notify Phase-3 online learner of a confirmed fill — best-effort."""
    try:
        fill_price = (
            getattr(order, "average_fill_price", None)
            or (order.get("fill_price") if isinstance(order, dict) else None)
            or signal_payload["entry_price"]
        )
        features = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "direction": direction,
                    "confidence": signal_payload.get("confidence", 0.0),
                    "fill_price": fill_price,
                    "ml_prob": signal_payload.get("probability", 0.5),
                    "source": "signal_engine_auto",
                }
            ]
        )
        notify_fill(features, label=1, primary_prob=signal_payload.get("probability"))
    except Exception as exc:
        logger.debug("notify_fill skipped after auto-trade: %s", exc)


async def _execute_if_approved(
    app_state: Any,
    symbol: str,
    signal_payload: dict[str, Any],
    data: dict[str, Any] | None = None,
) -> None:
    """
    Apply risk filter and execute an auto-trade if approved.

    Only runs when SIGNAL_ENGINE_AUTO_TRADE=true. Delegates each concern to
    a focused helper so each gate is independently testable:

      _check_live_trading_gate()   — 5-check pre-order safety gate
      _assess_risk_and_size()      — risk assessment + position sizing
      _place_order_and_notify()    — order placement + post-fill side-effects
    """
    if not _AUTO_TRADE:
        return

    if not _check_live_trading_gate():
        return

    broker: Any = getattr(app_state, "broker", None)
    risk_manager: Any = getattr(app_state, "risk_manager", None)

    if broker is None:
        return

    direction = signal_payload["direction"].upper()
    if direction not in ("BUY", "SELL"):
        return

    # ── Signal grade gate ─────────────────────────────────────────────────────
    # Only auto-trade STRONG and GOOD signals (composite score ≥ 0.60).
    # FAIR and WEAK signals are published for human review but never auto-executed.
    _grade = signal_payload.get("signal_grade", "UNKNOWN")
    _score = float(signal_payload.get("signal_strength_score", 0.5))
    _min_auto_score = float(os.getenv("AUTOTRADE_MIN_SIGNAL_SCORE", "0.60"))
    if _grade not in ("STRONG", "GOOD") and _score < _min_auto_score:
        logger.info(
            "Auto-trade blocked by signal grade gate: %s grade=%s score=%.3f < %.3f threshold",
            symbol,
            _grade,
            _score,
            _min_auto_score,
        )
        return

    if risk_manager is None:
        logger.error(
            "Auto-trade blocked for %s: risk_manager not initialised — cannot size without risk controls.",
            symbol,
        )
        return

    try:
        quantity = await _assess_risk_and_size(broker, risk_manager, symbol, direction, signal_payload, data)
    except Exception as exc:
        logger.error("Risk assessment failed in signal engine for %s: %s", symbol, exc)
        return

    if quantity is None:
        return

    try:
        await _place_order_and_notify(broker, app_state, symbol, direction, quantity, signal_payload)
    except Exception as exc:
        logger.error("Auto-trade order failed for %s: %s", symbol, exc)


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

    if len(highs) < _ATR_MIN_BARS or len(lows) < _ATR_MIN_BARS or len(closes) < _ATR_MIN_BARS:
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

    Priority:
    1. Strategy-provided values on the signal object (most specific).
    2. ATR-based levels computed from the OHLCV bar list.
    3. Fixed-percentage fallback (``_SL_FALLBACK_FRAC`` / ``_TP_FALLBACK_FRAC``)
       used when (a) ATR computation raises, or (b) no OHLCV bar data is
       present at all (empty ``data`` dict).

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

    # When the caller passes no bar data at all, skip ATR (which would only
    # return the ATR fallback fraction anyway) and go straight to the
    # documented fixed-percentage fallback.  This keeps the behaviour
    # predictable for callers that intentionally pass an empty data dict.
    has_bar_data = bool(data.get("prices") or data.get("highs") or data.get("lows"))
    if not has_bar_data:
        sl = (
            sl_raw
            if sl_raw is not None
            else (entry_price * (1 - _SL_FALLBACK_FRAC) if is_long else entry_price * (1 + _SL_FALLBACK_FRAC))
        )
        tp = (
            tp_raw
            if tp_raw is not None
            else (entry_price * (1 + _TP_FALLBACK_FRAC) if is_long else entry_price * (1 - _TP_FALLBACK_FRAC))
        )
        return sl, tp

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


def _push_mtf_bar(
    data: dict[str, Any],
    symbol: str,
    app_state: Any | None = None,
) -> None:
    """Push the latest OHLCV bar into the MTFFusionStore live buffers.

    The MTFFusionStore maintains H4 and D1 rolling buffers.  Calling
    push_bar() on each tick keeps those buffers current so align_to_h1()
    always sees the latest regime context without a full reload.

    Timeframe is inferred from the bar interval stored in data["interval"]
    (default "1h").  The store internally decides whether to aggregate the
    bar into H4 or D1 based on the timeframe label.

    Non-blocking: any error is logged at DEBUG level and silently ignored.
    """
    try:
        store = getattr(app_state, "mtf_store", None)
        if store is None:
            from research.pipeline.mtf_fusion import _MTF_STORE_SINGLETON

            store = _MTF_STORE_SINGLETON
        if store is None or not getattr(store, "is_ready", False):
            return

        bar = pd.DataFrame(
            [
                {
                    "open": data.get("open", data.get("close", 0.0)),
                    "high": data.get("high", data.get("close", 0.0)),
                    "low": data.get("low", data.get("close", 0.0)),
                    "close": data.get("close", 0.0),
                    "volume": data.get("volume", 0.0),
                }
            ],
            index=[datetime.now(UTC)],
        )
        timeframe = data.get("interval", "1h")
        store.push_bar(bar, timeframe=timeframe)
    except Exception as exc:
        logger.debug("_push_mtf_bar failed for %s (non-fatal): %s", symbol, exc)


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

        # ── MTF live bar update ───────────────────────────────────────────────
        # Push the latest bar into the MTFFusionStore so the H4/D1 buffers
        # stay current without requiring a full reload on each tick.
        _push_mtf_bar(data, symbol, app_state)

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

        entry_price = getattr(signal, "entry_price", data.get("close", 0.0))
        sl_raw, tp_raw = _resolve_sl_tp(signal, data, direction, entry_price)

        # ── Regime detection ──────────────────────────────────────────────────
        # Detect the current market regime and attach it to the payload so:
        #   1. The risk manager can apply regime-conditional position sizing.
        #   2. The WebSocket / frontend can display the current regime.
        #   3. The compliance log captures regime context per trade.
        regime_name = "UNKNOWN"
        regime_confidence = 0.0
        try:
            from core.regime_router import get_current_regime

            regime_result = get_current_regime(symbol)
            if regime_result is not None:
                regime_name = regime_result.get("regime", "UNKNOWN")
                regime_confidence = float(regime_result.get("confidence", 0.0))
        except Exception as _re:
            logger.debug("Regime detection unavailable for %s: %s", symbol, _re)

        regime_scalar = get_regime_position_scalar(regime_name)

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
            # Regime context — used by risk manager for position size scaling
            "regime": regime_name,
            "regime_confidence": round(regime_confidence, 4),
            "regime_size_scalar": round(regime_scalar, 4),
            # LSTM blend status — informational
            "lstm_blend_active": _LSTM_SIGNAL_ENABLED and _LSTM_SIGNAL_WEIGHT > 0.0,
            "lstm_signal_weight": _LSTM_SIGNAL_WEIGHT,
        }

        # ── Signal Strength Scoring ───────────────────────────────────────────
        # Multi-factor validation: ML confidence + technical consensus + macro
        # alignment + regime suitability + MTF confluence + volatility quality.
        # Score is added to the payload for WebSocket display and auto-trade gate.
        ohlcv_proxy = _build_ohlcv_proxy(data)
        # Fetch live macro features so macro_alignment dimension activates.
        _scorer_macro: pd.DataFrame | None = None
        try:
            _scorer_ohlcv = _build_ohlcv_df(data)
            _scorer_macro = _fetch_macro_df(_scorer_ohlcv, symbol)
        except Exception as _sm_exc:
            logger.debug("macro fetch for scorer failed (non-fatal): %s", _sm_exc)
        _enrich_with_signal_score(signal_payload, ohlcv_proxy, symbol, macro_df=_scorer_macro)

        # ── Factor Attribution ────────────────────────────────────────────────
        # Append live portfolio factor attribution (market/size/value betas and
        # residual alpha) to the payload so subscribers can see factor P&L.
        # Best-effort: fetches live positions from broker, falls back gracefully.
        try:
            _broker = getattr(app_state, "broker", None)
            if _broker is not None:
                _raw_pos = await _broker.get_positions()
                _pos_map = {getattr(p, "symbol", "UNK"): float(getattr(p, "quantity", 0)) for p in (_raw_pos or [])}
                _total_pnl = sum(float(getattr(p, "unrealized_pnl", 0)) for p in (_raw_pos or []))
                signal_payload = _enrich_signal_with_factors(signal_payload, _pos_map, _total_pnl, app_state=app_state)
        except Exception as _fac_exc:
            logger.debug("Factor enrichment skipped (non-fatal): %s", _fac_exc)

        # ── Factor Attribution ────────────────────────────────────────────────
        # Append live portfolio factor attribution (market/size/value betas and
        # residual alpha) to the payload so subscribers can see factor P&L.
        # Best-effort: fetches live positions from broker, falls back gracefully.
        try:
            _broker = getattr(app_state, "broker", None)
            if _broker is not None:
                _raw_pos = await _broker.get_positions()
                _pos_map = {getattr(p, "symbol", "UNK"): float(getattr(p, "quantity", 0)) for p in (_raw_pos or [])}
                _total_pnl = sum(float(getattr(p, "unrealized_pnl", 0)) for p in (_raw_pos or []))
                signal_payload = _enrich_signal_with_factors(signal_payload, _pos_map, _total_pnl, app_state=app_state)
        except Exception as _fac_exc:
            logger.debug("Factor enrichment skipped (non-fatal): %s", _fac_exc)

        await _publish_and_broadcast(app_state, symbol, signal_payload)
        await _execute_if_approved(app_state, symbol, signal_payload, data=data)


# ── Public accessor ───────────────────────────────────────────────────────────


class _SignalEngineProxy:
    """
    Lightweight proxy returned by get_signal_engine().

    The signal engine runs as a module-level asyncio loop (run_signal_engine)
    rather than a class instance.  This proxy exposes the attributes that
    health probes and admin endpoints expect (_active, status, symbols) so
    they can inspect the engine without importing internal state directly.
    """

    @property
    def _active(self) -> bool:
        """True when the signal engine loop is configured and running."""
        return bool(_SYMBOLS and _INTERVAL_SECONDS > 0)

    @property
    def symbols(self) -> list[str]:
        return list(_SYMBOLS)

    @property
    def interval_seconds(self) -> int:
        return _INTERVAL_SECONDS

    @property
    def auto_trade(self) -> bool:
        return _AUTO_TRADE

    @property
    def ml_available(self) -> bool:
        return _ML_AVAILABLE

    def status(self) -> dict[str, Any]:
        return get_signal_engine_status()


_signal_engine_proxy = _SignalEngineProxy()


def get_signal_engine() -> _SignalEngineProxy:
    """Return the signal engine proxy for health checks and admin inspection.

    The signal engine is a module-level asyncio loop, not a class instance.
    This accessor returns a proxy that exposes _active, symbols, and status()
    so callers don't need to know the internal implementation detail.
    """
    return _signal_engine_proxy
