# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
ml/sharpe_circuit_breaker.py
============================
Rolling live Sharpe circuit breaker — gates a model out of production when
its annualised Sharpe drops below a threshold for N consecutive evaluation
windows during a live session.

Problem solved
--------------
model_registry gates models at training time (OOS accuracy, Sharpe).
Nothing watches live Sharpe in real-time and pulls the model mid-session
if it degrades. This module fills that gap.

Architecture
------------
- SharpeCircuitBreaker.record_trade(pnl, model_version)
    Called by the trade executor after every fill.

- SharpeCircuitBreaker.is_open(model_version) -> bool
    Returns True when the circuit is open (model is gated out).
    The execution engine must check this before routing a signal.

- SharpeCircuitBreaker.run()
    Async background loop that evaluates rolling Sharpe every
    SHARPE_CB_EVAL_INTERVAL_S seconds.

Circuit-open conditions (all must hold for N consecutive windows):
  1. Rolling Sharpe < SHARPE_CB_MIN_SHARPE
  2. At least SHARPE_CB_MIN_TRADES trades in the window

Circuit-reset conditions:
  - Manual reset via reset(model_version)
  - Auto-reset after SHARPE_CB_RESET_AFTER_S seconds (configurable)
  - New model version promoted (previous version circuit is cleared)

Configuration (env vars)
------------------------
SHARPE_CB_WINDOW_TRADES    — rolling window size in trades (default: 50)
SHARPE_CB_MIN_SHARPE       — Sharpe threshold below which circuit trips (default: 0.0)
SHARPE_CB_CONSECUTIVE      — consecutive bad windows before circuit opens (default: 3)
SHARPE_CB_EVAL_INTERVAL_S  — evaluation interval in seconds (default: 60)
SHARPE_CB_MIN_TRADES       — minimum trades before evaluation (default: 20)
SHARPE_CB_RESET_AFTER_S    — auto-reset after N seconds (0 = never, default: 3600)
SHARPE_CB_ANNUALISE_FACTOR — sqrt(trades_per_year) for annualisation (default: sqrt(252))

Usage
-----
    from ml.sharpe_circuit_breaker import get_sharpe_cb

    cb = get_sharpe_cb()
    _t = asyncio.create_task(cb.run())
    _t.add_done_callback(lambda _: None)

    # In trade executor, after every fill:
    cb.record_trade(pnl=42.5, model_version="advanced_oos_v4")

    # In signal router, before placing an order:
    if cb.is_open("advanced_oos_v4"):
        logger.warning("Model gated by Sharpe circuit breaker — skipping signal")

