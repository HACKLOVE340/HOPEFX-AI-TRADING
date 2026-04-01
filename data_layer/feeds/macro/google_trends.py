# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/macro/google_trends.py
=========================================
Google Trends search volume for gold-related queries.

Uses the unofficial Google Trends API (pytrends) to fetch weekly
search interest for "gold price", "buy gold", "gold ETF", etc.

Produces:
  - gtrend_gold_price   — "gold price" search interest (0–100)
  - gtrend_buy_gold     — "buy gold" search interest (0–100)
  - gtrend_gold_etf     — "gold ETF" search interest (0–100)
  - gtrend_composite    — Equal-weight composite (average of above)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timezone
from functools import partial

UTC = timezone.utc
import pandas as pd

logger = logging.getLogger(__name__)

# Keywords to track
_KEYWORDS = ["gold price", "buy gold", "gold ETF"]
_SERIES_MAP = {
    "gold price": "gtrend_gold_price",
    "buy gold": "gtrend_buy_gold",
    "gold ETF": "gtrend_gold_etf",
}
_LOOKBACK_YEARS = int(os.getenv("GTRENDS_LOOKBACK_YEARS", "5"))


class GoogleTrendsFeed:
    """
    Google Trends search volume feed using pytrends.

    Fetches weekly search interest for gold-related queries and
    injects them into MacroStore as macro features.
    """

    async def fetch_series(self) -> dict[str, pd.Series]:
        """
        Fetch Google Trends data for gold keywords.

        Returns dict mapping series names to pd.Series(float, DatetimeIndex[UTC]).
        """
        try:
            from pytrends.request import TrendReq  # noqa: PLC0415
        except ImportError:
            logger.warning(
                "Google Trends: pytrends not installed. "
                "Install with: pip install pytrends"
            )
            return {}

        timeframe = f"today {_LOOKBACK_YEARS * 12}-m"
        loop = asyncio.get_event_loop()

        def _blocking_fetch() -> pd.DataFrame:
            pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
            pt.build_payload(
                kw_list=_KEYWORDS,
                cat=0,
                timeframe=timeframe,
                geo="",
                gprop="",
            )
            return pt.interest_over_time()

        try:
            df: pd.DataFrame = await loop.run_in_executor(None, _blocking_fetch)
        except Exception as exc:
            logger.warning("Google Trends fetch error: %s", exc)
            return {}

        if df.empty:
            return {}

        # Drop 'isPartial' column if present
        if "isPartial" in df.columns:
            df = df.drop(columns=["isPartial"])

        # Ensure UTC index
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        result: dict[str, pd.Series] = {}
        for kw, series_name in _SERIES_MAP.items():
            if kw in df.columns:
                result[series_name] = df[kw].astype(float).dropna()

        # Composite = equal-weight average of available series
        if result:
            avail = [s for s in result.values() if not s.empty]
            if avail:
                aligned = pd.concat(avail, axis=1).ffill()
                result["gtrend_composite"] = aligned.mean(axis=1).dropna()

        logger.info("Google Trends: fetched %d series (%d weeks)", len(result), len(df))
        return result

    async def inject_into_macro_store(self) -> int:
        """Fetch Google Trends and inject into MacroStore."""
        from ml.macro_store import macro_store  # noqa: PLC0415
        series = await self.fetch_series()
        count = 0
        for name, s in series.items():
            if not s.empty:
                macro_store._series[name] = s
                count += 1
        if count:
            logger.info("Google Trends: injected %d series", count)
        return count


google_trends_feed = GoogleTrendsFeed()
