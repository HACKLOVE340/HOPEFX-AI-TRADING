# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/background_tasks.py
========================
Long-running asyncio background tasks for the trading server.

Extracted from app.py to keep the application entry point under 300 lines.

Tasks
-----
- oanda_price_poller   — polls OANDA pricing endpoint, writes to broker price table
- price_stream_loop    — broadcasts paper-broker prices to WebSocket clients
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


async def oanda_price_poller(state: Any) -> None:
    """
    Background task: polls OANDA's pricing endpoint and writes real bid/ask
    into the active broker's price table via update_market_price().

    Only runs when BROKER_OANDA_TOKEN and BROKER_OANDA_ACCOUNT are set.
    Falls back silently if OANDA is unreachable so paper trading still works.
    """
    _SYMBOLS = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")
    _SYMBOLS = [s.strip().upper() for s in _SYMBOLS]
    _INTERVAL = float(os.getenv("OANDA_POLL_INTERVAL", "1.0"))

    oanda_token = os.getenv("BROKER_OANDA_TOKEN", "")
    oanda_account = os.getenv("BROKER_OANDA_ACCOUNT", "")
    oanda_env = os.getenv("BROKER_OANDA_ENVIRONMENT", "practice")

    if not oanda_token or not oanda_account:
        logger.info("OANDA price poller disabled — BROKER_OANDA_TOKEN/ACCOUNT not set")
        return

    try:
        from brokers.oanda import OANDAConnector

        oanda = OANDAConnector(
            api_key=oanda_token,
            account_id=oanda_account,
            practice=(oanda_env != "live"),
        )
        if not oanda.connect():
            logger.warning("OANDA price poller: connection failed — using static prices")
            return
        logger.info(
            "OANDA price poller connected — symbols=%s interval=%.1fs",
            _SYMBOLS,
            _INTERVAL,
        )
    except Exception as exc:
        logger.warning("OANDA price poller init failed: %s", exc)
        return

    from core.circuit_breaker import CircuitBreaker, CircuitBreakerOpen

    _cb = CircuitBreaker.get("oanda_poller", failure_threshold=5, reset_timeout=60.0)
    _backoff = 1.0
    _MAX_BACKOFF = 300.0

    while True:
        try:
            async with _cb:
                prices = oanda.get_live_prices(_SYMBOLS)
            broker = getattr(state, "broker", None)
            if broker is not None and prices:
                for sym, tick in prices.items():
                    mid = tick.get("mid", 0.0)
                    if mid > 0 and hasattr(broker, "update_market_price"):
                        broker.update_market_price(sym, mid)
            _backoff = 1.0
        except asyncio.CancelledError:
            logger.info("OANDA price poller stopped")
            oanda.disconnect()
            return
        except CircuitBreakerOpen as cbo:
            logger.warning(
                "OANDA price poller: circuit OPEN — sleeping %.0fs", cbo.retry_after
            )
            await asyncio.sleep(min(cbo.retry_after, _MAX_BACKOFF))
            continue
        except Exception as exc:
            logger.warning(
                "OANDA price poller error (backoff=%.0fs): %s", _backoff, exc
            )
            await asyncio.sleep(_backoff)
            _backoff = min(_backoff * 2, _MAX_BACKOFF)
            continue

        await asyncio.sleep(_INTERVAL)


async def price_stream_loop(ws_manager: Any) -> None:
    """
    Background task: polls the paper broker for current prices and broadcasts
    tick updates to all connected WebSocket clients.

    Uses the broker's in-memory price table so no external feed is required
    for paper trading.  When a real broker is wired in, replace the polling
    loop with the broker's native streaming callback.
    """
    from app import app_state

    _STREAM_SYMBOLS = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")
    _POLL_INTERVAL = float(os.getenv("PRICE_STREAM_INTERVAL", "1.0"))

    logger.info(
        "Price stream loop started — symbols=%s interval=%.1fs",
        _STREAM_SYMBOLS,
        _POLL_INTERVAL,
    )

    while True:
        try:
            broker = getattr(app_state, "broker", None)
            if broker is not None:
                for sym in _STREAM_SYMBOLS:
                    sym = sym.strip().upper()
                    price = broker.get_market_price(sym)
                    if price:
                        spread = price * 0.0001
                        await ws_manager.broadcast_price_update(
                            symbol=sym,
                            price=price,
                            bid=round(price - spread / 2, 5),
                            ask=round(price + spread / 2, 5),
                        )
        except asyncio.CancelledError:
            logger.info("Price stream loop stopped")
            return
        except Exception as exc:
            logger.warning("Price stream error: %s", exc)

        await asyncio.sleep(_POLL_INTERVAL)
