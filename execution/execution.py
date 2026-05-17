# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/execution.py
=======================
ExecutionSystem — complete startup wiring and orchestration entry point.

This is the ONLY file that should be imported to start the full execution
pipeline. It wires every component in the correct order and enforces the
single-source-of-truth contract.

Startup sequence
----------------
  1.  Start MarketDataOrchestrator (Redis, feeds, sentiment, calendar, macro)
  2.  Wire lineage_store (already started inside orchestrator)
  3.  Instantiate RiskManager(orchestrator, lineage_store)
  4.  Instantiate Gatekeeper(orchestrator, lineage_store)
  5.  Instantiate SmartRouter(lineage_store)
  6.  Connect brokers (OANDA, IBKR) — order execution only
  7.  Register brokers with SmartRouter
  8.  Wire ML inference function (optional)
  9.  Instantiate HopeFXEngine(orchestrator, router, risk, gate, lineage)
  10. Start HopeFXEngine tick loop
  11. Start health reporting loop
  12. Register SIGTERM/SIGINT handlers for graceful shutdown

Data flow (runtime)
-------------------
  orchestrator.get_latest_tick()   → HopeFXEngine._process_tick()
  orchestrator.get_ml_features()   → HopeFXEngine._run_inference()
                                   → RiskManager.size_order()
                                   → Gatekeeper.evaluate()
                                   → SmartRouter.route_and_execute()
  broker.place_order()             → fill
  orchestrator.notify_fill()       ← fill (replay + cache update)
  lineage_store.record_*()         ← every event

Architectural invariants enforced here
---------------------------------------
  - orchestrator.start() is called BEFORE any other component
  - No broker is connected before orchestrator is running
  - SmartRouter receives no broker until orchestrator is confirmed started
  - HopeFXEngine is started LAST, after all dependencies are wired
  - Graceful shutdown: engine stops first, then brokers, then orchestrator

Usage
-----
    from execution.execution import ExecutionSystem

    system = ExecutionSystem()
    await system.start()
    # ... runs until SIGTERM or system.stop()
    await system.stop()

Or as a standalone process:
    python -m execution.execution
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
from collections.abc import Callable
from datetime import timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

# ── env config ────────────────────────────────────────────────────────────────
_BROKER_PRIMARY = os.getenv("BROKER_PRIMARY", "oanda")  # "oanda" | "ibkr" | "cme" | "cpp_shim"
_BROKER_SECONDARY = os.getenv("BROKER_SECONDARY", "ibkr")  # fallback broker
_CME_ENABLED = os.getenv("CME_ENABLED", "false").lower() == "true"
_CPP_SHIM_ENABLED = os.getenv("CPP_SHIM_ENABLED", "false").lower() == "true"
_HEALTH_INTERVAL = float(os.getenv("HEALTH_INTERVAL_S", "30"))
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── Operational phase gate ────────────────────────────────────────────────────
# The C++ FIX shim is a latency-optimisation tool. It must NOT be enabled
# until the system has completed:
#   Phase 1 — paper trading (≥500 fills, ≥30 days)
#   Phase 2 — live trading validation (≥100 live fills, positive P&L)
#
# Correct order: validate edge → paper trade → live trade → optimise latency
#
# Set LATENCY_OPT_PHASE_UNLOCKED=true ONLY after live trading is validated.
# Without this flag, CPP_SHIM_ENABLED=true is silently ignored and a warning
# is logged. This prevents the V30 mistake of building latency optimisation
# before the first trade.
_LATENCY_OPT_UNLOCKED = os.getenv("LATENCY_OPT_PHASE_UNLOCKED", "false").lower() == "true"

# Minimum live fills required before latency optimisation is permitted.
_LATENCY_OPT_MIN_LIVE_FILLS = int(os.getenv("LATENCY_OPT_MIN_LIVE_FILLS", "100"))


