# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
heartbeat_monitor.py
HOPEFX AI Trading – Component Heartbeat Monitor

Tracks liveness of system components by expecting periodic "heartbeat" pings.
When a component misses its deadline the monitor:
  1. Logs a warning / critical message
  2. Fires registered alert callbacks
  3. Optionally triggers the KillSwitch for critical components

Usage
-----
    from heartbeat_monitor import HeartbeatMonitor

    monitor = HeartbeatMonitor(kill_switch=ks)
    monitor.register("price_feed",    timeout_sec=10, critical=True)
    monitor.register("risk_engine",   timeout_sec=30, critical=True)
    monitor.register("ml_inference",  timeout_sec=60, critical=False)

    await monitor.start()

    # In your component's loop:
    monitor.beat("price_feed")

    # Graceful shutdown:
    await monitor.stop()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from collections.abc import Callable
import contextlib

logger = logging.getLogger(__name__)


@dataclass
class ComponentStatus:
    """Runtime liveness record for one registered component."""

    name: str
    timeout_sec: float
    critical: bool
    last_beat: datetime = field(default_factory=lambda: datetime.now(UTC))
    missed_beats: int = 0
    alive: bool = True

    # ------------------------------------------------------------------ #
    def update(self) -> None:
        """Record a fresh heartbeat."""
        self.last_beat = datetime.now(UTC)
        self.missed_beats = 0
        self.alive = True

    def seconds_since_last_beat(self) -> float:
        return (datetime.now(UTC) - self.last_beat).total_seconds()

    def is_overdue(self) -> bool:
        return self.seconds_since_last_beat() > self.timeout_sec

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "timeout_sec": self.timeout_sec,
            "critical": self.critical,
            "last_beat": self.last_beat.isoformat(),
            "seconds_since_last_beat": round(self.seconds_since_last_beat(), 2),
            "missed_beats": self.missed_beats,
            "alive": self.alive,
        }


class HeartbeatMonitor:
    """
    Monitors liveness of named system components via periodic heartbeat pings.

    Args:
        check_interval_sec: How often the monitor checks all registered
                            components for missed heartbeats.
        kill_switch: Optional :class:`KillSwitch` instance.  When provided,
                     the monitor calls ``kill_switch.activate()`` whenever a
                     *critical* component goes silent.
    """

    def __init__(
        self,
        check_interval_sec: float = 5.0,
        kill_switch=None,
    ) -> None:
        self._check_interval = check_interval_sec
        self._kill_switch = kill_switch
        self._components: dict[str, ComponentStatus] = {}
        self._alert_callbacks: list[Callable[[ComponentStatus], None]] = []
        self._running: bool = False
        self._task: asyncio.Task | None = None

    # ---------------------------------------------------------------------- #
    # Registration                                                             #
    # ---------------------------------------------------------------------- #

    def register(
        self,
        name: str,
        timeout_sec: float = 30.0,
        critical: bool = False,
    ) -> None:
        """
        Register a component to be monitored.

        Args:
            name: Unique component identifier (e.g. ``"price_feed"``).
            timeout_sec: Maximum silence before the component is considered
                         stale.
            critical: When True, a missed heartbeat also triggers the
                      KillSwitch (if one is configured).
        """
        self._components[name] = ComponentStatus(
            name=name,
            timeout_sec=timeout_sec,
            critical=critical,
        )
        logger.info(
            "HeartbeatMonitor registered '%s' (timeout=%.0fs, critical=%s)",
            name,
            timeout_sec,
            critical,
        )

    def register_alert_callback(self, fn: Callable[[ComponentStatus], None]) -> None:
        """
        Register a callback invoked whenever a component is detected as stale.

        Args:
            fn: Callable that receives the stale :class:`ComponentStatus`.
        """
        self._alert_callbacks.append(fn)

    # ---------------------------------------------------------------------- #
    # Runtime API                                                              #
    # ---------------------------------------------------------------------- #

    def beat(self, name: str) -> None:
        """
        Record a live heartbeat for *name*.

        Call this from inside each monitored component's main loop to prove
        the component is running.  Missing several consecutive calls
        (determined by *timeout_sec* at registration time) marks the
        component as stale.

        Args:
            name: Component name as passed to :meth:`register`.
        """
        if name not in self._components:
            logger.debug("beat() called for unregistered component '%s'", name)
            return
        self._components[name].update()

    def status(self) -> list[dict]:
        """Return a JSON-serialisable snapshot of all component statuses."""
        return [s.to_dict() for s in self._components.values()]

    def all_alive(self) -> bool:
        """Return True only when every registered component is alive."""
        return all(not s.is_overdue() for s in self._components.values())

    def critical_alive(self) -> bool:
        """Return True only when every *critical* component is alive."""
        return all(not s.is_overdue() for s in self._components.values() if s.critical)

    # ---------------------------------------------------------------------- #
    # Lifecycle                                                                #
    # ---------------------------------------------------------------------- #

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop(), name="heartbeat_monitor")
        logger.info(
            "HeartbeatMonitor started (check interval: %.1fs, components: %d)",
            self._check_interval,
            len(self._components),
        )

    async def stop(self) -> None:
        """Stop the background monitoring loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("HeartbeatMonitor stopped")

    # ---------------------------------------------------------------------- #
    # Internal                                                                 #
    # ---------------------------------------------------------------------- #

    async def _monitor_loop(self) -> None:
        """Periodically inspect all registered components."""
        while self._running:
            try:
                self._check_all()
            except Exception as exc:
                logger.error("HeartbeatMonitor check error: %s", exc)
            await asyncio.sleep(self._check_interval)

    def _check_all(self) -> None:
        """Evaluate every component and raise alerts as needed."""
        for status in self._components.values():
            if status.is_overdue():
                status.missed_beats += 1
                status.alive = False
                elapsed = status.seconds_since_last_beat()

                if status.critical:
                    logger.critical(
                        "🚨 CRITICAL component '%s' missed heartbeat (%.0fs since last beat, missed: %d)",
                        status.name,
                        elapsed,
                        status.missed_beats,
                    )
                    print(f"\n🚨 HEARTBEAT TIMEOUT: critical component '{status.name}' silent for {elapsed:.0f}s")
                else:
                    logger.warning(
                        "⚠️  Component '%s' missed heartbeat (%.0fs since last beat, missed: %d)",
                        status.name,
                        elapsed,
                        status.missed_beats,
                    )

                # Fire user callbacks
                for cb in self._alert_callbacks:
                    try:
                        cb(status)
                    except Exception as exc:
                        logger.error("Alert callback error: %s", exc)

                # Trigger kill switch for critical components (only once per
                # outage, i.e. on the first missed beat)
                if (
                    status.critical
                    and status.missed_beats == 1
                    and self._kill_switch is not None
                    and not self._kill_switch.is_active()
                ):
                    self._kill_switch.activate(f"critical component '{status.name}' heartbeat timeout")
            # Component recovered
            elif not status.alive:
                status.alive = True
                status.missed_beats = 0
                logger.info("🟢 Component '%s' heartbeat restored", status.name)
