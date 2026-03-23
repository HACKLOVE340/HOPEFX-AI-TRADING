"""
kill_switch.py
HOPEFX AI Trading – System-Wide Kill Switch

Provides an instant, multi-trigger mechanism to halt all trading activity:
  • Programmatic activation via KillSwitch.activate()
  • File-based activation: place/remove `kill_switch.flag` next to this module
  • Event-bus integration: publishes/subscribes to KILL_SWITCH domain events
  • Environment variable override: HOPEFX_KILL_SWITCH=1

Usage
-----
    from kill_switch import KillSwitch

    ks = KillSwitch()
    await ks.start()                       # begin polling file flag
    ks.activate("daily drawdown exceeded") # immediate halt
    is_safe = ks.is_active()               # True when trading is halted
    await ks.stop()
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Default path for the manual file flag                                        #
# --------------------------------------------------------------------------- #
_DEFAULT_FLAG_FILE = Path(__file__).parent / "kill_switch.flag"


class KillSwitch:
    """
    System-wide kill switch that halts all trading activity immediately.

    Triggers (any one is sufficient to activate):
    1. ``activate(reason)`` called programmatically
    2. ``kill_switch.flag`` file exists on disk
    3. Environment variable ``HOPEFX_KILL_SWITCH=1``
    4. KILL_SWITCH event received from the event bus (optional integration)

    Args:
        flag_file: Path to the sentinel file monitored for manual activation.
        poll_interval_sec: How often (seconds) the file-flag is re-checked.
        event_bus: Optional event-bus instance.  When provided the kill switch
                   both *publishes* activation events and *subscribes* to
                   KILL_SWITCH events from other system components.
    """

    def __init__(
        self,
        flag_file: Optional[Path] = None,
        poll_interval_sec: float = 1.0,
        event_bus=None,
    ) -> None:
        self._flag_file: Path = flag_file or _DEFAULT_FLAG_FILE
        self._poll_interval: float = poll_interval_sec
        self._event_bus = event_bus

        self._active: bool = False
        self._reason: str = ""
        self._activated_at: Optional[datetime] = None

        self._callbacks: List[Callable[[str], None]] = []
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

        # Check env-var on construction so callers can inspect `is_active()`
        # before calling `start()`.
        if os.environ.get("HOPEFX_KILL_SWITCH", "0") == "1":
            self._activate_internal("HOPEFX_KILL_SWITCH env var is set")

    # ---------------------------------------------------------------------- #
    # Public API                                                               #
    # ---------------------------------------------------------------------- #

    def activate(self, reason: str = "manual activation") -> None:
        """Activate the kill switch immediately."""
        self._activate_internal(reason)

    def deactivate(self) -> None:
        """
        Deactivate the kill switch and allow trading to resume.

        Note: The file flag (if present) must also be removed, otherwise the
        background polling task will re-activate on the next poll cycle.
        """
        if not self._active:
            return
        self._active = False
        self._reason = ""
        self._activated_at = None
        logger.warning("🟢 Kill switch DEACTIVATED – trading may resume")

    def is_active(self) -> bool:
        """Return True when trading must be halted."""
        return self._active

    @property
    def reason(self) -> str:
        """Human-readable reason for the last activation."""
        return self._reason

    @property
    def activated_at(self) -> Optional[datetime]:
        """UTC timestamp of the last activation, or None if not active."""
        return self._activated_at

    def register_callback(self, fn: Callable[[str], None]) -> None:
        """
        Register a callback invoked on activation.

        Args:
            fn: A callable that accepts a single ``reason`` string argument.
                Called synchronously within the activation path.
        """
        self._callbacks.append(fn)

    async def start(self) -> None:
        """Start background polling for the file flag and env-var changes."""
        if self._running:
            return
        self._running = True

        # Wire up event-bus subscription
        if self._event_bus is not None:
            try:
                self._event_bus.subscribe("KILL_SWITCH", self.on_bus_event)
                logger.info("Kill switch subscribed to event bus KILL_SWITCH events")
            except Exception as exc:
                logger.warning("Could not subscribe to event bus: %s", exc)

        self._task = asyncio.create_task(self._poll_loop(), name="kill_switch_poll")
        logger.info(
            "Kill switch started (flag file: %s, poll interval: %.1fs)",
            self._flag_file,
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Stop background polling."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Kill switch polling stopped")

    def status(self) -> dict:
        """Return a JSON-serialisable status snapshot."""
        return {
            "active": self._active,
            "reason": self._reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
            "flag_file": str(self._flag_file),
            "flag_file_exists": self._flag_file.exists(),
        }

    # ---------------------------------------------------------------------- #
    # Internal helpers                                                         #
    # ---------------------------------------------------------------------- #

    def _activate_internal(self, reason: str) -> None:
        """Core activation logic (idempotent)."""
        if self._active:
            return  # already active – avoid duplicate log spam
        self._active = True
        self._reason = reason
        self._activated_at = datetime.now(timezone.utc)

        logger.critical(
            "🚨 KILL SWITCH ACTIVATED — reason: %s | time: %s",
            reason,
            self._activated_at.isoformat(),
        )
        print(f"\n🚨 KILL SWITCH ACTIVATED: {reason}")

        # Notify callbacks
        for cb in self._callbacks:
            try:
                cb(reason)
            except Exception as exc:
                logger.error("Kill switch callback error: %s", exc)

        # Publish to event bus (fire-and-forget)
        if self._event_bus is not None:
            self._publish_event(reason)

        # Write the flag file so that sibling processes can also detect it
        try:
            self._flag_file.write_text(
                f"activated_at={self._activated_at.isoformat()}\nreason={reason}\n"
            )
        except OSError as exc:
            logger.warning("Could not write kill switch flag file: %s", exc)

    def _publish_event(self, reason: str) -> None:
        """Schedule a KILL_SWITCH event publication on the running event loop."""
        try:
            from core.event_bus import DomainEvent  # noqa: PLC0415

            event = DomainEvent.create(
                "KILL_SWITCH",
                "kill_switch",
                {"reason": reason, "timestamp": datetime.now(timezone.utc).isoformat()},
                priority=0,
            )
            # publish() may be a coroutine; schedule it without blocking the
            # synchronous activation path.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._event_bus.publish(event))
            except RuntimeError:
                # No running loop (e.g. tests) – call only if synchronous
                import inspect as _inspect
                result = self._event_bus.publish(event)
                if _inspect.iscoroutine(result):
                    result.close()  # prevent "coroutine was never awaited" warning
        except Exception as exc:
            logger.warning("Could not publish kill-switch event: %s", exc)

    def set_event_bus(self, event_bus) -> None:
        """
        Attach an event-bus instance after construction.

        Subscribes the kill switch to incoming KILL_SWITCH events so that
        activation signals published by other components are honoured.

        Args:
            event_bus: Event bus instance (must expose ``subscribe`` and
                       ``publish`` methods).
        """
        self._event_bus = event_bus
        try:
            event_bus.subscribe("KILL_SWITCH", self.on_bus_event)
        except Exception as exc:
            logger.warning("Could not subscribe kill switch to event bus: %s", exc)

    def on_bus_event(self, event) -> None:
        """Handle incoming KILL_SWITCH events from the event bus (public API)."""
        try:
            data = event.decode() if hasattr(event, "decode") else {}
            reason = data.get("reason", "event bus signal")
        except Exception:
            reason = "event bus signal"
        self._activate_internal(f"[bus] {reason}")

    async def _poll_loop(self) -> None:
        """Background coroutine: check file flag and env-var on each tick."""
        while self._running:
            try:
                # File-flag check
                if self._flag_file.exists() and not self._active:
                    try:
                        content = self._flag_file.read_text()
                        reason = "flag file detected"
                        for line in content.splitlines():
                            if line.startswith("reason="):
                                reason = line.split("=", 1)[1].strip()
                                break
                    except OSError:
                        reason = "flag file detected"
                    self._activate_internal(f"[file] {reason}")

                # Env-var check (supports runtime injection)
                if os.environ.get("HOPEFX_KILL_SWITCH", "0") == "1" and not self._active:
                    self._activate_internal("[env] HOPEFX_KILL_SWITCH=1")

            except Exception as exc:
                logger.error("Kill switch poll error: %s", exc)

            await asyncio.sleep(self._poll_interval)