def _check_latency_opt_gate() -> bool:
    """
    Return True if the C++ shim / latency optimisation phase is unlocked.

    Gate conditions (all must be met):
      1. LATENCY_OPT_PHASE_UNLOCKED=true in environment
      2. Paper trading gate: ≥500 fills recorded in paper_trading_gate.json
      3. Live fills: LIVE_FILL_COUNT env var ≥ LATENCY_OPT_MIN_LIVE_FILLS

    If any condition fails, logs a clear message explaining what is missing
    and returns False. The shim is silently skipped — no crash.
    """
    if not _LATENCY_OPT_UNLOCKED:
        logger.warning(
            "C++ shim / latency optimisation BLOCKED: "
            "LATENCY_OPT_PHASE_UNLOCKED is not set. "
            "Required order: paper trade (≥500 fills, ≥30 days) → "
            "live trade (≥%d fills) → set LATENCY_OPT_PHASE_UNLOCKED=true. "
            "This prevents optimising latency before the first trade.",
            _LATENCY_OPT_MIN_LIVE_FILLS,
        )
        return False

    # Check paper trading gate
    try:
        from research.pipeline.paper_trading_gate import PaperTradingGate

        gate = PaperTradingGate()
        fill_count = gate._state.get("fill_count", 0)
        if fill_count < 500:
            logger.warning(
                "C++ shim BLOCKED: paper trading gate not met. "
                "fill_count=%d < 500 required. "
                "Complete paper trading phase before enabling latency optimisation.",
                fill_count,
            )
            return False
    except Exception as exc:
        logger.warning("C++ shim gate: could not read paper trading state (%s) — blocking shim", exc)
        return False

    # Check live fill count
    live_fills = int(os.getenv("LIVE_FILL_COUNT", "0"))
    if live_fills < _LATENCY_OPT_MIN_LIVE_FILLS:
        logger.warning(
            "C++ shim BLOCKED: live fill count %d < %d required. "
            "Complete live trading validation before enabling latency optimisation.",
            live_fills,
            _LATENCY_OPT_MIN_LIVE_FILLS,
        )
        return False

    logger.info(
        "C++ shim / latency optimisation UNLOCKED (paper_fills≥500, live_fills=%d≥%d, LATENCY_OPT_PHASE_UNLOCKED=true)",
        live_fills,
        _LATENCY_OPT_MIN_LIVE_FILLS,
    )
    return True


