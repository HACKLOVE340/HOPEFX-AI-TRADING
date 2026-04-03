#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/backfill_h1.py
======================
Convenience script: backfill H1 XAUUSD data from 2015-01-01 to today.

This fills the data depth gap vs competitors (QuantConnect: 40y tick,
TrendSpider: 50y all TFs). OANDA practice API provides ~10 years of H1
history, giving us 2015-present for regime analysis and multi-cycle
backtesting (2015 USD rally, 2018 correction, 2020 COVID, 2022 rate hike
cycle, 2024-2026 gold bull run).

Usage
-----
    python scripts/backfill_h1.py
    python scripts/backfill_h1.py --symbol XAU_USD --from 2015-01-01
    python scripts/backfill_h1.py --symbol EUR_USD --from 2018-01-01
    python scripts/backfill_h1.py --dry-run   # show what would be fetched

Requirements
------------
    OANDA_API_KEY and OANDA_ACCOUNT_ID must be set in .env.
    Falls back to yfinance (GC=F proxy) when OANDA credentials are absent.

Output
------
    data/XAU_USD_H1.csv  — appended with new bars (duplicates skipped)
    Prints progress: chunk dates, bars fetched, total appended.

Estimated time
--------------
    ~2 minutes for 10 years of H1 data (OANDA: ~87,600 bars in 18 chunks).
    yfinance fallback: ~30 seconds but limited to ~730 days of H1 data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path

# Ensure project root is on path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# Load .env if present
try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    ...  # nosec B110

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Default backfill parameters
_DEFAULT_SYMBOL = "XAU_USD"
_DEFAULT_GRANULARITY = "H1"
_DEFAULT_FROM = "2015-01-01"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill H1 XAUUSD data from 2015-01-01 to today",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/backfill_h1.py\n"
            "  python scripts/backfill_h1.py --symbol XAU_USD --from 2015-01-01\n"
            "  python scripts/backfill_h1.py --symbol EUR_USD --from 2018-01-01\n"
            "  python scripts/backfill_h1.py --granularity H4 --from 2015-01-01\n"
            "  python scripts/backfill_h1.py --dry-run\n"
        ),
    )
    parser.add_argument(
        "--symbol",
        default=_DEFAULT_SYMBOL,
        help=f"OANDA instrument code (default: {_DEFAULT_SYMBOL})",
    )
    parser.add_argument(
        "--granularity",
        default=_DEFAULT_GRANULARITY,
        help=f"Bar granularity (default: {_DEFAULT_GRANULARITY}). One of: M1 M5 M15 M30 H1 H4 D W M",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default=_DEFAULT_FROM,
        help=f"Start date YYYY-MM-DD (default: {_DEFAULT_FROM})",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default=None,
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be fetched without writing any data",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    from data.scheduler import TIMEFRAME_SECONDS, _csv_path, backfill

    from_dt = datetime.fromisoformat(args.from_date).replace(tzinfo=UTC)
    to_dt = datetime.fromisoformat(args.to_date).replace(tzinfo=UTC) if args.to_date else datetime.now(UTC)

    if args.granularity not in TIMEFRAME_SECONDS:
        print(f"Unknown granularity '{args.granularity}'. Supported: {', '.join(TIMEFRAME_SECONDS)}")
        sys.exit(1)

    bar_secs = TIMEFRAME_SECONDS[args.granularity]
    total_bars_estimate = int((to_dt - from_dt).total_seconds() / bar_secs)
    output_path = _csv_path(args.symbol, args.granularity)

    print("\nHOPEFX H1 Backfill")
    print("=" * 50)
    print(f"  Symbol      : {args.symbol}")
    print(f"  Granularity : {args.granularity}")
    print(f"  From        : {from_dt.strftime('%Y-%m-%d')}")
    print(f"  To          : {to_dt.strftime('%Y-%m-%d')}")
    print(f"  Est. bars   : ~{total_bars_estimate:,}")
    print(f"  Output      : {output_path}")
    print(f"  OANDA key   : {'SET' if os.getenv('OANDA_API_KEY') else 'NOT SET (yfinance fallback)'}")
    print()

    if args.dry_run:
        print("Dry run — no data written.")
        return

    if not os.getenv("OANDA_API_KEY"):
        print(
            "⚠️  OANDA_API_KEY not set.\n"
            "   Falling back to yfinance (GC=F proxy).\n"
            "   Note: yfinance H1 data is limited to ~730 days.\n"
            "   For full 2015-present history, set OANDA_API_KEY in .env.\n"
            "   Get a free practice account at https://www.oanda.com/register/\n"
        )

    count = await backfill(
        symbol=args.symbol,
        granularity=args.granularity,
        from_date=from_dt,
        to_date=to_dt,
    )

    print()
    print("=" * 50)
    print(f"Backfill complete: {count:,} bars appended to {output_path}")

    if output_path.exists():
        size_kb = output_path.stat().st_size / 1024
        print(f"File size: {size_kb:.1f} KB")

    if count == 0 and not os.getenv("OANDA_API_KEY"):
        print(
            "\nNo bars appended. To get full H1 history back to 2015:\n"
            "  1. Register at https://www.oanda.com/register/ (free practice account)\n"
            "  2. Get your API key from My Account → Manage API Access\n"
            "  3. Add to .env:\n"
            "       OANDA_API_KEY=your_key_here\n"
            "       OANDA_ACCOUNT_ID=your_account_id\n"
            "  4. Re-run: python scripts/backfill_h1.py\n"
        )


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
