# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
utils/fault_guard.py
====================
System-wide circuit breaker and heartbeat monitor.

Responsibilities
----------------
1. Circuit breaker per module: pause after 3 consecutive failures,
   auto-recover after 30 s, then allow one probe call.
2. Heartbeat monitor: each registered module must call heartbeat() within
   HEARTBEAT_TIMEOUT_S or it is marked unhealthy and a breach event fires.
3. Publishes breach events to hopefx:breach when a module trips or goes silent.
4. Exposes is_healthy(module) so callers can gate work behind a health check.

States (per module)
-------------------
  CLOSED    — normal; calls pass through
  OPEN      — tripped; calls rejected; auto-recover after RECOVER_S
  HALF_OPEN — one probe allowed; success → CLOSED, failure → OPEN

Usage
-----
    guard = FaultGuard()
    guard.register("market_ingest")

    # wrap a call
    async with guard.protect("market_ingest"):
        await do_work()

    # record heartbeat from inside a module
    guard.heartbeat("market_ingest")

    # run the background monitor
    await guard.run()   # runs until guard.stop() is called
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from enum import Enum, auto

from core.event_bus import bus

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
import os as _os

FAILURE_THRESHOLD: int = int(_os.environ.get("FAULT_FAILURE_THRESHOLD", "3"))
RECOVER_S: float = float(_os.environ.get("FAULT_RECOVER_S", "30"))
HEARTBEAT_TIMEOUT_S: float = float(_os.environ.get("FAULT_HEARTBEAT_TIMEOUT_S", "60"))
MONITOR_INTERVAL_S: float = float(_os.environ.get("FAULT_MONITOR_INTERVAL_S", "5"))


# ─────────────────────────────────────────────────────────────────────────────
# Circuit state
# ─────────────────────────────────────────────────────────────────────────────


class _State(Enum):
    CLOSED = auto()  # normal
    OPEN = auto()  # tripped — reject calls
    HALF_OPEN = auto()  # one probe allowed


@dataclass
class _ModuleState:
    """Per-module circuit-breaker + heartbeat state."""

    name: str
    state: _State = _State.CLOSED
    failures: int = 0
    last_failure_ts: float = 0.0  # monotonic
    last_heartbeat: float = field(default_factory=time.monotonic)
    probe_in_flight: bool = False
    total_trips: int = 0
    total_recoveries: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Context manager returned by protect()
# ─────────────────────────────────────────────────────────────────────────────


class _ProtectContext:
    """
    Async context manager that wraps a single call with circuit-breaker logic.

    On success: resets failure counter, closes circuit if HALF_OPEN.
    On failure: increments counter, trips circuit after FAILURE_THRESHOLD.
    """

    def __init__(self, guard: FaultGuard, module: str) -> None:
        self._guard = guard
        self._module = module

    async def __aenter__(self) -> _ProtectContext:
        ms = self._guard._modules.get(self._module)
        if ms is None:
            return self  # unregistered module — pass through

        if ms.state == _State.OPEN:
            elapsed = time.monotonic() - ms.last_failure_ts
            if elapsed >= RECOVER_S:
                # Transition to HALF_OPEN for one probe
                ms.state = _State.HALF_OPEN
                ms.probe_in_flight = True
                logger.info("FaultGuard [%s]: OPEN → HALF_OPEN (probe)", self._module)
            else:
                remaining = RECOVER_S - elapsed
                raise RuntimeError(f"FaultGuard [{self._module}]: circuit OPEN — recover in {remaining:.0f} s")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        ms = self._guard._modules.get(self._module)
        if ms is None:
            return False  # don't suppress

        if exc_type is None:
            # Success
            ms.failures = 0
            if ms.state == _State.HALF_OPEN:
                ms.state = _State.CLOSED
                ms.probe_in_flight = False
                ms.total_recoveries += 1
                logger.info("FaultGuard [%s]: HALF_OPEN → CLOSED (recovered)", self._module)
        else:
            # Failure
            ms.failures += 1
            ms.last_failure_ts = time.monotonic()

            if ms.state == _State.HALF_OPEN:
                # Probe failed — back to OPEN
                ms.state = _State.OPEN
                ms.probe_in_flight = False
                ms.total_trips += 1
                logger.error(
                    "FaultGuard [%s]: HALF_OPEN → OPEN (probe failed: %s)",
                    self._module,
                    exc_val,
                )
                _t = asyncio.create_task(self._guard._publish_breach(self._module, "probe_failed", str(exc_val)))
                _t.add_done_callback(lambda _: None)

            elif ms.failures >= FAILURE_THRESHOLD and ms.state == _State.CLOSED:
                ms.state = _State.OPEN
                ms.total_trips += 1
                logger.error(
                    "FaultGuard [%s]: CLOSED → OPEN after %d failures",
                    self._module,
                    ms.failures,
                )
                asyncio.create_task(
                    self._guard._publish_breach(
                        self._module,
                        "circuit_tripped",
                        f"{ms.failures} consecutive failures",
                    )
                )

        return False  # never suppress exceptions