class ExecutionSystem:
    """
    Full execution system — single entry point for the entire pipeline.

    All components are wired here. No component should be instantiated
    outside this class in production.
    """

    def __init__(self, ml_inference_fn: Callable[..., Any] | None = None) -> None:
        self._ml_inference_fn = ml_inference_fn
        self._started = False
        self._start_time: float | None = None

        # Components — populated in start()
        self._orchestrator: Any = None
        self._lineage: Any = None
        self._risk: Any = None
        self._gatekeeper: Any = None
        self._router: Any = None
        self._engine: Any = None
        self._brokers: dict[str, Any] = {}
        self._tasks: list[asyncio.Task[None]] = []

    # ── Startup ───────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start the full execution system in the correct dependency order.
        Raises on any critical failure.
        """
        if self._started:
            logger.warning("ExecutionSystem already started")
            return

        self._start_time = time.monotonic()
        _configure_logging()

        logger.info("=" * 60)
        logger.info("ExecutionSystem: starting up")
        logger.info("=" * 60)

        # ── Step 1: Start orchestrator ─────────────────────────────────────
        logger.info("Step 1/9: Starting MarketDataOrchestrator...")
        from data_layer.orchestrator import orchestrator

        self._orchestrator = orchestrator
        await self._orchestrator.start()
        logger.info("Step 1/9: MarketDataOrchestrator started ✓")

        # ── Step 2: Wire lineage store via orchestrator (single entry point) ─
        logger.info("Step 2/9: Wiring DataLineageStore via orchestrator...")
        self._lineage = self._orchestrator._lineage
        logger.info("Step 2/9: DataLineageStore wired ✓")

        # ── Step 3: Instantiate RiskManager ───────────────────────────────
        logger.info("Step 3/9: Instantiating RiskManager...")
        from risk.manager import RiskManager

        self._risk = RiskManager(
            orchestrator=self._orchestrator,
            lineage_store=self._lineage,
        )
        logger.info("Step 3/9: RiskManager ready ✓")

        # ── Step 4: Instantiate Gatekeeper ────────────────────────────────
        logger.info("Step 4/9: Instantiating Gatekeeper...")
        from risk.gatekeeper import Gatekeeper

        self._gatekeeper = Gatekeeper(
            orchestrator=self._orchestrator,
            lineage_store=self._lineage,
        )
        logger.info("Step 4/9: Gatekeeper ready ✓")

        # ── Step 5: Instantiate SmartRouter ───────────────────────────────
        logger.info("Step 5/9: Instantiating SmartRouter...")
        from execution.smart_router import SmartRouter

        self._router = SmartRouter(lineage_store=self._lineage)
        logger.info("Step 5/9: SmartRouter ready ✓")

        # ── Step 6: Connect brokers ────────────────────────────────────────
        logger.info("Step 6/9: Connecting brokers...")
        await self._connect_brokers()
        logger.info("Step 6/9: Brokers connected ✓")

        # ── Step 7: Register brokers with SmartRouter ──────────────────────
        logger.info("Step 7/9: Registering brokers with SmartRouter...")
        for broker_id, broker in self._brokers.items():
            self._router.add_broker(broker_id, broker)
        logger.info("Step 7/9: %d broker(s) registered ✓", len(self._brokers))

        # ── Step 8: Wire notify_fill into orchestrator ─────────────────────
        logger.info("Step 8/9: Wiring orchestrator.notify_fill...")
        _wire_notify_fill(self._orchestrator)
        logger.info("Step 8/9: notify_fill wired ✓")

        # ── Step 9: Start HopeFXEngine ─────────────────────────────────────
        logger.info("Step 9/9: Starting HopeFXEngine...")
        from execution.hopefx_engine import HopeFXEngine

        self._engine = HopeFXEngine(
            orchestrator=self._orchestrator,
            smart_router=self._router,
            risk_manager=self._risk,
            gatekeeper=self._gatekeeper,
            lineage_store=self._lineage,
            ml_inference_fn=self._ml_inference_fn,
        )
        await self._engine.start()
        logger.info("Step 9/9: HopeFXEngine started ✓")

        # ── Background tasks ───────────────────────────────────────────────
        self._tasks.append(asyncio.create_task(self._health_loop(), name="execution_health_loop"))

        # ── Signal handlers ────────────────────────────────────────────────
        self._install_signal_handlers()

        self._started = True
        elapsed = time.monotonic() - self._start_time
        logger.info("=" * 60)
        logger.info("ExecutionSystem: FULLY STARTED in %.2fs", elapsed)
        logger.info("  Orchestrator : %s", "running" if self._orchestrator._started else "ERROR")
        logger.info("  Brokers      : %s", list(self._brokers.keys()))
        logger.info("  Engine state : %s", self._engine._state.value)
        logger.info("=" * 60)

    # ── Broker connection ─────────────────────────────────────────────────────

    async def _connect_brokers(self) -> None:
        """Connect configured brokers. At least one must succeed."""
        connected_count = 0

        if _BROKER_PRIMARY == "oanda" or _BROKER_SECONDARY == "oanda":
            oanda = await _connect_oanda()
            if oanda:
                self._brokers["oanda"] = oanda
                connected_count += 1

        if _BROKER_PRIMARY == "ibkr" or _BROKER_SECONDARY == "ibkr":
            ibkr = await _connect_ibkr()
            if ibkr:
                self._brokers["ibkr"] = ibkr
                connected_count += 1

        # ── CME COMEX GC futures (enabled via CME_ENABLED=true) ───────────
        if _CME_ENABLED or _BROKER_PRIMARY in ("cme", "cme_comex", "comex", "gc"):
            cme = await _connect_cme()
            if cme:
                self._brokers["cme"] = cme
                connected_count += 1

        # ── C++ execution shim (enabled via CPP_SHIM_ENABLED=true) ────────
        # Phase gate: shim is a latency optimisation — only allowed after
        # paper trading AND live trading are validated. See _check_latency_opt_gate().
        if _CPP_SHIM_ENABLED or _BROKER_PRIMARY in ("cpp_shim", "shim"):
            if _check_latency_opt_gate():
                shim = await _connect_cpp_shim()
                if shim:
                    self._brokers["cpp_shim"] = shim
                    connected_count += 1
            else:
                logger.warning(
                    "CPP_SHIM_ENABLED=true but latency optimisation phase gate "
                    "is not met — shim skipped. Falling through to standard broker."
                )

        if connected_count == 0:
            logger.warning("No brokers connected — running in paper/simulation mode")
            paper = _build_paper_broker()
            self._brokers["paper"] = paper

    # ── Shutdown ──────────────────────────────────────────────────────────────

    async def stop(self) -> None:
        """Graceful shutdown in reverse dependency order."""
        logger.info("ExecutionSystem: shutting down...")

        # 1. Stop engine first (stops new orders)
        if self._engine:
            await self._engine.stop()

        # 2. Cancel background tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        # 3. Disconnect brokers
        for broker_id, broker in self._brokers.items():
            try:
                if hasattr(broker, "disconnect"):
                    await broker.disconnect()
                logger.info("ExecutionSystem: broker %s disconnected", broker_id)
            except (TimeoutError, RuntimeError, ConnectionError, AttributeError) as exc:
                logger.error("ExecutionSystem: broker %s disconnect error: %s", broker_id, exc)

        # 4. Stop orchestrator last
        if self._orchestrator:
            await self._orchestrator.stop()

        self._started = False
        logger.info("ExecutionSystem: shutdown complete")

    # ── Health loop ───────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        while self._started:
            await asyncio.sleep(_HEALTH_INTERVAL)
            try:
                self._log_health()
            except (RuntimeError, AttributeError, ValueError, TypeError) as exc:
                logger.debug("Health loop error: %s", exc)

    def _log_health(self) -> None:
        if not self._engine:
            return
        em = self._engine.metrics()
        rm = self._risk.metrics() if self._risk else {}
        gm = self._gatekeeper.metrics() if self._gatekeeper else {}
        sm = self._router.metrics() if self._router else {}
        oh = self._orchestrator.health() if self._orchestrator else {}

        logger.info(
            "HEALTH | engine: ticks=%d signals=%d fills=%d rejects=%d "
            "| risk: dd=%.2f%% halt=%s "
            "| gate: pass=%d block=%d "
            "| router: filled=%d/%d "
            "| orch: safe=%s feeds=%s",
            em.get("tick_count", 0),
            em.get("signal_count", 0),
            em.get("fill_count", 0),
            em.get("reject_count", 0),
            rm.get("current_drawdown", 0),
            rm.get("halt", False),
            gm.get("pass_count", 0),
            gm.get("block_count", 0),
            sm.get("total_filled", 0),
            sm.get("total_routed", 0),
            oh.get("is_safe", False),
            list(oh.get("gold_feeds", {}).keys()),
        )

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        def _handle_shutdown(sig_name: str) -> None:
            logger.warning("ExecutionSystem: received %s — initiating shutdown", sig_name)
            _t = asyncio.create_task(self.stop())
            _t.add_done_callback(lambda _: None)

        try:
            loop.add_signal_handler(signal.SIGTERM, lambda: _handle_shutdown("SIGTERM"))
            loop.add_signal_handler(signal.SIGINT, lambda: _handle_shutdown("SIGINT"))
        except RuntimeError:
            ...  # nosec B110

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        uptime = time.monotonic() - self._start_time if self._start_time else 0
        return {
            "started": self._started,
            "uptime_s": round(uptime, 1),
            "engine": self._engine.metrics() if self._engine else {},
            "risk": self._risk.metrics() if self._risk else {},
            "gatekeeper": self._gatekeeper.metrics() if self._gatekeeper else {},
            "router": self._router.metrics() if self._router else {},
            "orchestrator": self._orchestrator.health() if self._orchestrator else {},
        }


# ── Broker factory helpers ────────────────────────────────────────────────────


async def _connect_oanda() -> Any | None:
    from config.settings import resolve_oanda_account, resolve_oanda_token

    account_id = resolve_oanda_account()
    api_token = resolve_oanda_token()
    if not account_id or not api_token:
        logger.warning("OANDA credentials not set — skipping OANDA broker. Set OANDA_API_KEY and OANDA_ACCOUNT_ID.")
        return None
    try:
        from brokers.oanda import OANDABroker

        broker = OANDABroker(
            {
                "login": account_id,
                "password": api_token,
                "server": os.getenv("OANDA_ENVIRONMENT", "practice"),
            }
        )
        ok = await broker.connect()
        if ok:
            logger.info("OANDA broker connected")
            return broker
        logger.warning("OANDA broker connection failed")
        return None
    except (ImportError, RuntimeError, ValueError) as exc:
        logger.error("OANDA broker init error: %s", exc)
        return None


async def _connect_ibkr() -> Any | None:
    host = os.getenv("IBKR_HOST", "127.0.0.1")
    _port = int(os.getenv("IBKR_PORT", "7497"))
    try:
        from brokers.ibkr import IBKRBroker

        broker = IBKRBroker(
            {
                "server": os.getenv("IBKR_ENV", "paper"),
                "host": host,
                "client_id": int(os.getenv("IBKR_CLIENT_ID", "1")),
            }
        )
        ok = await broker.connect()
        if ok:
            logger.info("IBKR broker connected")
            return broker
        logger.warning("IBKR broker connection failed (TWS/Gateway not running?)")
        return None
    except (ImportError, RuntimeError, ValueError) as exc:
        logger.error("IBKR broker init error: %s", exc)
        return None


async def _connect_cme() -> Any | None:
    """Connect CME COMEX GC futures broker (FIX → IBKR fallback → paper)."""
    try:
        from brokers.cme_comex import CMEComexConnector

        broker = CMEComexConnector.from_env()
        ok = broker.connect()
        if ok:
            logger.info(
                "CME COMEX broker connected — fix=%s ibkr=%s paper=%s",
                broker._fix_available,
                broker._ibkr_available,
                broker._paper_fallback,
            )
            return broker
        logger.warning("CME COMEX broker connection failed")
        return None
    except (ImportError, RuntimeError, ValueError) as exc:
        logger.error("CME COMEX broker init error: %s", exc)
        return None


async def _connect_cpp_shim() -> Any | None:
    """Connect C++ execution shim via ZMQ."""
    try:
        from brokers.cpp_shim_connector import CPPShimConnector

        broker = CPPShimConnector.from_env()
        ok = broker.connect()
        if ok:
            logger.info("C++ execution shim connected — %s", broker._cmd_addr)
            return broker
        logger.warning(
            "C++ execution shim not available — is hopefx_shim running? "
            "Build: cd execution/cpp_shim && cmake -B build && cmake --build build"
        )
        return None
    except (ImportError, RuntimeError, ValueError) as exc:
        logger.error("C++ shim init error: %s", exc)
        return None


def _build_paper_broker() -> Any:
    """Paper broker for simulation when no live broker is available."""
    try:
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(config={})
        logger.warning("Using PaperTradingBroker — no live execution")
        return broker
    except (ImportError, RuntimeError, ValueError) as exc:
        logger.error("PaperTradingBroker init failed: %s", exc)
        raise RuntimeError("Cannot start paper broker") from exc


# ── notify_fill wiring ────────────────────────────────────────────────────────


def _wire_notify_fill(orchestrator: Any) -> None:
    """
    Add notify_fill() to the orchestrator if not already present.

    notify_fill() is called by HopeFXEngine on every confirmed fill.
    It updates the replay engine and Redis cache so they stay consistent
    with actual execution state.
    """
    if hasattr(orchestrator, "notify_fill"):
        return  # already wired

    def notify_fill(
        symbol: str,
        direction: str,
        quantity: float,
        fill_price: float,
        fill_id: str,
        signal_id: str,
        broker: str,
        latency_ms: float,
    ) -> None:
        """
        Called immediately after every confirmed fill.

        Updates:
          - Redis cache: stores fill record under hopefx:fills:<symbol>
          - Lineage store: records fill event
          - Replay engine: notifies of actual execution price
        """
        import json
        from datetime import datetime

        fill_record = {
            "fill_id": fill_id,
            "signal_id": signal_id,
            "symbol": symbol,
            "direction": direction,
            "quantity": quantity,
            "fill_price": fill_price,
            "broker": broker,
            "latency_ms": latency_ms,
            "filled_at": datetime.now(UTC).isoformat(),
        }

        # Update Redis cache
        try:
            if orchestrator._redis:
                key = f"hopefx:fills:{symbol}"
                orchestrator._redis.lpush(key, json.dumps(fill_record))
                orchestrator._redis.ltrim(key, 0, 999)  # keep last 1000 fills
                orchestrator._redis.expire(key, 86400)  # 24h TTL
        except (RuntimeError, TypeError) as exc:
            logger.debug("notify_fill Redis update failed: %s", exc)

        # Notify replay engine
        try:
            orchestrator._replay.on_fill(
                symbol=symbol,
                fill_price=fill_price,
                quantity=quantity,
                direction=direction,
                fill_id=fill_id,
            )
        except (RuntimeError, AttributeError, ValueError, TypeError) as exc:
            logger.debug("notify_fill replay engine update failed: %s", exc)

        logger.debug(
            "notify_fill: %s %s qty=%.4f price=%.4f broker=%s latency=%.1fms",
            direction,
            symbol,
            quantity,
            fill_price,
            broker,
            latency_ms,
        )

    orchestrator.notify_fill = notify_fill
    logger.info("orchestrator.notify_fill wired")


# ── Logging config ────────────────────────────────────────────────────────────


def _configure_logging() -> None:
    level = getattr(logging, _LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Suppress noisy third-party loggers
    for noisy in ("urllib3", "aiohttp", "asyncio", "ib_insync"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ── Module-level singleton ────────────────────────────────────────────────────
execution_system = ExecutionSystem()


# ── Standalone entry point ────────────────────────────────────────────────────


async def _main() -> None:
    system = ExecutionSystem()
    await system.start()
    try:
        # Run until SIGTERM/SIGINT
        while system._started:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        ...  # nosec B110
    finally:
        await system.stop()


if __name__ == "__main__":
    asyncio.run(_main())
