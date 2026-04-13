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
import uuid
from datetime import datetime, timedelta, timezone

from data_layer.feeds.gold.base import GoldFeedBase
from data_layer.types import FeedSource, GoldTick, OHLCVBar

logger = logging.getLogger(__name__)

_BASE = "https://www.goldapi.io/api"
_UTC = timezone.utc

# GoldAPI timeframe → calendar days per bar (used to build date-range requests)
_TF_TO_DAYS: dict[str, int] = {
    "1d": 1,
    "1w": 7,
    "1M": 30,
}

# GoldAPI historical endpoint: GET /api/XAU/USD/{YYYYMMDD}
# Returns the OHLCV for that specific calendar day.
# There is no intraday history endpoint on any GoldAPI tier.


class GoldAPIFeed(GoldFeedBase):
    """GoldAPI.io — REST polling adapter."""

    name = FeedSource.GOLDAPI
    _api_key_env = "GOLDAPI_IO_KEY"  # pragma: allowlist secret
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
        """Fetch historical daily OHLCV bars from GoldAPI.io.

        GoldAPI historical endpoint:
            GET https://www.goldapi.io/api/XAU/USD/{YYYYMMDD}

        Response shape (same as spot, but with historical date):
            {
              "price": 1985.5,
              "open_price": 1981.0,
              "high_price": 1990.0,
              "low_price": 1975.0,
              "prev_close_price": 1980.5,
              "timestamp": 1700000000,
              ...
            }

        Limitations:
        - GoldAPI only provides *daily* bars regardless of the requested
          timeframe.  Sub-daily timeframes (1m, 5m, 1h, 4h) are not
          supported; callers should use Dukascopy or OANDA for intraday
          history.  If a sub-daily timeframe is requested this method logs
          a warning and returns [] so the orchestrator can fall back.
        - Free tier: 100 requests/month.  Each bar = 1 request.
          ``limit`` is capped at 30 to protect the quota.
        - Weekends and market holidays return no data; those dates are
          silently skipped.

        Args:
            timeframe: Bar size.  Only "1d", "1w", "1M" are supported.
            limit:     Number of bars to fetch (capped at 30).

        Returns:
            List of OHLCVBar sorted oldest-first.  May be shorter than
            ``limit`` if some dates had no data (weekends / holidays).
        """
        if not self.is_configured:
            logger.warning("GoldAPIFeed.fetch_ohlcv: GOLDAPI_IO_KEY not set — returning []")
            return []

        # Only daily (and coarser) bars are available
        if timeframe not in _TF_TO_DAYS:
            logger.warning(
                "GoldAPIFeed.fetch_ohlcv: timeframe '%s' not supported by GoldAPI "
                "(only 1d/1w/1M available) — returning []",
                timeframe,
            )
            return []

        days_per_bar = _TF_TO_DAYS[timeframe]
        # Cap to protect free-tier quota
        effective_limit = min(limit, 30)

        headers = {
            "x-access-token": self._api_key,
            "Content-Type": "application/json",
        }

        bars: list[OHLCVBar] = []
        today = datetime.now(_UTC).date()

        # Walk backwards from yesterday, one bar at a time
        cursor = today - timedelta(days=1)
        fetched = 0

        while fetched < effective_limit:
            date_str = cursor.strftime("%Y%m%d")
            url = f"{_BASE}/XAU/USD/{date_str}"

            try:
                data = await self._get(url, headers=headers)
            except Exception as exc:
                # Non-fatal: log and skip this date (holiday / weekend / rate limit)
                logger.debug(
                    "GoldAPIFeed.fetch_ohlcv: skipping %s — %s",
                    date_str,
                    exc,
                )
                cursor -= timedelta(days=days_per_bar)
                continue

            # GoldAPI returns an error dict on bad dates
            if not data or data.get("error") or data.get("code") == 404:
                cursor -= timedelta(days=days_per_bar)
                continue

            open_price = float(data.get("open_price") or data.get("price") or 0)
            high_price = float(data.get("high_price") or data.get("price") or 0)
            low_price = float(data.get("low_price") or data.get("price") or 0)
            close_price = float(data.get("price") or 0)

            if close_price <= 0:
                cursor -= timedelta(days=days_per_bar)
                continue

            # Synthesise open/high/low from close when not provided
            if open_price <= 0:
                open_price = close_price
            if high_price <= 0 or high_price < close_price:
                high_price = max(open_price, close_price)
            if low_price <= 0 or low_price > close_price:
                low_price = min(open_price, close_price)

            bar_open_dt = datetime(cursor.year, cursor.month, cursor.day, 0, 0, 0, tzinfo=_UTC)
            bar_close_dt = datetime(cursor.year, cursor.month, cursor.day, 23, 59, 59, tzinfo=_UTC)

            bars.append(
                OHLCVBar(
                    symbol="XAU_USD",
                    timeframe=timeframe,
                    open_time=bar_open_dt,
                    close_time=bar_close_dt,
                    open=round(open_price, 4),
                    high=round(high_price, 4),
                    low=round(low_price, 4),
                    close=round(close_price, 4),
                    volume=0.0,  # GoldAPI does not provide volume
                    tick_count=0,
                    source=FeedSource.GOLDAPI,
                    lineage_id=str(uuid.uuid4()),
                )
            )
            fetched += 1
            cursor -= timedelta(days=days_per_bar)

        # Return oldest-first
        bars.reverse()
        logger.info(
            "GoldAPIFeed.fetch_ohlcv: fetched %d/%d bars (timeframe=%s)",
            len(bars),
            effective_limit,
            timeframe,
        )
        return bars
