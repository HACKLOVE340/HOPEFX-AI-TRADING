# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/performance_monitor.py
=========================
Live performance monitor with automatic model rollback.

After a new model is promoted to production, this monitor compares its
rolling P&L against the previous version over a configurable window.
If the new model underperforms by more than ROLLBACK_THRESHOLD_PCT, it
is automatically reverted to the previous version and an alert is fired.

Architecture
------------
- ModelPerformanceMonitor.record_trade()  — called by the trade executor
  after every fill to record the P&L contribution of the active model.
- ModelPerformanceMonitor.run()           — async background loop that
  evaluates the rolling window every CHECK_INTERVAL_SECONDS.
- Rollback is performed via ModelRegistry.promote(previous_version_name),
  which atomically updates the current.pkl symlink.

Configuration (env vars)
------------------------
ML_MONITOR_WINDOW_TRADES   — rolling window size in trades (default: 100)
ML_MONITOR_CHECK_INTERVAL  — evaluation interval in seconds (default: 300)
ML_MONITOR_ROLLBACK_THRESH — P&L underperformance threshold 0–1 (default: 0.20)
ML_MONITOR_MIN_TRADES      — minimum trades before evaluation (default: 20)

Usage
-----
    from ml.performance_monitor import get_monitor

    monitor = get_monitor()
    _t = asyncio.create_task(monitor.run())
    _t.add_done_callback(lambda _: None)

    # In trade executor, after every fill:
    monitor.record_trade(pnl=42.5, model_version="advanced_oos_v4")
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc

logger = logging.getLogger(__name__)

WINDOW_TRADES: int = int(os.getenv("ML_MONITOR_WINDOW_TRADES", "100"))
CHECK_INTERVAL: float = float(os.getenv("ML_MONITOR_CHECK_INTERVAL", "300"))
ROLLBACK_THRESHOLD: float = float(os.getenv("ML_MONITOR_ROLLBACK_THRESH", "0.20"))
MIN_TRADES: int = int(os.getenv("ML_MONITOR_MIN_TRADES", "20"))


class _VersionWindow:
    """Rolling P&L window for a single model version."""

    def __init__(self, name: str, maxlen: int) -> None:
        self.name = name
        self.pnl_window: collections.deque[float] = collections.deque(maxlen=maxlen)
        self.total_trades: int = 0
        self.promoted_at: datetime = datetime.now(UTC)

    def record(self, pnl: float) -> None:
        self.pnl_window.append(pnl)
        self.total_trades += 1

    @property
    def mean_pnl(self) -> float | None:
        if not self.pnl_window:
            return None
        return sum(self.pnl_window) / len(self.pnl_window)

    @property
    def trade_count(self) -> int:
        return len(self.pnl_window)


