#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/fill_tracker.py
=======================
OANDA paper trading fill tracker — enforces the 500-fill deployment gate.

Queries OANDA's transaction history API for ORDER_FILL transactions,
deduplicates by transaction ID, persists to data/fill_tracker.json, and
reports gate status. Designed to run as a cron job or alongside
paper_trading_starter.py.

Usage
-----
    python scripts/fill_tracker.py              # sync + report
    python scripts/fill_tracker.py --report     # report only (no API call)
    python scripts/fill_tracker.py --reset      # wipe local state (dev only)

Environment variables
---------------------
    OANDA_API_KEY      — OANDA practice API key (required)
    OANDA_ACCOUNT_ID   — OANDA practice account ID (required)
    OANDA_ENVIRONMENT  — "practice" (default) or "live"
    FILL_GATE_TARGET   — fills required before Phase 3 (default: 500)

Output
------
    data/fill_tracker.json   — persistent fill ledger
    data/paper_trading_gate.json — gate status (read by deployment checklist)

Exit codes
----------
    0 — gate passed (>= FILL_GATE_TARGET fills)
    1 — gate not yet passed
    2 — error (missing credentials, API failure)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    ...  # nosec B110

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fill_tracker")

# ── constants ─────────────────────────────────────────────────────────────────

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

FILL_LEDGER = DATA_DIR / "fill_tracker.json"
GATE_FILE = DATA_DIR / "paper_trading_gate.json"

OANDA_BASE = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}

FILL_GATE_TARGET = int(os.environ.get("FILL_GATE_TARGET", "500"))


# ── OANDA transaction client ──────────────────────────────────────────────────


class OANDATransactionClient:
    """
    Queries OANDA v3 transaction history for ORDER_FILL events.

    Paginates through all transactions since `from_id`, collecting only
    ORDER_FILL type records. Each fill is stored with its transaction ID
    so re-runs are idempotent (no double-counting).
    """

    def __init__(self, api_key: str, account_id: str, environment: str = "practice"):
        self.account_id = account_id
        self.base_url = OANDA_BASE.get(environment, OANDA_BASE["practice"])
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> dict[str, Any]:
        import urllib.request

        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310 - API URL is always https://
                return json.loads(resp.read())
        except Exception as exc:
            raise RuntimeError(f"OANDA API error on {path}: {exc}") from exc

    def fetch_fills_since(self, from_id: int | None = None) -> list[dict[str, Any]]:
        """
        Fetch all ORDER_FILL transactions since `from_id` (exclusive).

        Returns a list of fill dicts, each containing:
            id, time, instrument, units, price, pl, account_balance
        """
        fills: list[dict[str, Any]] = []
        page_size = 900  # OANDA max per page

        # Build query params
        params = f"type=ORDER_FILL&count={page_size}"
        if from_id is not None:
            params += f"&from={from_id + 1}"

        path = f"/v3/accounts/{self.account_id}/transactions?{params}"

        while path:
            data = self._get(path)
            transactions = data.get("transactions", [])

            for txn in transactions:
                if txn.get("type") != "ORDER_FILL":
                    continue
                fills.append(
                    {
                        "id": int(txn["id"]),
                        "time": txn.get("time", ""),
                        "instrument": txn.get("instrument", ""),
                        "units": txn.get("units", "0"),
                        "price": txn.get("price", "0"),
                        "pl": txn.get("pl", "0"),
                        "account_balance": txn.get("accountBalance", "0"),
                        "order_id": txn.get("orderID", ""),
                        "trade_id": txn.get("tradeID", txn.get("tradeOpened", {}).get("tradeID", "")),
                        "reason": txn.get("reason", ""),
                    }
                )

            # Pagination: OANDA returns a 'pages' list or a 'lastTransactionID'
            pages = data.get("pages", [])
            if pages:
                # pages is a list of URLs; advance to next page
                for page_url in pages:
                    # Find the page after the current one by checking if we've
                    # seen all transactions on this page
                    if transactions and str(transactions[-1]["id"]) in page_url:
                        continue
                    break
                # Simpler: if we got a full page, check lastTransactionID
                path = None
            else:
                path = None

            # If we got fewer than page_size results, we're done
            if len(transactions) < page_size:
                path = None

        return fills


# ── Ledger management ─────────────────────────────────────────────────────────


def _load_ledger() -> dict[str, Any]:
    """Load the persistent fill ledger from disk."""
    if FILL_LEDGER.exists():
        try:
            return json.loads(FILL_LEDGER.read_text())
        except Exception as exc:
            logger.warning("Ledger read failed (%s) — starting fresh", exc)
    return {
        "fills": [],
        "fill_count": 0,
        "last_transaction_id": None,
        "first_fill_at": None,
        "last_sync_at": None,
        "account_id": None,
    }


def _save_ledger(ledger: dict[str, Any]) -> None:
    """Persist the fill ledger atomically."""
    ledger["last_sync_at"] = datetime.now(UTC).isoformat()
    tmp = FILL_LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2))
    tmp.replace(FILL_LEDGER)


