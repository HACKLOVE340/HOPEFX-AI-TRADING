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

UTC = timezone.utc
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

_STAMP_PATH = Path(os.getenv("OANDA_PAPER_STAMP_PATH", "data/oanda_paper_start.json"))
_TARGET_DAYS = 30

# Sharpe tracker configuration (overridable via env)
_SHARPE_TARGET_N: int = int(os.getenv("SHARPE_TARGET_N", "600"))
_SHARPE_TARGET_SR: float = float(os.getenv("SHARPE_TARGET_SR", "1.5"))
_SHARPE_ANNUALISE: int = int(os.getenv("SHARPE_ANNUALISE", "252"))


class OandaPaperClock:
    """
    Manages the 30-day OANDA paper trading run clock.

    Thread-safe for reads. Writes are idempotent — calling maybe_start()
    multiple times only writes the stamp once (on first call).
    """

    def __init__(self, stamp_path: Path | None = None) -> None:
        self._stamp_path = stamp_path or _STAMP_PATH
        self._stamp_path.parent.mkdir(parents=True, exist_ok=True)
        # Sharpe progress tracker — updated on every confirmed fill
        self._sharpe_tracker = self._init_sharpe_tracker()

    def _init_sharpe_tracker(self):
        """Initialise the SharpeProgressTracker, returning a stub on import failure."""
        try:
            from ml.train_advanced import SharpeProgressTracker

            return SharpeProgressTracker(
                target_n=_SHARPE_TARGET_N,
                target_sharpe=_SHARPE_TARGET_SR,
                annualise=_SHARPE_ANNUALISE,
            )
        except Exception as exc:
            logger.warning(
                "OandaPaperClock: SharpeProgressTracker unavailable (%s); fill recording disabled",
                exc,
            )
            return None

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
                existing = json.loads(self._stamp_path.read_text(encoding="utf-8"))
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

        now = datetime.now(UTC)
        started_utc_str = started_utc_str or now.isoformat()

        # Parse to compute live_gate_opens
        try:
            started_dt = datetime.fromisoformat(started_utc_str)
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
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
            self._stamp_path.write_text(json.dumps(stamp, indent=2), encoding="utf-8")
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

    # ── Fill recording ────────────────────────────────────────────────────────

    def record_fill(
        self,
        trade_return: float,
        symbol: str = "UNKNOWN",
    ) -> dict[str, Any]:
        """
        Record a confirmed fill's fractional P&L and update the Sharpe tracker.

        Called by the execution layer on every closed paper trade.  Updates
        the rolling Sharpe ratio and publishes three Prometheus gauges:
          hopefx_sharpe_n_trades
          hopefx_sharpe_ratio
          hopefx_sharpe_gate_passed

        Parameters
        ----------
        trade_return : Fractional P&L (e.g. 0.012 = +1.2%).
        symbol       : Instrument symbol for log context.

        Returns
        -------
        The SharpeProgressTracker status dict, or an empty dict if the
        tracker is unavailable.
        """
        if self._sharpe_tracker is None:
            return {}

        status = self._sharpe_tracker.update(float(trade_return))

        # ── Prometheus ────────────────────────────────────────────────────────
        try:
            from core.metrics import SHARPE_GATE_PASSED, SHARPE_N_TRADES, SHARPE_RATIO

            SHARPE_N_TRADES.set(status["n_trades"])
            SHARPE_RATIO.set(status["sharpe"])
            SHARPE_GATE_PASSED.set(1.0 if status["gate_passed"] else 0.0)
        except Exception as exc:
            logger.debug("OandaPaperClock: Prometheus update failed: %s", exc)

        # ── Structured log ────────────────────────────────────────────────────
        logger.info(
            "OandaPaperClock fill: symbol=%s return=%.4f n=%d sharpe=%.3f se=%.3f gate=%s pct=%.1f%%",
            symbol,
            trade_return,
            status["n_trades"],
            status["sharpe"],
            status["sharpe_se"],
            status["gate_passed"],
            status["pct_to_gate"],
        )

        return status

    def sharpe_status(self) -> dict[str, Any]:
        """
        Return the current SharpeProgressTracker snapshot.

        Returns an empty dict if the tracker was not initialised.
        """
        if self._sharpe_tracker is None:
            return {
                "available": False,
                "note": "SharpeProgressTracker not initialised",
            }
        snap = self._sharpe_tracker.status()
        snap["available"] = True
        return snap

    # ── Gate sync ─────────────────────────────────────────────────────────────

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

    def status(self) -> dict[str, Any]:
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
                    "Clock not started. Set OANDA_API_KEY (or BROKER_OANDA_TOKEN) and restart with BROKER_TYPE=oanda."
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
                "sharpe_progress": self.sharpe_status(),
            }

        try:
            data = json.loads(self._stamp_path.read_text(encoding="utf-8"))

            # PENDING placeholder — clock is pre-seeded but no real connection yet
            if data.get("requires_real_account", False):
                started_str = data.get("started_utc", "")
                started_dt = datetime.fromisoformat(started_str)
                if started_dt.tzinfo is None:
                    started_dt = started_dt.replace(tzinfo=UTC)
                now = datetime.now(UTC)
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
                    "sharpe_progress": self.sharpe_status(),
                }

            started_str = data.get("started_utc", "")
            started_dt = datetime.fromisoformat(started_str)
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=UTC)
            now = datetime.now(UTC)
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
                "sharpe_progress": self.sharpe_status(),
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
                "sharpe_progress": self.sharpe_status(),
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

