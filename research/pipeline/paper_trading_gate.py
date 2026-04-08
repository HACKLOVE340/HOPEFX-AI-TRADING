# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/paper_trading_gate.py
=========================================
OANDA paper trading run clock and phase gate enforcement.

This module provides the authoritative gate checks for Phases 2 and 3.
It reads from environment variables and optionally from a persistent
state file so the gate survives process restarts.

Gate summary
------------
Phase 2 (Anomaly weighting):
  - 30 calendar days elapsed since OANDA_PAPER_RUN_START_UTC
  - Paper Sharpe drop < 0.2 after enabling (checked via check_sharpe_gate())

Phase 3 (Online learning):
  - 90 calendar days elapsed since OANDA_PAPER_RUN_START_UTC
  - >= 500 confirmed fills (OANDA_PAPER_FILL_COUNT)

Phase 4 (Deep ensemble):
  - OOS accuracy >= 70% (from model meta JSON)
  - p-value < 0.001 (from model meta JSON)
  - Enforced in DeepEnsembleStore.load() — not here

Usage
-----
    from research.pipeline.paper_trading_gate import PaperTradingGate

    gate = PaperTradingGate()
    gate.record_fill(profit_pnl=12.50)
    gate.record_sharpe(before=1.52, after=1.40)

    if gate.phase2_ready():
        logger.info("Enable FEATURE_ANOMALY_WEIGHTING=true")

    if gate.phase3_ready():
        logger.info("Enable FEATURE_ONLINE_LEARNING=true")

    # CLI usage
    python -m research.pipeline.paper_trading_gate --status
    python -m research.pipeline.paper_trading_gate --record-fill
    python -m research.pipeline.paper_trading_gate --set-start
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path

logger = logging.getLogger(__name__)

# Default path for the persistent gate state file
_DEFAULT_STATE_PATH = "data/paper_trading_gate.json"

# Gate thresholds (match spec exactly)
PHASE2_MIN_DAYS = 30
PHASE3_MIN_DAYS = 90
PHASE3_MIN_FILLS = 500
PHASE2_MAX_SHARPE_DROP = 0.2


