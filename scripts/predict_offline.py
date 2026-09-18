#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Run the model on the committed daily series, with no market feed.

    python scripts/predict_offline.py
    python scripts/predict_offline.py --bars 600 --file XAUUSD_5Y.csv

Why this exists as a script rather than a fallback inside the engine: the
cached series is months old, and a silent fallback to it would put fabricated
freshness back into the decision path that MASTER_OUTSTANDING §E12 just closed.
`RiskManager.size_order()` refuses when data quality is unmeasured, and a CSV
has no tick confidence to measure. So predicting on history is a thing someone
asks for on purpose, and the answer says how old the data was.

What this proves, and what it does not: it proves the model loads, builds its
features and produces a calibrated probability without any network. It does not
say the number is tradable — the series ends months ago and the macro features
that need a live store are zero-imputed, which the run reports.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD", help="cached symbol (default: XAUUSD)")
    ap.add_argument("--file", default=None, help="specific CSV in data/, e.g. XAUUSD_5Y.csv")
    ap.add_argument("--bars", type=int, default=400, help="bars of history to feed the model (default: 400)")
    ap.add_argument(
        "--full-history",
        action="store_true",
        help="use the whole committed series instead of the clean window (see ml.cached_series.CLEAN_SINCE)",
    )
    ap.add_argument("--verbose", action="store_true", help="show the engine's own logging")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="  %(levelname)s %(name)s: %(message)s",
    )

    from ml.cached_series import CLEAN_SINCE, load_cached_daily

    # Default to the window that needs no repair. XAUUSD_40Y.csv carries 441
    # impossible bars, all before 2020; --full-history opts into them.
    since = None if args.full_history else CLEAN_SINCE.get(args.symbol.upper().replace("_", ""))
    try:
        series = load_cached_daily(args.symbol, filename=args.file, since=since)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("─" * 74)
    print("DATA")
    print("─" * 74)
    print(f"  {series.describe()}")
    if since is not None:
        print(f"  window     from {since} — the range verified free of malformed bars (--full-history for all)")
    if series.is_stale:
        print(f"  NOT LIVE — this series ends {series.age_days} days ago. Treat the")
        print("  prediction below as a demonstration that the model runs, not as a signal.")

    window = series.frame.tail(args.bars)
    if len(window) < args.bars:
        print(f"  (only {len(window)} bars available)")

    from ml.inference_engine import get_inference_engine

    engine = get_inference_engine()
    result = engine.predict(window, symbol=f"{series.symbol[:3]}_{series.symbol[3:]}")

    print()
    print("─" * 74)
    print("THE MODEL SAID")
    print("─" * 74)
    if result.get("fallback"):
        print(f"  ABSTAINED — {result.get('reason') or 'no reason reported'}")
    else:
        print(f"  direction     {result.get('direction')}")
        print(f"  probability   {result.get('probability')}")
        print(f"  confidence    {result.get('confidence')}")
    for field in ("model_version", "bars_used", "last_close", "macro_active", "mtf_active", "latency_ms"):
        if field in result:
            print(f"  {field:<13} {result[field]}")

    # data_quality is None whenever nothing measured it — reported as absent
    # rather than as a perfect 1.0. Offline, nothing measures it, so None here
    # is the correct answer and not a gap.
    print(f"  {'data_quality':<13} {result.get('data_quality')!r}  (None = unmeasured, which is honest offline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
