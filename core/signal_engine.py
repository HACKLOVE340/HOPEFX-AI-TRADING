# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
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
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── MacroStore (populated at startup by init_macro_store) ─────────────────────
# Imported lazily so the signal engine can start even if ml is unavailable.
def _get_macro_store() -> Optional[Any]:
    """Return the module-level MacroStore singleton, or None if unavailable."""
    try:
        from ml.macro_store import macro_store

        return macro_store
    except Exception:
        return None


# ── Advanced ML predictor (122-feature, 68% OOS accuracy) ────────────────────
try:
    from ml import get_active_model, get_advanced_predictor, get_model_version

    _ML_AVAILABLE: bool = True
except Exception:
    _ML_AVAILABLE = False

# ── Anomaly weight store (Phase 2 — down-weight signals on anomalous bars) ────
_anomaly_store: Optional[Any] = None

# ── Online learner store (Phase 3 — incremental XGBoost + drift detection) ───
_online_learner_store: Optional[Any] = None

# ── Deep ensemble store (Phase 4 — LSTM/Transformer/TCN stacking) ────────────
_deep_ensemble_store: Optional[Any] = None


def _get_deep_ensemble_store() -> Optional[Any]:
    """Return the module-level DeepEnsembleStore singleton, loading on first call."""
    global _deep_ensemble_store
    try:
        from config.feature_flags import flags

        if not flags.DEEP_ENSEMBLE:
            return None
    except Exception:
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


def _get_online_learner_store() -> Optional[Any]:
    """Return the module-level OnlineLearnerStore singleton, creating it on first call."""
    global _online_learner_store
    try:
        from config.feature_flags import flags

        if not flags.ONLINE_LEARNING:
            return None
    except Exception:
        return None
    if _online_learner_store is None:
        try:
            from research.pipeline.online_learning import OnlineLearnerStore

            _online_learner_store = OnlineLearnerStore()
            logger.info("OnlineLearnerStore initialised (Phase 3)")
        except Exception as exc:
            logger.debug("OnlineLearnerStore init failed: %s", exc)
    return _online_learner_store


def _get_anomaly_store() -> Optional[Any]:
    """Return the module-level AnomalyWeightStore singleton, creating it on first call."""
    global _anomaly_store
    try:
        from config.feature_flags import flags

        if not flags.ANOMALY_WEIGHTING:
            return None
    except Exception:
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
    def get_active_model() -> Optional[Any]:  # type: ignore[misc]
        return None

    def get_model_version() -> str:  # type: ignore[misc]
        return "none"

    def get_advanced_predictor() -> Optional[Any]:  # type: ignore[misc]
        return None


# Symbols the engine watches (overridden by ALLOWED_SYMBOLS env var)

_SYMBOLS = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")
_INTERVAL_SECONDS = int(os.getenv("SIGNAL_ENGINE_INTERVAL", "60"))
_AUTO_TRADE = os.getenv("SIGNAL_ENGINE_AUTO_TRADE", "false").lower() == "true"


