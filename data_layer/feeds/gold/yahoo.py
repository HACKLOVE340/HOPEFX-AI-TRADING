# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/gold/yahoo.py
==============================
Keyless gold price feed backed by Yahoo Finance.

This is the DEFAULT gold tick source: it needs **no API key**, so the data
layer produces live gold prices out of the box without GoldAPI, Metals.dev,
OANDA, or any paid provider. When a keyed provider *is* configured it takes
priority (see GoldFeedManager); Yahoo is the always-available baseline.

Source
------
Yahoo's public chart endpoint for COMEX gold futures (GC=F), which tracks
XAU/USD spot closely (a small, slowly-varying basis). No key required:

    GET https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d

The response carries ``chart.result[0].meta.regularMarketPrice``. Yahoo does
not publish a real bid/ask here, so a typical gold spread is synthesised by the
base class (``_make_tick``). For execution you should still use a real broker
feed; this is for charting, signals, and paper trading.
"""

from __future__ import annotations

import logging

from data_layer.feeds.gold.base import GoldFeedBase
from data_layer.types import FeedSource, GoldTick

logger = logging.getLogger(__name__)

# COMEX gold front-month — keyless, reliable proxy for XAU/USD spot.
_YAHOO_GOLD_TICKER = "GC=F"
_CHART_URL = f"https://query1.finance.yahoo.com/v8/finance/chart/{_YAHOO_GOLD_TICKER}"

# Yahoo rejects requests without a browser-like User-Agent.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class YahooGoldFeed(GoldFeedBase):
    """Keyless Yahoo Finance gold feed (REST polling, no API key)."""

    name = FeedSource.YAHOO

    def __init__(self) -> None:
        super().__init__()
        # Yahoo tolerates a few requests/sec; keep a courteous floor.
        self._min_interval_s = 2.0

    @property
    def is_configured(self) -> bool:
        # Keyless — always available.
        return True

    async def fetch_tick(self) -> GoldTick:
        params = {"interval": "1m", "range": "1d"}
        data = await self._get(_CHART_URL, params=params, headers=_HEADERS)

        try:
            result = data["chart"]["result"][0]
            meta = result.get("meta", {})
        except (KeyError, IndexError, TypeError) as exc:
            self._on_error("parse", msg=f"unexpected Yahoo payload: {exc}")
            raise ValueError(f"Yahoo gold: unexpected payload shape: {exc}") from exc

        price = meta.get("regularMarketPrice")
        # Some payloads only populate the last close on the indicators array;
        # fall back to the most recent non-null close from the 1-minute series.
        if not price:
            try:
                closes = result["indicators"]["quote"][0]["close"]
                price = next((c for c in reversed(closes) if c), None)
            except (KeyError, IndexError, TypeError):
                price = None

        if not price or float(price) <= 0:
            self._on_error("empty", msg="Yahoo gold: no price in payload")
            raise ValueError("Yahoo gold: no usable price in payload")

        return self._make_tick(mid=float(price), raw={"source": "yahoo_chart", "ticker": _YAHOO_GOLD_TICKER})
