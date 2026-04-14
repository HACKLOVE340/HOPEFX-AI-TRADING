# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/gold/metalpriceapi.py
======================================
MetalpriceAPI adapter — https://metalpriceapi.com/

Free tier: 100 requests/month, 1 request/hour
Paid tiers: up to 50,000 requests/month, 1 request/minute

Endpoint: GET https://api.metalpriceapi.com/v1/latest?api_key=KEY&base=XAU&currencies=USD
Response: {"success":true,"base":"XAU","rates":{"USD":1985.5},"timestamp":1700000000}
"""

from __future__ import annotations

import logging

from data_layer.feeds.gold.base import GoldFeedBase
from data_layer.types import FeedSource, GoldTick

logger = logging.getLogger(__name__)

_BASE = "https://api.metalpriceapi.com/v1"


class MetalpriceAPIFeed(GoldFeedBase):
    """MetalpriceAPI — REST polling adapter."""

    name = FeedSource.METALPRICEAPI
    _api_key_env = "METALPRICEAPI_KEY"  # pragma: allowlist secret
    _base_url = _BASE
    _min_interval_s = 60.0  # free tier: 1 req/hour; paid: 1 req/min

    async def fetch_tick(self) -> GoldTick:
        if not self.is_configured:
            raise RuntimeError("METALPRICEAPI_KEY not set")

        data = await self._get(
            f"{_BASE}/latest",
            params={"api_key": self._api_key, "base": "XAU", "currencies": "USD"},
        )

        if not data.get("success"):
            raise ValueError(f"MetalpriceAPI error: {data}")

        rates = data.get("rates", {})
        usd_per_xau = float(rates.get("USD", 0))

        if usd_per_xau <= 0:
            raise ValueError(f"MetalpriceAPI invalid rate: {data}")

        return self._make_tick(mid=usd_per_xau, raw=data)
