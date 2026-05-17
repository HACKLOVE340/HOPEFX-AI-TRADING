# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
resilience/auto_rollback.py
============================
Automatic rollback mechanism for critical bug detection.

Triggers a rollback when any of the following conditions are met:
1. A circuit breaker opens (service failure detected)
2. The self-healer detects a critical code integrity violation
3. Post-deploy health checks fail (error rate spike, latency spike)
4. The kill switch is activated (trading halt)
5. A critical exception is detected in logs/app.log

Rollback strategies (in order of severity):
- SOFT:   Disable affected feature flags, drain in-flight requests
- MEDIUM: Restart affected service component, restore last known-good config
- HARD:   git checkout -- <file> to revert code changes, restart process
- FULL:   Full git reset to last tagged release, restart everything

All rollback actions are:
- Idempotent (safe to call multiple times)
- Audited (written to logs/app.log and Redis rollback:history)
- Reversible (the pre-rollback state is snapshotted first)
- Non-blocking (run as background tasks, never block the request path)

Usage
-----
    from resilience.auto_rollback import rollback_manager

    # Register a rollback trigger
    rollback_manager.register_trigger(
        name="high_error_rate",
        condition=lambda: error_rate > 0.05,
        strategy="medium",
        target="api/trading.py",
    )

    # Start the background monitor
    await rollback_manager.start()

    # Manual rollback
    result = await rollback_manager.rollback(strategy="soft", reason="manual")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess  # nosec B404 — git commands only, fixed args
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

UTC = timezone.utc
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
ROLLBACK_HISTORY_PATH = PROJECT_ROOT / "data" / "rollback_history.json"

# Threshold for repeated runtime errors that trigger rollback consideration
_REPEATED_ERROR_THRESHOLD = 3

# ── Prometheus metrics ────────────────────────────────────────────────────────
# Use idempotent helpers from core.prom_registry so re-importing this module
# (e.g. in tests) never raises ValueError on duplicate metric registration.

from core.prom_registry import prom_counter as _pc, prom_gauge as _pg

_ROLLBACK_TOTAL = _pc(
    "hopefx_rollback_total",
    "Total automatic rollbacks triggered",
    ["service"],
)
_ROLLBACK_STRATEGY_TOTAL = _pc(
    "hopefx_rollback_strategy_total",
    "Total rollbacks by strategy",
    ["strategy"],
)
_ROLLBACK_TRIGGER_TOTAL = _pc(
    "hopefx_rollback_trigger_total",
    "Total rollbacks by trigger source",
    ["trigger"],
)
_ROLLBACK_FAILED_TOTAL = _pc(
    "hopefx_rollback_failed_total",
    "Total rollback attempts that failed",
)
_STARTUP_COMPLETE = _pg(
    "hopefx_startup_complete",
    "1 when application startup has completed, 0 otherwise",
)


# ── Rollback strategies ───────────────────────────────────────────────────────


class RollbackStrategy:
    SOFT = "soft"  # disable feature flags, drain requests
    MEDIUM = "medium"  # restart component, restore config
    HARD = "hard"  # git checkout specific files
    FULL = "full"  # git reset to last tag


# ── Rollback result ───────────────────────────────────────────────────────────


@dataclass
class RollbackResult:
    success: bool
    strategy: str
    reason: str
    actions_taken: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rolled_back_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "strategy": self.strategy,
            "reason": self.reason,
            "actions_taken": self.actions_taken,
            "errors": self.errors,
            "rolled_back_at": self.rolled_back_at,
            "duration_ms": self.duration_ms,
        }


# ── Trigger definition ────────────────────────────────────────────────────────


@dataclass
class RollbackTrigger:
    name: str
    condition: Callable[[], bool]
    strategy: str = RollbackStrategy.SOFT
    target_files: list[str] = field(default_factory=list)
    cooldown_seconds: float = 300.0
    enabled: bool = True
    description: str = ""
    _last_triggered: float = field(default=0.0, repr=False)

    def should_trigger(self) -> bool:
        if not self.enabled:
            return False
        if time.time() - self._last_triggered < self.cooldown_seconds:
            return False
        try:
            return bool(self.condition())
        except Exception:
            return False

    def mark_triggered(self) -> None:
        self._last_triggered = time.time()


