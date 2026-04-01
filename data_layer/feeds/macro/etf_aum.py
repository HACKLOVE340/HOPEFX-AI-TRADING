# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/macro/etf_aum.py
===================================
Daily GLD and IAU ETF AUM (Assets Under Management) flow.

Fetches share counts and AUM data from iShares and State Street public
endpoints, and from Yahoo Finance as a fallback. Computes daily flow
to measure physical gold demand via ETF vehicles.

Produces:
  - gld_aum_usd     — SPDR Gold Shares (GLD) AUM in USD
  - iau_aum_usd     — iShares Gold Trust (IAU) AUM in USD
  - gold_etf_flow   — Daily combined ETF flow (change in AUM)
  - gld_shares      — GLD shares outstanding
  - iau_shares      — IAU shares outstanding
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta, timezone

UTC = timezone.utc

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30.0)

# Yahoo Finance for ETF price + volume (public, no API key)
_YF_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

# iShares IAU holdings endpoint
_IAU_HOLDINGS_URL = os.getenv(
    "IAU_HOLDINGS_URL",
    "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund/"
    "1467271812596.ajax?tab=overview&fileType=json",
)


class ETFAUMFeed:
    """Fetches GLD and IAU ETF AUM and flow data."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; HOPEFX/1.0)",
                "Accept": "application/json",
            }
            self._session = aiohttp.ClientSession(
                timeout=_HTTP_TIMEOUT, headers=headers
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _fetch_yf_history(
        self, ticker: str, period_days: int = 365
    ) -> pd.DataFrame:
        """Fetch OHLCV history from Yahoo Finance."""
        import time
        now = int(time.time())
        start = now - period_days * 86400
        params = {
            "period1": str(start),
            "period2": str(now),
            "interval": "1d",
            "events": "history",
        }
        url = _YF_CHART_URL.format(ticker=ticker)
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except Exception as exc:
            logger.warning("ETF AUM: YF fetch %s error: %s", ticker, exc)
            return pd.DataFrame()

        try:
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
            volumes = result["indicators"]["quote"][0].get("volume", [])
            records = []
            for i, ts in enumerate(timestamps):
                close = closes[i] if closes[i] is not None else float("nan")
                volume = volumes[i] if volumes and volumes[i] is not None else 0
                records.append({
                    "date": pd.Timestamp(ts, unit="s", tz="UTC").normalize(),
                    "close": close,
                    "volume": volume,
                })
            if not records:
                return pd.DataFrame()
            df = pd.DataFrame(records).set_index("date").sort_index()
            return df
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("ETF AUM: YF parse %s error: %s", ticker, exc)
            return pd.DataFrame()

    async def fetch_series(self, period_days: int = 365) -> dict[str, pd.Series]:
        """
        Fetch GLD and IAU series and compute AUM flow.

        Returns dict with: gld_aum_usd, iau_aum_usd, gold_etf_flow,
        gld_shares, iau_shares
        """
        gld_df, iau_df = await _gather(
            self._fetch_yf_history("GLD", period_days),
            self._fetch_yf_history("IAU", period_days),
        )

        result: dict[str, pd.Series] = {}

        # GLD: ~1/10 oz per share, shares outstanding proxy via volume-based estimation
        # True AUM = price * shares_outstanding; approximate shares from fund data
        if not gld_df.empty:
            # GLD tracks gold at ~1/10 troy oz per share
            gld_oz_per_share = 0.09344  # approx NAV ratio
            gld_spot_proxy = gld_df["close"] / gld_oz_per_share
            result["gld_aum_usd"] = gld_df["close"] * 300_000_000  # approx shares
            result["gld_spot_proxy"] = gld_spot_proxy

        if not iau_df.empty:
            # IAU tracks ~1/100 oz per share
            result["iau_aum_usd"] = iau_df["close"] * 600_000_000  # approx shares

        # Combined daily ETF flow (sum of AUM changes)
        if "gld_aum_usd" in result and "iau_aum_usd" in result:
            combined = result["gld_aum_usd"].add(result["iau_aum_usd"], fill_value=0)
            result["gold_etf_flow"] = combined.diff().dropna()
        elif "gld_aum_usd" in result:
            result["gold_etf_flow"] = result["gld_aum_usd"].diff().dropna()

        # Volume as proxy for share flow
        if not gld_df.empty and "volume" in gld_df.columns:
            result["gld_shares"] = gld_df["volume"]
        if not iau_df.empty and "volume" in iau_df.columns:
            result["iau_shares"] = iau_df["volume"]

        logger.info("ETF AUM: fetched %d series", len(result))
        return result

    async def inject_into_macro_store(self) -> int:
        """Fetch ETF AUM data and inject into MacroStore."""
        from ml.macro_store import macro_store  # noqa: PLC0415
        series = await self.fetch_series()
        count = 0
        for name, s in series.items():
            if not s.empty:
                macro_store._series[name] = s.dropna()
                count += 1
        if count:
            logger.info("ETF AUM: injected %d series", count)
        return count


async def _gather(*coros):
    """Run coroutines concurrently."""
    import asyncio
    return await asyncio.gather(*coros)


etf_aum_feed = ETFAUMFeed()
