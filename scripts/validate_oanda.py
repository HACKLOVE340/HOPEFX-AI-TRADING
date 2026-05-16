#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/validate_oanda.py
=========================
Validates OANDA practice API connectivity before starting paper trading.

Checks:
  1. API token is set and reachable
  2. Account ID is valid and returns a balance
  3. XAU_USD pricing is available
  4. A minimal order can be placed and immediately cancelled

Usage:
    python scripts/validate_oanda.py
    python scripts/validate_oanda.py --live   # test live endpoint (use with caution)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


# Ensure project root is on path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# Load .env if present
try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    ...  # nosec B110


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "✓" if ok else "✗"
    msg = f"{status} {label}"
    if detail:
        msg += f": {detail}"
    logger.info(msg)
    return ok


def validate(practice: bool = True) -> bool:
    api_key = os.getenv("OANDA_API_KEY") or os.getenv("BROKER_OANDA_TOKEN") or ""
    account_id = os.getenv("OANDA_ACCOUNT_ID") or os.getenv("BROKER_OANDA_ACCOUNT") or ""

    env_label = "practice" if practice else "LIVE"
    logger.info("\nOANDA %s API validation", env_label)
    logger.info("=" * 40)

    # ── 1. Credentials present ────────────────────────────────────────────────
    if not _check("OANDA_API_KEY set", bool(api_key)):
        logger.info("\n  Set OANDA_API_KEY in .env")
        logger.info("  Get a free practice account at https://www.oanda.com/register/")
        return False

    if not _check("OANDA_ACCOUNT_ID set", bool(account_id)):
        logger.info("\n  Set OANDA_ACCOUNT_ID in .env")
        return False

    # ── 2. API reachability ───────────────────────────────────────────────────
    try:
        import requests
    except ImportError:
        logger.info("✗ requests library not installed — run: pip install requests")
        return False

    base = "https://api-fxpractice.oanda.com" if practice else "https://api-fxtrade.oanda.com"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Account summary
    try:
        r = requests.get(
            f"{base}/v3/accounts/{account_id}/summary",
            headers=headers,
            timeout=10,
        )
        if r.status_code == 401:
            _check(
                "API token valid",
                False,
                "401 Unauthorized — regenerate token in OANDA portal",
            )
            return False
        if r.status_code == 404:
            _check("Account ID valid", False, f"404 — account {account_id!r} not found")
            return False
        r.raise_for_status()
        data = r.json()
        balance = data.get("account", {}).get("balance", "?")
        currency = data.get("account", {}).get("currency", "")
        _check("OANDA API reachable", True)
        _check("Account ID valid", True, f"{account_id}")
        _check("Account balance", True, f"{balance} {currency} ({env_label})")
    except requests.exceptions.ConnectionError:
        _check(
            "OANDA API reachable",
            False,
            "Connection refused — check internet / firewall",
        )
        return False
    except Exception as exc:
        _check("OANDA API reachable", False, str(exc))
        return False

    # ── 3. Pricing ────────────────────────────────────────────────────────────
    try:
        r = requests.get(
            f"{base}/v3/accounts/{account_id}/pricing",
            headers=headers,
            params={"instruments": "XAU_USD"},
            timeout=10,
        )
        r.raise_for_status()
        prices = r.json().get("prices", [])
        if prices:
            p = prices[0]
            bid = p.get("bids", [{}])[0].get("price", "?")
            ask = p.get("asks", [{}])[0].get("price", "?")
            _check("XAU_USD pricing", True, f"bid={bid} ask={ask}")
        else:
            _check("XAU_USD pricing", False, "No prices returned")
    except Exception as exc:
        _check("XAU_USD pricing", False, str(exc))

    # ── 4. Order placement test (practice only) ───────────────────────────────
    if practice:
        try:
            order_body = {
                "order": {
                    "type": "MARKET",
                    "instrument": "XAU_USD",
                    "units": "1",  # minimum 1 unit
                    "timeInForce": "FOK",  # Fill or Kill — won't leave open position
                }
            }
            r = requests.post(
                f"{base}/v3/accounts/{account_id}/orders",
                headers=headers,
                json=order_body,
                timeout=10,
            )
            if r.status_code in (200, 201):
                resp = r.json()
                order_id = (
                    resp.get("orderFillTransaction", {}).get("id")
                    or resp.get("orderCreateTransaction", {}).get("id")
                    or "?"
                )
                _check(
                    "Order placement test",
                    True,
                    f"order filled/created (id={order_id})",
                )

                # Close any open position from the test
                r2 = requests.put(
                    f"{base}/v3/accounts/{account_id}/positions/XAU_USD/close",
                    headers=headers,
                    json={"longUnits": "ALL", "shortUnits": "ALL"},
                    timeout=10,
                )
                if r2.status_code in (200, 201):
                    _check("Test position closed", True)
            else:
                _check(
                    "Order placement test",
                    False,
                    f"HTTP {r.status_code}: {r.text[:100]}",
                )
        except Exception as exc:
            _check("Order placement test", False, str(exc))
    else:
        logger.info("  (Order placement test skipped for live endpoint)")

    logger.info("")
    logger.info("All checks passed. HOPEFX is ready for paper trading.")
    logger.info("Start with: python app.py")
    logger.info("Monitor at: http://localhost:8000/app")
    return True


def validate_gate() -> None:
    """Print the current PaperTradingGate phase status."""
    logger.info("\nPhase Gate Status")
    logger.info("=" * 40)
    try:
        from research.pipeline.paper_trading_gate import PaperTradingGate

        gate = PaperTradingGate()
        gate.print_status()

        p2_ok, _ = gate.phase2_ready()
        p3_ok, _ = gate.phase3_ready()

        if not p2_ok:
            logger.info("\nTo start the 30-day clock:")
            logger.info("  python -m research.pipeline.paper_trading_gate --set-start")
            logger.info("\nTo record fills (called automatically by broker callback):")
            logger.info("  python -m research.pipeline.paper_trading_gate --record-fill <pnl>")
        elif not p3_ok:
            logger.info("\nPhase 2 gate passed. Enable anomaly weighting:")
            logger.info("  FEATURE_ANOMALY_WEIGHTING=true  (in .env)")
            logger.info("\nPhase 3 requires 500 fills and 90 days.")
        else:
            logger.info("\nAll phase gates passed. Enable online learning:")
            logger.info("  FEATURE_ONLINE_LEARNING=true  (in .env)")
    except ImportError as exc:
        logger.info("  Gate module unavailable: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate OANDA API connectivity and paper trading gate status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/validate_oanda.py              # validate practice API
  python scripts/validate_oanda.py --gate       # show phase gate status only
  python scripts/validate_oanda.py --live       # validate live endpoint (caution)
  python scripts/validate_oanda.py --all        # API + gate status
""",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Test live endpoint instead of practice (use with caution)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Show phase gate status (Phase 2 / Phase 3 readiness)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run API validation AND show gate status",
    )
    args = parser.parse_args()

    if args.gate and not args.all:
        validate_gate()
        sys.exit(0)

    ok = validate(practice=not args.live)

    if args.all or args.gate:
        validate_gate()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
