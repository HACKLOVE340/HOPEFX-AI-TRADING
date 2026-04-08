#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/test_ibkr_connection.py
================================
End-to-end IBKR paper connection smoke test.

Verifies:
  1. ib_insync is installed and importable.
  2. TWS/Gateway is reachable at IBKR_HOST:IBKR_PORT.
  3. At least one managed account is returned.
  4. Account summary (NetLiquidation) is readable.
  5. A market-data snapshot for XAUUSD (GC futures) is returned.
  6. Port is a recognised paper port (7497 or 4002) — warns if live port used.

Usage:
    # Paper TWS (default):
    python scripts/test_ibkr_connection.py

    # Custom host/port:
    IBKR_HOST=192.168.1.10 IBKR_PORT=4002 python scripts/test_ibkr_connection.py

    # Non-interactive (CI / health check):
    python scripts/test_ibkr_connection.py --no-interactive

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
    2 — ib_insync not installed
"""

from __future__ import annotations

import argparse
import os
import sys
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load .env if present (dev convenience)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    ...  # nosec B110

HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
PORT = int(os.environ.get("IBKR_PORT", "7497"))
CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID", "99"))  # 99 = test client
TIMEOUT = float(os.environ.get("IBKR_CONNECT_TIMEOUT", "10"))

PAPER_PORTS = {7497, 4002}
LIVE_PORTS = {7496, 4001}

_PASS = "  ✓"  # nosec B105 — status symbol, not a password
_FAIL = "  ✗"
_WARN = "  ⚠"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    icon = _PASS if ok else _FAIL
    line = f"{icon}  {label}"
    if detail:
        line += f"  — {detail}"
    logger.info(line)
    return ok


def run_checks(interactive: bool = True) -> int:
    """Run all checks. Returns 0 on full pass, 1 on any failure."""
    failures = 0

    logger.info("\n" + "=" * 60)
    logger.info("  IBKR Connection Smoke Test")
    logger.info(f"  Host: {HOST}:{PORT}  client_id={CLIENT_ID}")
    logger.info("=" * 60)

    # ── Check 1: ib_insync importable ────────────────────────────────────────
    try:
        from ib_insync import IB, ContFuture

        _check("ib_insync importable", True, "ib_insync available")
    except ImportError as exc:
        _check("ib_insync importable", False, str(exc))
        logger.info("\n  Install: pip install ib_insync==0.9.86")
        return 2

    # ── Check 2: Port sanity ─────────────────────────────────────────────────
    if PORT in LIVE_PORTS:
        logger.warning(
            f"{_WARN}  Port {PORT} is a LIVE trading port. Use 7497 (TWS paper) or 4002 (Gateway paper) for testing."
        )
    elif PORT in PAPER_PORTS:
        _check(f"Port {PORT} is a paper port", True)
    else:
        failures += int(
            not _check(
                f"Port {PORT} recognised",
                False,
                "expected 7497/4002 (paper) or 7496/4001 (live)",
            )
        )

    # ── Check 3: Connect ─────────────────────────────────────────────────────
    from ib_insync import IB

    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, readonly=True, timeout=TIMEOUT)
        _check("TCP connection established", True, f"{HOST}:{PORT}")
    except Exception as exc:
        _check("TCP connection established", False, str(exc))
        logger.info("\n  Ensure TWS/IB Gateway is running and API connections are enabled.")
        logger.info("  TWS: File → Global Configuration → API → Settings → Enable ActiveX and Socket Clients")
        return 1

    try:
        # ── Check 4: Managed accounts ────────────────────────────────────────
        accounts = ib.managedAccounts()
        ok = bool(accounts)
        failures += int(
            not _check(
                "Managed accounts returned",
                ok,
                f"accounts={accounts}" if ok else "no accounts returned",
            )
        )

        # ── Check 5: Account summary ─────────────────────────────────────────
        if accounts:
            acct = accounts[0]
            summary = ib.accountSummary(acct)
            net_liq = next((s.value for s in summary if s.tag == "NetLiquidation"), None)
            ok = net_liq is not None
            failures += int(
                not _check(
                    "Account summary readable",
                    ok,
                    f"NetLiquidation={net_liq}" if ok else "NetLiquidation tag missing",
                )
            )

        # ── Check 6: Market data snapshot (XAUUSD via GC continuous future) ──
        try:
            from ib_insync import ContFuture

            contract = ContFuture("GC", "COMEX")
            ib.qualifyContracts(contract)
            ticker = ib.reqMktData(contract, "", True, False)
            ib.sleep(2)  # allow snapshot to arrive
            has_price = ticker.last is not None or ticker.close is not None
            failures += int(
                not _check(
                    "Market data snapshot (GC/XAUUSD)",
                    has_price,
                    f"last={ticker.last} close={ticker.close}"
                    if has_price
                    else "no price data — check market data subscriptions",
                )
            )
            ib.cancelMktData(contract)
        except Exception as md_exc:
            failures += int(not _check("Market data snapshot (GC/XAUUSD)", False, str(md_exc)))

        # ── Check 7: Order placement dry-run (paper only) ────────────────────
        if PORT in PAPER_PORTS and interactive:
            try:
                from ib_insync import ContFuture, MarketOrder

                contract = ContFuture("GC", "COMEX")
                ib.qualifyContracts(contract)
                order = MarketOrder("BUY", 1)
                # whatIfOrder validates without submitting
                state = ib.whatIfOrder(contract, order)
                ok = state is not None
                failures += int(
                    not _check(
                        "Order dry-run (whatIfOrder)",
                        ok,
                        f"initMarginChange={getattr(state, 'initMarginChange', 'n/a')}"
                        if ok
                        else "whatIfOrder returned None",
                    )
                )
            except Exception as ord_exc:
                failures += int(not _check("Order dry-run (whatIfOrder)", False, str(ord_exc)))

    finally:
        ib.disconnect()
        _check("Disconnected cleanly", True)

    logger.info("\n" + "=" * 60)
    if failures == 0:
        logger.info("  ALL CHECKS PASSED — IBKR paper connection is healthy.")
    else:
        logger.error(f"  {failures} CHECK(S) FAILED — review output above.")
    logger.info("=" * 60 + "\n")

    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="IBKR paper connection smoke test")
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Skip order dry-run (safe for CI / health checks)",
    )
    args = parser.parse_args()
    sys.exit(run_checks(interactive=not args.no_interactive))


if __name__ == "__main__":
    main()