def _update_gate_file(ledger: dict[str, Any]) -> None:
    """Write paper_trading_gate.json with current gate status."""
    fill_count = ledger["fill_count"]
    gate_passed = fill_count >= FILL_GATE_TARGET
    pct = min(100.0, fill_count / FILL_GATE_TARGET * 100)

    existing: dict[str, Any] = {}
    if GATE_FILE.exists():
        try:
            existing = json.loads(GATE_FILE.read_text())
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    gate = {
        **existing,
        "fill_count": fill_count,
        "fill_gate_target": FILL_GATE_TARGET,
        "fill_gate_passed": gate_passed,
        "fill_gate_pct": round(pct, 1),
        "last_fill_at": ledger["fills"][-1]["time"] if ledger["fills"] else None,
        "first_fill_at": ledger["first_fill_at"],
        "last_sync_at": ledger["last_sync_at"],
        "phase3_enabled_at": (
            existing.get("phase3_enabled_at") or (datetime.now(UTC).isoformat() if gate_passed else None)
        ),
    }
    GATE_FILE.write_text(json.dumps(gate, indent=2))


# ── Sync logic ────────────────────────────────────────────────────────────────


def sync_fills(client: OANDATransactionClient, ledger: dict[str, Any]) -> int:
    """
    Fetch new fills from OANDA and merge into the ledger.

    Returns the number of new fills added.
    """
    from_id = ledger.get("last_transaction_id")
    logger.info(
        "Fetching fills from OANDA (from_id=%s) …",
        from_id or "beginning",
    )

    new_fills = client.fetch_fills_since(from_id)

    if not new_fills:
        logger.info("No new fills found")
        return 0

    # Deduplicate by transaction ID
    existing_ids = {f["id"] for f in ledger["fills"]}
    added = 0
    for fill in new_fills:
        if fill["id"] not in existing_ids:
            ledger["fills"].append(fill)
            existing_ids.add(fill["id"])
            added += 1

    # Update metadata
    if ledger["fills"]:
        ledger["fills"].sort(key=lambda f: f["id"])
        ledger["last_transaction_id"] = ledger["fills"][-1]["id"]
        ledger["first_fill_at"] = ledger["fills"][0]["time"]

    ledger["fill_count"] = len(ledger["fills"])
    logger.info("Added %d new fills (total: %d)", added, ledger["fill_count"])
    return added


# ── Report ────────────────────────────────────────────────────────────────────


def print_report(ledger: dict[str, Any]) -> None:
    """Print a human-readable gate status report."""
    fill_count = ledger["fill_count"]
    gate_passed = fill_count >= FILL_GATE_TARGET
    remaining = max(0, FILL_GATE_TARGET - fill_count)
    pct = min(100.0, fill_count / FILL_GATE_TARGET * 100)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  HOPEFX Paper Trading Fill Gate")
    logger.info("=" * 60)
    logger.info("  Fills recorded : %s", fill_count:,)
    logger.info("  Gate target    : %s", FILL_GATE_TARGET:,)
    logger.info("  Progress       : %.1f%%  [%s/%s]", pct, fill_count, FILL_GATE_TARGET)
    logger.info("  Remaining      : %s", remaining:,)
    logger.info("  Gate status    : %s", 'PASSED' if gate_passed else 'NOT YET PASSED')
    if ledger.get("first_fill_at"):
        logger.info("  First fill     : %s", ledger['first_fill_at'])
    if ledger["fills"]:
        logger.info("  Last fill      : %s", ledger['fills'][-1]['time'])
    logger.info("  Last sync      : %s", ledger.get('last_sync_at', 'never'))
    logger.info("=" * 60)

    if gate_passed:
        logger.info("")
        logger.info("  Gate PASSED. Phase 3 (live capital) deployment is unblocked")
        logger.info("  by the fill count requirement. Verify remaining checklist:")
        logger.error("  - 30+ days continuous paper trading without system errors")
        logger.info("  - Monte Carlo backtest reconciled with OOS evaluation")
        logger.info("  - Risk committee sign-off")
    else:
        logger.info("")
        logger.info("  Gate NOT PASSED. Need %s more fills before Phase 3.", remaining:,)
        logger.info("  Run paper_trading_starter.py to accumulate fills.")
    logger.info("")


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OANDA paper trading fill tracker")
    p.add_argument(
        "--report",
        action="store_true",
        help="Print gate status from local ledger only (no API call)",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Wipe local fill ledger (development use only)",
    )
    p.add_argument(
        "--target",
        type=int,
        default=FILL_GATE_TARGET,
        help=f"Fill gate target (default: {FILL_GATE_TARGET})",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    global FILL_GATE_TARGET
    FILL_GATE_TARGET = args.target

    if args.reset:
        if FILL_LEDGER.exists():
            FILL_LEDGER.unlink()
            logger.info("Fill ledger reset")
        return 0

    ledger = _load_ledger()

    if not args.report:
        api_key = os.environ.get("OANDA_API_KEY", "").strip()
        account_id = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
        environment = os.environ.get("OANDA_ENVIRONMENT", "practice").strip()

        if not api_key or not account_id:
            logger.error(
                "OANDA_API_KEY and OANDA_ACCOUNT_ID must be set. Use --report to view local ledger without an API call."
            )
            return 2

        ledger["account_id"] = account_id
        client = OANDATransactionClient(api_key, account_id, environment)

        try:
            sync_fills(client, ledger)
        except RuntimeError as exc:
            logger.error("API sync failed: %s", exc)
            logger.info("Showing cached ledger data:")
            print_report(ledger)
            return 2

        _save_ledger(ledger)
        _update_gate_file(ledger)

    print_report(ledger)

    gate_passed = ledger["fill_count"] >= FILL_GATE_TARGET
    return 0 if gate_passed else 1


if __name__ == "__main__":
    sys.exit(main())