Return
"""

from __future__ import annotations

import asyncio
import collections
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
WINDOW_TRADES: int = int(os.getenv("SHARPE_CB_WINDOW_TRADES", "50"))
MIN_SHARPE: float = float(os.getenv("SHARPE_CB_MIN_SHARPE", "0.0"))
CONSECUTIVE_WINDOWS: int = int(os.getenv("SHARPE_CB_CONSECUTIVE", "3"))
EVAL_INTERVAL_S: float = float(os.getenv("SHARPE_CB_EVAL_INTERVAL_S", "60"))
MIN_TRADES: int = int(os.getenv("SHARPE_CB_MIN_TRADES", "20"))
RESET_AFTER_S: float = float(os.getenv("SHARPE_CB_RESET_AFTER_S", "3600"))
# Annualisation: sqrt(252) for daily, sqrt(252*24) for hourly, etc.
ANNUALISE_FACTOR: float = float(os.getenv("SHARPE_CB_ANNUALISE_FACTOR", str(math.sqrt(252))))


@dataclass
class CircuitState:
    """Per-model circuit breaker state."""

    model_version: str
    pnl_window: collections.deque[float] = field(default_factory=lambda: collections.deque(maxlen=WINDOW_TRADES))
    total_trades: int = 0
    consecutive_bad_windows: int = 0
    is_open: bool = False
    opened_at: float | None = None  # monotonic time
    last_sharpe: float | None = None
    last_evaluated_at: datetime | None = None
    trip_reason: str = ""
    sharpe_history: list[tuple[datetime, float]] = field(default_factory=list)

    def record(self, pnl: float) -> None:
        self.pnl_window.append(pnl)
        self.total_trades += 1

    def rolling_sharpe(self) -> float | None:
        """
        Compute annualised Sharpe from the rolling P&L window.

        Returns None if fewer than MIN_TRADES trades are in the window.
        Uses the standard trade-level Sharpe: mean(pnl) / std(pnl) × annualise_factor.

        Zero-std case: if all trades have identical P&L (std == 0), return a
        large positive value when mean > 0 (perfect win streak) or a large
        negative value when mean < 0 (perfect loss streak). This ensures a
        consistent all-loss window correctly trips the circuit breaker.
        """
        if len(self.pnl_window) < MIN_TRADES:
            return None
        arr = np.array(self.pnl_window)
        mean = arr.mean()
        std = arr.std()
        if std == 0:
            # All trades identical — sign of mean determines direction
            if mean > 0:
                return float(ANNUALISE_FACTOR * 1e6)  # perfect wins
            if mean < 0:
                return float(-ANNUALISE_FACTOR * 1e6)  # perfect losses
            return 0.0
        return float(mean / std * ANNUALISE_FACTOR)


class SharpeCircuitBreaker:
    """
    Rolling live Sharpe circuit breaker for ML model gating.

    When a model's rolling Sharpe drops below MIN_SHARPE for
    CONSECUTIVE_WINDOWS consecutive evaluation windows, the circuit opens
    and the model is gated out of production until manually reset or
    auto-reset after RESET_AFTER_S seconds.
    """

    def __init__(self) -> None:
        self._states: dict[str, CircuitState] = {}
        self._running: bool = False
        self._lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def record_trade(self, pnl: float, model_version: str) -> None:
        """
        Record a trade P&L for the given model version.

        Thread-safe for single-producer use (deque append is atomic in CPython).
        """
        state = self._get_or_create(model_version)
        state.record(pnl)

    def is_open(self, model_version: str) -> bool:
        """
        Return True when the circuit is open (model is gated out).

        Also checks auto-reset: if RESET_AFTER_S > 0 and the circuit has
        been open for longer than RESET_AFTER_S, it is automatically closed.
        """
        state = self._states.get(model_version)
        if state is None or not state.is_open:
            return False

        # Auto-reset check
        if RESET_AFTER_S > 0 and state.opened_at is not None:
            elapsed = time.monotonic() - state.opened_at
            if elapsed > RESET_AFTER_S:
                logger.info(
                    "SharpeCircuitBreaker: auto-reset for '%s' after %.0fs",
                    model_version,
                    elapsed,
                )
                state.is_open = False
                state.opened_at = None
                state.consecutive_bad_windows = 0
                state.trip_reason = ""
                return False

        return True

    def reset(self, model_version: str) -> None:
        """Manually reset the circuit breaker for a model version."""
        state = self._states.get(model_version)
        if state is not None:
            state.is_open = False
            state.opened_at = None
            state.consecutive_bad_windows = 0
            state.trip_reason = ""
            logger.info("SharpeCircuitBreaker: manually reset for '%s'", model_version)

    def get_status(self) -> dict[str, dict]:
        """Return current state for all tracked model versions."""
        return {
            name: {
                "is_open": s.is_open,
                "last_sharpe": s.last_sharpe,
                "consecutive_bad_windows": s.consecutive_bad_windows,
                "total_trades": s.total_trades,
                "window_trades": len(s.pnl_window),
                "trip_reason": s.trip_reason,
                "opened_at": datetime.fromtimestamp(s.opened_at, tz=UTC).isoformat() if s.opened_at else None,
                "last_evaluated_at": s.last_evaluated_at.isoformat() if s.last_evaluated_at else None,
                "sharpe_history": [
                    {"ts": ts.isoformat(), "sharpe": sh}
                    for ts, sh in s.sharpe_history[-20:]  # last 20 evaluations
                ],
            }
            for name, s in self._states.items()
        }

    # ── Background loop ───────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the evaluation loop until cancelled."""
        self._running = True
        logger.info(
            "SharpeCircuitBreaker started (window=%d trades, min_sharpe=%.2f, consecutive=%d, interval=%.0fs)",
            WINDOW_TRADES,
            MIN_SHARPE,
            CONSECUTIVE_WINDOWS,
            EVAL_INTERVAL_S,
        )
        while self._running:
            try:
                await self._evaluate_all()
            except asyncio.CancelledError:
                logger.info("SharpeCircuitBreaker stopped")
                return
            except Exception as exc:
                logger.warning("SharpeCircuitBreaker evaluation error: %s", exc)
            await asyncio.sleep(EVAL_INTERVAL_S)

    def stop(self) -> None:
        self._running = False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_or_create(self, model_version: str) -> CircuitState:
        if model_version not in self._states:
            self._states[model_version] = CircuitState(model_version=model_version)
        return self._states[model_version]

    async def _evaluate_all(self) -> None:
        """Evaluate all tracked model versions."""
        for _version, state in list(self._states.items()):
            await self._evaluate_one(state)

    async def _evaluate_one(self, state: CircuitState) -> None:
        """Evaluate a single model version and trip/reset the circuit as needed."""
        sharpe = state.rolling_sharpe()
        now = datetime.now(UTC)
        state.last_evaluated_at = now

        if sharpe is None:
            logger.debug(
                "SharpeCircuitBreaker: '%s' — insufficient trades (%d/%d)",
                state.model_version,
                len(state.pnl_window),
                MIN_TRADES,
            )
            return

        state.last_sharpe = sharpe
        state.sharpe_history.append((now, sharpe))

        logger.info(
            "SharpeCircuitBreaker: '%s' rolling Sharpe=%.3f (threshold=%.2f, consecutive_bad=%d/%d, circuit=%s)",
            state.model_version,
            sharpe,
            MIN_SHARPE,
            state.consecutive_bad_windows,
            CONSECUTIVE_WINDOWS,
            "OPEN" if state.is_open else "closed",
        )

        if sharpe < MIN_SHARPE:
            state.consecutive_bad_windows += 1
            if not state.is_open and state.consecutive_bad_windows >= CONSECUTIVE_WINDOWS:
                await self._trip(state, sharpe)
        else:
            # Good window — reset consecutive counter (but don't close if already open)
            if state.consecutive_bad_windows > 0:
                logger.info(
                    "SharpeCircuitBreaker: '%s' Sharpe recovered to %.3f — resetting consecutive counter",
                    state.model_version,
                    sharpe,
                )
            state.consecutive_bad_windows = 0

    async def _trip(self, state: CircuitState, sharpe: float) -> None:
        """Open the circuit breaker for a model version."""
        state.is_open = True
        state.opened_at = time.monotonic()
        state.trip_reason = (
            f"Rolling Sharpe {sharpe:.3f} < threshold {MIN_SHARPE:.2f} "
            f"for {CONSECUTIVE_WINDOWS} consecutive windows "
            f"({len(state.pnl_window)} trades in window)"
        )

        logger.critical(
            "SharpeCircuitBreaker: CIRCUIT OPEN for '%s' — %s",
            state.model_version,
            state.trip_reason,
        )

        # Fire outbox event for cross-pod propagation
        self._fire_trip_event(state)

        # Attempt to retire the model in the registry
        await self._retire_model(state.model_version, state.trip_reason)

    def _fire_trip_event(self, state: CircuitState) -> None:
        """Write a circuit-trip event to the outbox."""
        try:
            from core.outbox import write_outbox_event_standalone

            write_outbox_event_standalone(
                event_type="SHARPE_CIRCUIT_OPEN",
                channel="hopefx:ml",
                payload={
                    "type": "sharpe_circuit_open",
                    "model_version": state.model_version,
                    "last_sharpe": state.last_sharpe,
                    "threshold": MIN_SHARPE,
                    "consecutive_bad_windows": state.consecutive_bad_windows,
                    "trip_reason": state.trip_reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            logger.warning("SharpeCircuitBreaker outbox write failed: %s", exc)

        # Also send alert
        try:
            from app import app_state

            ae = getattr(app_state, "alert_engine", None)
            if ae and hasattr(ae, "send_alert"):
                ae.send_alert(
                    title="Sharpe Circuit Breaker Tripped",
                    message=(f"Model '{state.model_version}' gated out of production.\nReason: {state.trip_reason}"),
                    severity="critical",
                )
        except Exception as exc:
            logger.debug("SharpeCircuitBreaker alert failed: %s", exc)

    async def _retire_model(self, model_version: str, reason: str) -> None:
        """Retire the model in the registry so it cannot be re-promoted without review."""
        try:
            from ml.model_registry import get_registry

            registry = get_registry()
            manifest = registry._load()
            entry = manifest["versions"].get(model_version)
            if entry and entry.get("state") == "production":
                entry["state"] = "retired"
                entry["retired_reason"] = reason
                entry["retired_at"] = datetime.now(UTC).isoformat()
                registry._save(manifest)
                logger.info(
                    "SharpeCircuitBreaker: model '%s' retired in registry",
                    model_version,
                )
        except Exception as exc:
            logger.warning(
                "SharpeCircuitBreaker: could not retire model '%s': %s",
                model_version,
                exc,
            )


# ── Module-level singleton ────────────────────────────────────────────────────

_sharpe_cb: SharpeCircuitBreaker | None = None


def get_sharpe_cb() -> SharpeCircuitBreaker:
    """Return the module-level SharpeCircuitBreaker singleton."""
    global _sharpe_cb
    if _sharpe_cb is None:
        _sharpe_cb = SharpeCircuitBreaker()
    return _sharpe_cb
