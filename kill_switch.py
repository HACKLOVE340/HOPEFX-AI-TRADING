# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
kill_switch.py
HOPEFX AI Trading – System-Wide Kill Switch

Provides an instant, multi-trigger mechanism to halt all trading activity:
  • Programmatic activation via KillSwitch.activate()
  • File-based activation: place/remove `kill_switch.flag` next to this module
  • Event-bus integration: publishes/subscribes to KILL_SWITCH domain events
  • Environment variable override: HOPEFX_KILL_SWITCH=1

IMPORTANT — this is a SOFTWARE kill switch only:
  • State is an in-memory boolean flag backed by a Redis latch and a flag file.
  • A Python process crash, OOM kill, or kernel panic can prevent the switch
    from firing if it has not yet been activated.
  • For hard real-money deployments consider a hardware kill switch in series:
    e.g. a managed network ACL, exchange-level "cancel on disconnect" (CoD),
    or a relay that cuts the WAN link on broker-level kill signals.
  • The ``reqGlobalCancel()`` escalation (IBKR) provides broker-level
    protection but still depends on this process being alive to issue it.

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
import contextlib
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

# FastAPI Request imported at module scope so route annotations resolve correctly
# under Pydantic v2 (inner-function imports create unresolvable ForwardRefs).
try:
    from fastapi import Request as _FastAPIRequest
except ImportError:
    _FastAPIRequest = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Pydantic request models — module-scope so Pydantic v2 can resolve them      #
# for OpenAPI schema generation (inner-function classes break forward refs).   #
# --------------------------------------------------------------------------- #
try:
    from pydantic import BaseModel as _BaseModel

    class _KSActivateRequest(_BaseModel):
        reason: str = "manual activation via API"

    class _KSDeactivateRequest(_BaseModel):
        token: str = ""