# ─────────────────────────────────────────────────────────────────────────────
# FaultGuard
# ─────────────────────────────────────────────────────────────────────────────


class FaultGuard:
    """
    System-wide circuit breaker and heartbeat monitor.

    Register every module at startup, then wrap calls with protect() and
    call heartbeat() from inside each module's main loop.
    """

    def __init__(self) -> None:
        self._modules: dict[str, _ModuleState] = {}
        self._running: bool = False

    # ── registration ──────────────────────────────────────────────────────────

    def register(self, module: str) -> None:
        """Register a module for circuit-breaker and heartbeat monitoring."""
        if module not in self._modules:
            self._modules[module] = _ModuleState(name=module)
            logger.info("FaultGuard: registered module '%s'", module)

    # ── heartbeat ─────────────────────────────────────────────────────────────

    def heartbeat(self, module: str) -> None:
        """
        Record a heartbeat for a module.

        Call this from inside each module's main loop to signal liveness.
        """
        ms = self._modules.get(module)
        if ms:
            ms.last_heartbeat = time.monotonic()

    # ── protect ───────────────────────────────────────────────────────────────

    def protect(self, module: str) -> _ProtectContext:
        """
        Return an async context manager that wraps a call with circuit-breaker logic.

        Usage:
            async with guard.protect("market_ingest"):
                await do_work()
        """
        return _ProtectContext(self, module)

    # ── health check ──────────────────────────────────────────────────────────

    def is_healthy(self, module: str) -> bool:
        """Return True when the module's circuit is CLOSED or HALF_OPEN."""
        ms = self._modules.get(module)
        if ms is None:
            return True  # unregistered — assume healthy
        return ms.state != _State.OPEN

    def state_of(self, module: str) -> str:
        """Return the circuit state name for a module."""
        ms = self._modules.get(module)
        return ms.state.name if ms else "UNKNOWN"

    # ── background monitor ────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Background task: checks heartbeats every MONITOR_INTERVAL_S seconds.

        Publishes a breach event when a module's heartbeat goes silent for
        longer than HEARTBEAT_TIMEOUT_S.
        """
        self._running = True
        logger.info(
            "FaultGuard monitor started — heartbeat_timeout=%.0f s  interval=%.0f s",
            HEARTBEAT_TIMEOUT_S,
            MONITOR_INTERVAL_S,
        )
        while self._running:
            await asyncio.sleep(MONITOR_INTERVAL_S)
            await self._check_heartbeats()

    async def stop(self) -> None:
        self._running = False
        logger.info("FaultGuard monitor stopped.")

    async def _check_heartbeats(self) -> None:
        """Scan all registered modules for stale heartbeats."""
        now = time.monotonic()
        for name, ms in self._modules.items():
            age = now - ms.last_heartbeat
            if age > HEARTBEAT_TIMEOUT_S:
                logger.warning(
                    "FaultGuard [%s]: heartbeat silent for %.0f s (threshold %.0f s)",
                    name,
                    age,
                    HEARTBEAT_TIMEOUT_S,
                )
                await self._publish_breach(name, "heartbeat_timeout", f"No heartbeat for {age:.0f} s")

    # ── breach publisher ──────────────────────────────────────────────────────

    async def _publish_breach(self, module: str, reason: str, detail: str) -> None:
        """Publish a breach event to hopefx:breach."""
        try:
            await bus.publish_breach(
                {
                    "reason": reason,
                    "module": module,
                    "detail": detail,
                    "state": self.state_of(module),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as exc:
            logger.warning("FaultGuard: breach publish failed: %s", exc)

    # ── metrics ───────────────────────────────────────────────────────────────

    def metrics(self) -> dict:
        """Return a snapshot of all module states."""
        return {
            name: {
                "state": ms.state.name,
                "failures": ms.failures,
                "total_trips": ms.total_trips,
                "total_recoveries": ms.total_recoveries,
                "heartbeat_age_s": round(time.monotonic() - ms.last_heartbeat, 1),
            }
            for name, ms in self._modules.items()
        }
