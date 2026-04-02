# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
core/main_loop.py
=================
Async system orchestrator — starts every sub-system in the correct order,
wires shutdown, and checkpoints state on exit.

Start order
-----------
1. EventBus          — Redis pub/sub backbone (core/event_bus.py)
2. FaultGuard        — circuit-breaker heartbeat monitor (utils/fault_guard.py)
3. MarketIngest      — XAUUSD tick stream (data/market_ingest.py)
4. StrategyEngine    — ML signal producer (strategy/engine.py)
5. Gatekeeper        — prop-firm risk filter (risk/gatekeeper.py)
6. FIXRouter         — order execution (execution/fix_router.py)

Shutdown
--------
- Triggered by SIGINT / SIGTERM or a kill_event on hopefx:breach.
- Each sub-system is stopped in reverse start order.
- Final state is checkpointed to state/main_loop_checkpoint.json.

Usage
-----
    python -m core.main_loop
    # or
    from core.main_loop import run
    asyncio.run(run())
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import signal
import sys
from datetime import datetime, timezone

UTC = timezone.utc

from dotenv import load_dotenv

from core.event_bus import bus, CH_BREACH
from data.market_ingest import MarketIngest
from data.news_calendar_feed import NewsCalendarFeed
from execution.fix_router import FIXRouter
from risk.gatekeeper import Gatekeeper
from strategy.engine import StrategyEngine
from utils.fault_guard import FaultGuard

logger = logging.getLogger(__name__)

