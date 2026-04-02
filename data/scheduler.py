# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data/scheduler.py — Multi-timeframe market data scheduler

Fetches and appends OHLCV bars for all supported timeframes:
  M1, M5, M15, M30, H1, H4, D, W, M

Primary source: OANDA practice REST API (requires OANDA_API_KEY + OANDA_ACCOUNT_ID).
Fallback source: yfinance (maps XAU_USD → GC=F).

Each timeframe is stored in its own CSV:
  data/XAU_USD_M1.csv, data/XAU_USD_M5.csv, ..., data/XAU_USD_M.csv

Usage (standalone)::

    python -m data.scheduler                    # update all timeframes once
    python -m data.scheduler --timeframe H1     # update single timeframe
    python -m data.scheduler --backfill         # backfill 8 years of H1
    python -m data.scheduler --backfill --granularity M5 --from 2020-01-01

Usage (from app startup)::

    from data.scheduler import DataScheduler
    scheduler = DataScheduler()
    asyncio.create_task(scheduler.start())

Environment variables::

    OANDA_ACCOUNT_ID    — OANDA practice account ID
    OANDA_API_KEY       — OANDA practice API key
    OANDA_ENVIRONMENT   — "practice" or "live" (default: practice)
    OANDA_REGION        — "us", "eu", or "sg" (default: us)
    DATA_DIR            — directory for CSV files (default: data/)
    DATA_SYMBOL         — symbol to fetch (default: XAU_USD)
    DATA_TIMEFRAME      — primary timeframe (default: H1)
    SCHEDULER_INTERVAL  — update interval in seconds (default: 3600)
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
_SYMBOL = os.getenv("DATA_SYMBOL", "XAU_USD")
_TIMEFRAME = os.getenv("DATA_TIMEFRAME", "H1")
_OANDA_ACCOUNT = os.getenv("OANDA_ACCOUNT_ID", "")
_OANDA_KEY = os.getenv("OANDA_API_KEY", "")
_OANDA_ENV = os.getenv("OANDA_ENVIRONMENT", "practice")
_OANDA_REGION = os.getenv("OANDA_REGION", "us")

# OANDA base URLs by region and environment
_OANDA_URLS: dict[str, dict[str, str]] = {
    "us": {
        "practice": "https://api-fxpractice.oanda.com",
        "live": "https://api-fxtrade.oanda.com",
    },
    "eu": {
        "practice": "https://api-fxpractice.oanda.com",
        "live": "https://api-fxtrade.oanda.com",
    },
    "sg": {
        "practice": "https://api-fxpractice.oanda.com",
        "live": "https://api-fxtrade.oanda.com",
    },
}

_OANDA_BASE = _OANDA_URLS.get(_OANDA_REGION, _OANDA_URLS["us"]).get(_OANDA_ENV, "https://api-fxpractice.oanda.com")

# Granularity codes and their duration in seconds
# Supported: M1, M5, M15, M30, H1, H4, D, W, M
TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1_800,
    "H1": 3_600,
    "H4": 14_400,
    "D": 86_400,
    "W": 604_800,
    "M": 2_592_000,  # ~30 days
}

# yfinance interval mapping for each OANDA granularity
_YF_INTERVAL_MAP: dict[str, str] = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D": "1d",
    "W": "1wk",
    "M": "1mo",
}

# yfinance lookback period for each granularity (intraday data has limits)
_YF_PERIOD_MAP: dict[str, str] = {
    "M1": "7d",
    "M5": "60d",
    "M15": "60d",
    "M30": "60d",
    "H1": "730d",
    "H4": "730d",
    "D": "max",
    "W": "max",
    "M": "max",
}

# yfinance symbol map
_YF_SYMBOL_MAP: dict[str, str] = {
    "XAU_USD": "GC=F",
    "XAUUSD": "GC=F",
    "EUR_USD": "EURUSD=X",
    "GBP_USD": "GBPUSD=X",
    "USD_JPY": "JPY=X",
    "GBP_JPY": "GBPJPY=X",
    "EUR_JPY": "EURJPY=X",
}

# OANDA returns max 5000 candles per request
_OANDA_MAX_COUNT = 5_000

# Default update interval (1 hour — matches H1 bar close)
_UPDATE_INTERVAL_SECS = int(os.getenv("SCHEDULER_INTERVAL", "3600"))

# All timeframes updated on each scheduler run
ALL_TIMEFRAMES: tuple[str, ...] = ("M1", "M5", "M15", "M30", "H1", "H4", "D", "W", "M")