class ModelPerformanceMonitor:
    """
    Monitors live P&L per model version and auto-reverts on degradation.

    Thread-safety: record_trade() is called from the trade executor (sync or
    async context).  The deque is thread-safe for single-producer use.
    The evaluation loop runs in a single asyncio task.
    """

    def __init__(self) -> None:
        self._windows: dict[str, _VersionWindow] = {}
        self._current_version: str | None = None
        self._previous_version: str | None = None
        self._running = False
        self._rollback_count: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def on_model_promoted(self, new_version: str, previous_version: str | None) -> None:
        """
        Notify the monitor that a new model version was promoted.

        Call this immediately after ModelRegistry.promote() succeeds.
        Resets the rolling window for the new version.
        """
        logger.info(
            "ModelPerformanceMonitor: tracking new version '%s' (previous: '%s')",
            new_version,
            previous_version,
        )
        self._previous_version = previous_version
        self._current_version = new_version
        if new_version not in self._windows:
            self._windows[new_version] = _VersionWindow(new_version, WINDOW_TRADES)

    def record_trade(self, pnl: float, model_version: str | None = None) -> None:
        """
        Record a trade P&L for the given model version.

        Parameters
        ----------
        pnl           : Realised P&L of the trade (positive = profit).
        model_version : Version name that generated the signal.
                        Defaults to the current active version.
        """
        version = model_version or self._current_version
        if version is None:
            return
        if version not in self._windows:
            self._windows[version] = _VersionWindow(version, WINDOW_TRADES)
        self._windows[version].record(pnl)

    def get_stats(self) -> dict[str, dict]:
        """Return current rolling stats for all tracked versions."""
        return {
            name: {
                "mean_pnl": w.mean_pnl,
                "trade_count": w.trade_count,
                "total_trades": w.total_trades,
                "promoted_at": w.promoted_at.isoformat(),
            }
            for name, w in self._windows.items()
        }

    def status(self) -> dict:
        """Return a summary status dict (alias for get_stats with extra metadata)."""
        return {
            "current_version": self._current_version,
            "previous_version": self._previous_version,
            "running": self._running,
            "window_trades": WINDOW_TRADES,
            "rollback_threshold": ROLLBACK_THRESHOLD,
            "versions": self.get_stats(),
        }

    # ── Background loop ───────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the evaluation loop until cancelled."""
        self._running = True
        logger.info(
            "ModelPerformanceMonitor started (window=%d trades, interval=%.0fs, threshold=%.0f%%)",
            WINDOW_TRADES,
            CHECK_INTERVAL,
            ROLLBACK_THRESHOLD * 100,
        )
        while self._running:
            try:
                await self._evaluate()
            except asyncio.CancelledError:
                logger.info("ModelPerformanceMonitor stopped")
                return
            except Exception as exc:
                logger.warning("ModelPerformanceMonitor evaluation error: %s", exc)
            await asyncio.sleep(CHECK_INTERVAL)

    def stop(self) -> None:
        self._running = False

    async def _evaluate(self) -> None:
        """Compare current vs previous version; rollback if degraded."""
        current = self._current_version
        previous = self._previous_version

        if not current or not previous:
            return  # nothing to compare yet

        cur_win = self._windows.get(current)
        prev_win = self._windows.get(previous)

        if cur_win is None or cur_win.trade_count < MIN_TRADES:
            logger.debug(
                "ModelPerformanceMonitor: skipping evaluation — current version '%s' has only %d/%d trades",
                current,
                cur_win.trade_count if cur_win else 0,
                MIN_TRADES,
            )
            return

        cur_mean = cur_win.mean_pnl
        prev_mean = prev_win.mean_pnl if prev_win else None

        if cur_mean is None:
            return

        logger.info(
            "ModelPerformanceMonitor: current='%s' mean_pnl=%.4f  previous='%s' mean_pnl=%s  trades=%d",
            current,
            cur_mean,
            previous,
            f"{prev_mean:.4f}" if prev_mean is not None else "N/A",
            cur_win.trade_count,
        )

        should_rollback, reason = self._should_rollback(cur_mean, prev_mean)
        if should_rollback:
            await self._rollback(current, previous, reason)

    def _should_rollback(self, cur_mean: float, prev_mean: float | None) -> tuple[bool, str]:
        """
        Determine whether to roll back the current model.

        Rollback conditions:
        1. Current mean P&L is negative AND worse than previous by > threshold.
        2. Current mean P&L is negative AND no previous version to compare
           (absolute loss guard: mean < -ROLLBACK_THRESHOLD * some baseline).
        """
        # Condition 1: compare against previous version
        if prev_mean is not None:
            if prev_mean > 0 and cur_mean < prev_mean * (1 - ROLLBACK_THRESHOLD):
                return True, (
                    f"current mean_pnl={cur_mean:.4f} is {ROLLBACK_THRESHOLD * 100:.0f}%+ "
                    f"below previous mean_pnl={prev_mean:.4f}"
                )
            if prev_mean <= 0 and cur_mean < prev_mean - abs(prev_mean) * ROLLBACK_THRESHOLD:
                return True, (f"current mean_pnl={cur_mean:.4f} degraded vs previous mean_pnl={prev_mean:.4f}")

        # Condition 2: absolute loss guard (no previous baseline)
        if prev_mean is None and cur_mean < -ROLLBACK_THRESHOLD:
            return True, (f"current mean_pnl={cur_mean:.4f} is below absolute loss threshold -{ROLLBACK_THRESHOLD:.2f}")

        return False, ""

    async def _rollback(self, current: str, previous: str, reason: str) -> None:
        """Revert to the previous model version."""
        self._rollback_count += 1
        logger.critical(
            "ModelPerformanceMonitor: AUTO-ROLLBACK #%d — reverting '%s' → '%s'. Reason: %s",
            self._rollback_count,
            current,
            previous,
            reason,
        )

        try:
            from ml.model_registry import get_registry

            registry = get_registry()
            manifest = registry._load()

            # Re-stage the previous version so it can be promoted again
            prev_entry = manifest["versions"].get(previous)
            if prev_entry and prev_entry.get("state") == "retired":
                prev_entry["state"] = "staging"
                registry._save(manifest)

            registry.promote(previous)
            self._current_version = previous
            self._previous_version = None  # prevent rollback loop

            logger.info(
                "ModelPerformanceMonitor: rollback complete — '%s' is now active",
                previous,
            )
        except Exception as exc:
            logger.error(
                "ModelPerformanceMonitor: rollback FAILED for '%s' → '%s': %s",
                current,
                previous,
                exc,
            )

        # Fire alert
        self._fire_rollback_alert(current, previous, reason)

    def _fire_rollback_alert(self, current: str, previous: str, reason: str) -> None:
        """Send a rollback alert via the outbox and alert engine."""
        try:
            from core.outbox import write_outbox_event_standalone

            write_outbox_event_standalone(
                event_type="ML_ROLLBACK",
                channel="hopefx:ml",
                payload={
                    "type": "ml_rollback",
                    "reverted_from": current,
                    "reverted_to": previous,
                    "reason": reason,
                    "rollback_count": self._rollback_count,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            logger.warning("ML rollback outbox write failed: %s", exc)

        try:
            from app import app_state

            ae = getattr(app_state, "alert_engine", None)
            if ae and hasattr(ae, "send_alert"):
                ae.send_alert(
                    title="ML Model Auto-Rollback",
                    message=(f"Model '{current}' was automatically reverted to '{previous}'.\nReason: {reason}"),
                    severity="critical",
                )
        except Exception as exc:
            logger.warning("ML rollback alert failed: %s", exc)


# ── Module-level singleton ────────────────────────────────────────────────────

_monitor: ModelPerformanceMonitor | None = None


def get_monitor() -> ModelPerformanceMonitor:
    """Return the module-level ModelPerformanceMonitor singleton."""
    global _monitor
    if _monitor is None:
        _monitor = ModelPerformanceMonitor()
    return _monitor
