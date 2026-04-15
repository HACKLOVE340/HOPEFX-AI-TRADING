# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/oanda_ws.py — REMOVED: streaming moved to data_feed.NuclearStreamer.

This module previously contained OANDAStreamAdapter, which streamed live
prices from OANDA's SSE endpoint.  That responsibility has been transferred
to data_feed.NuclearStreamer (Finnhub / Twelve Data / Polygon WebSockets).

OANDAStreamAdapter is retained as a tombstone class that raises
StreamingForbiddenError on any attempt to start a stream, so that stale import
sites fail loudly at startup rather than silently delivering no data.

Migration
---------
Replace any usage of OANDAStreamAdapter with NuclearStreamer:

    # Before (wrong — broker used for streaming):
    from brokers.oanda_ws import OANDAStreamAdapter
    adapter = OANDAStreamAdapter(api_key=..., account_id=..., instruments=[...])
    await adapter.start()

    # After (correct — dedicated streaming layer):
    from data_feed import NuclearStreamer
    streamer = NuclearStreamer()
    streamer.subscribe(my_component)   # component must have on_new_price(price)
    await streamer.run()

OANDA credentials are still used for ORDER EXECUTION via brokers.oanda_stream
(OANDAStream) and brokers.oanda (OANDABroker).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class StreamingForbiddenError(RuntimeError):
    """
    Raised when code attempts to stream prices through OANDAStreamAdapter.

    Live price data must flow exclusively through data_feed.NuclearStreamer.
    """

    def __init__(self, method: str = "start") -> None:
        super().__init__(
            f"ARCHITECTURAL VIOLATION: OANDAStreamAdapter.{method}() called. "
            "OANDA is for ORDER EXECUTION ONLY. "
            "Use data_feed.NuclearStreamer for live price streaming "
            "(Finnhub / Twelve Data / Polygon WebSockets)."
        )


class OANDAStreamAdapter:
    """
    Tombstone — raises StreamingForbiddenError on any streaming attempt.

    Kept so that stale import sites fail loudly at startup.
    Migrate to data_feed.NuclearStreamer.
    """

    def __init__(
        self,
        api_key: str = "",
        account_id: str = "",
        instruments: list[str] | None = None,
        practice: bool = True,
        on_tick: Callable[[dict[str, Any]], None] | None = None,
        connect_timeout: float = 30.0,
        reconcile_timeout: float = 10.0,
    ) -> None:
        logger.error(
            "OANDAStreamAdapter instantiated — this class is a tombstone. "
            "Migrate to data_feed.NuclearStreamer immediately. "
            "See brokers/oanda_ws.py module docstring for migration guide."
        )

    async def start(self) -> None:
        raise StreamingForbiddenError("start")

    async def stop(self) -> None:
        raise StreamingForbiddenError("stop")

    async def poll_rest(self) -> list[dict[str, Any]]:
        raise StreamingForbiddenError("poll_rest")