# ---------------------------------------------------------------------------
# OANDA fetcher
# ---------------------------------------------------------------------------


async def _fetch_oanda(
    symbol: str,
    granularity: str,
    count: int = 500,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> list[dict]:
    """
    Fetch OHLCV bars from OANDA REST API.

    Uses ``from`` + ``count`` when from_dt is provided, otherwise fetches
    the most recent ``count`` bars.  ``to_dt`` is used as an upper bound
    when backfilling a specific window.
    """
    try:
        import aiohttp
    except ImportError:
        logger.error("aiohttp required: pip install aiohttp")
        return []

    if granularity not in TIMEFRAME_SECONDS:
        logger.error(
            "Unsupported granularity: %s. Supported: %s",
            granularity,
            list(TIMEFRAME_SECONDS),
        )
        return []

    headers = {
        "Authorization": f"Bearer {_OANDA_KEY}",
        "Content-Type": "application/json",
    }
    params: dict = {
        "granularity": granularity,
        "price": "M",  # midpoint candles
    }

    if from_dt is not None:
        params["from"] = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        if to_dt is not None:
            params["to"] = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            params["count"] = min(count, _OANDA_MAX_COUNT)
    else:
        params["count"] = min(count, _OANDA_MAX_COUNT)

    url = f"{_OANDA_BASE}/v3/instruments/{symbol}/candles"

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, headers=headers, params=params, timeout=timeout) as resp,
        ):
            if resp.status == 401:
                logger.error("OANDA auth failed (401) — check OANDA_API_KEY")
                return []
            if resp.status == 400:
                text = await resp.text()
                logger.error("OANDA bad request (400): %s", text[:300])
                return []
            if resp.status != 200:
                text = await resp.text()
                logger.error("OANDA fetch failed status=%d: %s", resp.status, text[:200])
                return []
            data = await resp.json()
    except TimeoutError:
        logger.error("OANDA fetch timed out for %s/%s", symbol, granularity)
        return []
    except Exception as exc:
        logger.error("OANDA fetch error: %s", exc)
        return []

    bars: list[dict] = []
    for candle in data.get("candles", []):
        if not candle.get("complete", True):
            continue
        mid = candle.get("mid", {})
        try:
            bars.append(
                {
                    "timestamp": candle["time"][:19],
                    "open": float(mid["o"]),
                    "high": float(mid["h"]),
                    "low": float(mid["l"]),
                    "close": float(mid["c"]),
                    "volume": int(candle.get("volume", 0)),
                }
            )
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping malformed candle: %s", exc)

    logger.info(
        "OANDA: fetched %d bars for %s/%s (from=%s)",
        len(bars),
        symbol,
        granularity,
        from_dt.strftime("%Y-%m-%d") if from_dt else "latest",
    )
    return bars


# ---------------------------------------------------------------------------
# yfinance fallback fetcher
# ---------------------------------------------------------------------------


