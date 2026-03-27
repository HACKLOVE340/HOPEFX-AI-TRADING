# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/oanda_paper_clock.py
============================
OANDA paper trading run clock.

Responsibilities
----------------
1. Detect when OANDA credentials are present (OANDA_API_KEY or BROKER_OANDA_TOKEN).
2. On first successful broker connection, write data/oanda_paper_start.json with
   the UTC start timestamp, environment, and account ID.
3. Expose clock_status() for the /api/status/paper-trading endpoint.
4. Auto-start: called from brokers/oanda.py connect() on success.
5. Integrate with research/pipeline/paper_trading_gate.PaperTradingGate so the
   phase gate clock starts automatically.

The stamp file survives process restarts. If it already exists, the clock is
not reset — the original start time is preserved.

Usage
-----
    from brokers.oanda_paper_clock import OandaPaperClock

    clock = OandaPaperClock()
    clock.maybe_start(account_id="101-001-123", environment="practice")
    status = clock.status()
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_STAMP_PATH = Path(os.getenv("OANDA_PAPER_STAMP_PATH", "data/oanda_paper_start.json"))
_TARGET_DAYS = 30


class OandaPaperClock:
    """
    Manages the 30-day OANDA paper trading run clock.

    Thread-safe for reads. Writes are idempotent — calling maybe_start()
    multiple times only writes the stamp once (on first call).
    """

    def __init__(self, stamp_path: Optional[Path] = None) -> None:
        self._stamp_path = stamp_path or _STAMP_PATH
        self._stamp_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Clock start ───────────────────────────────────────────────────────────

    def maybe_start(
        self,
        account_id: str = "",
        environment: str = "practice",
    ) -> bool:
        """
        Start the clock if not already started.

        Called by the OANDA broker connector on first successful connection.
        Idempotent — does nothing if the stamp file already exists.

        Parameters
        ----------
        account_id  : OANDA account ID (for audit trail).
        environment : "practice" or "live".

        Returns True if the clock was started now, False if already running.
        """
        if self._stamp_path.exists():
            logger.debug("OandaPaperClock: already started, stamp exists at %s", self._stamp_path)
            return False

        now = datetime.now(timezone.utc)
        stamp = {
            "started_utc": now.isoformat(),
            "target_days": _TARGET_DAYS,
            "account_id": account_id,
            "environment": environment,
            "note": (
                f"OANDA paper trading clock started {now.date()}. "
                f"Live trading gate opens after {_TARGET_DAYS} days."
            ),
        }
        try:
            self._stamp_path.write_text(json.dumps(stamp, indent=2))
            logger.info(
                "OandaPaperClock: 30-day clock STARTED at %s (account=%s env=%s)",
                now.isoformat(), account_id, environment,
            )
            # Also sync to PaperTradingGate so phase gates use the same start time
            self._sync_gate(now)
            return True
        except Exception as exc:
            logger.error("OandaPaperClock: failed to write stamp: %s", exc)
            return False

    def _sync_gate(self, start_dt: datetime) -> None:
        """Sync start time to PaperTradingGate singleton."""
        try:
            from research.pipeline.paper_trading_gate import get_gate
            gate = get_gate()
            if gate.run_start is None:
                gate.set_run_start(start_dt)
                logger.debug("OandaPaperClock: synced start to PaperTradingGate")
        except Exception as exc:
            logger.debug("OandaPaperClock: gate sync skipped: %s", exc)

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """
        Return the current clock status dict.

        Compatible with the /api/status/paper-trading response schema.
        """
        if not self._stamp_path.exists():
            oanda_key = os.getenv("OANDA_API_KEY", "") or os.getenv("BROKER_OANDA_TOKEN", "")
            if oanda_key:
                note = (
                    "OANDA credentials detected but broker has not connected yet. "
                    "Start the server with BROKER_TYPE=oanda to begin the 30-day clock."
                )
            else:
                note = (
                    "Clock not started. Set OANDA_API_KEY (or BROKER_OANDA_TOKEN) "
                    "and restart with BROKER_TYPE=oanda."
                )
            return {
                "started": False,
                "started_utc": None,
                "elapsed_days": 0.0,
                "remaining_days": float(_TARGET_DAYS),
                "target_days": _TARGET_DAYS,
                "complete": False,
                "environment": None,
                "account_id": None,
                "note": note,
            }

        try:
            data = json.loads(self._stamp_path.read_text())
            started_str = data.get("started_utc", "")
            started_dt = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            elapsed = (now - started_dt).total_seconds() / 86400.0
            target = float(data.get("target_days", _TARGET_DAYS))
            remaining = max(0.0, target - elapsed)
            complete = elapsed >= target

            return {
                "started": True,
                "started_utc": started_str,
                "elapsed_days": round(elapsed, 2),
                "remaining_days": round(remaining, 2),
                "target_days": int(target),
                "complete": complete,
                "environment": data.get("environment"),
                "account_id": data.get("account_id"),
                "note": (
                    f"Run complete — {elapsed:.1f} days elapsed."
                    if complete
                    else f"{elapsed:.1f} days elapsed, {remaining:.1f} days remaining."
                ),
            }
        except Exception as exc:
            logger.warning("OandaPaperClock.status: read error: %s", exc)
            return {
                "started": False,
                "started_utc": None,
                "elapsed_days": 0.0,
                "remaining_days": float(_TARGET_DAYS),
                "target_days": _TARGET_DAYS,
                "complete": False,
                "environment": None,
                "account_id": None,
                "note": f"Clock read error: {exc}",
            }

    def is_complete(self) -> bool:
        """Return True if the 30-day paper run is complete."""
        return self.status().get("complete", False)

    def elapsed_days(self) -> float:
        """Return elapsed days as a float."""
        return float(self.status().get("elapsed_days", 0.0))

    def reset(self) -> None:
        """Delete the stamp file (for testing only)."""
        if self._stamp_path.exists():
            self._stamp_path.unlink()
            logger.warning("OandaPaperClock: stamp file deleted (reset)")


# ── Module-level singleton ────────────────────────────────────────────────────

_clock: Optional[OandaPaperClock] = None


def get_clock() -> OandaPaperClock:
    """Return the module-level OandaPaperClock singleton."""
    global _clock
    if _clock is None:
        _clock = OandaPaperClock()
    return _clock
