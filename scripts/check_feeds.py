#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/check_feeds.py
======================
Feed connectivity self-test. Run this in YOUR deployment after setting API keys
and allowing network egress to verify each data source actually flows into the
signal — so "connect the feeds" is verifiable, not guesswork.

It checks, for each source:
  * whether the required env var(s) are set,
  * whether the provider host is reachable (egress),
  * a lightweight live probe where possible.

Macro is also checked via the committed-CSV offline fallback (works with no
network), so you can see macro is available even before live FRED is connected.

Usage:
    python scripts/check_feeds.py
Exit code 0 if all *required* feeds are green, else 1.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Treat these as "not really set" (bootstrap placeholders / obvious stubs).
_PLACEHOLDER_HINTS = ("changeme", "placeholder", "your_", "xxxx", "todo", "example")


def _key_set(*names: str) -> tuple[bool, str]:
    """True if at least one of *names* is set to a non-placeholder value."""
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v and not any(h in v.lower() for h in _PLACEHOLDER_HINTS):
            return True, n
    return False, names[0]


def _reachable(url: str, timeout: float = 6.0) -> tuple[bool, str]:
    """Lightweight egress probe — any HTTP response (even 401/403) means the host
    is reachable; a network error means egress is blocked."""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "hopefx-feedcheck"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - fixed https hosts
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:  # reachable, just returned an error code
        return True, f"HTTP {e.code}"
    except Exception as e:
        return False, type(e).__name__


# feed: (label, host_to_probe, env_keys, required)
FEEDS = [
    ("Macro / FRED", "https://api.stlouisfed.org", ("FRED_API_KEY",), False),
    ("Gold spot", "https://www.gold-api.com", ("GOLDAPI_IO_KEY", "METALS_API_KEY"), True),
    ("OHLCV / MTF", "https://api.twelvedata.com", ("TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_KEY"), True),
    ("News / sentiment", "https://finnhub.io", ("FINNHUB_API_KEY",), False),
    ("Broker (OANDA)", "https://api-fxpractice.oanda.com", ("OANDA_API_TOKEN",), False),
]


def _check_macro_offline() -> str:
    """Macro has a committed-CSV fallback that works with no network."""
    try:
        from ml.macro_store import macro_store

        if len(macro_store) == 0:
            macro_store.load_defaults()
        n = len(macro_store)
        return (
            f"offline CSV fallback OK ({n} series: {', '.join(list(macro_store._series)[:6])})"
            if n
            else "no offline data"
        )
    except Exception as e:
        return f"offline check failed: {type(e).__name__}"


def main() -> int:
    print("─" * 74)
    print("  HOPEFX feed connectivity self-test")
    print("─" * 74)
    print(f"  {'FEED':<20}{'KEY':<8}{'EGRESS':<14}{'STATUS'}")
    print("  " + "-" * 70)

    all_required_ok = True
    for label, host, keys, required in FEEDS:
        key_ok, key_name = _key_set(*(keys if isinstance(keys, tuple) else (keys,)))
        reach_ok, reach_msg = _reachable(host)
        green = key_ok and reach_ok
        if required and not green:
            all_required_ok = False
        status = "✅ live" if green else ("⚠️ " + ("no key" if not key_ok else f"blocked ({reach_msg})"))
        tag = "" if required else " (optional)"
        print(f"  {label:<20}{'set' if key_ok else '—':<8}{reach_msg:<14}{status}{tag}")

    print("  " + "-" * 70)
    print(f"  Macro offline: {_check_macro_offline()}")
    print("─" * 74)
    if all_required_ok:
        print("  ✅ Required feeds are live. Run a backtest/engine and confirm coverage:")
        print("     python run.py --mode backtest --strategy ml")
        print("     (Feature sources active: macro/MTF should rise above 0%.)")
    else:
        print("  ⚠️ One or more required feeds are not live. Fixes:")
        print("     • set the missing API keys in .env / your secrets manager")
        print("     • allow outbound HTTPS egress to the provider hosts")
        print("     • see docs/LIVE_DATA_SETUP.md")
    print("─" * 74)
    return 0 if all_required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
