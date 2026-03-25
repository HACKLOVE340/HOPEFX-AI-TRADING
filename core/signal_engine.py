"""
Signal Engine — bridges StrategyBrain to live order execution.

Runs as a background asyncio task. On each tick:
1. Fetches live OHLCV from yfinance (or broker price feed)
2. Runs StrategyBrain.analyze_joint()
3. If consensus reached → passes signal through RiskManager
4. If approved → places order via broker
5. Broadcasts result over WebSocket
6. Logs to ComplianceManager audit trail
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Macro-aware ML model (loaded lazily) ─────────────────────────────────────
try:
    from ml import get_active_model, get_model_version
    _ML_AVAILABLE: bool = True
except Exception:
    _ML_AVAILABLE = False

    def get_active_model() -> Optional[Any]:  # type: ignore[misc]
        return None

    def get_model_version() -> str:  # type: ignore[misc]
        return "none"

# Symbols the engine watches (overridden by ALLOWED_SYMBOLS env var)
import os
_SYMBOLS = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")
_INTERVAL_SECONDS = int(os.getenv("SIGNAL_ENGINE_INTERVAL", "60"))
_AUTO_TRADE = os.getenv("SIGNAL_ENGINE_AUTO_TRADE", "false").lower() == "true"


async def _fetch_market_data(symbol: str, app_state: Any = None) -> Optional[Dict[str, Any]]:
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
                highs  = [float(b["high"])  for b in bars]
                lows   = [float(b["low"])   for b in bars]
                volumes = [float(b.get("volume", 0)) for b in bars]
                return {
                    "symbol": symbol,
                    "open":   float(last["open"]),
                    "high":   float(last["high"]),
                    "low":    float(last["low"]),
                    "close":  float(last["close"]),
                    "volume": float(last.get("volume", 0)),
                    "prices": prices,
                    "highs":  highs,
                    "lows":   lows,
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
                    "open": price, "high": price, "low": price, "close": price,
                    "volume": 0.0,
                    "prices": [price],
                    "highs":  [price],
                    "lows":   [price],
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
        _SYMBOLS, _INTERVAL_SECONDS, _AUTO_TRADE,
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


async def _tick(app_state: Any) -> None:
    """Process one tick for all watched symbols."""
    brain: Any = getattr(app_state, "strategy_brain", None)
    if brain is None:
        return

    sym: str
    for sym in _SYMBOLS:
        symbol: str = sym.strip().upper()
        data: Optional[Dict[str, Any]] = await _fetch_market_data(symbol, app_state=app_state)
        if not data:
            continue

        # ── Run StrategyBrain ────────────────────────────────────────────────
        result: Dict[str, Any] = brain.analyze_joint(data)

        if not result.get("consensus_reached"):
            logger.debug("No consensus for %s: %s", symbol, result.get("reason"))
            continue

        signal: Any = result.get("consensus_signal")
        if signal is None:
            continue

        direction: str = (
            signal.signal_type.value
            if hasattr(signal.signal_type, "value")
            else str(signal.signal_type)
        )
        base_confidence: float = getattr(signal, "confidence", 0.0)

        # ── ML model probability enrichment ──────────────────────────────────
        ml_probability: float = base_confidence
        active_model: Optional[Any] = get_active_model() if _ML_AVAILABLE else None
        model_ver: str = get_model_version() if _ML_AVAILABLE else "none"

        if active_model is not None:
            try:
                import pandas as pd
                import numpy as np
                # Build a minimal feature row from available OHLCV data
                prices = data.get("prices", [data["close"]])
                closes = pd.Series(prices)
                feat = {
                    "close": data["close"],
                    "open":  data["open"],
                    "high":  data["high"],
                    "low":   data["low"],
                    "volume": data.get("volume", 0),
                    "ret_1":  closes.pct_change(1).iloc[-1] if len(closes) > 1 else 0,
                    "ret_5":  closes.pct_change(5).iloc[-1] if len(closes) > 5 else 0,
                    "ret_20": closes.pct_change(20).iloc[-1] if len(closes) > 20 else 0,
                    "vol_20": closes.pct_change().rolling(20).std().iloc[-1] if len(closes) > 20 else 0,
                }
                X = pd.DataFrame([feat])
                # Use predict_proba if available, else predict
                if hasattr(active_model, "predict_proba"):
                    proba = active_model.predict_proba(X)
                    # Take probability of the positive class
                    ml_probability = float(proba[0][1]) if proba.shape[1] > 1 else float(proba[0][0])
                elif hasattr(active_model, "predict"):
                    ml_probability = float(active_model.predict(X)[0])
                logger.debug("ML model (%s) probability for %s: %.4f", model_ver, symbol, ml_probability)
            except Exception as ml_exc:
                logger.debug("ML enrichment failed for %s: %s", symbol, ml_exc)

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

        # ── Publish typed SignalEvent ─────────────────────────────────────────
        try:
            from events.typed_events import EventEnvelope, SignalEvent, publish_sync
            typed_signal = SignalEvent(
                symbol=symbol,
                action=direction.upper(),
                confidence=base_confidence,
                probability=ml_probability,
                entry_price=signal_payload["entry_price"],
                stop_loss=signal_payload["stop_loss"],
                take_profit=signal_payload["take_profit"],
                model_version=model_ver,
            )
            publish_sync(EventEnvelope.wrap(source="signal_engine", payload=typed_signal, model_version=model_ver))
        except Exception as ev_exc:
            logger.debug("Typed event publish failed: %s", ev_exc)

        logger.info(
            "Brain consensus: %s %s confidence=%.2f ml_prob=%.4f model=%s",
            symbol, direction, base_confidence, ml_probability, model_ver,
        )

        # ── Broadcast signal over WebSocket ──────────────────────────────────
        ws = getattr(app_state, "ws_manager", None)
        if ws is not None:
            try:
                await ws.broadcast_signal(symbol, signal_payload)
            except Exception as ws_exc:
                logger.warning("Signal broadcast failed: %s", ws_exc)

        # ── Auto-trade if enabled and risk approved ───────────────────────────
        if not _AUTO_TRADE:
            continue

        broker: Any = getattr(app_state, "broker", None)
        risk_manager: Any = getattr(app_state, "risk_manager", None)
        if broker is None:
            continue

        # Map signal direction to order side
        direction = signal_payload["direction"].upper()
        if direction not in ("BUY", "SELL"):
            continue

        # Risk gate
        quantity: float
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
                        "Auto-trade blocked by risk manager: %s", assessment.messages
                    )
                    continue

                # Calculate position size
                equity: float = account_info.get("equity", 100_000)
                sizing: Any = risk_manager.calculate_position_size(
                    symbol=symbol,
                    signal_strength=signal_payload["confidence"],
                    entry_price=signal_payload["entry_price"],
                    stop_loss_price=signal_payload["stop_loss"] or signal_payload["entry_price"] * 0.99,
                    take_profit_price=signal_payload["take_profit"] or signal_payload["entry_price"] * 1.02,
                    account_equity=equity,
                    volatility=0.1,
                    existing_positions=positions_dicts,
                )
                if not sizing.approved:
                    logger.info("Auto-trade sizing rejected: %s", sizing.reason)
                    continue
                quantity = sizing.recommended_size
            except Exception as risk_exc:
                logger.error("Risk check failed in signal engine: %s", risk_exc)
                continue
        else:
            quantity = 1000.0  # minimal fallback lot

        # Place order
        try:
            order = await broker.place_market_order(
                symbol=symbol,
                side=direction.lower(),
                quantity=quantity,
            )
            logger.info(
                "Auto-trade executed: %s %s %s qty=%s order_id=%s",
                direction, symbol, signal_payload["confidence"], quantity, order.id,
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