_clock: OandaPaperClock | None = None


def get_clock() -> OandaPaperClock:
    """Return the module-level OandaPaperClock singleton."""
    global _clock
    if _clock is None:
        _clock = OandaPaperClock()
    return _clock


# ── Startup validation ────────────────────────────────────────────────────────


def validate_oanda_account_at_startup() -> dict[str, Any]:
    """
    Validate OANDA account state at server startup.

    Called from startup_factories.init_broker() after the broker is
    initialised.  Logs a prominent warning when:

    1. The stamp file has ``requires_real_account: true`` (PENDING) — meaning
       the 30-day clock is running but no real fills are being collected.
    2. BROKER_TYPE=oanda but credentials are missing — the clock will never
       start.
    3. The stamp file is missing entirely — clock has not been seeded.

    Returns a dict with keys:
      account_verified  bool   — True only when a real account_id is stamped
      account_id        str    — masked account_id or "PENDING"
      elapsed_days      float  — days elapsed since clock start
      remaining_days    float  — days until live gate opens
      warnings          list   — human-readable warning strings
    """
    clock = get_clock()
    status = clock.status()
    warnings: ClassVar[list] = []

    account_id = status.get("account_id") or "PENDING"
    pending = status.get("pending_real_account", False) or account_id == "PENDING"
    broker_type = os.getenv("BROKER_TYPE", "paper").lower()
    has_token = bool(os.getenv("BROKER_OANDA_TOKEN", "") or os.getenv("OANDA_API_KEY", ""))
    has_account = bool(os.getenv("BROKER_OANDA_ACCOUNT", "") or os.getenv("OANDA_ACCOUNT_ID", ""))

    # Validate account ID format — reject placeholder values like ACC123
    # that look like they might be real but are not OANDA v20 format.
    raw_account_env = os.getenv("BROKER_OANDA_ACCOUNT", "") or os.getenv("OANDA_ACCOUNT_ID", "")
    if raw_account_env and raw_account_env not in ("PENDING", ""):
        try:
            from brokers.oanda import validate_oanda_account_id

            if not validate_oanda_account_id(raw_account_env):
                warnings.append(
                    f"OANDA account ID {raw_account_env!r} does not match the required format "
                    f"101-XXX-XXXXXXXX-XXX. This is not a valid OANDA v20 account ID. "
                    f"Obtain your real account ID from the OANDA portal."
                )
                logger.warning(
                    "⚠ OANDA account ID %r is not a valid v20 format (101-XXX-XXXXXXXX-XXX).",
                    raw_account_env[:12],
                )
        except Exception as _exc:
            logger.debug("Account ID format check skipped: %s", _exc)

    if pending:
        elapsed = status.get("elapsed_days", 0.0)
        remaining = status.get("remaining_days", float(_TARGET_DAYS))
        warnings.append(
            f"OANDA paper account is PENDING — no real fills are being collected. "
            f"Clock has been running {elapsed:.1f} days ({remaining:.1f} days remain). "
            f"Set BROKER_TYPE=oanda, BROKER_OANDA_TOKEN, and BROKER_OANDA_ACCOUNT "
            f"then restart to connect a real practice account."
        )
        logger.warning(
            "⚠ OANDA account PENDING — %s days elapsed, %s days remain. No real fills until credentials are set.",
            round(elapsed, 1),
            round(remaining, 1),
        )

    if broker_type == "oanda" and not has_token:
        warnings.append(
            "BROKER_TYPE=oanda but BROKER_OANDA_TOKEN is not set. The broker will fall back to paper simulation."
        )
        logger.warning("⚠ BROKER_TYPE=oanda but BROKER_OANDA_TOKEN not set — falling back to paper simulation.")

    if broker_type == "oanda" and has_token and not has_account:
        warnings.append(
            "BROKER_OANDA_TOKEN is set but BROKER_OANDA_ACCOUNT is missing. "
            "Set BROKER_OANDA_ACCOUNT to your practice account ID."
        )
        logger.warning("⚠ BROKER_OANDA_TOKEN set but BROKER_OANDA_ACCOUNT missing.")

    if not status.get("started", False):
        warnings.append(
            "OANDA paper trading clock has not started. Connect OANDA credentials to begin the 30-day paper run."
        )

    result = {
        "account_verified": not pending and status.get("started", False),
        "account_id": account_id,
        "elapsed_days": status.get("elapsed_days", 0.0),
        "remaining_days": status.get("remaining_days", float(_TARGET_DAYS)),
        "live_gate_opens": status.get("live_gate_opens"),
        "warnings": warnings,
        "broker_type": broker_type,
        "credentials_present": has_token and has_account,
    }

    if not warnings:
        logger.info(
            "OANDA account verified: %s (%s) — %.1f days elapsed",
            account_id,
            status.get("environment", "practice"),
            status.get("elapsed_days", 0.0),
        )

    return result
