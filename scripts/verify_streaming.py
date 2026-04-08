#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/verify_streaming.py
=============================
Verifies that all live data feeds are correctly configured and reachable.

Checks performed
----------------
1. Environment — required API keys present in .env
2. GoldFeedManager — at least one gold price API key configured
3. NuclearStreamer — at least one WebSocket key configured
4. FRED feed — FRED_API_KEY set, fetches one series to confirm connectivity
5. CFTC COT — downloads current-year ZIP, parses gold rows
6. IMF gold — hits IMF IFS API, parses at least one observation
7. Yahoo macro — yfinance installed, fetches SPX close
8. Redis — ping (optional, warns if unavailable)

Usage
-----
    python scripts/verify_streaming.py

Exit codes
----------
    0 — all critical checks passed (warnings allowed)
    1 — one or more critical checks failed
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
import logging
logger = logging.getLogger(__name__)


# Ensure project root is on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

OK = "✅"
WARN = "⚠️ "
FAIL = "❌"

results: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))
    logger.info(f"  {status}  {name}: {detail}")


# ── 1. Environment keys ───────────────────────────────────────────────────────

logger.info("\n=== 1. Environment keys ===")


def check_env(var: str, critical: bool = True) -> bool:
    val = os.getenv(var, "")
    if val and not val.startswith("YOUR_") and not val.startswith("CHANGE_ME"):
        record(OK, var, f"set ({val[:6]}...)")
        return True
    status = FAIL if critical else WARN
    record(status, var, "NOT SET — see .env")
    return False


check_env("SECURITY_JWT_SECRET")
check_env("CONFIG_ENCRYPTION_KEY")
check_env("OANDA_API_KEY", critical=False)
check_env("OANDA_ACCOUNT_ID", critical=False)
check_env("FINNHUB_API_KEY", critical=False)
check_env("GOLDAPI_IO_KEY", critical=False)
check_env("FRED_API_KEY", critical=False)
check_env("NEWSAPI_ORG_KEY", critical=False)

# ── 2. GoldFeedManager configured sources ────────────────────────────────────

logger.info("\n=== 2. Gold price feed sources ===")

gold_keys = {
    "GOLDAPI_IO_KEY": "GoldAPI.io",
    "METALS_DEV_KEY": "Metals.dev",
    "METALS_API_KEY": "Metals-API",
    "METALPRICEAPI_KEY": "MetalpriceAPI",
    "COMMODITY_PRICE_API_KEY": "CommodityPriceAPI",
}
configured_gold = [
    name for var, name in gold_keys.items() if os.getenv(var, "").strip() and not os.getenv(var, "").startswith("YOUR_")
]
if configured_gold:
    record(OK, "GoldFeedManager", f"{len(configured_gold)} source(s): {', '.join(configured_gold)}")
else:
    record(FAIL, "GoldFeedManager", "NO gold API keys set — live price data will not flow")

# ── 3. NuclearStreamer WebSocket sources ──────────────────────────────────────

logger.info("\n=== 3. NuclearStreamer WebSocket sources ===")

ws_keys = {
    "FINNHUB_API_KEY": "Finnhub",
    "TWELVE_API_KEY": "Twelve Data",
    "POLYGON_API_KEY": "Polygon.io",
}
configured_ws = [
    name for var, name in ws_keys.items() if os.getenv(var, "").strip() and not os.getenv(var, "").startswith("YOUR_")
]
if configured_ws:
    record(OK, "NuclearStreamer", f"{len(configured_ws)} WebSocket source(s): {', '.join(configured_ws)}")
else:
    record(WARN, "NuclearStreamer", "No WebSocket keys set — tick streaming disabled until keys added")

# ── 4. FRED connectivity ──────────────────────────────────────────────────────

logger.info("\n=== 4. FRED macro feed ===")


async def check_fred() -> None:
    fred_key = os.getenv("FRED_API_KEY", "")
    if not fred_key or fred_key.startswith("YOUR_"):
        record(WARN, "FRED", "FRED_API_KEY not set — macro features will use CSV fallback")
        return
    try:
        from data_layer.feeds.macro.fred import FREDFeed, FRED_SERIES

        feed = FREDFeed()
        series = await feed.fetch_series("DGS10", limit=5)
        await feed.close()
        if not series.empty:
            record(OK, "FRED", f"Connected — DGS10 latest={series.iloc[-1]:.3f} on {series.index[-1].date()}")
            record(OK, "FRED series count", f"{len(FRED_SERIES)} series configured: {', '.join(FRED_SERIES.keys())}")
        else:
            record(WARN, "FRED", "Connected but returned empty series — check FRED_API_KEY")
    except Exception as exc:
        record(FAIL, "FRED", f"Error: {exc}")