except ImportError:  # pydantic not installed (e.g. minimal test env)
    _KSActivateRequest = None  # type: ignore[assignment,misc]
    _KSDeactivateRequest = None  # type: ignore[assignment,misc]

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
        flag_file: Path | None = None,
        poll_interval_sec: float = 1.0,
        event_bus=None,
        deactivation_token: str | None = None,
    ) -> None:
        self._flag_file: Path = flag_file or _DEFAULT_FLAG_FILE
        # JSON state file sits next to the flag file and survives restarts.
        self._state_file: Path = self._flag_file.with_suffix(".state.json")
        self._poll_interval: float = poll_interval_sec
        self._event_bus = event_bus

        # Token required to call deactivate().  Loaded from the
        # HOPEFX_KILL_SWITCH_TOKEN env var when not supplied directly.
        # If neither is set, deactivation is disabled until a token is
        # configured — this prevents accidental or unauthenticated resumption.
        self._deactivation_token: str | None = deactivation_token or os.environ.get("HOPEFX_KILL_SWITCH_TOKEN")

        self._active: bool = False
        self._reason: str = ""
        self._activated_at: datetime | None = None

        self._callbacks: list[Callable[[str], None]] = []
        self._running: bool = False
        self._task: asyncio.Task | None = None
        # Background task that subscribes to Redis CH_BREACH for cross-pod propagation
        self._redis_sub_task: asyncio.Task | None = None
        # Background task that watches K8s ConfigMap — fallback when Redis is unreachable
        self._k8s_watch_task: asyncio.Task | None = None

        # Restore persisted state from the previous process before checking
        # the env-var, so that a restart after an activation does not silently
        # resume trading.
        self._restore_state()

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

    def deactivate(self, token: str | None = None) -> None:
        """
        Deactivate the kill switch and allow trading to resume.

        Args:
            token: The deactivation token.  Must match the value set via
                   ``deactivation_token`` constructor argument or the
                   ``HOPEFX_KILL_SWITCH_TOKEN`` environment variable.
                   If no token is configured, deactivation is refused to
                   prevent accidental or unauthenticated resumption of trading.

        Raises:
            PermissionError: When the supplied token does not match or no
                             token is configured.

        Note: The flag file (if present) must also be removed manually,
        otherwise the background polling task will re-activate on the next
        poll cycle.  This is intentional — it forces an explicit operator
        action before trading resumes.
        """
        if not self._active:
            return

        # Authentication check — refuse if no token is configured or token
        # does not match.  Use constant-time comparison to prevent timing attacks.
        import hmac as _hmac

        if not self._deactivation_token:
            raise PermissionError(
                "Kill switch deactivation is disabled: no HOPEFX_KILL_SWITCH_TOKEN "
                "is configured.  Set the env var or pass deactivation_token= to "
                "KillSwitch() to enable authenticated deactivation."
            )
        provided = (token or "").encode()
        expected = self._deactivation_token.encode()
        if not _hmac.compare_digest(provided, expected):
            logger.critical("Kill switch deactivation REFUSED — invalid token supplied")
            raise PermissionError("Kill switch deactivation refused: invalid token.")

        self._active = False
        self._reason = ""
        self._activated_at = None
        # Remove both the state file and the flag file so the next process
        # restart starts clean and does not re-activate from stale files.
        self._clear_state()
        # Clear the Redis distributed latch so restarting pods do not re-activate.
        self._clear_redis_latch()
        logger.warning("Kill switch DEACTIVATED — trading may resume")

    def is_active(self) -> bool:
        """Return True when trading must be halted.

        Priority order (highest to lowest):
        1. In-memory ``_active`` flag (set by ``activate()`` / startup latch check)
        2. ``kill_switch.flag`` file on disk (polled every 2 s — survives process crash)
        3. ``HOPEFX_KILL_SWITCH=1`` environment variable (K8s override / ops runbook)
        4. Redis distributed latch (cross-pod; ``ks:latch`` key, TTL=7d)
        5. K8s ConfigMap watcher (Redis-down fallback; ``hopefx-kill-switch`` key)

        When Redis is down:
        - The flag file and env-var remain active (priority 2+3 are Redis-independent).
        - The K8s ConfigMap watcher (priority 5) provides cross-pod propagation.
        - Any pod that activated the switch writes a local JSON state file that
          survives restarts even if Redis is unreachable at startup.
        """
        return self._active

    def reset_for_testing(self) -> None:
        """
        Reset all mutable state to the clean (inactive) baseline.

        **Only call this from test fixtures.**  It bypasses the token check,
        resets in-memory state, and clears the Redis distributed latch so
        that tests are fully isolated from each other.
        """
        self._active = False
        self._reason = ""
        self._activated_at = None
        self._callbacks.clear()
        # Clear the Redis latch so the next KillSwitch.start() does not
        # re-activate from a latch written by a previous test.
        import contextlib

        with contextlib.suppress(Exception):
            self._clear_redis_latch()
        logger.debug("KillSwitch.reset_for_testing() called")

    @property
    def reason(self) -> str:
        """Human-readable reason for the last activation."""
        return self._reason

    @property
    def activated_at(self) -> datetime | None:
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

        # Check Redis distributed latch at startup — any pod that starts while
        # the kill switch is active (even if Redis pub/sub was down when it was
        # first activated) will detect the latch and activate immediately.
        # This prevents the split-brain scenario where a restarting pod resumes
        # trading while sibling pods are halted.
        await self._check_redis_latch()

        # Wire up legacy in-process event-bus subscription (kept for backward compat)
        if self._event_bus is not None:
            try:
                self._event_bus.subscribe("KILL_SWITCH", self.on_bus_event)
                logger.info("Kill switch subscribed to event bus KILL_SWITCH events")
            except Exception as exc:
                logger.warning("Could not subscribe to event bus: %s", exc)

        # Start Redis breach subscription for cross-pod kill propagation
        self._redis_sub_task = asyncio.create_task(self._redis_breach_listener(), name="kill_switch_redis_sub")

        # Start K8s ConfigMap watcher as fallback when Redis is unreachable.
        # When Redis pub/sub is down, the ConfigMap write+watch path ensures
        # all pods in the cluster see the kill switch activation.
        self._k8s_watch_task = asyncio.create_task(self._k8s_configmap_watcher(), name="kill_switch_k8s_watch")

        self._task = asyncio.create_task(self._poll_loop(), name="kill_switch_poll")
        logger.info(
            "Kill switch started (flag file: %s, poll interval: %.1fs)",
            self._flag_file,
            self._poll_interval,
        )

    # ---------------------------------------------------------------------- #
    # Redis distributed latch — prevents split-brain on pod restart           #
    # ---------------------------------------------------------------------- #

    _REDIS_LATCH_KEY = "hopefx:kill_switch:active"
    _REDIS_REASON_KEY = "hopefx:kill_switch:reason"

    async def _check_redis_latch(self) -> None:
        """
        Check for a persistent Redis kill-switch latch on startup.

        The latch is written by _write_redis_latch() when the kill switch is
        activated.  Any pod that starts after activation (including pods that
        restarted after a crash) will find the latch and activate immediately.

        This closes the split-brain window where:
          1. Pod A activates the kill switch and writes the latch.
          2. Pod B crashes and restarts.
          3. Pod B does not receive the Redis pub/sub event (already fired).
          4. Without the latch, Pod B resumes trading — split-brain.
          5. With the latch, Pod B reads the key at startup and halts.
        """
        try:
            r = self._get_latch_redis()
            if r is None:
                return
            latch_val = r.get(self._REDIS_LATCH_KEY)
            if latch_val and str(latch_val).lower() == "true":
                reason = r.get(self._REDIS_REASON_KEY) or "redis latch (kill switch was active on peer pod)"
                if not self._active:
                    logger.critical(
                        "Kill switch: Redis distributed latch detected at startup — activating. Reason: %s",
                        reason,
                    )
                    self._activate_internal(f"[redis-latch] {reason}")
        except Exception as exc:
            logger.debug("Kill switch: Redis latch check failed (non-fatal): %s", exc)

    def _write_redis_latch(self, reason: str) -> None:
        """
        Write the persistent Redis kill-switch latch.

        Called from _activate_internal() so that any pod restarting after this
        activation will read the latch and halt immediately (see _check_redis_latch).

        The latch is a plain string key (not pub/sub) so it survives Redis
        restarts and is available to pods that come up after the pub/sub event.
        TTL is set to 7 days to prevent stale latches from blocking trading
        indefinitely after an intended manual reset.
        """
        _LATCH_TTL = 7 * 24 * 3600  # 7 days
        try:
            r = self._get_latch_redis()
            if r is not None:
                r.set(self._REDIS_LATCH_KEY, "true", ex=_LATCH_TTL)
                r.set(self._REDIS_REASON_KEY, reason, ex=_LATCH_TTL)
                logger.info("Kill switch: Redis distributed latch written (TTL=%ds)", _LATCH_TTL)
        except Exception as exc:
            logger.warning("Kill switch: could not write Redis latch (non-fatal): %s", exc)

    def _clear_redis_latch(self) -> None:
        """Remove the Redis kill-switch latch on deactivation."""
        try:
            r = self._get_latch_redis()
            if r is not None:
                r.delete(self._REDIS_LATCH_KEY, self._REDIS_REASON_KEY)
                logger.info("Kill switch: Redis distributed latch cleared")
        except Exception as exc:
            logger.debug("Kill switch: could not clear Redis latch (non-fatal): %s", exc)

    def _get_latch_redis(self):
        """
        Return a sync Redis client for latch operations.

        Prefers the already-connected client from the event bus to avoid
        creating a new connection on every call.  Falls back to a fresh
        connection only when the bus client is unavailable.

        The returned client is owned by the caller and should not be closed
        when it comes from the event bus (it is shared).  When a new client
        is created here it is short-lived and will be garbage-collected after
        the caller's operation completes — no persistent handle is stored.
        """
        try:
            from core.event_bus import bus as _bus

            r = getattr(_bus, "_redis", None) or getattr(_bus, "_client", None)
            if r is not None:
                return r
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)

        try:
            import redis as _redis_lib

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            # socket_connect_timeout prevents indefinite blocking when Redis is down.
            return _redis_lib.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        except Exception:
            return None

    async def stop(self) -> None:
        """Stop background polling and Redis subscription."""
        self._running = False
        for task in (self._task, self._redis_sub_task, self._k8s_watch_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        logger.info("Kill switch polling stopped")

    def status(self) -> dict:
        """Return a JSON-serialisable status snapshot."""
        return {
            "active": self._active,
            "reason": self._reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
            "flag_file": str(self._flag_file),
            "flag_file_exists": self._flag_file.exists(),
            "state_file": str(self._state_file),
            "state_file_exists": self._state_file.exists(),
            "deactivation_token_configured": bool(self._deactivation_token),
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
        self._activated_at = datetime.now(UTC)

        logger.critical(
            "KILL SWITCH ACTIVATED — reason: %s | time: %s",
            reason,
            self._activated_at.isoformat(),
        )
        # Also write to stderr so the message appears even if the log handler
        # is misconfigured or the process is about to crash.
        import sys as _sys

        _sys.stderr.write(f"\nKILL SWITCH ACTIVATED: {reason}\n")
        _sys.stderr.flush()

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
            self._flag_file.write_text(f"activated_at={self._activated_at.isoformat()}\nreason={reason}\n")
        except OSError as exc:
            logger.warning("Could not write kill switch flag file: %s", exc)

        # Persist state to JSON so the next process restart can restore it.
        self._persist_state()

        # Write Redis distributed latch so pods that restart after this activation
        # will read the latch and halt immediately (prevents split-brain).
        self._write_redis_latch(reason)

        # Send Sentry critical alert (fire-and-forget)
        try:
            from monitoring.sentry_config import capture_kill_switch_alert

            capture_kill_switch_alert(reason=reason, triggered_by="system")
        except Exception as _sentry_exc:
            logger.debug("Sentry kill-switch alert failed: %s", _sentry_exc)

        # Send risk-halt email alert (fire-and-forget, never blocks trading halt)
        try:
            from notifications.email_triggers import send_risk_halt_email

            send_risk_halt_email(
                reason=reason,
                drawdown_pct=0.0,  # caller can override via callback if needed
                limit_pct=0.0,
            )
        except Exception as _email_exc:
            logger.debug("Risk halt email skipped (non-critical): %s", _email_exc)

        # Cancel all open orders and close all positions at the broker level.
        # This is a best-effort call — failure is logged but never prevents
        # the kill switch from activating. Each broker connector implements
        # its own mass-cancel (IBKR: reqGlobalCancel, OANDA: bulk position
        # close, MT5: iterate positions/orders).
        self._broker_cancel_all(reason)

    def _broker_cancel_all(self, reason: str) -> None:
        """
        Best-effort broker-level mass cancel on kill switch activation.

        Resolves the active broker from the module registry and calls
        cancel_all_orders(). Async brokers (OANDA, MT5) are dispatched
        via asyncio. Failure is logged but never prevents the kill switch
        from activating — the flag is already set before this is called.
        """
        try:
            # Try to get the active broker from the execution engine registry
            broker = None
            try:
                from execution.engine import get_active_broker

                broker = get_active_broker()
            except Exception:  # nosec B110 — execution engine may not be initialised; try fallback
                pass

            # Fallback: try the smart router's primary broker
            if broker is None:
                try:
                    from execution.smart_router import get_router

                    router = get_router()
                    if router is not None:
                        broker = getattr(router, "_primary_broker", None) or getattr(router, "broker", None)
                except Exception:  # nosec B110 — smart router may not be initialised; logged below
                    pass

            if broker is None:
                logger.warning("KillSwitch._broker_cancel_all: no active broker found — skipping broker cancel")
                return

            broker_name = getattr(broker, "name", type(broker).__name__)
            logger.warning("KillSwitch._broker_cancel_all: calling cancel_all_orders on %s", broker_name)

            cancel_fn = getattr(broker, "cancel_all_orders", None)
            if cancel_fn is None:
                logger.warning("KillSwitch._broker_cancel_all: %s has no cancel_all_orders method", broker_name)
                return

            import asyncio
            import inspect

            if inspect.iscoroutinefunction(cancel_fn):
                # Async broker (OANDA, MT5) — schedule on the running loop or run in new loop
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(cancel_fn())
                    logger.warning(
                        "KillSwitch._broker_cancel_all: async cancel_all_orders scheduled on %s", broker_name
                    )
                except RuntimeError:
                    # No running loop — run synchronously in a new loop
                    asyncio.run(cancel_fn())
                    logger.warning(
                        "KillSwitch._broker_cancel_all: async cancel_all_orders completed on %s", broker_name
                    )
            else:
                # Sync broker (IBKR)
                ok = cancel_fn()
                logger.warning(
                    "KillSwitch._broker_cancel_all: cancel_all_orders on %s returned %s",
                    broker_name,
                    ok,
                )

        except Exception as exc:
            # Never let broker cancel failure prevent the kill switch from activating
            logger.error("KillSwitch._broker_cancel_all: unexpected error: %s", exc)

    def _persist_state(self) -> None:
        """
        Write activation state to a JSON file next to the flag file.

        This ensures that a process restart after activation does not silently
        resume trading.  The state is read back in ``_restore_state()`` which
        is called from ``__init__`` before any env-var checks.
        """
        import json as _json

        state = {
            "active": self._active,
            "reason": self._reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
        }
        try:
            self._state_file.write_text(_json.dumps(state, indent=2))
        except OSError as exc:
            logger.warning("Could not persist kill switch state: %s", exc)

    def _restore_state(self) -> None:
        """
        Restore activation state from the JSON state file on startup.

        If the state file records an active kill switch, the switch is
        re-activated immediately so that a restart does not bypass the halt.
        The flag file is also checked as a secondary signal.

        Stale-flag guard: if the persisted activation is older than 24 hours
        and APP_ENV is not 'production', a WARNING is emitted and the flag is
        NOT automatically restored — the operator must manually confirm by
        keeping the file or re-activating programmatically.  In production
        mode the flag is always restored regardless of age.
        """
        import json as _json
        from datetime import timedelta

        _STALE_THRESHOLD = timedelta(hours=24)
        _is_production = os.environ.get("APP_ENV", "production") == "production"

        def _is_stale(activated_at: datetime | None) -> bool:
            if activated_at is None:
                return False
            now = datetime.now(UTC)
            # Make activated_at timezone-aware if it isn't already
            if activated_at.tzinfo is None:
                activated_at = activated_at.replace(tzinfo=UTC)
            return (now - activated_at) > _STALE_THRESHOLD

        # Primary: JSON state file (written by _persist_state)
        if self._state_file.exists():
            try:
                data = _json.loads(self._state_file.read_text())
                if data.get("active"):
                    reason = data.get("reason", "persisted state from previous session")
                    activated_at_str = data.get("activated_at")
                    activated_at = datetime.fromisoformat(activated_at_str) if activated_at_str else None

                    if not _is_production and _is_stale(activated_at):
                        logger.warning(
                            "Kill switch state file is STALE (activated >24 h ago: %s). "
                            "Reason: %s. "
                            "Not auto-restoring in non-production mode. "
                            "Delete kill_switch.state.json to clear, or set APP_ENV=production "
                            "to always restore.",
                            activated_at_str,
                            reason,
                        )
                        return

                    self._active = True
                    self._reason = reason
                    self._activated_at = activated_at or datetime.now(UTC)
                    logger.critical(
                        "Kill switch restored from persisted state — reason: %s | originally activated: %s",
                        reason,
                        self._activated_at.isoformat(),
                    )
                    return
            except Exception as exc:
                logger.warning("Could not read kill switch state file: %s", exc)

        # Secondary: plain flag file (written by _activate_internal / external tools)
        if self._flag_file.exists():
            try:
                reason, activated_at = self._parse_flag_file()
                if not _is_production and _is_stale(activated_at):
                    logger.warning(
                        "kill_switch.flag is STALE (activated >24 h ago: %s). "
                        "Reason: %s. "
                        "Not auto-restoring in non-production mode. "
                        "Delete kill_switch.flag to clear, or set APP_ENV=production "
                        "to always restore.",
                        activated_at.isoformat() if activated_at else "unknown",
                        reason,
                    )
                    return

                self._active = True
                self._reason = reason
                self._activated_at = activated_at or datetime.now(UTC)
                logger.critical(
                    "Kill switch activated from flag file at startup — reason: %s",
                    reason,
                )
                # Write the JSON state file so future restarts use the richer format
                self._persist_state()
            except Exception as exc:
                logger.warning("Could not read kill switch flag file: %s", exc)

    def _parse_flag_file(self) -> tuple:
        """Parse the plain-text flag file and return (reason, activated_at).

        Returns a (str, Optional[datetime]) tuple. Falls back to safe defaults
        when fields are missing or malformed.
        """
        content = self._flag_file.read_text()
        reason = "flag file present at startup"
        activated_at: datetime | None = None
        for line in content.splitlines():
            if line.startswith("reason="):
                reason = line.split("=", 1)[1].strip()
            elif line.startswith("activated_at="):
                with contextlib.suppress(ValueError):
                    activated_at = datetime.fromisoformat(line.split("=", 1)[1].strip())
        return reason, activated_at

    def _clear_state(self) -> None:
        """
        Remove both the state file and the flag file after a successful deactivation.

        Both files must be removed so that the next process restart does not
        re-activate the kill switch from stale on-disk state.
        """
        for path in (self._state_file, self._flag_file):
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                logger.warning("Could not remove kill switch file %s: %s", path, exc)

    def _publish_event(self, reason: str) -> None:
        """
        Publish a KILL_SWITCH breach event.

        Write path (guaranteed delivery):
          1. Write to outbox_events table (transactional outbox) — survives
             Redis downtime; OutboxRelay delivers once Redis recovers.
          2. Attempt immediate publish to Redis EventBus (cross-pod, low latency).
          3. Fall back to legacy in-process event bus if Redis is unavailable.

        The outbox write is the source of truth — the direct Redis publish is
        a best-effort optimisation to reduce latency when Redis is healthy.
        """
        payload = {
            "type": "kill_switch",
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # ── Step 1: Write to transactional outbox (at-least-once guarantee) ──
        try:
            from core.outbox import write_outbox_event_standalone

            write_outbox_event_standalone(
                event_type="KILL_SWITCH",
                channel="hopefx:breach",
                payload=payload,
            )
        except Exception as _ob_exc:
            logger.warning("Kill switch outbox write failed (non-fatal): %s", _ob_exc)

        # ── Step 2: Immediate Redis publish (best-effort, low latency) ────────
        try:
            from core.event_bus import bus as _redis_bus

            try:
                loop = asyncio.get_running_loop()
                _t = loop.create_task(_redis_bus.publish_breach(payload))
                _t.add_done_callback(lambda _: None)
                logger.info("Kill switch breach event scheduled on Redis CH_BREACH")
                return
            except RuntimeError:
                import inspect as _inspect

                result = _redis_bus.publish_breach(payload)
                if _inspect.iscoroutine(result):
                    result.close()
                return
        except Exception as exc:
            logger.warning(
                "Could not publish kill-switch event to Redis bus: %s — "
                "falling back to legacy in-process bus (outbox will retry)",
                exc,
            )

        # ── Step 3: Fallback — legacy in-process event bus ────────────────────
        if self._event_bus is not None:
            try:
                from core.event_bus import DomainEvent

                event = DomainEvent.create(
                    "KILL_SWITCH",
                    "kill_switch",
                    payload,
                    priority=0,
                )
                try:
                    loop = asyncio.get_running_loop()
                    _t = loop.create_task(self._event_bus.publish(event))
                    _t.add_done_callback(lambda _: None)
                except RuntimeError:
                    import inspect as _inspect

                    result = self._event_bus.publish(event)
                    if _inspect.iscoroutine(result):
                        result.close()
            except Exception as exc:
                logger.warning("Could not publish kill-switch event (fallback): %s", exc)

        # ── Step 4: K8s ConfigMap write — ensures cross-pod propagation ───────
        # When Redis is down, all pods watch the ConfigMap and will activate
        # their local kill switch when they see kill_switch_active=true.
        # This is the last-resort guarantee that no pod keeps trading after
        # a drawdown breach even if Redis is completely unavailable.
        self._write_k8s_configmap(reason)

    async def _redis_breach_listener(self) -> None:
        """
        Subscribe to CH_BREACH on the Redis EventBus and activate the kill
        switch when a kill_switch breach event arrives from another pod.

        This is the cross-pod propagation path.  Without this loop, activating
        the kill switch on Pod A does not affect Pods B and C.
        """
        try:
            from core.event_bus import CH_BREACH
            from core.event_bus import bus as _redis_bus
        except ImportError:
            logger.warning("Kill switch: could not import Redis EventBus — cross-pod propagation disabled")
            return

        # Ensure the bus is connected before subscribing
        try:
            await _redis_bus.connect()
        except Exception as exc:
            logger.warning(
                "Kill switch: Redis EventBus connect failed (%s) — cross-pod propagation disabled",
                exc,
            )
            return

        logger.info("Kill switch: listening for breach events on Redis CH_BREACH")
        try:
            async for message in _redis_bus.subscribe(CH_BREACH):
                if not self._running:
                    break
                try:
                    msg_type = message.get("type", "")
                    if msg_type != "kill_switch":
                        continue
                    reason = message.get("reason", "remote kill switch activation")
                    if not self._active:
                        logger.warning(
                            "Kill switch: received remote activation via Redis CH_BREACH — reason: %s",
                            reason,
                        )
                        # activate() is idempotent; it will not re-publish since
                        # we are already in the activated state from the remote pod.
                        self._activate_internal(f"[remote] {reason}")
                except Exception as exc:
                    logger.warning("Kill switch: error processing breach message: %s", exc)
        except asyncio.CancelledError:
            ...  # nosec B110
        except Exception as exc:
            logger.error("Kill switch: Redis breach listener exited unexpectedly: %s", exc)

    # ── K8s ConfigMap fallback ────────────────────────────────────────────────

    async def _k8s_configmap_watcher(self) -> None:
        """
        Watch a Kubernetes ConfigMap for kill switch state.

        This is the fallback cross-pod propagation path used when Redis
        pub/sub is unreachable. It polls the ConfigMap every
        K8S_KS_POLL_INTERVAL_S seconds and activates the kill switch if
        the ConfigMap contains ``kill_switch_active: "true"``.

        Write path (called from _publish_event when Redis is down):
            _write_k8s_configmap(reason) — patches the ConfigMap via the
            Kubernetes API so all pods in the cluster see the activation.

        Read path (this method):
            Polls the ConfigMap and calls _activate_internal() when the
            kill switch flag is set.

        Configuration (env vars)
        ------------------------
        K8S_KS_NAMESPACE       — namespace of the ConfigMap (default: hopefx)
        K8S_KS_CONFIGMAP_NAME  — ConfigMap name (default: hopefx-kill-switch)
        K8S_KS_POLL_INTERVAL_S — poll interval in seconds (default: 5)
        KUBERNETES_SERVICE_HOST — set automatically inside a pod; absence
                                  means we are running outside K8s (skip watcher)
        """
        namespace = os.getenv("K8S_KS_NAMESPACE", "hopefx")
        cm_name = os.getenv("K8S_KS_CONFIGMAP_NAME", "hopefx-kill-switch")
        poll_interval = float(os.getenv("K8S_KS_POLL_INTERVAL_S", "5"))

        # Only run inside a Kubernetes pod
        if not os.getenv("KUBERNETES_SERVICE_HOST"):
            logger.debug(
                "Kill switch K8s watcher: not running inside a pod (KUBERNETES_SERVICE_HOST not set) — skipping"
            )
            return

        try:
            from kubernetes_asyncio import client as k8s_client
            from kubernetes_asyncio import config as k8s_config

            await k8s_config.load_incluster_config()
            v1 = k8s_client.CoreV1Api()
        except ImportError:
            logger.warning(
                "Kill switch K8s watcher: kubernetes-asyncio not installed — "
                "install kubernetes-asyncio for ConfigMap fallback"
            )
            return
        except Exception as exc:
            logger.warning(
                "Kill switch K8s watcher: failed to load in-cluster config (%s) — ConfigMap fallback disabled",
                exc,
            )
            return

        logger.info(
            "Kill switch K8s ConfigMap watcher started (namespace=%s, configmap=%s, interval=%.0fs)",
            namespace,
            cm_name,
            poll_interval,
        )

        while self._running:
            try:
                cm = await v1.read_namespaced_config_map(cm_name, namespace)
                data = cm.data or {}
                active_flag = data.get("kill_switch_active", "false").lower()
                reason = data.get("kill_switch_reason", "k8s configmap activation")

                if active_flag == "true" and not self._active:
                    logger.critical(
                        "Kill switch K8s watcher: ConfigMap flag set — activating. Reason: %s",
                        reason,
                    )
                    self._activate_internal(f"[k8s-configmap] {reason}")

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug(
                    "Kill switch K8s watcher: poll error (%s) — will retry in %.0fs",
                    exc,
                    poll_interval,
                )

            await asyncio.sleep(poll_interval)

    def _write_k8s_configmap(self, reason: str) -> None:
        """
        Patch the K8s ConfigMap to signal kill switch activation to all pods.

        Called synchronously from _publish_event() when Redis is unavailable.
        Uses a fire-and-forget asyncio task if a loop is running, otherwise
        runs synchronously via the kubernetes (sync) client.

        This is the write side of the ConfigMap fallback. The read side is
        _k8s_configmap_watcher() running on every pod.
        """
        namespace = os.getenv("K8S_KS_NAMESPACE", "hopefx")
        cm_name = os.getenv("K8S_KS_CONFIGMAP_NAME", "hopefx-kill-switch")

        if not os.getenv("KUBERNETES_SERVICE_HOST"):
            return  # not in a pod — skip silently

        patch_body = {
            "data": {
                "kill_switch_active": "true",
                "kill_switch_reason": reason,
                "kill_switch_timestamp": datetime.now(UTC).isoformat(),
            }
        }

        async def _async_patch() -> None:
            try:
                from kubernetes_asyncio import (
                    client as k8s_client,
                )
                from kubernetes_asyncio import (
                    config as k8s_config,
                )

                await k8s_config.load_incluster_config()
                v1 = k8s_client.CoreV1Api()
                await v1.patch_namespaced_config_map(cm_name, namespace, patch_body)
                logger.info(
                    "Kill switch: K8s ConfigMap '%s/%s' patched (reason=%s)",
                    namespace,
                    cm_name,
                    reason,
                )
            except Exception as exc:
                logger.error(
                    "Kill switch: K8s ConfigMap patch failed (%s) — pods without Redis will not see this activation",
                    exc,
                )

        try:
            loop = asyncio.get_running_loop()
            _t = loop.create_task(_async_patch(), name="kill_switch_k8s_patch")
            _t.add_done_callback(lambda _: None)
        except RuntimeError:
            # No running loop — use sync kubernetes client
            try:
                from kubernetes import client as k8s_sync
                from kubernetes import config as k8s_sync_config

                k8s_sync_config.load_incluster_config()
                v1 = k8s_sync.CoreV1Api()
                v1.patch_namespaced_config_map(cm_name, namespace, patch_body)
                logger.info(
                    "Kill switch: K8s ConfigMap '%s/%s' patched (sync, reason=%s)",
                    namespace,
                    cm_name,
                    reason,
                )
            except Exception as exc:
                logger.error("Kill switch: K8s ConfigMap sync patch failed: %s", exc)

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
        except Exception as exc:
            logger.debug("Kill switch bus event decode failed: %s", exc)
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


# ---------------------------------------------------------------------------
# FastAPI router — wire into app.py with:
#   from kill_switch import create_kill_switch_router
#   app.include_router(create_kill_switch_router(kill_switch_instance))
# ---------------------------------------------------------------------------


def create_kill_switch_router(ks: KillSwitch):
    """
    Create a FastAPI router exposing the kill switch via REST.

    Endpoints:
        GET  /api/kill-switch/status   — current state (no auth required for monitoring)
        POST /api/kill-switch/activate — halt all trading (admin only)
        POST /api/kill-switch/deactivate — resume trading (admin only, requires token)

    Authentication is enforced by the caller — pass an auth dependency when
    including the router, or use the dependency injection shown below.
    """
    try:
        from fastapi import APIRouter, Depends, HTTPException
        from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    except ImportError:
        logger.warning("FastAPI not available — kill switch router not created")
        return None

    if _FastAPIRequest is None:
        logger.warning("FastAPI Request not available — kill switch router not created")
        return None

    router = APIRouter(prefix="/api/kill-switch", tags=["Kill Switch"])
    _bearer = HTTPBearer(auto_error=True)

    def _require_admin(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
        """
        Verify the bearer token and require role >= 'admin'.
        Raises 401 for invalid/expired tokens, 403 for insufficient role.
        Logs all failures so auth errors are never silently swallowed.
        """
        try:
            from api.auth import _decode_token

            user = _decode_token(credentials.credentials)
        except HTTPException:
            raise
        except Exception as exc:
            # Misconfigured auth service — log at critical so it is never silent.
            logger.critical(
                "Kill switch auth dependency raised unexpected error: %s — denying access (fail closed)",
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="Authentication service error — access denied",
            ) from exc

        _role_rank = {"user": 0, "trader": 1, "admin": 2, "superadmin": 3}
        if _role_rank.get(getattr(user, "role", "user"), -1) < _role_rank["admin"]:
            logger.warning(
                "Kill switch access denied: user=%s role=%s — admin required",
                getattr(user, "sub", "unknown"),
                getattr(user, "role", "unknown"),
            )
            raise HTTPException(status_code=403, detail="Role 'admin' required")
        return user

    @router.get("/status")
    async def get_status():
        """Return current kill switch state. No authentication required."""
        return ks.status()

    # In-memory rate limiter: max 5 activate/deactivate attempts per minute per user.
    # Prevents brute-force token guessing against the deactivate endpoint.
    import time as _time
    from collections import defaultdict as _defaultdict

    _ks_attempt_times: dict = _defaultdict(list)
    _KS_RATE_LIMIT = 5
    _KS_RATE_WINDOW = 60  # seconds

    def _check_rate_limit(user_id: str) -> None:
        now = _time.monotonic()
        attempts = _ks_attempt_times[user_id]
        # Purge attempts outside the window
        _ks_attempt_times[user_id] = [t for t in attempts if now - t < _KS_RATE_WINDOW]
        if len(_ks_attempt_times[user_id]) >= _KS_RATE_LIMIT:
            logger.warning(
                "Kill switch rate limit exceeded for user=%s (%d attempts in %ds)",
                user_id,
                len(_ks_attempt_times[user_id]),
                _KS_RATE_WINDOW,
            )
            raise HTTPException(status_code=429, detail="Too many kill switch requests")
        _ks_attempt_times[user_id].append(now)

    @router.post("/activate")
    async def activate(req: _KSActivateRequest, request: _FastAPIRequest, user=Depends(_require_admin)):
        """
        Halt all trading immediately.

        Sets the kill switch active, cancels open orders, and blocks new
        order submission until deactivated.  Requires role >= 'admin'.
        Rate limited to 5 requests per minute per user.
        """
        user_id = getattr(user, "sub", "unknown")
        _check_rate_limit(user_id)

        if ks.is_active():
            logger.info("Kill switch activate called but already active (user=%s)", user_id)
            return {"status": "already_active", "reason": ks.reason}

        reason = f"[api:{user_id}] {req.reason}"
        ks.activate(reason)
        logger.critical(
            "AUDIT: Kill switch ACTIVATED via API | user=%s | ip=%s | reason=%r",
            user_id,
            request.client.host if request.client else "unknown",
            req.reason,
        )
        return {
            "status": "activated",
            "reason": ks.reason,
            "activated_at": ks.activated_at.isoformat() if ks.activated_at else None,
        }

    @router.post("/deactivate")
    async def deactivate(
        req: _KSDeactivateRequest,
        request: _FastAPIRequest,
        user=Depends(_require_admin),
    ):
        """
        Resume trading after a kill switch event.

        Requires role >= 'admin' AND the HMAC deactivation token configured
        via HOPEFX_KILL_SWITCH_TOKEN.  Both checks must pass.
        Rate limited to 5 requests per minute per user.
        """
        user_id = getattr(user, "sub", "unknown")
        _check_rate_limit(user_id)

        if not ks.is_active():
            logger.info("Kill switch deactivate called but already inactive (user=%s)", user_id)
            return {"status": "already_inactive"}

        try:
            ks.deactivate(token=req.token or None)
        except PermissionError as exc:
            logger.critical(
                "AUDIT: Kill switch deactivation REFUSED | user=%s | ip=%s | reason=%s",
                user_id,
                request.client.host if request.client else "unknown",
                exc,
            )
            raise HTTPException(status_code=403, detail="Permission denied") from None

        logger.warning(
            "AUDIT: Kill switch DEACTIVATED via API | user=%s | ip=%s",
            user_id,
            request.client.host if request.client else "unknown",
        )
        return {"status": "deactivated"}

    return router


# ── Module-level singleton ────────────────────────────────────────────────────
# Imported by nuclear_supervisor and connect_to_life as:
#   from kill_switch import kill_switch
#
# trigger_nuclear_mode() is an async wrapper so callers can await it uniformly.

kill_switch = KillSwitch()


async def trigger_nuclear_mode(reason: str = "RL nuclear supervisor triggered") -> None:
    """Activate the kill switch for a nuclear event. Async-safe wrapper."""
    kill_switch.activate(reason)
    logger.critical("☢️ trigger_nuclear_mode called: %s", reason)
