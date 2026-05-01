# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/background_tasks.py
========================
Long-running asyncio background tasks for the trading server.

Tasks
-----
nuclear_price_bridge  — subscribes to NuclearStreamer (Finnhub / Twelve Data /
                        Polygon) and writes validated ticks into the active
                        broker's price table via update_market_price().
                        OANDA is never used as a price source.

price_stream_loop     — reads the broker's in-memory price table and broadcasts
                        tick updates to all connected WebSocket clients.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


async def nuclear_price_bridge(state: Any) -> None:
    """
    Subscribe to NuclearStreamer and write ticks into the broker price table.

    Requires at least one of:
        FINNHUB_API_KEY, TWELVE_API_KEY, POLYGON_API_KEY

    When a validated tick arrives it calls ``broker.update_market_price(sym, price)``
    so the paper broker and any downstream consumers see live prices without
    polling OANDA or any other broker endpoint.
    """
    has_key = any(
        [
            os.getenv("FINNHUB_API_KEY"),
            os.getenv("TWELVE_API_KEY"),
            os.getenv("POLYGON_API_KEY"),
        ]
    )
    if not has_key:
        logger.info(
            "nuclear_price_bridge disabled — set FINNHUB_API_KEY, TWELVE_API_KEY, "
            "or POLYGON_API_KEY to enable live WebSocket price feed."
        )
        return

    try:
        from data_feed import NuclearStreamer
    except ImportError as exc:
        logger.error("nuclear_price_bridge: cannot import NuclearStreamer — %s", exc)
        return

    symbol = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")[0].strip().upper()

    class _BrokerPriceBridge:
        """Subscriber that writes each validated tick into the broker price table."""

        async def on_new_price(self, price: float) -> None:
            broker = getattr(state, "broker", None)
            if broker is not None and hasattr(broker, "update_market_price"):
                try:
                    broker.update_market_price(symbol, price)
                except Exception as _exc:
                    logger.debug("update_market_price error: %s", _exc)

    streamer = NuclearStreamer(symbol=symbol)
    streamer.subscribe(_BrokerPriceBridge())

    logger.info(
        "nuclear_price_bridge started — symbol=%s finnhub=%s twelvedata=%s polygon=%s",
        symbol,
        bool(os.getenv("FINNHUB_API_KEY")),
        bool(os.getenv("TWELVE_API_KEY")),
        bool(os.getenv("POLYGON_API_KEY")),
    )

    try:
        await streamer.run()
    except asyncio.CancelledError:
        await streamer.stop()
        logger.info("nuclear_price_bridge stopped")
    except Exception as exc:
        logger.error("nuclear_price_bridge fatal error: %s", exc)
        await streamer.stop()


async def price_stream_loop(ws_manager: Any) -> None:
    """
    Broadcast live prices to all connected WebSocket clients.

    Reads the broker's in-memory price table (populated by nuclear_price_bridge)
    and pushes updates to ws_manager at PRICE_STREAM_INTERVAL seconds.
    """
    from core.app_state import app_state

    _STREAM_SYMBOLS = [s.strip().upper() for s in os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",") if s.strip()]
    _POLL_INTERVAL = float(os.getenv("PRICE_STREAM_INTERVAL", "1.0"))

    logger.info(
        "price_stream_loop started — symbols=%s interval=%.1fs",
        _STREAM_SYMBOLS,
        _POLL_INTERVAL,
    )

    while True:
        try:
            broker = getattr(app_state, "broker", None)
            if broker is not None:
                for sym in _STREAM_SYMBOLS:
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
            logger.info("price_stream_loop stopped")
            return
        except Exception as exc:
            logger.warning("price_stream_loop error: %s", exc)

        await asyncio.sleep(_POLL_INTERVAL)
