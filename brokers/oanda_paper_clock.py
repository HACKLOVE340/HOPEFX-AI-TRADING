# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
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
        Start the clock on first real OANDA connection.

        Called by the OANDA broker connector on first successful connection.
        Handles two cases:
        1. No stamp file — write a fresh stamp and start the clock.
        2. Stamp file exists with ``requires_real_account: true`` (PENDING
           placeholder) — overwrite with the real account_id while preserving
           the original started_utc so the 30-day clock is not reset.

        Returns True if the clock was started or updated, False if already
        running with a real account.
        """
        if self._stamp_path.exists():
            try:
                existing = json.loads(self._stamp_path.read_text())
            except Exception:
                existing = {}

            # If a real account is already stamped, preserve the clock.
            if not existing.get("requires_real_account", False):
                logger.debug(
                    "OandaPaperClock: already running (account=%s…), not overwriting",
                    str(existing.get("account_id", "?"))[:8],
                )
                return False

            # PENDING placeholder — overwrite with real account, keep started_utc.
            started_utc_str = existing.get("started_utc")
            logger.info(
                "OandaPaperClock: replacing PENDING placeholder with real account %s…",
                account_id[:8] if account_id else "?",
            )
        else:
            started_utc_str = None

        now = datetime.now(timezone.utc)
        started_utc_str = started_utc_str or now.isoformat()

        # Parse to compute live_gate_opens
        try:
            started_dt = datetime.fromisoformat(started_utc_str.replace("Z", "+00:00"))
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=timezone.utc)
        except Exception:
            started_dt = now

        from datetime import timedelta
        live_gate_opens = (started_dt + timedelta(days=_TARGET_DAYS)).isoformat()

        # Mask account_id: first 8 chars + ellipsis
        masked = (account_id[:8] + "…") if len(account_id) > 8 else account_id

        stamp = {
            "started_utc": started_utc_str,
            "target_days": _TARGET_DAYS,
            "account_id": masked,
            "environment": environment,
            "live_gate_opens": live_gate_opens,
            "note": (
                f"OANDA paper trading clock running since {started_dt.date()}. "
                f"Live trading gate opens after {_TARGET_DAYS} days "
                f"({live_gate_opens[:10]})."
            ),
        }
        try:
            self._stamp_path.write_text(json.dumps(stamp, indent=2))
            logger.info(
                "OandaPaperClock: clock stamped — started=%s account=%s env=%s gate=%s",
                started_utc_str,
                masked,
                environment,
                live_gate_opens[:10],
            )
            self._sync_gate(started_dt)
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
            oanda_key = os.getenv("OANDA_API_KEY", "") or os.getenv(
                "BROKER_OANDA_TOKEN", ""
            )
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

            # PENDING placeholder — clock is pre-seeded but no real connection yet
            if data.get("requires_real_account", False):
                started_str = data.get("started_utc", "")
                started_dt = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
                if started_dt.tzinfo is None:
                    started_dt = started_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                elapsed = (now - started_dt).total_seconds() / 86400.0
                target = float(data.get("target_days", _TARGET_DAYS))
                remaining = max(0.0, target - elapsed)
                return {
                    "started": True,
                    "started_utc": started_str,
                    "elapsed_days": round(elapsed, 2),
                    "remaining_days": round(remaining, 2),
                    "target_days": int(target),
                    "complete": False,
                    "environment": data.get("environment", "practice"),
                    "account_id": "PENDING",
                    "pending_real_account": True,
                    "live_gate_opens": data.get("live_gate_opens"),
                    "note": (
                        "Clock is running but no real OANDA account has connected. "
                        "Set BROKER_TYPE=oanda, BROKER_OANDA_TOKEN, and "
                        "BROKER_OANDA_ACCOUNT, then restart the server. "
                        "The account_id will be stamped on first successful connection."
                    ),
                }

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
                "pending_real_account": False,
                "live_gate_opens": data.get("live_gate_opens"),
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
                "pending_real_account": False,
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
