# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/gold/commodity_api.py
=======================================
CommodityPriceAPI adapter — https://commoditypriceapi.com/

Free tier: 100 requests/month
Paid tiers: up to 100,000 requests/month

Endpoint: GET https://api.commoditypriceapi.com/v1/latest?api_key=KEY&base=XAU&symbols=USD
Response: {"success":true,"base":"XAU","rates":{"USD":1985.5},"timestamp":1700000000}
"""

from __future__ import annotations

import logging

from data_layer.feeds.gold.base import GoldFeedBase
from data_layer.types import FeedSource, GoldTick

logger = logging.getLogger(__name__)

_BASE = "https://api.commoditypriceapi.com/v1"


class CommodityAPIFeed(GoldFeedBase):
    """CommodityPriceAPI — REST polling adapter."""

    name = FeedSource.COMMODITY_API
    _api_key_env = "COMMODITY_PRICE_API_KEY"  # pragma: allowlist secret
    _base_url = _BASE
    _min_interval_s = 60.0

    async def fetch_tick(self) -> GoldTick:
        if not self.is_configured:
            raise RuntimeError("COMMODITY_PRICE_API_KEY not set")

        data = await self._get(
            f"{_BASE}/latest",
            params={
                "api_key": self._api_key,
                "base": "XAU",
                "symbols": "USD",
            },
        )

        if not data.get("success"):
            raise ValueError(f"CommodityPriceAPI error: {data}")

        rates = data.get("rates", {})
        usd_per_xau = float(rates.get("USD", 0))

        if usd_per_xau <= 0:
            raise ValueError(f"CommodityPriceAPI invalid rate: {data}")

        return self._make_tick(mid=usd_per_xau, raw=data)