# ── 5. CFTC COT ───────────────────────────────────────────────────────────────

logger.info("\n=== 5. CFTC COT feed ===")


async def check_cot() -> None:
    try:
        from data_layer.feeds.macro.cftc_cot import CFTCCOTFeed

        feed = CFTCCOTFeed()
        import datetime

        df = await feed._download_year(datetime.datetime.now().year)
        await feed.close()
        if not df.empty:
            record(OK, "CFTC COT", f"Downloaded {len(df)} gold rows for current year")
        else:
            record(WARN, "CFTC COT", "No rows parsed — CFTC site may be slow, will retry on startup")
    except Exception as exc:
        record(FAIL, "CFTC COT", f"Error: {exc}")


# ── 6. IMF gold ───────────────────────────────────────────────────────────────

logger.info("\n=== 6. IMF central bank gold feed ===")


async def check_imf() -> None:
    try:
        from data_layer.feeds.macro.imf_gold import IMFGoldFeed

        feed = IMFGoldFeed()
        import datetime

        series = await feed._fetch_raw(datetime.datetime.now().year - 2)
        await feed.close()
        if not series.empty:
            record(
                OK,
                "IMF gold",
                f"{len(series)} monthly obs, latest={series.iloc[-1]:.0f}t on {series.index[-1].date()}",
            )
        else:
            record(WARN, "IMF gold", "No data returned — IMF API may be slow, CSV fallback will be used")
    except Exception as exc:
        record(FAIL, "IMF gold", f"Error: {exc}")


# ── 7. Yahoo macro ────────────────────────────────────────────────────────────

logger.info("\n=== 7. Yahoo Finance macro feed ===")


async def check_yahoo() -> None:
    try:
        import yfinance as yf

        loop = asyncio.get_running_loop()
        import functools

        df = await loop.run_in_executor(
            None, functools.partial(yf.download, "^GSPC", period="5d", progress=False, auto_adjust=True)
        )
        if not df.empty:
            close = float(df["Close"].iloc[-1])
            record(OK, "Yahoo macro (yfinance)", f"SPX latest close={close:.2f}")
        else:
            record(WARN, "Yahoo macro", "yfinance returned empty — check network")
    except ImportError:
        record(FAIL, "Yahoo macro", "yfinance not installed — run: pip install yfinance")
    except Exception as exc:
        record(WARN, "Yahoo macro", f"Error: {exc}")


# ── 8. FIX protocol backend ───────────────────────────────────────────────────

logger.info("\n=== 8. FIX protocol backend ===")


def check_fix() -> None:
    try:
        from execution.fix_adapter import _FIX_BACKEND

        if _FIX_BACKEND == "quickfix":
            record(OK, "FIX backend", "quickfix (C-extension) — production ready")
        elif _FIX_BACKEND == "pyfixmsg":
            record(WARN, "FIX backend", "pyfixmsg (pure Python) — functional but higher latency than quickfix")
        elif _FIX_BACKEND == "simplefix":
            record(WARN, "FIX backend", "simplefix (message encoding only) — install quickfix for full FIX sessions")
        else:
            record(
                FAIL,
                "FIX backend",
                "no FIX library — install: sudo apt-get install libquickfix-dev && pip install quickfix==1.15.1",
            )
    except Exception as exc:
        record(FAIL, "FIX backend", f"import error: {exc}")


check_fix()

# ── 9. Redis ──────────────────────────────────────────────────────────────────

logger.info("\n=== 9. Redis ===")


def check_redis() -> None:
    try:
        import redis

        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        record(OK, "Redis", f"Connected — {os.getenv('REDIS_URL', 'redis://localhost:6379/0')}")
    except ImportError:
        record(WARN, "Redis", "redis package not installed")
    except Exception as exc:
        record(WARN, "Redis", f"Not running ({exc}) — start Redis for caching (task 11)")


# ── Run all async checks ──────────────────────────────────────────────────────


async def main() -> int:
    await check_fred()
    await check_cot()
    await check_imf()
    await check_yahoo()
    check_redis()

    # Summary
    logger.info("\n=== Summary ===")
    passed = sum(1 for s, _, _ in results if s == OK)
    warned = sum(1 for s, _, _ in results if s == WARN)
    failed = sum(1 for s, _, _ in results if s == FAIL)
    logger.error(f"  {OK} {passed} passed   {WARN} {warned} warnings   {FAIL} {failed} failed")

    if failed > 0:
        logger.error("\nCritical failures detected. Fix the ❌ items before starting paper trading.")
        return 1
    if warned > 0:
        logger.warning("\nWarnings present. Add missing API keys to .env to enable all features.")
    else:
        logger.info("\nAll checks passed. Ready to start paper trading.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