class PaperTradingGate:
    """
    Tracks the OANDA paper trading run and enforces phase gates.

    State is persisted to a JSON file so it survives process restarts.
    All timestamps are stored and compared in UTC.

    Parameters
    ----------
    state_path : Path to the persistent state JSON file.
                 Defaults to PAPER_GATE_STATE_PATH env var or data/paper_trading_gate.json.
    """

    def __init__(self, state_path: str | None = None) -> None:
        self._state_path = Path(state_path or os.getenv("PAPER_GATE_STATE_PATH", _DEFAULT_STATE_PATH))
        self._state: dict = self._load_state()

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        """Load state from disk, falling back to env vars if file missing."""
        default: dict = {
            "run_start_utc": os.getenv("OANDA_PAPER_RUN_START_UTC", ""),
            "fill_count": int(os.getenv("OANDA_PAPER_FILL_COUNT", "0")),
            "fills": [],  # list of {ts, pnl} dicts
            "sharpe_before": None,
            "sharpe_after": None,
            "phase2_enabled_at": None,
            "phase3_enabled_at": None,
        }
        if self._state_path.exists():
            try:
                with Path(self._state_path).open(encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge: file values override defaults
                default.update(loaded)
                logger.debug("PaperTradingGate: state loaded from %s", self._state_path)
            except Exception as exc:
                logger.warning("PaperTradingGate: state load failed (%s), using defaults", exc)
        return default

    def _save_state(self) -> None:
        """Persist current state to disk."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with Path(self._state_path).open("w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, default=str)
        except Exception as exc:
            logger.warning("PaperTradingGate: state save failed: %s", exc)

    # ── Run clock ─────────────────────────────────────────────────────────────

    def set_run_start(self, ts: datetime | None = None) -> None:
        """
        Record the paper run start timestamp.

        Parameters
        ----------
        ts : UTC datetime. Defaults to now.
        """
        if ts is None:
            ts = datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        self._state["run_start_utc"] = ts.isoformat()
        self._save_state()
        logger.info("PaperTradingGate: run start set to %s", ts.isoformat())

    @property
    def run_start(self) -> datetime | None:
        """Return the run start as a UTC datetime, or None if not set."""
        s = self._state.get("run_start_utc", "")
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            return None

    @property
    def elapsed_days(self) -> int:
        """Calendar days elapsed since run start. Returns 0 if not started."""
        start = self.run_start
        if start is None:
            return 0
        return (datetime.now(UTC) - start).days

    # ── Fill tracking ─────────────────────────────────────────────────────────

    def record_fill(self, pnl: float = 0.0) -> int:
        """
        Record a confirmed paper trading fill.

        Parameters
        ----------
        pnl : Profit/loss of the fill in account currency.

        Returns
        -------
        Total fill count after recording.
        """
        self._state["fill_count"] = self._state.get("fill_count", 0) + 1
        self._state.setdefault("fills", []).append(
            {
                "ts": datetime.now(UTC).isoformat(),
                "pnl": float(pnl),
            }
        )
        # Keep only last 1000 fills in memory to bound file size
        if len(self._state["fills"]) > 1000:
            self._state["fills"] = self._state["fills"][-1000:]
        self._save_state()
        return self._state["fill_count"]

    @property
    def fill_count(self) -> int:
        return int(self._state.get("fill_count", 0))

    # ── Sharpe tracking ───────────────────────────────────────────────────────

    def record_sharpe(self, before: float, after: float) -> None:
        """
        Record Sharpe ratios before and after enabling anomaly weighting.

        Parameters
        ----------
        before : Sharpe ratio before enabling FEATURE_ANOMALY_WEIGHTING.
        after  : Sharpe ratio after 30-day window with anomaly weighting on.
        """
        self._state["sharpe_before"] = float(before)
        self._state["sharpe_after"] = float(after)
        self._save_state()
        logger.info(
            "PaperTradingGate: Sharpe recorded before=%.3f after=%.3f drop=%.3f",
            before,
            after,
            before - after,
        )

    # ── Gate checks ───────────────────────────────────────────────────────────

    def phase2_ready(self) -> tuple[bool, str]:
        """
        Check whether Phase 2 (anomaly weighting) gate is satisfied.

        Returns (passed, reason).
        """
        # Time gate
        if self.run_start is None:
            return False, ("Run start not set. Call set_run_start() or set OANDA_PAPER_RUN_START_UTC.")
        if self.elapsed_days < PHASE2_MIN_DAYS:
            remaining = PHASE2_MIN_DAYS - self.elapsed_days
            return False, (
                f"Phase 2: {self.elapsed_days} days elapsed, {remaining} days remaining (need {PHASE2_MIN_DAYS})."
            )

        # Sharpe gate (only checked if Sharpe has been recorded)
        sb = self._state.get("sharpe_before")
        sa = self._state.get("sharpe_after")
        if sb is not None and sa is not None:
            drop = float(sb) - float(sa)
            if drop > PHASE2_MAX_SHARPE_DROP:
                return False, (
                    f"Phase 2 Sharpe gate failed: drop={drop:.3f} ({sb:.3f}→{sa:.3f}), max={PHASE2_MAX_SHARPE_DROP}."
                )

        return True, (f"Phase 2 gate passed: {self.elapsed_days} days elapsed.")

    def phase3_ready(self) -> tuple[bool, str]:
        """
        Check whether Phase 3 (online learning) gate is satisfied.

        Returns (passed, reason).
        """
        # Fill count gate
        if self.fill_count < PHASE3_MIN_FILLS:
            return False, (f"Phase 3: {self.fill_count} fills, need >= {PHASE3_MIN_FILLS}.")

        # Time gate
        if self.run_start is None:
            return False, ("Run start not set. Call set_run_start() or set OANDA_PAPER_RUN_START_UTC.")
        if self.elapsed_days < PHASE3_MIN_DAYS:
            remaining = PHASE3_MIN_DAYS - self.elapsed_days
            return False, (
                f"Phase 3: {self.elapsed_days} days elapsed, {remaining} days remaining (need {PHASE3_MIN_DAYS})."
            )

        return True, (f"Phase 3 gate passed: {self.elapsed_days} days elapsed, {self.fill_count} fills.")

    def status(self) -> dict:
        """Return a full status dict for health-check endpoints."""
        p2_ok, p2_reason = self.phase2_ready()
        p3_ok, p3_reason = self.phase3_ready()
        return {
            "run_start_utc": self._state.get("run_start_utc", ""),
            "elapsed_days": self.elapsed_days,
            "fill_count": self.fill_count,
            "sharpe_before": self._state.get("sharpe_before"),
            "sharpe_after": self._state.get("sharpe_after"),
            "phase2_ready": p2_ok,
            "phase2_reason": p2_reason,
            "phase3_ready": p3_ok,
            "phase3_reason": p3_reason,
            "phase2_min_days": PHASE2_MIN_DAYS,
            "phase3_min_days": PHASE3_MIN_DAYS,
            "phase3_min_fills": PHASE3_MIN_FILLS,
            "phase2_max_sharpe_drop": PHASE2_MAX_SHARPE_DROP,
        }

    def print_status(self) -> None:
        """Print a human-readable status report to stdout."""
        s = self.status()
        logger.info("=" * 60)
        logger.info("OANDA Paper Trading Gate Status")
        logger.info("=" * 60)
        logger.info(f"  Run start (UTC) : {s['run_start_utc'] or 'NOT SET'}")
        logger.info(f"  Elapsed days    : {s['elapsed_days']}")
        logger.info(f"  Fill count      : {s['fill_count']}")
        if s["sharpe_before"] is not None:
            drop = s["sharpe_before"] - s["sharpe_after"]
            logger.info(f"  Sharpe before   : {s['sharpe_before']:.3f}")
            logger.info(f"  Sharpe after    : {s['sharpe_after']:.3f}")
            logger.info(f"  Sharpe drop     : {drop:.3f}")
        logger.info("")
        p2 = "✅ READY" if s["phase2_ready"] else "❌ NOT READY"
        p3 = "✅ READY" if s["phase3_ready"] else "❌ NOT READY"
        logger.info(f"  Phase 2 (Anomaly)  : {p2}")
        logger.info(f"    {s['phase2_reason']}")
        logger.info(f"  Phase 3 (Online)   : {p3}")
        logger.info(f"    {s['phase3_reason']}")
        logger.info("=" * 60)


# ── Module-level singleton ────────────────────────────────────────────────────

_gate: PaperTradingGate | None = None


def get_gate() -> PaperTradingGate:
    """Return the module-level PaperTradingGate singleton."""
    global _gate
    if _gate is None:
        _gate = PaperTradingGate()
    return _gate


# ── CLI entry point ───────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="OANDA paper trading gate management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current gate status",
    )
    parser.add_argument(
        "--set-start",
        action="store_true",
        help="Set the paper run start to now",
    )
    parser.add_argument(
        "--record-fill",
        type=float,
        metavar="PNL",
        nargs="?",
        const=0.0,
        help="Record a fill with optional PNL",
    )
    parser.add_argument(
        "--record-sharpe",
        nargs=2,
        type=float,
        metavar=("BEFORE", "AFTER"),
        help="Record Sharpe before and after enabling anomaly weighting",
    )
    parser.add_argument(
        "--state-path",
        type=str,
        default=None,
        help="Override state file path",
    )
    args = parser.parse_args()

    gate = PaperTradingGate(state_path=args.state_path)

    if args.set_start:
        gate.set_run_start()
        logger.info(f"Run start set to {gate.run_start.isoformat()}")

    if args.record_fill is not None:
        count = gate.record_fill(pnl=args.record_fill)
        logger.info(f"Fill recorded. Total fills: {count}")

    if args.record_sharpe:
        gate.record_sharpe(before=args.record_sharpe[0], after=args.record_sharpe[1])
        logger.info(f"Sharpe recorded: {args.record_sharpe[0]:.3f} → {args.record_sharpe[1]:.3f}")

    if args.status or not any([args.set_start, args.record_fill is not None, args.record_sharpe]):
        gate.print_status()


if __name__ == "__main__":
    _cli()