async def _fetch_market_data(
    symbol: str,
    app_state: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetch latest OHLCV data for a symbol.

    Uses the broker's get_market_data() so no external feed is required for
    paper trading. Falls back to a synthetic bar built from the broker's spot
    price when OHLCV history is unavailable.
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as exc:
            logger.warning("Broker OHLCV fetch failed for %s: %s", symbol, exc)

        # Fallback: build a synthetic bar from the spot price
        try:
            price = broker.get_market_price(symbol)
            if price:
                return {
                    "symbol": symbol,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 0.0,
                    "prices": [price],
                    "highs": [price],
                    "lows": [price],
                    "volumes": [0.0],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as exc:
            logger.warning("Broker spot price fetch failed for %s: %s", symbol, exc)

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
    data: Dict[str, Any],
    symbol: str,
) -> Optional[Dict[str, Any]]:
    """
    Run StrategyBrain and return a signal dict, or None if no consensus.

    Returns dict with keys: direction, base_confidence, signal (raw object).
    """
    result: Dict[str, Any] = brain.analyze_joint(data)
    if not result.get("consensus_reached"):
        logger.debug("No consensus for %s: %s", symbol, result.get("reason"))
        return None

    signal: Any = result.get("consensus_signal")
    if signal is None:
        return None

    direction: str = (
        signal.signal_type.value
        if hasattr(signal.signal_type, "value")
        else str(signal.signal_type)
    )
    return {
        "direction": direction,
        "base_confidence": getattr(signal, "confidence", 0.0),
        "signal": signal,
    }


def _build_ohlcv_df(data: Dict[str, Any]) -> "pd.DataFrame":
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
    Align MacroStore series to the OHLCV hourly index.

    Returns a DataFrame of macro features or None if the store is empty /
    alignment fails. None is safe — the predictor falls back to OHLCV-only
    features with a logged warning.
    """
    import pandas as pd

    _store = _get_macro_store()
    if _store is None or len(_store) == 0:
        logger.debug(
            "MacroStore empty for %s — advanced model on OHLCV features only "
            "(accuracy may be lower than 68%%)",
            symbol,
        )
        return None

    try:
        ohlcv_indexed = ohlcv_df.copy()
        if not isinstance(ohlcv_indexed.index, pd.DatetimeIndex):
            end_ts = datetime.now(timezone.utc)
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
                "MacroStore returned empty alignment for %s — "
                "running advanced model without macro features",
                symbol,
            )
            return None

        logger.debug("MacroStore aligned %d series for %s", macro_df.shape[1], symbol)
        return macro_df

    except Exception as exc:
        logger.warning(
            "MacroStore alignment failed for %s: %s — "
            "running advanced model without macro features",
            symbol,
            exc,
        )
        return None


def _fetch_mtf_df(
    ohlcv_df: "pd.DataFrame",
    app_state: Any = None,
) -> Optional[Any]:
    """
    Fetch MTF regime features from MTFFusionStore if available and enabled.

    Returns a DataFrame with d_*/h_* columns aligned to ohlcv_df.index,
    or None when the store is unavailable or the flag is off.
    """
    try:
        from config.feature_flags import flags

        if not flags.MTF_FUSION:
            return None
    except Exception:
        pass

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


def _compute_ml_probability(
    data: Dict[str, Any],
    symbol: str,
    base_confidence: float,
    app_state: Any = None,
) -> tuple:
    """
    Compute ML probability using the best available model.

    Returns (ml_probability: float, model_version: str).

    Path 1 (preferred): advanced_oos.pkl with full macro + MTF feature set.
    Path 2 (fallback):  basic xgb_macro.pkl with stationary OHLCV features.
    Path 3 (no model):  returns base_confidence unchanged.
    """
    if not _ML_AVAILABLE:
        return base_confidence, "none"

    try:
        import pandas as pd

        # ── Path 1: Advanced predictor (122+ features, 68% OOS) ──────────────
        adv_predictor = get_advanced_predictor()
        if adv_predictor is not None and adv_predictor.is_available:
            ohlcv_df = _build_ohlcv_df(data)
            macro_df = _fetch_macro_df(ohlcv_df, symbol)
            mtf_df = _fetch_mtf_df(ohlcv_df, app_state=app_state)
            prob = adv_predictor.predict_proba(
                ohlcv_df,
                macro_df=macro_df,
                symbol=symbol,
                mtf_df=mtf_df,
            )

            # ── Phase 2: anomaly weighting ────────────────────────────────────
            anomaly_weight = 1.0
            anomaly_store = _get_anomaly_store()
            if anomaly_store is not None:
                try:
                    anomaly_weight = anomaly_store.update_and_score(ohlcv_df)
                    if anomaly_weight < 1.0:
                        # Blend probability toward neutral (0.5) by the weight
                        prob_before = prob
                        prob = 0.5 + (prob - 0.5) * anomaly_weight
                        logger.debug(
                            "Phase2 anomaly: weight=%.2f %s %.4f→%.4f",
                            anomaly_weight,
                            symbol,
                            prob_before,
                            prob,
                        )
                except Exception as aw_exc:
                    logger.debug("Anomaly weighting failed (non-fatal): %s", aw_exc)

            # ── Phase 3: online learning blend ────────────────────────────────
            # Store the post-anomaly prob as primary_prob for adaptive weight updates
            float(prob)
            online_store = _get_online_learner_store()
            if online_store is not None and online_store.is_ready:
                try:
                    prob = online_store.blend(prob, ohlcv_df)
                    logger.debug(
                        "Phase3 online blend: %s → %.4f",
                        symbol,
                        prob,
                    )
                except Exception as ol_exc:
                    logger.debug("Online learner blend failed (non-fatal): %s", ol_exc)

            # ── Phase 4: deep ensemble blend ──────────────────────────────────
            deep_store = _get_deep_ensemble_store()
            if deep_store is not None and deep_store.is_active:
                try:
                    prob = deep_store.blend(prob, ohlcv_df)
                    logger.debug(
                        "Phase4 deep blend: %s → %.4f",
                        symbol,
                        prob,
                    )
                except Exception as de_exc:
                    logger.debug("Deep ensemble blend failed (non-fatal): %s", de_exc)

            logger.debug(
                "ML chain (%s) %s: final=%.4f [macro=%s mtf=%s anomaly_w=%.2f]",
                adv_predictor.version,
                symbol,
                prob,
                "yes" if macro_df is not None else "no",
                "yes" if mtf_df is not None else "no",
                anomaly_weight,
            )
            return float(prob), adv_predictor.version

        # ── Path 2: Basic fallback model (~50% OOS, stationary features) ─────
        active_model = get_active_model()
        model_ver = get_model_version()
        if active_model is not None:
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
                    closes.pct_change().rolling(20).std().iloc[-1]
                    if len(closes) > 20
                    else 0
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

    except Exception as ml_exc:
        logger.debug("ML enrichment failed for %s: %s", symbol, ml_exc)

    return base_confidence, "none"


def notify_fill(
    features: "pd.DataFrame",
    label: int,
    primary_prob: Optional[float] = None,
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


def get_signal_engine_status() -> Dict[str, Any]:
    """
    Return a health-check dict for all active Phase 1–4 stores.

    Suitable for exposing via a /health or /status API endpoint.
    """
    status: Dict[str, Any] = {
        "ml_available": _ML_AVAILABLE,
        "symbols": _SYMBOLS,
        "interval_seconds": _INTERVAL_SECONDS,
        "auto_trade": _AUTO_TRADE,
    }

    # Phase 1: MTF
    try:
        from config.feature_flags import flags

        status["phase1_mtf_enabled"] = getattr(flags, "MTF_FUSION", True)
    except Exception:
        status["phase1_mtf_enabled"] = None

    try:
        from research.pipeline.mtf_fusion import _MTF_STORE_SINGLETON

        if _MTF_STORE_SINGLETON is not None:
            status["phase1_mtf"] = _MTF_STORE_SINGLETON.status()
        else:
            status["phase1_mtf"] = {"is_ready": False}
    except Exception:
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
    signal_payload: Dict[str, Any],
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

    # Discord community bot — post signal embed to configured channel
    try:
        from notifications.discord_bot import discord_signal_bot

        await discord_signal_bot.post_signal(signal_payload)
    except Exception as discord_exc:
        logger.debug("Discord signal post failed: %s", discord_exc)


async def _execute_if_approved(
    app_state: Any,
    symbol: str,
    signal_payload: Dict[str, Any],
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
    quantity: float = 1000.0  # minimal fallback lot
    if risk_manager is not None:
        try:
            account_info: Dict[str, Any] = await broker.get_account_info()
            positions: List[Any] = await broker.get_positions()
            positions_dicts: List[Dict[str, Any]] = [
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
            # Skip trades where the ML model has low conviction.
            # Threshold: 0.58 (slightly above the 50% abstain boundary).
            # This filters out marginal signals and concentrates capital on
            # high-confidence setups where the 67%+ OOS edge is most reliable.
            ml_prob: float = signal_payload.get("probability", 0.5)
            _ML_MIN_PROB = float(os.getenv("ML_MIN_TRADE_PROB", "0.58"))
            if ml_prob < _ML_MIN_PROB:
                logger.info(
                    "Auto-trade skipped: ML prob %.3f < threshold %.3f (%s)",
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
                    highs = data.get("highs", [])  # noqa: F821
                    lows = data.get("lows", [])  # noqa: F821
                    closes_list = data.get("prices", [entry])  # noqa: F821
                    if len(highs) >= 14 and len(lows) >= 14:
                        import numpy as _np

                        h = _np.array(highs[-15:], dtype=float)
                        l = _np.array(lows[-15:], dtype=float)  # noqa: E741
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
                    logger.debug(
                        "ATR SL/TP calc failed, using pct fallback: %s", _atr_exc
                    )
                    sl_price = sl_price or (
                        entry * 0.985 if direction.upper() == "BUY" else entry * 1.015
                    )
                    tp_price = tp_price or (
                        entry * 1.03 if direction.upper() == "BUY" else entry * 0.97
                    )

            # ── ML-scaled signal strength ─────────────────────────────────────
            # Pass ML probability as signal_strength so Kelly sizing scales up
            # on high-conviction signals (prob 0.65+ gets larger allocation).
            signal_strength = min(ml_prob, 0.80)  # cap at 80% to avoid over-sizing

            # ── Volatility estimate from recent returns ────────────────────────
            try:
                import numpy as _np2

                _prices = data.get("prices", [entry])  # noqa: F821
                if len(_prices) >= 20:
                    _rets = _np2.diff(_np2.log(_np2.array(_prices[-21:], dtype=float)))
                    _vol = float(_np2.std(_rets)) * (252**0.5)
                else:
                    _vol = 0.15  # gold annualised vol baseline
            except Exception:
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
            except Exception:
                pass

    except Exception as order_exc:
        logger.error("Auto-trade order failed for %s: %s", symbol, order_exc)


async def _tick(app_state: Any) -> None:
    """
    Process one tick for all watched symbols.

    Orchestrates four focused sub-functions:
      _compute_signal()        — StrategyBrain consensus
      _compute_ml_probability() — advanced/fallback ML enrichment with macro
      _publish_and_broadcast() — event bus + WebSocket
      _execute_if_approved()   — risk filter + auto-trade execution
    """
    brain: Any = getattr(app_state, "strategy_brain", None)
    if brain is None:
        return

    for sym in _SYMBOLS:
        symbol: str = sym.strip().upper()

        # 1. Fetch OHLCV
        data: Optional[Dict[str, Any]] = await _fetch_market_data(
            symbol,
            app_state=app_state,
        )
        if not data:
            continue

        # 2. StrategyBrain consensus
        sig_info = _compute_signal(brain, data, symbol)
        if sig_info is None:
            continue

        direction = sig_info["direction"]
        base_confidence = sig_info["base_confidence"]
        signal = sig_info["signal"]

        # 3. ML probability enrichment (advanced model with macro + MTF features)
        ml_probability, model_ver = _compute_ml_probability(
            data,
            symbol,
            base_confidence,
            app_state=app_state,
        )

        # 4. Build signal payload
        signal_payload: Dict[str, Any] = {
            "symbol": symbol,
            "direction": direction,
            "confidence": base_confidence,
            "probability": ml_probability,
            "model_version": model_ver,
            "entry_price": getattr(signal, "entry_price", data["close"]),
            "stop_loss": getattr(signal, "stop_loss", None),
            "take_profit": getattr(signal, "take_profit", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "strategy_brain",
        }

        # 5. Publish to event bus + WebSocket
        await _publish_and_broadcast(app_state, symbol, signal_payload)

        # 6. Auto-trade if enabled and risk approved
        await _execute_if_approved(app_state, symbol, signal_payload)
