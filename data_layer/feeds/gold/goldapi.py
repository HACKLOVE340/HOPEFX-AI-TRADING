# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/gold/goldapi.py
================================
GoldAPI.io adapter — https://www.goldapi.io/

Free tier: 100 requests/month
Paid tiers: up to 10,000 requests/month

Endpoint: GET https://www.goldapi.io/api/XAU/USD
Response includes: price, bid, ask, open, high, low, close, change, change_pct

API key header: x-access-token
"""

from __future__ import annotations

import logging

from data_layer.feeds.gold.base import GoldFeedBase
from data_layer.types import FeedSource, GoldTick, OHLCVBar

logger = logging.getLogger(__name__)

_BASE = "https://www.goldapi.io/api"


class GoldAPIFeed(GoldFeedBase):
    """GoldAPI.io — REST polling adapter."""

    name = FeedSource.GOLDAPI
    _api_key_env = "GOLDAPI_IO_KEY"
    _base_url = _BASE
    _min_interval_s = 2.0  # conservative — free tier is 100 req/month

    async def fetch_tick(self) -> GoldTick:
        if not self.is_configured:
            raise RuntimeError("GOLDAPI_IO_KEY not set")

        data = await self._get(
            f"{_BASE}/XAU/USD",
            headers={
                "x-access-token": self._api_key,
                "Content-Type": "application/json",
            },
        )

        # GoldAPI response shape:
        # {"metal":"XAU","currency":"USD","exchange":"FOREXCOM","symbol":"FOREXCOM:XAUUSD",
        #  "timestamp":1700000000,"prev_close_price":1980.5,"open_price":1981.0,
        #  "low_price":1975.0,"high_price":1990.0,"open_time":1700000000,
        #  "price":1985.5,"ch":5.0,"chp":0.25,"ask":1985.8,"bid":1985.2}

        price = float(data.get("price", 0))
        bid = float(data.get("bid", 0)) or None
        ask = float(data.get("ask", 0)) or None

        if price <= 0:
            raise ValueError(f"GoldAPI returned invalid price: {data}")

        return self._make_tick(mid=price, bid=bid, ask=ask, raw=data)

    async def fetch_ohlcv(self, timeframe: str = "1d", limit: int = 30) -> list[OHLCVBar]:
        """GoldAPI supports date-range historical queries."""
        # GoldAPI historical: GET /api/XAU/USD/{YYYYMMDD}
        # For simplicity, return empty — orchestrator uses Dukascopy for history
        return []