CHECKPOINT_FILE = "state/main_loop_checkpoint.json"


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class MainLoop:
    """
    Starts all sub-systems as concurrent asyncio tasks and manages their
    lifecycle as a single unit.
    """

    def __init__(self) -> None:
        self._ingest = MarketIngest()
        self._news = NewsCalendarFeed()
        self._strategy = StrategyEngine()
        self._gatekeeper = Gatekeeper()
        self._router = FIXRouter()
        self._fault = FaultGuard()

        self._tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()
        self._start_time: datetime | None = None

    # ── entry point ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start all sub-systems and block until shutdown."""
        load_dotenv(override=False)
        self._start_time = datetime.now(UTC)

        # Register OS signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._request_shutdown)

        logger.info("MainLoop: connecting EventBus …")
        await bus.connect()

        # Register all modules with FaultGuard so heartbeats are monitored
        self._fault.register("market_ingest")
        self._fault.register("strategy_engine")
        self._fault.register("gatekeeper")
        self._fault.register("fix_router")

        logger.info("MainLoop: starting sub-systems …")

        # Launch each sub-system as an independent task
        self._tasks = [
            asyncio.create_task(self._fault.run(), name="fault_guard"),
            asyncio.create_task(self._news.run(), name="news_calendar"),
            asyncio.create_task(self._ingest.start(), name="market_ingest"),
            asyncio.create_task(self._strategy.start(), name="strategy_engine"),
            asyncio.create_task(self._gatekeeper.start(), name="gatekeeper"),
            asyncio.create_task(self._router.start(), name="fix_router"),
            asyncio.create_task(self._breach_watcher(), name="breach_watcher"),
        ]

        logger.info("MainLoop: all sub-systems running.")

        # Block until shutdown is requested
        await self._shutdown_event.wait()

        logger.info("MainLoop: shutdown initiated.")
        await self._stop_all()

    # ── shutdown ──────────────────────────────────────────────────────────────

    def _request_shutdown(self) -> None:
        """Called by OS signal handler — schedules graceful stop."""
        logger.warning("MainLoop: shutdown signal received.")
        self._shutdown_event.set()

    async def _stop_all(self) -> None:
        """Stop sub-systems in reverse order, then checkpoint."""
        # Cancel all tasks
        for task in reversed(self._tasks):
            if not task.done():
                task.cancel()

        # Wait for all tasks to finish (ignore CancelledError)
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        for task, result in zip(self._tasks, results, strict=False):
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                logger.error("MainLoop: task %s raised: %s", task.get_name(), result)

        # Stop sub-systems explicitly (some may need clean teardown)
        for name, coro in [
            ("fix_router", self._router.stop()),
            ("gatekeeper", self._gatekeeper.stop()),
            ("strategy_engine", self._strategy.stop()),
            ("market_ingest", self._ingest.stop()),
            ("news_calendar", self._news.stop()),
            ("fault_guard", self._fault.stop()),
            ("event_bus", bus.close()),
        ]:
            try:
                await coro
            except Exception as exc:
                logger.warning("MainLoop: %s stop error: %s", name, exc)

        await self._checkpoint()
        logger.info("MainLoop: shutdown complete.")

    # ── breach watcher ────────────────────────────────────────────────────────

    async def _breach_watcher(self) -> None:
        """
        Monitor hopefx:breach for kill events.

        A kill_event or kill_switch breach triggers full system shutdown.
        """
        async for msg in bus.subscribe(CH_BREACH):
            reason = msg.get("reason", "")
            if reason in ("kill_switch", "kill_event", "kill_switch_active"):
                logger.critical("MainLoop: kill event received (reason=%s) — shutting down.", reason)
                self._shutdown_event.set()
                return

    # ── checkpoint ────────────────────────────────────────────────────────────

    async def _checkpoint(self) -> None:
        """Write final state snapshot to disk."""
        uptime_s = (datetime.now(UTC) - self._start_time).total_seconds() if self._start_time else 0
        state = {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_s": round(uptime_s, 1),
            "ingest_ticks": self._ingest.tick_count,
            "signals": self._strategy.metrics().get("signal_count", 0),
            "gate_passed": self._gatekeeper.metrics().get("pass_count", 0),
            "gate_blocked": self._gatekeeper.metrics().get("block_count", 0),
            "fills": self._router.metrics().get("fill_count", 0),
            "rejects": self._router.metrics().get("reject_count", 0),
            "bus_metrics": bus.metrics(),
            "fault_metrics": self._fault.metrics(),
        }
        try:
            pathlib.Path(CHECKPOINT_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
            logger.info("MainLoop: checkpoint saved → %s", CHECKPOINT_FILE)
        except OSError as exc:
            logger.warning("MainLoop: checkpoint write failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


async def run() -> None:
    """Convenience coroutine — create and run a MainLoop instance."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    # Validate required environment variables before starting any sub-system
    _validate_startup_env()

    loop = MainLoop()
    await loop.run()


def _validate_startup_env() -> None:
    """
    Check that all connector hub secrets are present and the active model
    artifact passes SHA-256 integrity verification.

    Logs a WARNING for each missing optional var and exits with a clear
    error message if any hard-required var is absent or the model is corrupt.
    """
    hard_required = [
        ("OANDA_API_KEY", "OANDA v20 API key — get from https://www.oanda.com/"),
        ("OANDA_ACCOUNT_ID", "OANDA account ID — found in your OANDA dashboard"),
    ]
    soft_required = [
        ("REDIS_URL", "Redis event bus URL (default: redis://localhost:6379/0)"),
        (
            "TELEGRAM_BOT_TOKEN",
            "Telegram bot token for alerts (optional but recommended)",
        ),
        ("TELEGRAM_CHAT_ID", "Telegram chat ID for alerts (optional but recommended)"),
        ("INITIAL_BALANCE", "Starting balance for drawdown tracking (default: 100000)"),
    ]

    missing_hard = []
    for key, desc in hard_required:
        if not os.environ.get(key, "").strip():
            missing_hard.append(f"  {key}: {desc}")

    for key, desc in soft_required:
        if not os.environ.get(key, "").strip():
            logger.warning("Missing optional env var %s — %s", key, desc)

    if missing_hard:
        msg = (
            "MainLoop: cannot start — missing required environment variables:\n"
            + "\n".join(missing_hard)
            + "\n\nCopy .env.example → .env and fill in the missing values."
        )
        logger.critical(msg)
        sys.exit(1)

    # ── Model registry integrity check ────────────────────────────────────────
    _verify_model_registry()


def _verify_model_registry() -> None:
    """
    Verify the active production model's SHA-256 integrity via ModelRegistry.

    Behaviour
    ---------
    - If registry.json does not exist: bootstrap it from advanced_oos_meta.json
      and log a WARNING (non-fatal — model is staging, not production).
    - If an active production model is registered: verify its SHA-256 digest.
      A mismatch is fatal (sys.exit(1)) — a corrupted model must not serve.
    - If no active production model is registered (all staging): log INFO.
      This is the expected state until the Sharpe gate passes and a model
      is promoted via ModelRegistry.promote().
    """
    try:
        from ml.model_registry import ModelRegistry

        reg = ModelRegistry()

        # Bootstrap registry.json from existing artifacts if it doesn't exist
        manifest = reg._load()
        if not manifest["versions"]:
            logger.info("ModelRegistry: registry.json is empty — bootstrapping from advanced_oos_meta.json …")
            entry = reg.bootstrap_from_meta(name="advanced_oos_v1", promote=False)
            if entry:
                logger.info(
                    "ModelRegistry: bootstrapped '%s'  sha256=%s…",
                    entry["name"],
                    entry["sha256"][:16],
                )
            else:
                logger.warning(
                    "ModelRegistry: bootstrap failed — advanced_oos.pkl not found. Train a model before deploying."
                )
            return

        # Verify active production model if one is registered
        active = manifest.get("active_version")
        if not active:
            logger.info(
                "ModelRegistry: no active production model (all versions are staging). "
                "Promote a model via ModelRegistry.promote() after the Sharpe gate passes."
            )
            return

        ok, msg = reg.verify_active()
        if ok:
            logger.info("ModelRegistry: %s", msg)
        else:
            logger.critical(
                "ModelRegistry: INTEGRITY FAILURE — %s. "
                "The model artifact may be corrupted or tampered with. "
                "Re-train and re-register before starting.",
                msg,
            )
            sys.exit(1)

    except Exception as exc:
        # Registry check failure is non-fatal in development; fatal in production
        app_env = os.getenv("APP_ENV", "development").lower()
        if app_env == "production":
            logger.critical(
                "ModelRegistry: startup check failed in production: %s — aborting.",
                exc,
            )
            sys.exit(1)
        logger.warning("ModelRegistry: startup check skipped: %s", exc)


if __name__ == "__main__":
    asyncio.run(run())
