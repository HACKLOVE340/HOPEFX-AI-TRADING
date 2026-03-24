"""
data/scheduler.py — Daily market data update scheduler

Appends new OHLCV bars to the local CSV dataset once per day using
the OANDA practice REST API (free, no key required for practice accounts).

Falls back to yfinance if OANDA credentials are not configured.

Usage (standalone)::

    python -m data.scheduler          # run once immediately then loop daily

Usage (from app startup)::

    from data.scheduler import DataScheduler
    scheduler = DataScheduler()
    asyncio.create_task(scheduler.start())

Environment variables::

    OANDA_ACCOUNT_ID   — OANDA practice account ID
    OANDA_API_KEY      — OANDA practice API key
    DATA_DIR           — directory for CSV files (default: data/)
    DATA_SYMBOL        — symbol to fetch (default: XAU_USD)
    DATA_TIMEFRAME     — OANDA granularity (default: H1)
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
_SYMBOL = os.getenv("DATA_SYMBOL", "XAU_USD")
_TIMEFRAME = os.getenv("DATA_TIMEFRAME", "H1")
_OANDA_ACCOUNT = os.getenv("OANDA_ACCOUNT_ID", "")
_OANDA_KEY = os.getenv("OANDA_API_KEY", "")
_OANDA_BASE = "https://api-fxpractice.oanda.com"

# How many bars to fetch per update run (covers ~1 week of H1 bars)
_FETCH_COUNT = 200

# Daily update interval
_UPDATE_INTERVAL_SECS = 86_400  # 24 hours


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

async def _fetch_oanda(
    symbol: str,
    granularity: str,
    count: int,
    from_dt: Optional[datetime] = None,
) -> List[Dict]:
    """Fetch OHLCV bars from OANDA practice REST API."""
    try:
        import aiohttp
    except ImportError:
        logger.error("aiohttp required for OANDA fetch: pip install aiohttp")
        return []

    headers = {
        "Authorization": f"Bearer {_OANDA_KEY}",
        "Content-Type": "application/json",
    }
    params: Dict = {
        "granularity": granularity,
        "count": count,
        "price": "M",  # midpoint candles
    }
    if from_dt:
        params["from"] = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        del params["count"]

    url = f"{_OANDA_BASE}/v3/instruments/{symbol}/candles"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("OANDA fetch failed status=%d: %s", resp.status, text[:200])
                    return []
                data = await resp.json()
    except Exception as exc:
        logger.error("OANDA fetch error: %s", exc)
        return []

    bars = []
    for candle in data.get("candles", []):
        if not candle.get("complete", True):
            continue
        mid = candle.get("mid", {})
        try:
            bars.append({
                "timestamp": candle["time"][:19],  # trim sub-second
                "open":   float(mid["o"]),
                "high":   float(mid["h"]),
                "low":    float(mid["l"]),
                "close":  float(mid["c"]),
                "volume": int(candle.get("volume", 0)),
            })
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping malformed candle: %s", exc)

    logger.info("OANDA: fetched %d bars for %s/%s", len(bars), symbol, granularity)
    return bars


async def _fetch_yfinance(symbol: str, period: str = "5d", interval: str = "1h") -> List[Dict]:
    """Fallback: fetch bars via yfinance (maps XAU_USD → GC=F)."""
    _YF_MAP = {
        "XAU_USD": "GC=F",
        "XAUUSD":  "GC=F",
        "EUR_USD": "EURUSD=X",
        "GBP_USD": "GBPUSD=X",
    }
    yf_symbol = _YF_MAP.get(symbol, symbol)

    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance required for fallback fetch: pip install yfinance")
        return []

    try:
        loop = asyncio.get_event_loop()
        ticker = await loop.run_in_executor(None, lambda: yf.Ticker(yf_symbol))
        hist = await loop.run_in_executor(
            None, lambda: ticker.history(period=period, interval=interval)
        )
    except Exception as exc:
        logger.error("yfinance fetch error: %s", exc)
        return []

    bars = []
    for ts, row in hist.iterrows():
        try:
            bars.append({
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "open":   float(row["Open"]),
                "high":   float(row["High"]),
                "low":    float(row["Low"]),
                "close":  float(row["Close"]),
                "volume": int(row.get("Volume", 0)),
            })
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping malformed yfinance row: %s", exc)

    logger.info("yfinance: fetched %d bars for %s", len(bars), yf_symbol)
    return bars


# ---------------------------------------------------------------------------
# CSV persistence
# ---------------------------------------------------------------------------

def _csv_path(symbol: str, timeframe: str) -> Path:
    safe = symbol.replace("/", "_").replace("=", "")
    return _DATA_DIR / f"{safe}_{timeframe}.csv"


def _load_existing_timestamps(path: Path) -> set:
    if not path.exists():
        return set()
    timestamps = set()
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                timestamps.add(row.get("timestamp", ""))
    except Exception as exc:
        logger.warning("Could not read existing CSV %s: %s", path, exc)
    return timestamps


def _append_bars(path: Path, bars: List[Dict]) -> int:
    """Append new bars to CSV, skipping duplicates. Returns count appended."""
    existing = _load_existing_timestamps(path)
    new_bars = [b for b in bars if b["timestamp"] not in existing]

    if not new_bars:
        logger.info("No new bars to append to %s", path)
        return 0

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()

    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        if write_header:
            writer.writeheader()
        writer.writerows(new_bars)

    logger.info("Appended %d new bars to %s", len(new_bars), path)
    return len(new_bars)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class DataScheduler:
    """
    Runs a daily data update job.

    Fetches new OHLCV bars from OANDA (if credentials set) or yfinance,
    validates them, and appends to the local CSV dataset.
    """

    def __init__(
        self,
        symbol: str = _SYMBOL,
        timeframe: str = _TIMEFRAME,
        interval_secs: int = _UPDATE_INTERVAL_SECS,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.interval_secs = interval_secs
        self._running = False

    async def run_once(self) -> int:
        """Fetch and append new bars. Returns number of bars appended."""
        from data.validator import DataValidator

        # Determine last timestamp in existing data
        path = _csv_path(self.symbol, self.timeframe)
        existing = _load_existing_timestamps(path)
        from_dt: Optional[datetime] = None
        if existing:
            try:
                last_ts = max(existing)
                from_dt = datetime.fromisoformat(last_ts).replace(tzinfo=timezone.utc)
                # Fetch from 1 bar after the last known bar
                tf_secs = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D": 86400}
                from_dt += timedelta(seconds=tf_secs.get(self.timeframe, 3600))
            except Exception:
                pass

        # Try OANDA first, fall back to yfinance
        if _OANDA_KEY and _OANDA_ACCOUNT:
            bars = await _fetch_oanda(self.symbol, self.timeframe, _FETCH_COUNT, from_dt)
        else:
            logger.info("OANDA credentials not set — using yfinance fallback")
            bars = await _fetch_yfinance(self.symbol)

        if not bars:
            logger.warning("DataScheduler: no bars fetched for %s", self.symbol)
            return 0

        # Validate before persisting
        validator = DataValidator(symbol=self.symbol.replace("_", ""))
        valid_bars = []
        for i, bar in enumerate(bars):
            result = validator.validate_bar(bar)
            if result.ok:
                valid_bars.append(bar)
            else:
                logger.warning("Dropping invalid bar %d: %s", i, result.errors)

        appended = _append_bars(path, valid_bars)
        return appended

    async def start(self) -> None:
        """Run the update job immediately, then repeat every interval_secs."""
        self._running = True
        logger.info(
            "DataScheduler started: symbol=%s timeframe=%s interval=%ds",
            self.symbol, self.timeframe, self.interval_secs,
        )
        while self._running:
            try:
                count = await self.run_once()
                logger.info("DataScheduler: update complete, %d new bars", count)
            except Exception as exc:
                logger.error("DataScheduler: update failed: %s", exc, exc_info=True)
            await asyncio.sleep(self.interval_secs)

    def stop(self) -> None:
        self._running = False
        logger.info("DataScheduler stopped")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async def _main():
        scheduler = DataScheduler()
        count = await scheduler.run_once()
        print(f"Fetched and appended {count} new bars.")

    asyncio.run(_main())