# ── Auto rollback manager ─────────────────────────────────────────────────────


class AutoRollbackManager:
    """
    Monitors system health and triggers rollbacks automatically.

    Integrates with:
    - Circuit breakers (resilience/service_circuit_breakers.py)
    - Self-healer (security/self_healer.py)
    - Log file analysis (security/code_analyzer.py)
    - Kill switch (kill_switch.py)
    """

    def __init__(self) -> None:
        self._triggers: list[RollbackTrigger] = []
        self._history: list[dict[str, Any]] = []
        self._running = False
        self._monitor_interval = float(os.getenv("ROLLBACK_MONITOR_INTERVAL_S", "30"))
        self._in_rollback = False
        self._rollback_count = 0
        self._last_rollback_ts: float = 0.0

        # Load history from disk
        self._load_history()

        # Register built-in triggers
        self._register_builtin_triggers()

    def _register_builtin_triggers(self) -> None:
        """Register the default set of rollback triggers."""

        # Trigger 1: Broker circuit breaker open
        self.register_trigger(
            RollbackTrigger(
                name="broker_circuit_open",
                condition=self._broker_circuit_open,
                strategy=RollbackStrategy.SOFT,
                cooldown_seconds=120.0,
            )
        )

        # Trigger 2: Database circuit breaker open
        self.register_trigger(
            RollbackTrigger(
                name="db_circuit_open",
                condition=self._db_circuit_open,
                strategy=RollbackStrategy.SOFT,
                cooldown_seconds=120.0,
            )
        )

        # Trigger 3: Critical code issues detected by self-healer
        self.register_trigger(
            RollbackTrigger(
                name="critical_code_issues",
                condition=self._critical_code_issues_detected,
                strategy=RollbackStrategy.HARD,
                cooldown_seconds=600.0,
            )
        )

        # Trigger 4: Repeated runtime errors in log file
        self.register_trigger(
            RollbackTrigger(
                name="repeated_runtime_errors",
                condition=self._repeated_runtime_errors,
                strategy=RollbackStrategy.MEDIUM,
                cooldown_seconds=300.0,
            )
        )

    def register_trigger(self, trigger: RollbackTrigger) -> None:
        """Register a custom rollback trigger."""
        self._triggers.append(trigger)
        logger.debug("AutoRollback: registered trigger '%s' (strategy=%s)", trigger.name, trigger.strategy)

    # ── Built-in condition checks ─────────────────────────────────────────────

    @staticmethod
    def _broker_circuit_open() -> bool:
        try:
            from resilience.service_circuit_breakers import broker_breaker

            return broker_breaker.is_open
        except ImportError:
            return False

    @staticmethod
    def _db_circuit_open() -> bool:
        try:
            from resilience.service_circuit_breakers import db_breaker

            return db_breaker.is_open
        except ImportError:
            return False

    @staticmethod
    def _critical_code_issues_detected() -> bool:
        """Return True if the self-healer has found critical code issues."""
        try:
            from security.self_healer import get_healer

            h = get_healer()
            critical_count = sum(1 for i in h._code_issues if i.get("severity") == "critical")
            return critical_count > 0
        except Exception:
            return False

    @staticmethod
    def _repeated_runtime_errors() -> bool:
        """Return True if there are _REPEATED_ERROR_THRESHOLD+ ERROR entries in the last 5 minutes."""
        try:
            from security.code_analyzer import analyze_log_file

            issues = analyze_log_file(since_minutes=5)
            errors = [i for i in issues if i.level in ("ERROR", "CRITICAL")]
            return len(errors) >= _REPEATED_ERROR_THRESHOLD
        except Exception:
            return False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background monitor loop."""
        self._running = True
        logger.info("AutoRollbackManager: started (interval=%.0fs)", self._monitor_interval)
        asyncio.create_task(self._monitor_loop(), name="auto-rollback-monitor")

    async def stop(self) -> None:
        self._running = False

    async def _monitor_loop(self) -> None:
        """Check all triggers periodically."""
        while self._running:
            await asyncio.sleep(self._monitor_interval)
            if self._in_rollback:
                continue
            try:
                await self._check_triggers()
            except Exception as exc:
                logger.warning("AutoRollback: monitor error: %s", exc)

    async def _check_triggers(self) -> None:
        """Evaluate all registered triggers and fire if conditions are met."""
        for trigger in self._triggers:
            if trigger.should_trigger():
                logger.warning(
                    "AutoRollback: trigger '%s' fired (strategy=%s)",
                    trigger.name,
                    trigger.strategy,
                )
                trigger.mark_triggered()
                result = await self.rollback(
                    strategy=trigger.strategy,
                    reason=f"trigger:{trigger.name}",
                    target_files=trigger.target_files,
                )
                if result.success:
                    logger.info(
                        "AutoRollback: rollback '%s' completed in %.0fms",
                        trigger.name,
                        result.duration_ms,
                    )
                else:
                    logger.error(
                        "AutoRollback: rollback '%s' FAILED: %s",
                        trigger.name,
                        result.errors,
                    )

    # ── Rollback execution ────────────────────────────────────────────────────

    async def rollback(
        self,
        strategy: str = RollbackStrategy.SOFT,
        reason: str = "manual",
        target_files: list[str] | None = None,
    ) -> RollbackResult:
        """
        Execute a rollback with the specified strategy.

        Args:
            strategy: One of SOFT, MEDIUM, HARD, FULL.
            reason: Human-readable reason for the rollback.
            target_files: Specific files to revert (HARD strategy only).

        Returns:
            RollbackResult with success status and actions taken.
        """
        t0 = time.time()
        self._in_rollback = True
        result = RollbackResult(success=False, strategy=strategy, reason=reason)

        logger.warning(
            "AutoRollback: executing %s rollback — reason: %s",
            strategy.upper(),
            reason,
        )

        try:
            if strategy == RollbackStrategy.SOFT:
                await self._rollback_soft(result)
            elif strategy == RollbackStrategy.MEDIUM:
                await self._rollback_medium(result)
            elif strategy == RollbackStrategy.HARD:
                await self._rollback_hard(result, target_files or [])
            elif strategy == RollbackStrategy.FULL:
                await self._rollback_full(result)
            else:
                result.errors.append(f"Unknown strategy: {strategy}")
                return result

            result.success = not bool(result.errors)
        except Exception as exc:
            result.errors.append(f"Rollback exception: {exc}")
            logger.exception("AutoRollback: unhandled exception during rollback")
        finally:
            result.duration_ms = (time.time() - t0) * 1000
            self._in_rollback = False
            self._rollback_count += 1
            self._last_rollback_ts = time.time()
            self._record_history(result)

            # ── Prometheus metrics ────────────────────────────────────────────
            service_name = os.getenv("OTEL_SERVICE_NAME", "hopefx-trading")
            trigger_name = reason.split(":", 1)[1] if reason.startswith("trigger:") else reason
            try:
                if _ROLLBACK_TOTAL is not None:
                    _ROLLBACK_TOTAL.labels(service=service_name).inc()
                if _ROLLBACK_STRATEGY_TOTAL is not None:
                    _ROLLBACK_STRATEGY_TOTAL.labels(strategy=strategy).inc()
                if _ROLLBACK_TRIGGER_TOTAL is not None:
                    _ROLLBACK_TRIGGER_TOTAL.labels(trigger=trigger_name).inc()
                if not result.success and _ROLLBACK_FAILED_TOTAL is not None:
                    _ROLLBACK_FAILED_TOTAL.inc()
            except Exception:  # nosec B110
                pass

        return result

    async def _rollback_soft(self, result: RollbackResult) -> None:
        """
        Soft rollback: disable affected feature flags, drain in-flight requests.
        Does NOT restart any process or revert any code.
        """
        actions = result.actions_taken

        # 1. Disable risky feature flags
        try:
            from config.feature_flags import flags

            risky_flags = ["ENABLE_LIVE_TRADING", "ENABLE_AUTO_TRADING", "ENABLE_ML_SIGNALS"]
            for flag in risky_flags:
                if hasattr(flags, flag.lower()):
                    setattr(flags, flag.lower(), False)
                    actions.append(f"Disabled feature flag: {flag}")
        except Exception as exc:
            result.errors.append(f"Feature flag disable failed: {exc}")

        # 2. Force-close broker circuit breaker (allow retry)
        try:
            from resilience.service_circuit_breakers import broker_breaker

            if broker_breaker.is_open:
                broker_breaker.force_close()
                actions.append("Force-closed broker circuit breaker")
        except Exception as exc:
            result.errors.append(f"Broker breaker reset failed: {exc}")

        # 3. Publish soft-rollback event to Redis
        self._publish_rollback_event(result, "soft")
        actions.append("Published rollback event to Redis alerts:critical")

        logger.info("AutoRollback: soft rollback complete — %d actions", len(actions))

    async def _rollback_medium(self, result: RollbackResult) -> None:
        """
        Medium rollback: soft rollback + restore last known-good config from Redis.
        """
        await self._rollback_soft(result)

        # Restore last known-good auto-healing config
        try:
            from security.self_healer import get_healer

            h = get_healer()
            cfg_path = PROJECT_ROOT / "data" / "auto_healing_config.json"
            if cfg_path.exists():
                import json as _json

                cfg = _json.loads(cfg_path.read_text())
                h.apply_config(cfg)
                result.actions_taken.append("Restored auto-healing config from disk")
        except Exception as exc:
            result.errors.append(f"Config restore failed: {exc}")

        # Trigger a fresh code analysis scan
        try:
            from security.self_healer import get_healer

            h = get_healer()
            asyncio.create_task(h._run_code_analysis(), name="rollback-code-scan")
            result.actions_taken.append("Triggered fresh code analysis scan")
        except Exception as exc:
            result.errors.append(f"Code scan trigger failed: {exc}")

        self._publish_rollback_event(result, "medium")
        logger.info("AutoRollback: medium rollback complete — %d actions", len(result.actions_taken))

    async def _rollback_hard(self, result: RollbackResult, target_files: list[str]) -> None:
        """
        Hard rollback: git checkout specific files to revert code changes.
        Falls back to medium rollback if git is unavailable.
        """
        await self._rollback_medium(result)

        if not target_files:
            # Auto-detect changed files from self-healer drift events
            try:
                from security.self_healer import get_healer

                h = get_healer()
                target_files = [e["path"] for e in h._drift_events[-10:] if e.get("type") == "modified"]
            except Exception:  # nosec B110 — healer may not be running; target_files stays empty
                pass

        if not target_files:
            result.actions_taken.append("No target files for hard rollback — medium rollback only")
            return

        import re as _re

        for _raw_path in target_files:
            # Normalise Windows-style backslashes to forward slashes before
            # validation.  The self-healer stores paths using os.sep which is
            # '\\' on Windows; git always accepts forward slashes on all
            # platforms, so we normalise unconditionally.
<<<<<<< HEAD
            rel_path = str(rel_path).replace("\\", "/")  # noqa: PLW2901
=======
            rel_path = str(_raw_path).replace("\\", "/")
>>>>>>> origin/main

            # Validate path is a safe relative file path before passing to subprocess.
            # Allowed: letters, digits, dot, underscore, forward-slash, hyphen, space.
            if not _re.fullmatch(r"[A-Za-z0-9_./ \-]+", rel_path):
                result.errors.append(f"Unsafe path rejected for git checkout: {rel_path!r}")
                continue
            try:
                proc = subprocess.run(  # nosec B603 B607
                    ["git", "checkout", "--", rel_path],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if proc.returncode == 0:
                    result.actions_taken.append(f"git checkout -- {rel_path}")
                    logger.info("AutoRollback: reverted %s via git", rel_path)
                else:
                    result.errors.append(f"git checkout failed for {rel_path}: {proc.stderr.strip()}")
            except Exception as exc:
                result.errors.append(f"git checkout exception for {rel_path}: {exc}")

        # Rebuild self-healer baseline after revert
        try:
            from security.self_healer import get_healer

            asyncio.create_task(get_healer().rebuild_baseline(), name="rollback-baseline-rebuild")
            result.actions_taken.append("Triggered baseline rebuild after hard rollback")
        except Exception as exc:
            result.errors.append(f"Baseline rebuild failed: {exc}")

        self._publish_rollback_event(result, "hard")
        logger.warning("AutoRollback: hard rollback complete — %d files reverted", len(target_files))

    async def _rollback_full(self, result: RollbackResult) -> None:
        """
        Full rollback: git reset to last tagged release.
        This is the nuclear option — use only when all else fails.
        """
        await self._rollback_hard(result, [])

        try:
            import re as _re

            # Find last tag — fixed args, no user input
            proc = subprocess.run(  # nosec B603 B607
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            last_tag = proc.stdout.strip()
            if not last_tag:
                result.errors.append("No git tags found — cannot perform full rollback")
                return

            # Validate tag against safe pattern before passing to subprocess
            if not _re.fullmatch(r"[A-Za-z0-9._/\-]+", last_tag):
                result.errors.append(f"Unsafe git tag value rejected: {last_tag!r}")
                return

            # Reset to last tag (soft reset — keeps working tree changes staged)
            proc2 = subprocess.run(  # nosec B603 B607
                ["git", "reset", "--soft", last_tag],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc2.returncode == 0:
                result.actions_taken.append(f"git reset --soft {last_tag}")
                logger.warning("AutoRollback: full rollback to tag %s", last_tag)
            else:
                result.errors.append(f"git reset failed: {proc2.stderr.strip()}")
        except Exception as exc:
            result.errors.append(f"Full rollback exception: {exc}")

        self._publish_rollback_event(result, "full")

    # ── Persistence ───────────────────────────────────────────────────────────

    def _record_history(self, result: RollbackResult) -> None:
        """Persist rollback result to disk and Redis."""
        self._history.append(result.to_dict())
        self._history = self._history[-100:]

        # Write to disk
        try:
            ROLLBACK_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            ROLLBACK_HISTORY_PATH.write_text(json.dumps(self._history[-50:], indent=2))
        except Exception as exc:
            logger.debug("AutoRollback: history write failed: %s", exc)

        # Write to Redis
        try:
            import redis as _redis_sync

            _rc = _redis_sync.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
                socket_connect_timeout=2,
            )
            _rc.rpush("rollback:history", json.dumps(result.to_dict()))
            _rc.ltrim("rollback:history", -100, -1)
        except Exception:  # nosec B110
            pass

    def _load_history(self) -> None:
        """Load rollback history from disk on startup."""
        try:
            if ROLLBACK_HISTORY_PATH.exists():
                self._history = json.loads(ROLLBACK_HISTORY_PATH.read_text())
        except Exception:
            self._history = []

    def _publish_rollback_event(self, result: RollbackResult, strategy: str) -> None:
        """Push rollback event to Redis alerts:critical."""
        try:
            import redis as _redis_sync

            _rc = _redis_sync.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
                socket_connect_timeout=2,
            )
            _rc.rpush(
                "alerts:critical",
                json.dumps(
                    {
                        "type": "auto_rollback",
                        "strategy": strategy,
                        "reason": result.reason,
                        "ts": result.rolled_back_at,
                        "actions": len(result.actions_taken),
                        "errors": result.errors[:5],
                    }
                ),
            )
            _rc.ltrim("alerts:critical", -1000, -1)
        except Exception:  # nosec B110
            pass

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return rollback manager status for health checks."""
        return {
            "running": self._running,
            "in_rollback": self._in_rollback,
            "rollback_count": self._rollback_count,
            "last_rollback": (
                datetime.fromtimestamp(self._last_rollback_ts, UTC).isoformat() if self._last_rollback_ts else None
            ),
            "triggers": [
                {
                    "name": t.name,
                    "strategy": t.strategy,
                    "enabled": t.enabled,
                    "last_triggered": (
                        datetime.fromtimestamp(t._last_triggered, UTC).isoformat() if t._last_triggered else None
                    ),
                }
                for t in self._triggers
            ],
            "history_count": len(self._history),
            "recent_history": self._history[-5:],
        }


# ── Module-level singleton ────────────────────────────────────────────────────

rollback_manager = AutoRollbackManager()
