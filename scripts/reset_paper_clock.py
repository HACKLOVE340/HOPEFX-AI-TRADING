# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
scripts/reset_paper_clock.py
=============================
Reset the paper trading run clock to now.

Clears both the OandaPaperClock stamp file and the PaperTradingGate state,
then writes a fresh start timestamp so the 30-day paper run begins from
this moment.

Usage
-----
    python scripts/reset_paper_clock.py [--account-id ACCOUNT_ID] [--env practice|live]

Environment variables
---------------------
    OANDA_PAPER_STAMP_PATH   — override stamp file path (default: data/oanda_paper_start.json)
    PAPER_GATE_STATE_PATH    — override gate state path (default: data/paper_trading_gate.json)
    OANDA_ACCOUNT_ID         — account ID to stamp (can also be passed via --account-id)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc

# Ensure project root is on sys.path when run directly
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("reset_paper_clock")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset the HOPEFX paper trading run clock to now.",
    )
    parser.add_argument(
        "--account-id",
        default=os.environ.get("OANDA_ACCOUNT_ID", "PENDING"),
        help="OANDA account ID to stamp (default: OANDA_ACCOUNT_ID env or 'PENDING')",
    )
    parser.add_argument(
        "--env",
        choices=["practice", "live"],
        default="practice",
        help="Broker environment (default: practice)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching disk",
    )
    return parser.parse_args()


def reset_oanda_paper_clock(
    account_id: str,
    environment: str,
    dry_run: bool = False,
) -> dict:
    """
    Reset OandaPaperClock: delete existing stamp and write a fresh one.

    Returns the new stamp dict.
    """
    from brokers.oanda_paper_clock import OandaPaperClock

    clock = OandaPaperClock()

    # Delete existing stamp so maybe_start() writes a fresh one
    if clock._stamp_path.exists():
        if dry_run:
            logger.info("[DRY-RUN] Would delete: %s", clock._stamp_path)
        else:
            clock._stamp_path.unlink()
            logger.info("Deleted existing stamp: %s", clock._stamp_path)
    else:
        logger.info("No existing stamp found at %s", clock._stamp_path)

    if dry_run:
        now = datetime.now(UTC)
        logger.info("[DRY-RUN] Would stamp: account=%s env=%s started=%s", account_id, environment, now.isoformat())
        return {"started_utc": now.isoformat(), "account_id": account_id, "environment": environment}

    started = clock.maybe_start(account_id=account_id, environment=environment)
    if started:
        logger.info("OandaPaperClock: fresh clock stamped.")
    else:
        logger.warning("OandaPaperClock: maybe_start() returned False — check stamp file.")

    # Read back what was written
    if clock._stamp_path.exists():
        stamp = json.loads(clock._stamp_path.read_text(encoding="utf-8"))
        logger.info("Stamp contents: %s", json.dumps(stamp, indent=2))
        return stamp
    return {}


def reset_paper_trading_gate(dry_run: bool = False) -> None:
    """
    Reset PaperTradingGate: clear fill count and set run_start to now.
    """
    # Import the module directly to avoid research/__init__.py pulling in the
    # full FastAPI/JWT stack at module level.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "paper_trading_gate",
        _ROOT / "research" / "pipeline" / "paper_trading_gate.py",
    )
    _mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_mod)
    PaperTradingGate = _mod.PaperTradingGate

    gate = PaperTradingGate()

    if dry_run:
        logger.info("[DRY-RUN] Would reset PaperTradingGate state at %s", gate._state_path)
        return

    # Wipe state and set fresh start
    gate._state = {
        "run_start_utc": "",
        "fill_count": 0,
        "fills": [],
        "sharpe_before": None,
        "sharpe_after": None,
        "phase2_enabled_at": None,
        "phase3_enabled_at": None,
    }
    gate.set_run_start()  # sets to now and saves
    logger.info(
        "PaperTradingGate: reset complete. run_start=%s fill_count=0",
        gate.run_start.isoformat() if gate.run_start else "?",
    )


def main() -> int:
    args = _parse_args()

    logger.info(
        "Resetting paper trading clock — account=%s env=%s dry_run=%s",
        args.account_id,
        args.env,
        args.dry_run,
    )

    stamp = reset_oanda_paper_clock(
        account_id=args.account_id,
        environment=args.env,
        dry_run=args.dry_run,
    )
    reset_paper_trading_gate(dry_run=args.dry_run)

    if not args.dry_run:
        logger.info(
            "Paper trading clock reset complete.\n"
            "  started_utc : %s\n"
            "  account_id  : %s\n"
            "  environment : %s\n"
            "  gate_opens  : %s\n"
            "\nRun `python execution/paper_runner.py` to start producing fills.",
            stamp.get("started_utc", "?"),
            stamp.get("account_id", "?"),
            stamp.get("environment", "?"),
            stamp.get("live_gate_opens", "?"),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