async def _fetch_yfinance(
    symbol: str,
    granularity: str = "H1",
    from_dt: datetime | None = None,
) -> list[dict]:
    """
    Fetch bars via yfinance as a fallback when OANDA credentials are absent.

    Maps OANDA granularity codes to yfinance interval strings.
    Intraday data (M1–H4) is limited to 60 days by Yahoo Finance.
    """
    yf_symbol = _YF_SYMBOL_MAP.get(symbol, symbol)
    interval = _YF_INTERVAL_MAP.get(granularity, "1h")
    period = _YF_PERIOD_MAP.get(granularity, "60d")

    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance required: pip install yfinance")
        return []

    try:
        loop = asyncio.get_event_loop()

        if from_dt is not None:
            end_dt = datetime.now(UTC)
            hist = await loop.run_in_executor(
                None,
                lambda: yf.download(
                    yf_symbol,
                    start=from_dt.strftime("%Y-%m-%d"),
                    end=end_dt.strftime("%Y-%m-%d"),
                    interval=interval,
                    progress=False,
                    auto_adjust=True,
                ),
            )
        else:
            ticker = await loop.run_in_executor(None, lambda: yf.Ticker(yf_symbol))
            hist = await loop.run_in_executor(None, lambda: ticker.history(period=period, interval=interval))
    except Exception as exc:
        logger.error("yfinance fetch error for %s/%s: %s", yf_symbol, interval, exc)
        return []

    if hist is None or (hasattr(hist, "empty") and hist.empty):
        logger.warning("yfinance returned empty data for %s/%s", yf_symbol, interval)
        return []

    # Flatten MultiIndex columns if present (yfinance >= 0.2.x)
    if hasattr(hist.columns, "levels"):
        hist.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in hist.columns]
    else:
        hist.columns = [c.lower() for c in hist.columns]

    bars: list[dict] = []
    for ts, row in hist.iterrows():
        try:
            # Normalise timestamp to ISO format without timezone
            if hasattr(ts, "tz_convert"):
                ts_str = ts.tz_convert(None).strftime("%Y-%m-%dT%H:%M:%S")
            elif hasattr(ts, "strftime"):
                ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                ts_str = str(ts)[:19]

            bars.append(
                {
                    "timestamp": ts_str,
                    "open": float(row.get("open", row.get("Open", 0))),
                    "high": float(row.get("high", row.get("High", 0))),
                    "low": float(row.get("low", row.get("Low", 0))),
                    "close": float(row.get("close", row.get("Close", 0))),
                    "volume": int(row.get("volume", row.get("Volume", 0))),
                }
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping malformed yfinance row: %s", exc)

    logger.info(
        "yfinance: fetched %d bars for %s/%s (interval=%s)",
        len(bars),
        yf_symbol,
        granularity,
        interval,
    )
    return bars


# ---------------------------------------------------------------------------
# CSV persistence
# ---------------------------------------------------------------------------


def _csv_path(symbol: str, timeframe: str) -> Path:
    """Return the CSV path for a symbol/timeframe pair."""
    safe = symbol.replace("/", "_").replace("=", "")
    return _DATA_DIR / f"{safe}_{timeframe}.csv"


def _load_existing_timestamps(path: Path) -> set:
    """Return the set of timestamp strings already in the CSV."""
    if not path.exists():
        return set()
    timestamps: set = set()
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get("timestamp", "")
                if ts:
                    timestamps.add(ts)
    except Exception as exc:
        logger.warning("Could not read existing CSV %s: %s", path, exc)
    return timestamps


def _get_last_timestamp(path: Path) -> str | None:
    """Return the most recent timestamp string in the CSV, or None."""
    existing = _load_existing_timestamps(path)
    if not existing:
        return None
    return max(existing)


def _append_bars(path: Path, bars: list[dict]) -> int:
    """
    Append new bars to CSV, skipping duplicates.

    Returns the number of bars actually written.
    """
    existing = _load_existing_timestamps(path)
    new_bars = [b for b in bars if b.get("timestamp", "") not in existing]

    if not new_bars:
        logger.debug("No new bars to append to %s", path.name)
        return 0

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0

    fieldnames = ["timestamp", "open", "high", "low", "close", "volume"]
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(new_bars)

    logger.info("Appended %d new bars to %s", len(new_bars), path.name)
    return len(new_bars)


# ---------------------------------------------------------------------------
# Single-timeframe update
# ---------------------------------------------------------------------------


async def _update_timeframe(
    symbol: str,
    granularity: str,
    fetch_count: int = 500,
) -> int:
    """
    Fetch and append new bars for one symbol/timeframe.

    Determines the last known timestamp and requests only bars after it.
    Falls back to yfinance when OANDA credentials are absent.

    Returns the number of new bars appended.
    """
    path = _csv_path(symbol, granularity)
    last_ts = _get_last_timestamp(path)

    from_dt: datetime | None = None
    if last_ts:
        try:
            from_dt = datetime.fromisoformat(last_ts).replace(tzinfo=UTC)
            bar_secs = TIMEFRAME_SECONDS.get(granularity, 3600)
            from_dt += timedelta(seconds=bar_secs)
        except ValueError:
            logger.warning(
                "Could not parse last timestamp '%s' for %s/%s",
                last_ts,
                symbol,
                granularity,
            )

    # Choose data source
    if _OANDA_KEY and _OANDA_ACCOUNT:
        bars = await _fetch_oanda(symbol, granularity, count=fetch_count, from_dt=from_dt)
    else:
        logger.info("OANDA credentials absent — using yfinance for %s/%s", symbol, granularity)
        bars = await _fetch_yfinance(symbol, granularity, from_dt=from_dt)

    if not bars:
        logger.info("No bars fetched for %s/%s", symbol, granularity)
        return 0

    # Validate before persisting
    try:
        from data.validator import DataValidator

        validator = DataValidator(symbol=symbol.replace("_", ""))
        valid_bars: list[dict] = []
        for i, bar in enumerate(bars):
            result = validator.validate_bar(bar)
            if result.ok:
                valid_bars.append(bar)
            else:
                logger.warning(
                    "Dropping invalid bar %d (%s/%s): %s",
                    i,
                    symbol,
                    granularity,
                    result.errors,
                )
    except Exception:  # nosec B110 — validator unavailable; persist all bars
        valid_bars = bars

    return _append_bars(path, valid_bars)


# ---------------------------------------------------------------------------
# DataScheduler
# ---------------------------------------------------------------------------


class DataScheduler:
    """
    Periodic multi-timeframe data update scheduler.

    On each tick, updates all configured timeframes for the configured symbol.
    Timeframes: M1, M5, M15, M30, H1, H4, D, W, M.

    Primary source: OANDA practice REST API.
    Fallback: yfinance (GC=F for XAU_USD).
    """

    def __init__(
        self,
        symbol: str = _SYMBOL,
        timeframes: tuple[str, ...] = ALL_TIMEFRAMES,
        interval_secs: int = _UPDATE_INTERVAL_SECS,
    ) -> None:
        self.symbol = symbol
        self.timeframes = timeframes
        self.interval_secs = interval_secs
        self._running = False

    async def run_once(self) -> dict[str, int]:
        """
        Fetch and append new bars for all configured timeframes.

        Returns a dict mapping timeframe → bars appended.
        """
        results: dict[str, int] = {}
        for tf in self.timeframes:
            try:
                count = await _update_timeframe(self.symbol, tf)
                results[tf] = count
            except Exception as exc:
                logger.error(
                    "Update failed for %s/%s: %s",
                    self.symbol,
                    tf,
                    exc,
                    exc_info=True,
                )
                results[tf] = 0
        total = sum(results.values())
        logger.info(
            "DataScheduler run_once complete: %d total new bars across %d timeframes",
            total,
            len(self.timeframes),
        )
        return results

    async def start(self) -> None:
        """Run the update job immediately, then repeat every interval_secs."""
        self._running = True
        logger.info(
            "DataScheduler started: symbol=%s timeframes=%s interval=%ds",
            self.symbol,
            self.timeframes,
            self.interval_secs,
        )
        while self._running:
            try:
                results = await self.run_once()
                logger.info("DataScheduler update: %s", results)
            except Exception as exc:
                logger.error("DataScheduler update failed: %s", exc, exc_info=True)
            await asyncio.sleep(self.interval_secs)

    def stop(self) -> None:
        self._running = False
        logger.info("DataScheduler stopped")


# ---------------------------------------------------------------------------
# Historical backfill
# ---------------------------------------------------------------------------


async def backfill(
    symbol: str = _SYMBOL,
    granularity: str = "H1",
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> int:
    """
    Backfill historical OHLCV data from OANDA practice API.

    Fetches data in _OANDA_MAX_COUNT-bar chunks from ``from_date`` to
    ``to_date`` (defaults: 2015-01-01 → now).  Skips bars already in the CSV.

    For intraday timeframes (M1–H4), OANDA practice API provides full history.
    For D/W/M, yfinance provides longer history (GC=F back to ~1974).

    Returns total bars appended.
    """
    now = datetime.now(UTC)
    if to_date is None:
        to_date = now
    if from_date is None:
        # Default: 2015-01-01 — covers 10+ years of H1 data for regime analysis
        # and multi-cycle backtesting (2015 USD rally, 2018 correction, 2020 COVID,
        # 2022 rate hike cycle, 2024-2026 gold bull run).
        from_date = datetime(2015, 1, 1, tzinfo=UTC)

    if granularity not in TIMEFRAME_SECONDS:
        logger.error("Unsupported granularity: %s", granularity)
        return 0

    bar_secs = TIMEFRAME_SECONDS[granularity]
    chunk_secs = _OANDA_MAX_COUNT * bar_secs

    path = _csv_path(symbol, granularity)
    total_appended = 0
    cursor = from_date

    logger.info(
        "Backfill started: %s/%s from %s to %s",
        symbol,
        granularity,
        from_date.strftime("%Y-%m-%d"),
        to_date.strftime("%Y-%m-%d"),
    )

    if not (_OANDA_KEY and _OANDA_ACCOUNT):
        logger.warning(
            "OANDA credentials not set — backfill requires OANDA_API_KEY and "
            "OANDA_ACCOUNT_ID.  Set them in .env and retry.\n"
            "  OANDA_API_KEY=your_practice_key\n"
            "  OANDA_ACCOUNT_ID=your_account_id\n"
            "Get a free practice account at https://www.oanda.com/register/\n"
            "Falling back to yfinance for %s/%s ...",
            symbol,
            granularity,
        )
        bars = await _fetch_yfinance(symbol, granularity, from_dt=from_date)
        if bars:
            total_appended = _append_bars(path, bars)
        logger.info(
            "yfinance backfill complete: %d bars appended to %s",
            total_appended,
            path,
        )
        return total_appended

    while cursor < to_date:
        chunk_end = min(cursor + timedelta(seconds=chunk_secs), to_date)
        logger.info(
            "  Fetching chunk %s → %s ...",
            cursor.strftime("%Y-%m-%d %H:%M"),
            chunk_end.strftime("%Y-%m-%d %H:%M"),
        )

        bars = await _fetch_oanda(
            symbol,
            granularity,
            count=_OANDA_MAX_COUNT,
            from_dt=cursor,
            to_dt=chunk_end,
        )
        if not bars:
            logger.warning(
                "  No bars returned for chunk starting %s — stopping",
                cursor,
            )
            break

        appended = _append_bars(path, bars)
        total_appended += appended

        # Advance cursor past the last bar received
        try:
            last_ts = bars[-1]["timestamp"]
            cursor = datetime.fromisoformat(last_ts).replace(tzinfo=UTC)
            cursor += timedelta(seconds=bar_secs)
        except (ValueError, TypeError, KeyError, IndexError):
            cursor += timedelta(seconds=chunk_secs)

        # Respect OANDA rate limits (120 req/min for practice)
        await asyncio.sleep(0.6)

    logger.info("Backfill complete: %d bars appended to %s", total_appended, path)
    return total_appended


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="HOPEFX multi-timeframe data scheduler / backfill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m data.scheduler                                    # update all timeframes\n"
            "  python -m data.scheduler --timeframe H1                     # update H1 only\n"
            "  python -m data.scheduler --backfill                         # backfill H1 from 2015-01-01\n"
            "  python -m data.scheduler --backfill --from 2015-01-01       # explicit 2015 start\n"
            "  python -m data.scheduler --backfill --symbol XAU_USD --granularity H1 --from 2015-01-01\n"
            "  python -m data.scheduler --backfill --granularity M5 --from 2022-01-01\n"
            "  python -m data.scheduler --backfill --granularity D         # daily bars (max history)\n"
        ),
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Run historical backfill instead of incremental update",
    )
    parser.add_argument(
        "--symbol",
        default=_SYMBOL,
        help=f"Instrument symbol (default: {_SYMBOL})",
    )
    parser.add_argument(
        "--timeframe",
        default=None,
        help="Single timeframe to update (default: all). One of: " + ", ".join(ALL_TIMEFRAMES),
    )
    parser.add_argument(
        "--granularity",
        default="H1",
        help="Granularity for backfill (default: H1). One of: " + ", ".join(ALL_TIMEFRAMES),
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help="Backfill start date YYYY-MM-DD (default: 2015-01-01)",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default=None,
        help="Backfill end date YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args()

    async def _main() -> None:
        if args.backfill:
            from_dt = datetime.fromisoformat(args.from_date).replace(tzinfo=UTC) if args.from_date else None
            to_dt = datetime.fromisoformat(args.to_date).replace(tzinfo=UTC) if args.to_date else None
            count = await backfill(
                symbol=args.symbol,
                granularity=args.granularity,
                from_date=from_dt,
                to_date=to_dt,
            )
            print(f"\nBackfill complete: {count} bars appended.")
            print(f"Data saved to: {_csv_path(args.symbol, args.granularity)}")
        elif args.timeframe:
            if args.timeframe not in TIMEFRAME_SECONDS:
                print(f"Unknown timeframe '{args.timeframe}'. Supported: {', '.join(ALL_TIMEFRAMES)}")
                return
            count = await _update_timeframe(args.symbol, args.timeframe)
            print(f"Fetched and appended {count} new bars for {args.symbol}/{args.timeframe}.")
        else:
            scheduler = DataScheduler(symbol=args.symbol)
            results = await scheduler.run_once()
            total = sum(results.values())
            print(f"\nUpdate complete: {total} total new bars")
            for tf, n in results.items():
                path = _csv_path(args.symbol, tf)
                print(f"  {tf:>4}  {n:>5} new bars  →  {path}")

    asyncio.run(_main())
