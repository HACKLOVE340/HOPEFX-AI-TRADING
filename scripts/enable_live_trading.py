#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/enable_live_trading.py
================================
Safety gate for enabling live trading.

Checks all prerequisites before setting FEATURE_LIVE_TRADING=true in .env:
  1. Paper trading has run for at least 30 days
  2. Zero execution errors in paper trading logs
  3. OANDA credentials are set and validated
  4. Risk limits are configured
  5. User explicitly confirms with a typed phrase

This script will NOT enable live trading automatically — it only sets the
flag after all checks pass AND the user types the confirmation phrase.

Usage:
    python scripts/enable_live_trading.py
    python scripts/enable_live_trading.py --check-only   # run checks, don't modify .env
    python scripts/enable_live_trading.py --force        # skip 30-day check (dev only)
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

_ENV_PATH = _ROOT / ".env"
_MIN_PAPER_DAYS = 30
_CONFIRM_PHRASE = "I understand this uses real money"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "✓" if ok else "✗"
    msg = f"  {status} {label}"
    if detail:
        msg += f"\n      {detail}"
    print(msg)
    return ok


def run_checks(force: bool = False) -> dict:
    """Run all prerequisite checks. Returns dict of {check_name: passed}."""
    results = {}
    print("\nLive Trading Prerequisites")
    print("=" * 50)

    # ── 1. OANDA credentials ──────────────────────────────────────────────────
    api_key = os.getenv("OANDA_API_KEY") or os.getenv("BROKER_OANDA_TOKEN") or ""
    account_id = os.getenv("OANDA_ACCOUNT_ID") or os.getenv("BROKER_OANDA_ACCOUNT") or ""
    results["oanda_key"] = _check(
        "OANDA_API_KEY set",
        bool(api_key),
        "" if api_key else "Set OANDA_API_KEY in .env",
    )
    results["oanda_account"] = _check(
        "OANDA_ACCOUNT_ID set",
        bool(account_id),
        "" if account_id else "Set OANDA_ACCOUNT_ID in .env",
    )

    # ── 2. Practice flag must be explicitly set to false ──────────────────────
    practice = os.getenv("OANDA_PRACTICE", "true").lower()
    results["practice_flag"] = _check(
        "OANDA_PRACTICE=false in .env",
        practice == "false",
        "Set OANDA_PRACTICE=false in .env to enable live orders" if practice != "false" else "",
    )

    # ── 3. Risk limits configured ─────────────────────────────────────────────
    max_pos = os.getenv("RISK_MAX_POSITION_SIZE_PCT", "")
    max_dd = os.getenv("RISK_MAX_DRAWDOWN_PCT", "")
    results["risk_limits"] = _check(
        "Risk limits configured",
        bool(max_pos and max_dd),
        "Set RISK_MAX_POSITION_SIZE_PCT and RISK_MAX_DRAWDOWN_PCT in .env"
        if not (max_pos and max_dd)
        else f"position_size={max_pos} max_drawdown={max_dd}",
    )

    # ── 4. Paper trading duration ─────────────────────────────────────────────
    if force:
        results["paper_duration"] = _check(
            f"Paper trading ≥ {_MIN_PAPER_DAYS} days",
            True,
            "--force flag set, skipping duration check",
        )
    else:
        paper_days = _estimate_paper_trading_days()
        results["paper_duration"] = _check(
            f"Paper trading ≥ {_MIN_PAPER_DAYS} days",
            paper_days >= _MIN_PAPER_DAYS,
            f"Estimated {paper_days} days of paper trading data found"
            + (f" — need {_MIN_PAPER_DAYS - paper_days} more days" if paper_days < _MIN_PAPER_DAYS else ""),
        )

    # ── 5. No execution errors in logs ────────────────────────────────────────
    error_count = _count_execution_errors()
    results["no_errors"] = _check(
        "Zero execution errors in paper trading logs",
        error_count == 0,
        f"{error_count} execution errors found in logs/paper_trading.log"
        if error_count > 0
        else "No execution errors found",
    )

    # ── 6. OANDA API reachable ────────────────────────────────────────────────
    if api_key and account_id:
        reachable = _test_oanda_connection(api_key, account_id, practice=False)
        results["oanda_reachable"] = _check(
            "OANDA live API reachable",
            reachable,
            "" if reachable else "Run: python scripts/validate_oanda.py --live",
        )
    else:
        results["oanda_reachable"] = _check(
            "OANDA live API reachable",
            False,
            "Cannot test — credentials not set",
        )

    return results


