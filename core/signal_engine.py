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
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Symbols the engine watches (overridden by ALLOWED_SYMBOLS env var)
import os
_SYMBOLS = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")
_INTERVAL_SECONDS = int(os.getenv("SIGNAL_ENGINE_INTERVAL", "60"))
_AUTO_TRADE = os.getenv("SIGNAL_ENGINE_AUTO_TRADE", "false").lower() == "true"


async def _fetch_market_data(symbol: str) -> Optional[dict]:
    """Fetch latest OHLCV bar from yfinance."""
    try:
        import yfinance as yf
        _TICKER_MAP = {
            "XAUUSD": "GC=F",
            "EURUSD": "EURUSD=X",
            "BTCUSD": "BTC-USD",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "USDJPY=X",
            "AUDUSD": "AUDUSD=X",
            "USDCHF": "USDCHF=X",
        }
        ticker = _TICKER_MAP.get(symbol.upper(), symbol)
        df = yf.download(ticker, period="5d", interval="1h", progress=False, auto_adjust=True)
        if df.empty:
            return None
        row = df.iloc[-1]
        prices = df["Close"].dropna().tolist()
        highs = df["High"].dropna().tolist()
        lows = df["Low"].dropna().tolist()
        volumes = df["Volume"].dropna().tolist()
        return {
            "symbol": symbol,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
            "prices": prices,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("Market data fetch failed for %s: %s", symbol, exc)
        return None


async def run_signal_engine(app_state: Any):
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


async def _tick(app_state: Any):
    """Process one tick for all watched symbols."""
    brain = getattr(app_state, "strategy_brain", None)
    if brain is None:
        return

    for symbol in _SYMBOLS:
        symbol = symbol.strip().upper()
        data = await _fetch_market_data(symbol)
        if not data:
            continue

        # ── Run StrategyBrain ────────────────────────────────────────────────
        result = brain.analyze_joint(data)

        if not result.get("consensus_reached"):
            logger.debug("No consensus for %s: %s", symbol, result.get("reason"))
            continue

        signal = result.get("consensus_signal")
        if signal is None:
            continue

        signal_payload = {
            "symbol": symbol,
            "direction": signal.signal_type.value if hasattr(signal.signal_type, "value") else str(signal.signal_type),
            "confidence": getattr(signal, "confidence", 0.0),
            "entry_price": getattr(signal, "entry_price", data["close"]),
            "stop_loss": getattr(signal, "stop_loss", None),
            "take_profit": getattr(signal, "take_profit", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "strategy_brain",
        }

        logger.info(
            "Brain consensus: %s %s confidence=%.2f",
            symbol, signal_payload["direction"], signal_payload["confidence"],
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

        broker = getattr(app_state, "broker", None)
        risk_manager = getattr(app_state, "risk_manager", None)
        if broker is None:
            continue

        # Map signal direction to order side
        direction = signal_payload["direction"].upper()
        if direction not in ("BUY", "SELL"):
            continue

        # Risk gate
        if risk_manager is not None:
            try:
                account_info = await broker.get_account_info()
                positions = await broker.get_positions()
                positions_dicts = [
                    {"symbol": p.symbol, "quantity": p.quantity,
                     "current_price": getattr(p, "current_price", 0)}
                    for p in positions
                ]
                assessment = risk_manager.assess_risk(account_info, positions_dicts)
                if not assessment.can_trade:
                    logger.info(
                        "Auto-trade blocked by risk manager: %s", assessment.messages
                    )
                    continue

                # Calculate position size
                equity = account_info.get("equity", 100_000)
                sizing = risk_manager.calculate_position_size(
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
            quantity = 1000  # minimal fallback lot

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
