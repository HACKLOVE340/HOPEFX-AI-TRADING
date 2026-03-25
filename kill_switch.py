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
        deactivation_token: Optional[str] = None,
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
        self._deactivation_token: Optional[str] = (
            deactivation_token
            or os.environ.get("HOPEFX_KILL_SWITCH_TOKEN")
        )

        self._active: bool = False
        self._reason: str = ""
        self._activated_at: Optional[datetime] = None

        self._callbacks: List[Callable[[str], None]] = []
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

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

    def deactivate(self, token: Optional[str] = None) -> None:
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
            logger.critical(
                "Kill switch deactivation REFUSED — invalid token supplied"
            )
            raise PermissionError("Kill switch deactivation refused: invalid token.")

        self._active = False
        self._reason = ""
        self._activated_at = None
        # Remove both the state file and the flag file so the next process
        # restart starts clean and does not re-activate from stale files.
        self._clear_state()
        logger.warning("Kill switch DEACTIVATED — trading may resume")

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
        self._activated_at = datetime.now(timezone.utc)

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
            self._flag_file.write_text(
                f"activated_at={self._activated_at.isoformat()}\nreason={reason}\n"
            )
        except OSError as exc:
            logger.warning("Could not write kill switch flag file: %s", exc)

        # Persist state to JSON so the next process restart can restore it.
        self._persist_state()

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
        """
        import json as _json

        # Primary: JSON state file (written by _persist_state)
        if self._state_file.exists():
            try:
                data = _json.loads(self._state_file.read_text())
                if data.get("active"):
                    reason = data.get("reason", "persisted state from previous session")
                    activated_at_str = data.get("activated_at")
                    self._active = True
                    self._reason = reason
                    self._activated_at = (
                        datetime.fromisoformat(activated_at_str)
                        if activated_at_str
                        else datetime.now(timezone.utc)
                    )
                    logger.critical(
                        "Kill switch restored from persisted state — reason: %s | "
                        "originally activated: %s",
                        reason,
                        self._activated_at.isoformat(),
                    )
                    return
            except Exception as exc:
                logger.warning("Could not read kill switch state file: %s", exc)

        # Secondary: plain flag file (written by _activate_internal / external tools)
        if self._flag_file.exists():
            try:
                content = self._flag_file.read_text()
                reason = "flag file present at startup"
                for line in content.splitlines():
                    if line.startswith("reason="):
                        reason = line.split("=", 1)[1].strip()
                        break
                self._active = True
                self._reason = reason
                self._activated_at = datetime.now(timezone.utc)
                logger.critical(
                    "Kill switch activated from flag file at startup — reason: %s",
                    reason,
                )
                # Write the JSON state file so future restarts use the richer format
                self._persist_state()
            except Exception as exc:
                logger.warning("Could not read kill switch flag file: %s", exc)

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


# ---------------------------------------------------------------------------
# FastAPI router — wire into app.py with:
#   from kill_switch import create_kill_switch_router
#   app.include_router(create_kill_switch_router(kill_switch_instance))
# ---------------------------------------------------------------------------

def create_kill_switch_router(ks: "KillSwitch"):
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
        from fastapi import APIRouter, HTTPException, Depends, Request
        from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
        from pydantic import BaseModel
    except ImportError:
        logger.warning("FastAPI not available — kill switch router not created")
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
                "Kill switch auth dependency raised unexpected error: %s — "
                "denying access (fail closed)",
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="Authentication service error — access denied",
            )

        _ROLE_RANK = {"user": 0, "trader": 1, "admin": 2, "superadmin": 3}
        if _ROLE_RANK.get(getattr(user, "role", "user"), -1) < _ROLE_RANK["admin"]:
            logger.warning(
                "Kill switch access denied: user=%s role=%s — admin required",
                getattr(user, "sub", "unknown"),
                getattr(user, "role", "unknown"),
            )
            raise HTTPException(status_code=403, detail="Role 'admin' required")
        return user

    class ActivateRequest(BaseModel):
        reason: str = "manual activation via API"

    class DeactivateRequest(BaseModel):
        token: str = ""

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
                user_id, len(_ks_attempt_times[user_id]), _KS_RATE_WINDOW,
            )
            raise HTTPException(status_code=429, detail="Too many kill switch requests")
        _ks_attempt_times[user_id].append(now)

    @router.post("/activate")
    async def activate(req: ActivateRequest, request: Request, user=Depends(_require_admin)):
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
    async def deactivate(req: DeactivateRequest, request: Request, user=Depends(_require_admin)):
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
            raise HTTPException(status_code=403, detail=str(exc))

        logger.warning(
            "AUDIT: Kill switch DEACTIVATED via API | user=%s | ip=%s",
            user_id,
            request.client.host if request.client else "unknown",
        )
        return {"status": "deactivated"}

    return router