def _estimate_paper_trading_days() -> int:
    """Estimate days of paper trading from log file or CSV data."""
    # Check paper trading log
    log_path = _ROOT / "logs" / "paper_trading.log"
    if log_path.exists():
        try:
            lines = log_path.read_text().splitlines()
            if len(lines) >= 2:  # noqa: PLR2004
                # Parse first and last timestamps
                ts_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
                first_match = ts_pattern.search(lines[0])
                last_match = ts_pattern.search(lines[-1])
                if first_match and last_match:
                    first = datetime.fromisoformat(first_match.group(1))
                    last = datetime.fromisoformat(last_match.group(1))
                    return (last - first).days
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    # Fallback: check CSV modification time
    csv_path = _ROOT / "data" / "XAU_USD_H1.csv"
    if csv_path.exists():
        mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
        age = (datetime.now() - mtime).days
        # If CSV is recent, paper trading may have been running
        if age < 7:  # noqa: PLR2004
            return 0  # Can't confirm 30 days
    return 0


def _count_execution_errors() -> int:
    """Count ERROR lines in paper trading log."""
    log_path = _ROOT / "logs" / "paper_trading.log"
    if not log_path.exists():
        return 0
    try:
        content = log_path.read_text()
        return content.count("ERROR") + content.count("execution failed")
    except Exception:
        return 0


def _test_oanda_connection(api_key: str, account_id: str, practice: bool) -> bool:
    """Quick connectivity test to OANDA live endpoint."""
    try:
        import requests

        base = "https://api-fxpractice.oanda.com" if practice else "https://api-fxtrade.oanda.com"
        r = requests.get(
            f"{base}/v3/accounts/{account_id}/summary",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
        return r.status_code == 200  # noqa: PLR2004
    except Exception:
        return False


def enable_live_trading() -> None:
    """Write FEATURE_LIVE_TRADING=true to .env."""
    if not _ENV_PATH.exists():
        print(f"\n✗ .env not found at {_ENV_PATH}")
        print("  Copy .env.example to .env first: cp .env.example .env")
        sys.exit(1)

    content = _ENV_PATH.read_text()

    if "FEATURE_LIVE_TRADING=true" in content:
        print("\n  FEATURE_LIVE_TRADING is already true in .env")
        return

    if "FEATURE_LIVE_TRADING=false" in content:
        content = content.replace("FEATURE_LIVE_TRADING=false", "FEATURE_LIVE_TRADING=true")
    elif "FEATURE_LIVE_TRADING=" in content:
        content = re.sub(r"FEATURE_LIVE_TRADING=.*", "FEATURE_LIVE_TRADING=true", content)
    else:
        content += "\nFEATURE_LIVE_TRADING=true\n"

    _ENV_PATH.write_text(content)
    print("\n✓ FEATURE_LIVE_TRADING=true written to .env")
    print("\nNext steps:")
    print("  1. Restart the app: python app.py")
    print("  2. Start with minimum position size ($100 max)")
    print("  3. Monitor every order at /api/trading/positions")
    print("  4. Set RISK_MAX_POSITION_SIZE_PCT=0.001 for the first week")


def main() -> None:
    parser = argparse.ArgumentParser(description="Safety gate for enabling live trading")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run checks only, do not modify .env",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip 30-day paper trading check (dev/testing only)",
    )
    args = parser.parse_args()

    results = run_checks(force=args.force)
    all_passed = all(results.values())

    print()
    if not all_passed:
        failed = [k for k, v in results.items() if not v]
        print(f"✗ {len(failed)} check(s) failed. Fix them before enabling live trading.")
        print("\nSee docs/oanda_paper_trading_setup.md for setup instructions.")
        sys.exit(1)

    print("✓ All checks passed.")

    if args.check_only:
        print("\n(--check-only: .env not modified)")
        return

    # Require explicit confirmation
    print("\n" + "!" * 60)
    print("WARNING: Live trading uses REAL MONEY.")
    print("Start with the minimum position size ($100 max).")
    print("!" * 60)
    print(f'\nType exactly: "{_CONFIRM_PHRASE}"')
    print("(or Ctrl+C to cancel)\n")

    try:
        user_input = input("> ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(0)

    if user_input != _CONFIRM_PHRASE:
        print(f'\n✗ Confirmation phrase did not match. Expected: "{_CONFIRM_PHRASE}"')
        sys.exit(1)

    enable_live_trading()


if __name__ == "__main__":
    main()
